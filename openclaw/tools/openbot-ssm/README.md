# OpenBot SSM Tool for OpenClaw

Control OpenBot automation runtime on EC2 via AWS Systems Manager (SSM).

## Features

- **SSM-only access** - No SSH, no inbound ports required
- **Secure credentials** - Uses AWS SDK default credential chain (no embedded secrets)
- **Allowlisted commands** - Only executes OpenBot bridge subcommands
- **Capped output** - Prevents memory issues with large outputs
- **Severity parsing** - Extracts severity from bridge output for notification decisions

## Installation

```bash
npm install @openbot/openclaw-ssm-tool
```

## Configuration

### AWS Credentials

The tool uses the AWS SDK v3 default credential chain. Set credentials via:

1. Environment variables:
   ```bash
   export AWS_ACCESS_KEY_ID=your-key
   export AWS_SECRET_ACCESS_KEY=your-secret
   export AWS_REGION=us-east-2
   ```

2. Shared credentials file (`~/.aws/credentials`)

3. AWS SSO configuration

4. IAM role (when running on AWS infrastructure)

**Never embed credentials in code or configuration files.**

### Tool Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENBOT_INSTANCE_ID` | `i-0dd3b26129b0681ce` | EC2 instance ID |
| `OPENBOT_REGION` | `us-east-2` | AWS region |
| `OPENBOT_TIMEOUT_SECONDS` | `180` | Command timeout |
| `OPENBOT_POLL_INTERVAL_MS` | `1500` | Polling interval |
| `OPENBOT_MAX_OUTPUT_CHARS` | `50000` | Max output size |
| `OPENBOT_PATH` | `/usr/local/bin/openbot` | OpenBot CLI path |

## Usage

### As OpenClaw Plugin

```typescript
import { createPlugin } from "@openbot/openclaw-ssm-tool";

const plugin = createPlugin();
// Register plugin.tools with OpenClaw
```

### Direct Usage

```typescript
import { createTool } from "@openbot/openclaw-ssm-tool";

const tool = createTool();

// Get status
const status = await tool.status();
console.log(status);
// {
//   ok: true,
//   ssmStatus: "Success",
//   severity: "OK",
//   command: "openbot status",
//   stdout: "{ ... }",
//   ...
// }

// Trigger night run
const run = await tool.nightRun();

// Get logs
const logs = await tool.logs({ lines: 50 });

// Restart service
const restart = await tool.restart();
```

### Tool Call Shapes

When used as an OpenClaw tool, calls look like:

```json
{
  "name": "openbot_ssm",
  "parameters": {
    "action": "status"
  }
}
```

```json
{
  "name": "openbot_ssm",
  "parameters": {
    "action": "night_run"
  }
}
```

```json
{
  "name": "openbot_ssm",
  "parameters": {
    "action": "logs",
    "lines": 100
  }
}
```

```json
{
  "name": "openbot_ssm",
  "parameters": {
    "action": "restart"
  }
}
```

## Response Structure

All actions return:

```typescript
interface ToolResponse {
  ok: boolean;              // Overall success
  ssmStatus: string;        // SSM invocation status
  severity: "OK" | "WARN" | "ERROR" | "UNKNOWN";
  command: string;          // Command executed
  stdout: string;           // Standard output (capped)
  stderr: string;           // Standard error (capped)
  combined: string;         // Combined output (capped)
  commandId: string;        // SSM command ID
  durationMs: number;       // Execution time
  error?: string;           // Error message if applicable
}
```

## Severity Levels

The tool parses severity from OpenBot bridge output:

| Severity | Meaning | Notify |
|----------|---------|--------|
| `OK` | All systems healthy | No |
| `WARN` | Degraded but functional | Yes |
| `ERROR` | Tests failed or system error | Yes |
| `UNKNOWN` | Could not determine | Maybe |

## Security

### Allowlisted Commands

Only these commands can be executed:

- `openbot bridge status`
- `openbot bridge night-run`
- `openbot bridge logs -n <lines>`
- `openbot bridge service restart`

### Output Sanitization

OpenBot bridge already redacts secrets in output. The tool additionally caps output size to prevent memory issues.

### Forbidden Paths

The bridge blocks access to:
- `/etc/openbot/credentials.yaml`
- `/etc/openbot/credentials`
- `/etc/openbot/github_token`

## OpenClaw Config Example

```yaml
plugins:
  - name: openbot-ssm
    path: "@openbot/openclaw-ssm-tool"

agents:
  main:
    allowed_tools:
      - openbot_ssm
```

See `examples/openclaw-config.yaml` for full example.

## Error Handling

The tool handles:

- **SSM throttling** - Returns clear error message
- **Instance unreachable** - Returns `Undeliverable` status
- **Command timeout** - Returns `TimedOut` status
- **Invalid parameters** - Validates before execution

## License

MIT
