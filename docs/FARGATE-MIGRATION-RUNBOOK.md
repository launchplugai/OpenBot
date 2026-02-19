# OpenBot/OpenClaw Fargate Migration Runbook

> **Operational playbook for migrating from EC2 snowflake to Fargate + EFS.**
> Every command is copy-paste ready. Every step has a verification gate.
> If a step fails, the rollback path is immediately below it.
>
> **Target architecture:** Fargate runs compute. EFS holds state. Secrets Manager holds keys.
> No snowflake servers. No losing lessons.json because a box got wiped.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Pre-Migration: Export from Old EC2](#2-pre-migration-export-from-old-ec2)
3. [AWS Foundation: Create Resources](#3-aws-foundation-create-resources)
4. [Build Container Images](#4-build-container-images)
5. [Hydrate EFS](#5-hydrate-efs)
6. [Fill Secrets Manager](#6-fill-secrets-manager)
7. [Register Task Definitions](#7-register-task-definitions)
8. [Deploy Gateway Service](#8-deploy-gateway-service)
9. [Verification Checklist](#9-verification-checklist)
10. [Cutover: EC2 → Fargate](#10-cutover-ec2--fargate)
11. [Post-Cutover Operations](#11-post-cutover-operations)
12. [Rollback: Fargate → EC2](#12-rollback-fargate--ec2)
13. [Day-2 Operations](#13-day-2-operations)
14. [Cost Reality](#14-cost-reality)
15. [Reference: Known Gotchas](#15-reference-known-gotchas)

---

## 1. Architecture Overview

### Before (EC2 Snowflake)

```
Telegram → EC2 i-0dd3b26129b0681ce (t3.medium)
             ├── OpenClaw gateway (systemd)
             ├── /root/.openclaw/ (state on disk)
             ├── /opt/openbot/ (git repo)
             ├── Tailscale
             └── Everything dies if this box dies
```

### After (Fargate + EFS)

```
Telegram → ALB → Fargate Task (openclaw-gateway)
                    ├── EFS mount at /root/.openclaw (persistent state)
                    ├── Secrets from Secrets Manager (injected at boot)
                    └── Logs to CloudWatch

                 Fargate Task (openbot-worker) [scheduled/on-demand]
                    ├── EFS mount (shared read/write)
                    └── Receipts to S3 or CloudWatch
```

### What Lives Where

| Data | Location | Survives redeploy? |
|------|----------|-------------------|
| Memory (MEMORY.md, lessons, daily notes) | EFS | Yes |
| Config (openclaw.json, models.json) | EFS | Yes |
| System prompt (system.md) | EFS | Yes |
| Config profiles (switchable personalities) | EFS | Yes |
| API keys | Secrets Manager | Yes |
| Sessions (/tmp/openclaw/sessions/) | Container /tmp | No (intentional) |
| Gateway process | Fargate task | Recreated on deploy |
| Logs | CloudWatch | Yes |

---

## 2. Pre-Migration: Export from Old EC2

> Run all commands on the **old EC2** via SSM.

### 2.1 Pull Migration Scripts

```bash
aws ssm start-session --target i-0dd3b26129b0681ce --region us-east-2
```

Then on the EC2:

```bash
cd /opt/openbot
git fetch origin claude/fix-openclaw-diagnostics-skxvK
git checkout claude/fix-openclaw-diagnostics-skxvK
git pull origin claude/fix-openclaw-diagnostics-skxvK
```

### 2.2 Dry Run Export

```bash
bash scripts/export-consciousness.sh --dry-run
```

**Expected:** All critical files show `FOUND`. Sessions excluded.

### 2.3 Full Export

```bash
bash scripts/export-consciousness.sh
TARBALL=$(ls -t /tmp/openclaw-transplant-*.tar.gz | head -1)
echo "Tarball: $TARBALL ($(du -h "$TARBALL" | cut -f1))"
```

### 2.4 Verify Secrets Are Scrubbed

```bash
mkdir -p /tmp/transplant-check
tar xzf "$TARBALL" -C /tmp/transplant-check

# Scan for leaked secrets
grep -RIn --exclude-dir=.git -E \
  "(sk-ant-|ghp_|xoxb-|tskey-auth-)" \
  /tmp/transplant-check | grep -v "CHANGE_ME" || echo "CLEAN — no secrets found"

rm -rf /tmp/transplant-check
```

**Gate:** Must show "CLEAN". If secrets found, STOP and re-run export.

### 2.5 Upload to S3

```bash
S3_BUCKET="YOUR-BUCKET"
aws s3 cp "$TARBALL" "s3://${S3_BUCKET}/migration/"
aws s3 ls "s3://${S3_BUCKET}/migration/"
```

---

## 3. AWS Foundation: Create Resources

> Run from your local machine or a CI runner with AWS CLI configured.

### 3.1 Set Environment Variables

```bash
export AWS_REGION=us-east-2
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export VPC_ID=vpc-XXXXX              # Your VPC
export SUBNET_PRIVATE_1=subnet-XXXXX  # Private subnet AZ-a
export SUBNET_PRIVATE_2=subnet-XXXXX  # Private subnet AZ-b
export SUBNET_PUBLIC_1=subnet-XXXXX   # Public subnet AZ-a (for ALB)
export SUBNET_PUBLIC_2=subnet-XXXXX   # Public subnet AZ-b (for ALB)
```

### 3.2 Dry Run

```bash
bash infra/setup-aws.sh --dry-run
```

Review every resource. Then:

### 3.3 Create Resources

```bash
bash infra/setup-aws.sh --yes
```

### 3.4 Manual Steps After Script

The script creates the resources but some wiring requires resource IDs from previous steps. Do these in order:

**A. Security Group Rules:**

```bash
# Get SG IDs
SG_ALB=$(aws ec2 describe-security-groups --filters Name=group-name,Values=openclaw-alb-sg --query 'SecurityGroups[0].GroupId' --output text --region $AWS_REGION)
SG_GW=$(aws ec2 describe-security-groups --filters Name=group-name,Values=openclaw-gateway-sg --query 'SecurityGroups[0].GroupId' --output text --region $AWS_REGION)
SG_EFS=$(aws ec2 describe-security-groups --filters Name=group-name,Values=openclaw-efs-sg --query 'SecurityGroups[0].GroupId' --output text --region $AWS_REGION)

# ALB: allow inbound HTTP from internet
aws ec2 authorize-security-group-ingress --group-id $SG_ALB --protocol tcp --port 80 --cidr 0.0.0.0/0 --region $AWS_REGION

# Gateway: allow inbound 18789 from ALB SG only
aws ec2 authorize-security-group-ingress --group-id $SG_GW --protocol tcp --port 18789 --source-group $SG_ALB --region $AWS_REGION

# EFS: allow inbound NFS (2049) from Gateway SG
aws ec2 authorize-security-group-ingress --group-id $SG_EFS --protocol tcp --port 2049 --source-group $SG_GW --region $AWS_REGION
```

**B. EFS Mount Targets + Access Point:**

```bash
# Get EFS ID
EFS_ID=$(aws efs describe-file-systems --query 'FileSystems[?Name==`openclaw-state`].FileSystemId' --output text --region $AWS_REGION)

# Mount targets in private subnets
aws efs create-mount-target --file-system-id $EFS_ID --subnet-id $SUBNET_PRIVATE_1 --security-groups $SG_EFS --region $AWS_REGION
aws efs create-mount-target --file-system-id $EFS_ID --subnet-id $SUBNET_PRIVATE_2 --security-groups $SG_EFS --region $AWS_REGION

# Wait for mount targets
echo "Waiting for mount targets..."
sleep 30
aws efs describe-mount-targets --file-system-id $EFS_ID --region $AWS_REGION --query 'MountTargets[].LifeCycleState'

# Access point (root owns /openclaw on EFS)
EFS_AP=$(aws efs create-access-point --file-system-id $EFS_ID \
  --posix-user Uid=0,Gid=0 \
  --root-directory "Path=/openclaw,CreationInfo={OwnerUid=0,OwnerGid=0,Permissions=755}" \
  --region $AWS_REGION \
  --query 'AccessPointId' --output text)
echo "Access Point: $EFS_AP"
```

**C. ALB Listener:**

```bash
ALB_ARN=$(aws elbv2 describe-load-balancers --names openclaw-alb --query 'LoadBalancers[0].LoadBalancerArn' --output text --region $AWS_REGION)
TG_ARN=$(aws elbv2 describe-target-groups --names openclaw-tg --query 'TargetGroups[0].TargetGroupArn' --output text --region $AWS_REGION)

aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN --region $AWS_REGION
```

**D. Record Resource IDs:**

```bash
echo "=== Resource IDs ==="
echo "EFS_ID:     $EFS_ID"
echo "EFS_AP:     $EFS_AP"
echo "ALB_ARN:    $ALB_ARN"
echo "TG_ARN:     $TG_ARN"
echo "SG_ALB:     $SG_ALB"
echo "SG_GW:      $SG_GW"
echo "SG_EFS:     $SG_EFS"
```

**Save these. You need them for task definitions.**

### 3.5 IAM Roles

Create if they don't exist:

**ecsTaskExecutionRole** (allows ECS to pull images + read secrets):

```bash
# Trust policy
cat > /tmp/ecs-trust.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role --role-name ecsTaskExecutionRole --assume-role-policy-document file:///tmp/ecs-trust.json
aws iam attach-role-policy --role-name ecsTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Add Secrets Manager access
cat > /tmp/secrets-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:openclaw/*"
  }]
}
EOF

aws iam put-role-policy --role-name ecsTaskExecutionRole --policy-name OpenClawSecretsAccess --policy-document file:///tmp/secrets-policy.json
```

**openclawTaskRole** (gateway task permissions):

```bash
aws iam create-role --role-name openclawTaskRole --assume-role-policy-document file:///tmp/ecs-trust.json

# EFS access
cat > /tmp/efs-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
      "elasticfilesystem:ClientRootAccess"
    ],
    "Resource": "*"
  }]
}
EOF

aws iam put-role-policy --role-name openclawTaskRole --policy-name EFSAccess --policy-document file:///tmp/efs-policy.json

# ECS Exec (for debugging)
cat > /tmp/exec-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel"
    ],
    "Resource": "*"
  }]
}
EOF

aws iam put-role-policy --role-name openclawTaskRole --policy-name ECSExec --policy-document file:///tmp/exec-policy.json
```

---

## 4. Build Container Images

> Run from a machine with Docker installed.

### 4.1 Clone and Checkout

```bash
git clone https://github.com/launchplugai/OpenBot.git
cd OpenBot
git checkout claude/fix-openclaw-diagnostics-skxvK
```

### 4.2 ECR Login

```bash
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
```

### 4.3 Build Gateway Image

```bash
docker build -t openclaw-gateway:latest -f infra/Dockerfile.gateway .
docker tag openclaw-gateway:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openclaw-gateway:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openclaw-gateway:latest
```

**Verify:**

```bash
aws ecr describe-images --repository-name openclaw-gateway --region $AWS_REGION \
  --query 'imageDetails[0].[imagePushedAt,imageSizeInBytes]'
```

### 4.4 Build Worker Image

```bash
docker build -t openbot-worker:latest -f infra/Dockerfile.worker .
docker tag openbot-worker:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openbot-worker:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openbot-worker:latest
```

### 4.5 Local Smoke Test (Optional)

```bash
# Test gateway image locally
mkdir -p /tmp/test-efs/memory /tmp/test-efs/agents/main/agent

docker run --rm -p 18789:18789 \
  -v /tmp/test-efs:/root/.openclaw \
  -e ANTHROPIC_API_KEY=test \
  openclaw-gateway:latest &

sleep 60
curl -s http://localhost:18789/ | head -5
docker stop $(docker ps -q --filter ancestor=openclaw-gateway:latest)
```

---

## 5. Hydrate EFS

> Populate EFS with the transplant data before starting the gateway.

### 5.1 Run Hydration as One-Off Fargate Task

Create a temporary task definition that just runs the hydration:

```bash
# Register a one-off hydration task
cat > /tmp/task-def-hydrate.json << EOF
{
  "family": "openclaw-hydrate",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/openclawTaskRole",
  "volumes": [{
    "name": "openclaw-efs",
    "efsVolumeConfiguration": {
      "fileSystemId": "${EFS_ID}",
      "transitEncryption": "ENABLED",
      "authorizationConfig": {
        "accessPointId": "${EFS_AP}",
        "iam": "ENABLED"
      }
    }
  }],
  "containerDefinitions": [{
    "name": "hydrator",
    "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openbot-worker:latest",
    "essential": true,
    "mountPoints": [{
      "sourceVolume": "openclaw-efs",
      "containerPath": "/root/.openclaw",
      "readOnly": false
    }],
    "command": ["/bin/bash", "-c",
      "bash /opt/openbot/infra/hydrate-efs.sh --from-s3 s3://YOUR-BUCKET/migration/openclaw-transplant-XXXXX.tar.gz --mount-point /root/.openclaw"
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/openbot-worker",
        "awslogs-region": "${AWS_REGION}",
        "awslogs-stream-prefix": "hydrate"
      }
    }
  }]
}
EOF

aws ecs register-task-definition --cli-input-json file:///tmp/task-def-hydrate.json --region $AWS_REGION
```

Run it:

```bash
aws ecs run-task --cluster openclaw \
  --task-definition openclaw-hydrate \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_PRIVATE_1],securityGroups=[$SG_GW],assignPublicIp=ENABLED}" \
  --region $AWS_REGION
```

> **Note:** `assignPublicIp=ENABLED` needed if in public subnet without NAT, so it can reach S3.

### 5.2 Verify Hydration

Check CloudWatch logs for the hydration task:

```bash
aws logs get-log-events --log-group-name /ecs/openbot-worker \
  --log-stream-name "hydrate/hydrator/TASK_ID" \
  --region $AWS_REGION \
  --query 'events[].message' --output text | tail -30
```

**Expected:** All verification checks show `PASS`.

### 5.3 Verify EFS Contents via ECS Exec

If you want to poke around EFS interactively, start a debug task:

```bash
# Run a shell task
aws ecs run-task --cluster openclaw \
  --task-definition openclaw-hydrate \
  --launch-type FARGATE \
  --enable-execute-command \
  --overrides '{"containerOverrides":[{"name":"hydrator","command":["sleep","3600"]}]}' \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_PRIVATE_1],securityGroups=[$SG_GW],assignPublicIp=ENABLED}" \
  --region $AWS_REGION

# Wait for task to start, then exec in:
TASK_ARN=$(aws ecs list-tasks --cluster openclaw --family openclaw-hydrate --query 'taskArns[0]' --output text --region $AWS_REGION)
aws ecs execute-command --cluster openclaw --task $TASK_ARN --container hydrator --interactive --command "/bin/bash" --region $AWS_REGION
```

Then inside:

```bash
ls -la /root/.openclaw/memory/
cat /root/.openclaw/memory/MEMORY.md | head -5
python3 -c "import json; d=json.load(open('/root/.openclaw/memory/lessons.json')); print(f'{len(d)} lessons')"
cat /root/.openclaw/openclaw.json | python3 -c "import json,sys; c=json.load(sys.stdin); print(f'CHANGE_ME count: {json.dumps(c).count(\"CHANGE_ME\")}')"
```

---

## 6. Fill Secrets Manager

### 6.1 Update Each Secret

```bash
# Anthropic API Key
aws secretsmanager update-secret \
  --secret-id openclaw/anthropic-api-key \
  --secret-string "sk-ant-YOUR_REAL_KEY_HERE" \
  --region $AWS_REGION

# Moonshot/Kimi API Key
aws secretsmanager update-secret \
  --secret-id openclaw/moonshot-api-key \
  --secret-string "YOUR_MOONSHOT_KEY" \
  --region $AWS_REGION

# OpenAI API Key
aws secretsmanager update-secret \
  --secret-id openclaw/openai-api-key \
  --secret-string "sk-YOUR_OPENAI_KEY" \
  --region $AWS_REGION

# Telegram Bot Token
aws secretsmanager update-secret \
  --secret-id openclaw/telegram-bot-token \
  --secret-string "123456789:ABCdefGHI..." \
  --region $AWS_REGION

# GitHub PAT
aws secretsmanager update-secret \
  --secret-id openclaw/github-pat \
  --secret-string "ghp_YOUR_TOKEN" \
  --region $AWS_REGION
```

### 6.2 Verify Secrets

```bash
for secret in anthropic-api-key moonshot-api-key openai-api-key telegram-bot-token github-pat; do
    VAL=$(aws secretsmanager get-secret-value --secret-id "openclaw/$secret" --query SecretString --output text --region $AWS_REGION 2>/dev/null)
    if [ "$VAL" = "CHANGE_ME" ] || [ -z "$VAL" ]; then
        echo "MISSING: openclaw/$secret"
    else
        echo "SET:     openclaw/$secret (${VAL:0:6}...)"
    fi
done
```

**Gate:** All secrets show `SET`, none show `MISSING`.

---

## 7. Register Task Definitions

### 7.1 Fill Placeholders in Task Definitions

```bash
cd OpenBot

# Replace placeholders in gateway task def
sed -e "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" \
    -e "s/REGION/${AWS_REGION}/g" \
    -e "s/EFS_FILE_SYSTEM_ID/${EFS_ID}/g" \
    -e "s/EFS_ACCESS_POINT_ID/${EFS_AP}/g" \
    infra/ecs/task-def-gateway.json > /tmp/task-def-gateway-filled.json

# Replace placeholders in worker task def
sed -e "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" \
    -e "s/REGION/${AWS_REGION}/g" \
    -e "s/EFS_FILE_SYSTEM_ID/${EFS_ID}/g" \
    -e "s/EFS_ACCESS_POINT_ID/${EFS_AP}/g" \
    infra/ecs/task-def-worker.json > /tmp/task-def-worker-filled.json
```

### 7.2 Register

```bash
aws ecs register-task-definition --cli-input-json file:///tmp/task-def-gateway-filled.json --region $AWS_REGION
aws ecs register-task-definition --cli-input-json file:///tmp/task-def-worker-filled.json --region $AWS_REGION
```

### 7.3 Verify

```bash
aws ecs describe-task-definition --task-definition openclaw-gateway --region $AWS_REGION \
  --query 'taskDefinition.[family,revision,status]'

aws ecs describe-task-definition --task-definition openbot-worker --region $AWS_REGION \
  --query 'taskDefinition.[family,revision,status]'
```

**Expected:** Both show `ACTIVE`.

---

## 8. Deploy Gateway Service

### 8.1 Fill Service Definition

```bash
sed -e "s/PRIVATE_SUBNET_1/${SUBNET_PRIVATE_1}/g" \
    -e "s/PRIVATE_SUBNET_2/${SUBNET_PRIVATE_2}/g" \
    -e "s/SG_GATEWAY/${SG_GW}/g" \
    -e "s|arn:aws:elasticloadbalancing:REGION:ACCOUNT_ID:targetgroup/openclaw-tg/XXXX|${TG_ARN}|g" \
    infra/ecs/service-gateway.json > /tmp/service-gateway-filled.json
```

### 8.2 Create Service

```bash
aws ecs create-service --cli-input-json file:///tmp/service-gateway-filled.json \
  --cluster openclaw --region $AWS_REGION
```

### 8.3 Wait for Stabilization

```bash
echo "Waiting for service to stabilize (this takes 2-3 minutes)..."
aws ecs wait services-stable --cluster openclaw --services openclaw-gateway --region $AWS_REGION
echo "Service stable."
```

### 8.4 Verify Service

```bash
aws ecs describe-services --cluster openclaw --services openclaw-gateway --region $AWS_REGION \
  --query 'services[0].[status,runningCount,desiredCount,healthCheckGracePeriodSeconds]'
```

**Expected:** `["ACTIVE", 1, 1, 120]`

### 8.5 Verify ALB Health

```bash
ALB_DNS=$(aws elbv2 describe-load-balancers --names openclaw-alb --query 'LoadBalancers[0].DNSName' --output text --region $AWS_REGION)
echo "ALB DNS: $ALB_DNS"

# Check target health
aws elbv2 describe-target-health --target-group-arn $TG_ARN --region $AWS_REGION \
  --query 'TargetHealthDescriptions[0].TargetHealth.State'
```

**Expected:** `"healthy"`

### 8.6 Test Gateway Endpoint

```bash
curl -s --connect-timeout 30 "http://${ALB_DNS}/" | head -10
echo ""
echo "Status: $([ $? -eq 0 ] && echo 'RESPONDING' || echo 'NOT RESPONDING')"
```

---

## 9. Verification Checklist

Run through every one before cutover.

### 9.1 Infrastructure

```bash
echo "=== Infrastructure ==="
echo "ECS Service:  $(aws ecs describe-services --cluster openclaw --services openclaw-gateway --query 'services[0].status' --output text --region $AWS_REGION)"
echo "Running tasks: $(aws ecs describe-services --cluster openclaw --services openclaw-gateway --query 'services[0].runningCount' --output text --region $AWS_REGION)"
echo "ALB healthy:  $(aws elbv2 describe-target-health --target-group-arn $TG_ARN --query 'TargetHealthDescriptions[0].TargetHealth.State' --output text --region $AWS_REGION)"
echo "ALB DNS:      $ALB_DNS"
```

### 9.2 Gateway Health (via ECS Exec)

```bash
TASK_ARN=$(aws ecs list-tasks --cluster openclaw --service-name openclaw-gateway --query 'taskArns[0]' --output text --region $AWS_REGION)

aws ecs execute-command --cluster openclaw --task $TASK_ARN \
  --container openclaw-gateway --interactive \
  --command "curl -s http://localhost:18789/ | head -5" \
  --region $AWS_REGION
```

### 9.3 Memory Intact

```bash
aws ecs execute-command --cluster openclaw --task $TASK_ARN \
  --container openclaw-gateway --interactive \
  --command "bash -c 'echo MEMORY.md: \$(wc -l < /root/.openclaw/memory/MEMORY.md) lines; echo Lessons: \$(python3 -c \"import json; print(len(json.load(open('/root/.openclaw/memory/lessons.json'))))\" 2>/dev/null); echo Daily: \$(ls /root/.openclaw/memory/daily/ | wc -l) notes'" \
  --region $AWS_REGION
```

### 9.4 Secrets Injected

```bash
aws ecs execute-command --cluster openclaw --task $TASK_ARN \
  --container openclaw-gateway --interactive \
  --command "python3 -c \"import json; c=json.load(open('/root/.openclaw/openclaw.json')); cm=json.dumps(c).count('CHANGE_ME'); print(f'CHANGE_ME remaining: {cm}')\"" \
  --region $AWS_REGION
```

**Expected:** `CHANGE_ME remaining: 0`

### 9.5 CloudWatch Logs

```bash
aws logs tail /ecs/openclaw-gateway --since 10m --region $AWS_REGION | tail -20
```

### 9.6 Telegram Bot Test

1. Open Telegram
2. Message `@MarvinAI_open_bot`: "health check"
3. Wait 90 seconds
4. If no response, check logs:

```bash
aws logs tail /ecs/openclaw-gateway --since 5m --region $AWS_REGION | grep -i "error\|telegram\|fatal"
```

### 9.7 OpenBot Worker Test

```bash
aws ecs run-task --cluster openclaw \
  --task-definition openbot-worker \
  --launch-type FARGATE \
  --overrides '{"containerOverrides":[{"name":"openbot-worker","command":["doctor","--local"]}]}' \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_PRIVATE_1],securityGroups=[$SG_GW],assignPublicIp=ENABLED}" \
  --region $AWS_REGION
```

Check worker logs:

```bash
aws logs tail /ecs/openbot-worker --since 5m --region $AWS_REGION
```

---

## 10. Cutover: EC2 → Fargate

> **Only proceed after ALL verification checks pass.**

### 10.1 Stop Old Gateway

On old EC2 via SSM:

```bash
systemctl stop openclaw-gateway
systemctl disable openclaw-gateway
echo "Old gateway stopped."
```

### 10.2 Update Telegram Webhook (if applicable)

If your Telegram bot webhook points to the old Tailscale IP or EC2:

```bash
# Point webhook to ALB DNS
# The exact method depends on your Telegram bot setup
# If OpenClaw handles webhook registration automatically, it should pick up the new endpoint
```

### 10.3 Final Telegram Test

Message `@MarvinAI_open_bot` again. Confirm it responds from Fargate (check CloudWatch logs for activity).

### 10.4 Keep Old EC2 as Rollback (72 Hours)

Do NOT terminate the old EC2 yet. Keep it stopped but available:

```bash
# From local machine — STOP, don't terminate
aws ec2 stop-instances --instance-ids i-0dd3b26129b0681ce --region us-east-2
```

---

## 11. Post-Cutover Operations

### 11.1 Update Documentation

Update `docs/openclaw/ONBOARDING.md` infrastructure section:

| Resource | Old Value | New Value |
|----------|-----------|-----------|
| EC2 Instance | i-0dd3b26129b0681ce | N/A (Fargate) |
| Tailscale IP | 100.101.182.58 | N/A (ALB) |
| Gateway access | SSM → systemd | ECS Exec → Fargate |
| State storage | EC2 disk | EFS |
| Secrets | Config files | Secrets Manager |
| Logs | journalctl | CloudWatch |

### 11.2 Set Up Memory Snapshots

Periodic backup of EFS to S3 (so you have a time machine):

```bash
# Run as scheduled Fargate task (EventBridge every 24h)
aws ecs run-task --cluster openclaw \
  --task-definition openbot-worker \
  --overrides '{"containerOverrides":[{"name":"openbot-worker","command":["/bin/bash","-c","tar czf /tmp/memory-snapshot-$(date +%Y%m%d).tar.gz -C /root/.openclaw memory/ && aws s3 cp /tmp/memory-snapshot-*.tar.gz s3://YOUR-BUCKET/snapshots/"]}]}' \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_PRIVATE_1],securityGroups=[$SG_GW],assignPublicIp=ENABLED}" \
  --region $AWS_REGION
```

### 11.3 Terminate Old EC2 (After 72 Hours)

```bash
aws ec2 terminate-instances --instance-ids i-0dd3b26129b0681ce --region us-east-2
```

---

## 12. Rollback: Fargate → EC2

If Fargate has critical issues:

### 12.1 Restart Old EC2

```bash
aws ec2 start-instances --instance-ids i-0dd3b26129b0681ce --region us-east-2
# Wait for SSM connectivity
sleep 120
aws ssm start-session --target i-0dd3b26129b0681ce --region us-east-2
```

### 12.2 Restart Old Gateway

```bash
systemctl enable openclaw-gateway
systemctl start openclaw-gateway
sleep 60
systemctl is-active openclaw-gateway
```

### 12.3 Stop Fargate Service

```bash
aws ecs update-service --cluster openclaw --service openclaw-gateway --desired-count 0 --region $AWS_REGION
```

### 12.4 Investigate and Retry

Check Fargate logs:

```bash
aws logs tail /ecs/openclaw-gateway --since 1h --region $AWS_REGION | grep -i "error\|fatal\|exception"
```

Fix the issue, redeploy, then cutover again.

---

## 13. Day-2 Operations

### Deploying New Gateway Version

```bash
# Build new image
docker build -t openclaw-gateway:latest -f infra/Dockerfile.gateway .
docker tag openclaw-gateway:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openclaw-gateway:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openclaw-gateway:latest

# Force new deployment (pulls latest image)
aws ecs update-service --cluster openclaw --service openclaw-gateway --force-new-deployment --region $AWS_REGION
```

### Debugging a Running Task

```bash
TASK_ARN=$(aws ecs list-tasks --cluster openclaw --service-name openclaw-gateway --query 'taskArns[0]' --output text --region $AWS_REGION)
aws ecs execute-command --cluster openclaw --task $TASK_ARN --container openclaw-gateway --interactive --command /bin/bash --region $AWS_REGION
```

### Viewing Logs

```bash
# Real-time tail
aws logs tail /ecs/openclaw-gateway --follow --region $AWS_REGION

# Search for errors
aws logs filter-log-events --log-group-name /ecs/openclaw-gateway \
  --filter-pattern "ERROR" --start-time $(date -d '1 hour ago' +%s000) \
  --region $AWS_REGION
```

### Rotating Secrets

```bash
aws secretsmanager update-secret --secret-id openclaw/anthropic-api-key --secret-string "sk-ant-NEW_KEY" --region $AWS_REGION

# Force task restart to pick up new secret
aws ecs update-service --cluster openclaw --service openclaw-gateway --force-new-deployment --region $AWS_REGION
```

### Scaling (If Needed)

```bash
# Scale gateway (usually 1 is enough — be careful with EFS concurrent writes)
aws ecs update-service --cluster openclaw --service openclaw-gateway --desired-count 2 --region $AWS_REGION
```

---

## 14. Cost Reality

| Resource | Monthly Cost (us-east-2) | Notes |
|----------|-------------------------|-------|
| Fargate (0.5 vCPU, 2GB, 24/7) | ~$15-20 | Gateway always-on |
| EFS (1-5GB, bursting) | ~$0.30-1.50 | Memory + config |
| ALB | ~$16-22 | Fixed hourly + LCU |
| Secrets Manager (5 secrets) | ~$2 | $0.40/secret/month |
| CloudWatch Logs (5GB) | ~$2.50 | Ingestion + storage |
| NAT Gateway (if used) | ~$32 + data | **The sneaky one** |
| ECR (image storage) | ~$0.50 | Two images |

| Scenario | Total |
|----------|-------|
| Public subnets, no NAT | **~$37-48/mo** |
| Private subnets + NAT | **~$70-82/mo** |
| Old EC2 (t3.medium) | ~$30/mo |

**Cost tip:** Use public subnets with `assignPublicIp=ENABLED` and strict security groups. Saves ~$32/mo by avoiding NAT Gateway. The ALB handles inbound routing; outbound (API calls) goes direct from the task.

---

## 15. Reference: Known Gotchas

| # | Gotcha | Impact | Fix |
|---|--------|--------|-----|
| 1 | Gateway must bind `0.0.0.0` not `127.0.0.1` | ALB health checks fail | OpenClaw defaults to all interfaces — verify in task logs |
| 2 | EFS mount must be writable | Gateway EPERM crash | Access point with Uid=0, Gid=0, Permissions=755 |
| 3 | Sessions on EFS | Bloat persists across restarts | Never mount /tmp on EFS. entrypoint cleans EFS sessions dir. |
| 4 | Gateway 50s startup | ALB marks target unhealthy too fast | healthCheckGracePeriodSeconds=120 in service def |
| 5 | Secrets only read at task start | Updated secrets need redeploy | `aws ecs update-service --force-new-deployment` |
| 6 | NAT Gateway costs $32/mo | Surprise bill | Use public subnets + SG lockdown instead |
| 7 | Concurrent EFS writes | Two tasks writing same file | Run only 1 gateway task (desiredCount=1) |
| 8 | ECR image pull timeout | Task stuck in PROVISIONING | Check SG allows outbound HTTPS to ECR endpoints |
| 9 | Anthropic baseUrl | Must be `https://api.anthropic.com` (no /v1) | SDK appends /v1/messages |
| 10 | EFS throughput in bursting mode | Slow reads on cold start | Switch to elastic throughput if consistent |

---

*End of runbook. Last updated: 2026-02-19.*
*Architecture: Fargate + EFS + Secrets Manager + ALB + CloudWatch.*
*No snowflake servers. Reboot is a reboot, not a reincarnation.*
