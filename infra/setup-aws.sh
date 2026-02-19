#!/bin/bash
# setup-aws.sh — Create all AWS resources for OpenClaw on Fargate
#
# This script creates:
#   1. ECR repositories (gateway + worker images)
#   2. EFS file system + access point (persistent state)
#   3. Secrets Manager entries (credential placeholders)
#   4. CloudWatch log groups
#   5. Security groups (gateway, EFS, ALB)
#   6. ALB + target group + listener
#   7. ECS cluster
#   8. IAM roles (task execution + task roles)
#
# Usage:
#   export AWS_REGION=us-east-2
#   export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
#   export VPC_ID=vpc-XXXXX
#   export SUBNET_PRIVATE_1=subnet-XXXXX
#   export SUBNET_PRIVATE_2=subnet-XXXXX
#   export SUBNET_PUBLIC_1=subnet-XXXXX
#   export SUBNET_PUBLIC_2=subnet-XXXXX
#
#   bash infra/setup-aws.sh --dry-run    # Preview
#   bash infra/setup-aws.sh --yes        # Execute
#
# Teardown:
#   bash infra/setup-aws.sh --teardown   # Reverse order deletion

set -euo pipefail

MODE="${1:---dry-run}"
REGION="${AWS_REGION:-us-east-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
VPC_ID="${VPC_ID:-}"
SUBNET_PRIVATE_1="${SUBNET_PRIVATE_1:-}"
SUBNET_PRIVATE_2="${SUBNET_PRIVATE_2:-}"
SUBNET_PUBLIC_1="${SUBNET_PUBLIC_1:-}"
SUBNET_PUBLIC_2="${SUBNET_PUBLIC_2:-}"

# Resource names
ECS_CLUSTER="openclaw"
EFS_NAME="openclaw-state"
ECR_GATEWAY="openclaw-gateway"
ECR_WORKER="openbot-worker"
ALB_NAME="openclaw-alb"
TG_NAME="openclaw-tg"
SG_GATEWAY_NAME="openclaw-gateway-sg"
SG_EFS_NAME="openclaw-efs-sg"
SG_ALB_NAME="openclaw-alb-sg"
LOG_GROUP_GATEWAY="/ecs/openclaw-gateway"
LOG_GROUP_WORKER="/ecs/openbot-worker"

echo "============================================================"
echo "  OpenClaw Fargate Infrastructure Setup"
echo "  Region:     $REGION"
echo "  Account:    ${ACCOUNT_ID:-NOT SET}"
echo "  VPC:        ${VPC_ID:-NOT SET}"
echo "  Mode:       $MODE"
echo "============================================================"
echo ""

# ── Preflight ──────────────────────────────────────────────────────────────

if [ -z "$ACCOUNT_ID" ]; then
    echo "ERROR: Set AWS_ACCOUNT_ID (or run: export AWS_ACCOUNT_ID=\$(aws sts get-caller-identity --query Account --output text))"
    exit 1
fi

if [ -z "$VPC_ID" ]; then
    echo "ERROR: Set VPC_ID"
    exit 1
fi

if [ -z "$SUBNET_PRIVATE_1" ] || [ -z "$SUBNET_PRIVATE_2" ]; then
    echo "ERROR: Set SUBNET_PRIVATE_1 and SUBNET_PRIVATE_2"
    exit 1
fi

if [ -z "$SUBNET_PUBLIC_1" ] || [ -z "$SUBNET_PUBLIC_2" ]; then
    echo "ERROR: Set SUBNET_PUBLIC_1 and SUBNET_PUBLIC_2"
    exit 1
fi

run_cmd() {
    local desc="$1"
    shift
    echo "  $desc"
    if [ "$MODE" = "--yes" ]; then
        "$@" 2>&1 | head -20
        echo ""
    else
        echo "    [DRY RUN] $*"
        echo ""
    fi
}

# ── 1. ECR Repositories ───────────────────────────────────────────────────

echo "=== 1. ECR Repositories ==="

run_cmd "Creating ECR: $ECR_GATEWAY" \
    aws ecr create-repository --repository-name "$ECR_GATEWAY" --region "$REGION" \
    --image-scanning-configuration scanOnPush=true

run_cmd "Creating ECR: $ECR_WORKER" \
    aws ecr create-repository --repository-name "$ECR_WORKER" --region "$REGION" \
    --image-scanning-configuration scanOnPush=true

# ── 2. Security Groups ────────────────────────────────────────────────────

echo "=== 2. Security Groups ==="

run_cmd "Creating SG: $SG_ALB_NAME (ALB — inbound 80/443 from internet)" \
    aws ec2 create-security-group \
    --group-name "$SG_ALB_NAME" \
    --description "ALB for OpenClaw - inbound HTTP/HTTPS" \
    --vpc-id "$VPC_ID" \
    --region "$REGION"

# Note: After creation, add rules:
# aws ec2 authorize-security-group-ingress --group-id SG_ALB_ID --protocol tcp --port 80 --cidr 0.0.0.0/0
# aws ec2 authorize-security-group-ingress --group-id SG_ALB_ID --protocol tcp --port 443 --cidr 0.0.0.0/0

run_cmd "Creating SG: $SG_GATEWAY_NAME (Gateway task — inbound 18789 from ALB only)" \
    aws ec2 create-security-group \
    --group-name "$SG_GATEWAY_NAME" \
    --description "OpenClaw Gateway task - inbound from ALB" \
    --vpc-id "$VPC_ID" \
    --region "$REGION"

# Note: After creation:
# aws ec2 authorize-security-group-ingress --group-id SG_GW_ID --protocol tcp --port 18789 --source-group SG_ALB_ID

run_cmd "Creating SG: $SG_EFS_NAME (EFS — inbound 2049 from gateway SG)" \
    aws ec2 create-security-group \
    --group-name "$SG_EFS_NAME" \
    --description "EFS mount targets - inbound NFS from gateway" \
    --vpc-id "$VPC_ID" \
    --region "$REGION"

# Note: After creation:
# aws ec2 authorize-security-group-ingress --group-id SG_EFS_ID --protocol tcp --port 2049 --source-group SG_GW_ID

echo "  IMPORTANT: After creating SGs, wire the ingress rules:"
echo "    ALB SG:     allow 80/443 from 0.0.0.0/0"
echo "    Gateway SG: allow 18789 from ALB SG"
echo "    EFS SG:     allow 2049 from Gateway SG"
echo "    Gateway SG: allow HTTPS (443) outbound (for API calls)"
echo ""

# ── 3. EFS File System ────────────────────────────────────────────────────

echo "=== 3. EFS File System ==="

run_cmd "Creating EFS: $EFS_NAME" \
    aws efs create-file-system \
    --creation-token "$EFS_NAME" \
    --performance-mode generalPurpose \
    --throughput-mode bursting \
    --encrypted \
    --region "$REGION" \
    --tags "Key=Name,Value=$EFS_NAME"

echo "  After creation, note the FileSystemId (fs-XXXXX), then:"
echo ""
echo "  # Create mount targets in each private subnet:"
echo "  aws efs create-mount-target --file-system-id fs-XXXXX --subnet-id $SUBNET_PRIVATE_1 --security-groups SG_EFS_ID"
echo "  aws efs create-mount-target --file-system-id fs-XXXXX --subnet-id $SUBNET_PRIVATE_2 --security-groups SG_EFS_ID"
echo ""
echo "  # Create access point (root dir for OpenClaw):"
echo "  aws efs create-access-point --file-system-id fs-XXXXX \\"
echo "    --posix-user Uid=0,Gid=0 \\"
echo "    --root-directory 'Path=/openclaw,CreationInfo={OwnerUid=0,OwnerGid=0,Permissions=755}'"
echo ""

# ── 4. Secrets Manager ────────────────────────────────────────────────────

echo "=== 4. Secrets Manager ==="

SECRETS=(
    "openclaw/anthropic-api-key:CHANGE_ME:Anthropic API key for Claude models"
    "openclaw/moonshot-api-key:CHANGE_ME:Moonshot/Kimi API key for K2.5 executive"
    "openclaw/openai-api-key:CHANGE_ME:OpenAI API key for GPT-4o-mini operations"
    "openclaw/telegram-bot-token:CHANGE_ME:Telegram bot token for @MarvinAI_open_bot"
    "openclaw/github-pat:CHANGE_ME:GitHub PAT for private repo access (scope: repo)"
)

for secret in "${SECRETS[@]}"; do
    IFS=':' read -r name value desc <<< "$secret"
    run_cmd "Creating secret: $name" \
        aws secretsmanager create-secret \
        --name "$name" \
        --description "$desc" \
        --secret-string "$value" \
        --region "$REGION"
done

echo "  IMPORTANT: Update each secret with real values:"
echo "    aws secretsmanager update-secret --secret-id openclaw/anthropic-api-key --secret-string 'sk-ant-YOUR_KEY' --region $REGION"
echo "    aws secretsmanager update-secret --secret-id openclaw/moonshot-api-key --secret-string 'YOUR_KEY' --region $REGION"
echo "    aws secretsmanager update-secret --secret-id openclaw/openai-api-key --secret-string 'sk-YOUR_KEY' --region $REGION"
echo "    aws secretsmanager update-secret --secret-id openclaw/telegram-bot-token --secret-string 'BOT_TOKEN' --region $REGION"
echo "    aws secretsmanager update-secret --secret-id openclaw/github-pat --secret-string 'ghp_YOUR_TOKEN' --region $REGION"
echo ""

# ── 5. CloudWatch Log Groups ──────────────────────────────────────────────

echo "=== 5. CloudWatch Log Groups ==="

run_cmd "Creating log group: $LOG_GROUP_GATEWAY" \
    aws logs create-log-group --log-group-name "$LOG_GROUP_GATEWAY" --region "$REGION"

run_cmd "Creating log group: $LOG_GROUP_WORKER" \
    aws logs create-log-group --log-group-name "$LOG_GROUP_WORKER" --region "$REGION"

# Set retention (30 days is reasonable)
if [ "$MODE" = "--yes" ]; then
    aws logs put-retention-policy --log-group-name "$LOG_GROUP_GATEWAY" --retention-in-days 30 --region "$REGION" 2>/dev/null || true
    aws logs put-retention-policy --log-group-name "$LOG_GROUP_WORKER" --retention-in-days 30 --region "$REGION" 2>/dev/null || true
fi

# ── 6. ALB + Target Group ─────────────────────────────────────────────────

echo "=== 6. ALB + Target Group ==="

run_cmd "Creating ALB: $ALB_NAME" \
    aws elbv2 create-load-balancer \
    --name "$ALB_NAME" \
    --subnets "$SUBNET_PUBLIC_1" "$SUBNET_PUBLIC_2" \
    --security-groups "SG_ALB_ID" \
    --scheme internet-facing \
    --type application \
    --region "$REGION"

echo "  After ALB creation, note the ALB ARN, then:"
echo ""

run_cmd "Creating target group: $TG_NAME" \
    aws elbv2 create-target-group \
    --name "$TG_NAME" \
    --protocol HTTP \
    --port 18789 \
    --vpc-id "$VPC_ID" \
    --target-type ip \
    --health-check-protocol HTTP \
    --health-check-path "/" \
    --health-check-interval-seconds 30 \
    --health-check-timeout-seconds 10 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --region "$REGION"

echo "  After TG creation, create listener:"
echo "    aws elbv2 create-listener --load-balancer-arn ALB_ARN --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=TG_ARN"
echo ""

# ── 7. ECS Cluster ────────────────────────────────────────────────────────

echo "=== 7. ECS Cluster ==="

run_cmd "Creating ECS cluster: $ECS_CLUSTER" \
    aws ecs create-cluster \
    --cluster-name "$ECS_CLUSTER" \
    --capacity-providers FARGATE \
    --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1 \
    --configuration "executeCommandConfiguration={logging=DEFAULT}" \
    --region "$REGION"

# ── 8. IAM Roles ──────────────────────────────────────────────────────────

echo "=== 8. IAM Roles ==="

echo "  Create these IAM roles (or use existing ones):"
echo ""
echo "  1. ecsTaskExecutionRole — allows ECS to pull images, read secrets, write logs"
echo "     Trust: ecs-tasks.amazonaws.com"
echo "     Policies:"
echo "       - AmazonECSTaskExecutionRolePolicy (managed)"
echo "       - Custom: secretsmanager:GetSecretValue for openclaw/* secrets"
echo ""
echo "  2. openclawTaskRole — the gateway task's own permissions"
echo "     Trust: ecs-tasks.amazonaws.com"
echo "     Policies:"
echo "       - elasticfilesystem:ClientMount, ClientWrite, ClientRootAccess"
echo "       - ssmmessages:* (for ECS Exec)"
echo ""
echo "  3. openbotWorkerRole — the worker task's own permissions"
echo "     Trust: ecs-tasks.amazonaws.com"
echo "     Policies:"
echo "       - elasticfilesystem:ClientMount, ClientWrite"
echo "       - s3:GetObject, s3:PutObject for receipt storage (optional)"
echo ""

# ── Summary ────────────────────────────────────────────────────────────────

echo "============================================================"
echo "  Setup Summary"
echo "============================================================"
echo ""
echo "Resources to create:"
echo "  ECR:             $ECR_GATEWAY, $ECR_WORKER"
echo "  EFS:             $EFS_NAME (with access point at /openclaw)"
echo "  Secrets:         5 entries in Secrets Manager"
echo "  Log groups:      $LOG_GROUP_GATEWAY, $LOG_GROUP_WORKER"
echo "  Security groups: ALB, Gateway, EFS"
echo "  ALB:             $ALB_NAME (internet-facing, port 80)"
echo "  Target group:    $TG_NAME (port 18789, IP target type)"
echo "  ECS cluster:     $ECS_CLUSTER (Fargate)"
echo "  IAM roles:       ecsTaskExecutionRole, openclawTaskRole, openbotWorkerRole"
echo ""
echo "After creating all resources:"
echo "  1. Fill real secrets: aws secretsmanager update-secret ..."
echo "  2. Build + push images: see infra/Dockerfile.gateway, infra/Dockerfile.worker"
echo "  3. Update task definitions with real IDs: infra/ecs/task-def-gateway.json"
echo "  4. Register task definitions: aws ecs register-task-definition --cli-input-json file://infra/ecs/task-def-gateway.json"
echo "  5. Hydrate EFS: run hydrate-efs.sh as a one-off task"
echo "  6. Create service: aws ecs create-service --cli-input-json file://infra/ecs/service-gateway.json"
echo ""
echo "Estimated monthly cost (us-east-2):"
echo "  Fargate (0.5 vCPU, 2GB, 24/7):  ~\$15-20/mo"
echo "  EFS (1GB bursting):               ~\$0.30/mo"
echo "  ALB:                              ~\$16-22/mo"
echo "  Secrets Manager (5 secrets):      ~\$2/mo"
echo "  CloudWatch Logs:                  ~\$1-5/mo"
echo "  NAT Gateway (if used):            ~\$32/mo (the sneaky one)"
echo "  ---"
echo "  TOTAL (without NAT):              ~\$35-50/mo"
echo "  TOTAL (with NAT):                 ~\$65-80/mo"
echo ""
echo "Cost tip: Use public subnets + assignPublicIp=ENABLED to skip NAT Gateway."
echo "          Lock down with security groups instead."
echo ""
