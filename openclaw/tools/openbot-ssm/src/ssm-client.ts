/**
 * SSM Client Wrapper
 *
 * Handles AWS SSM SendCommand and GetCommandInvocation with polling.
 * Uses AWS SDK v3 default credential chain (env vars, shared config, SSO, or IAM role).
 */

import {
  SSMClient,
  SendCommandCommand,
  GetCommandInvocationCommand,
  type SendCommandCommandOutput,
  type GetCommandInvocationCommandOutput,
} from "@aws-sdk/client-ssm";

import {
  type ToolConfig,
  type SSMStatus,
  TERMINAL_STATES,
} from "./types.js";

/**
 * Result of executing a command via SSM
 */
export interface SSMExecutionResult {
  commandId: string;
  status: SSMStatus | "Unknown";
  stdout: string;
  stderr: string;
  durationMs: number;
  error?: string;
}

/**
 * SSM client wrapper with polling support
 */
export class SSMClientWrapper {
  private client: SSMClient;
  private config: ToolConfig;

  constructor(config: ToolConfig) {
    this.config = config;
    // Uses default credential chain - NO embedded credentials
    this.client = new SSMClient({ region: config.region });
  }

  /**
   * Execute a command on the EC2 instance and wait for completion
   */
  async executeCommand(command: string): Promise<SSMExecutionResult> {
    const startTime = Date.now();
    let commandId = "";

    try {
      // Send the command
      const sendResult = await this.sendCommand(command);
      commandId = sendResult.Command?.CommandId ?? "";

      if (!commandId) {
        return {
          commandId: "",
          status: "Unknown",
          stdout: "",
          stderr: "",
          durationMs: Date.now() - startTime,
          error: "No command ID returned from SendCommand",
        };
      }

      // Poll for completion
      const result = await this.pollForCompletion(commandId, startTime);
      return result;

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);

      // Handle specific AWS errors
      if (errorMessage.includes("ThrottlingException")) {
        return {
          commandId,
          status: "Unknown",
          stdout: "",
          stderr: "",
          durationMs: Date.now() - startTime,
          error: "AWS SSM throttling - too many requests. Retry later.",
        };
      }

      if (errorMessage.includes("InvalidInstanceId")) {
        return {
          commandId,
          status: "Undeliverable",
          stdout: "",
          stderr: "",
          durationMs: Date.now() - startTime,
          error: `Instance ${this.config.instanceId} not reachable via SSM`,
        };
      }

      return {
        commandId,
        status: "Unknown",
        stdout: "",
        stderr: "",
        durationMs: Date.now() - startTime,
        error: `SSM error: ${errorMessage}`,
      };
    }
  }

  /**
   * Send a command to the instance
   */
  private async sendCommand(command: string): Promise<SendCommandCommandOutput> {
    const sendCommand = new SendCommandCommand({
      InstanceIds: [this.config.instanceId],
      DocumentName: this.config.documentName,
      Parameters: {
        commands: [command],
      },
      TimeoutSeconds: this.config.timeoutSeconds,
    });

    return this.client.send(sendCommand);
  }

  /**
   * Poll GetCommandInvocation until terminal state
   */
  private async pollForCompletion(
    commandId: string,
    startTime: number
  ): Promise<SSMExecutionResult> {
    const timeoutMs = this.config.timeoutSeconds * 1000;

    while (Date.now() - startTime < timeoutMs) {
      try {
        const invocation = await this.getInvocation(commandId);
        const status = (invocation.Status as SSMStatus) ?? "Unknown";

        if (TERMINAL_STATES.has(status)) {
          return {
            commandId,
            status,
            stdout: this.capOutput(invocation.StandardOutputContent ?? ""),
            stderr: this.capOutput(invocation.StandardErrorContent ?? ""),
            durationMs: Date.now() - startTime,
          };
        }

        // Not terminal - wait and poll again
        await this.sleep(this.config.pollIntervalMs);

      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);

        // InvocationDoesNotExist is normal early in execution - retry
        if (errorMessage.includes("InvocationDoesNotExist")) {
          await this.sleep(this.config.pollIntervalMs);
          continue;
        }

        // Other errors - return with error
        return {
          commandId,
          status: "Unknown",
          stdout: "",
          stderr: "",
          durationMs: Date.now() - startTime,
          error: `Polling error: ${errorMessage}`,
        };
      }
    }

    // Timeout reached
    return {
      commandId,
      status: "TimedOut",
      stdout: "",
      stderr: "",
      durationMs: Date.now() - startTime,
      error: `Command timed out after ${this.config.timeoutSeconds}s`,
    };
  }

  /**
   * Get command invocation details
   */
  private async getInvocation(commandId: string): Promise<GetCommandInvocationCommandOutput> {
    const getCommand = new GetCommandInvocationCommand({
      CommandId: commandId,
      InstanceId: this.config.instanceId,
    });

    return this.client.send(getCommand);
  }

  /**
   * Cap output to configured maximum
   */
  private capOutput(output: string): string {
    if (output.length <= this.config.maxOutputChars) {
      return output;
    }
    return output.substring(0, this.config.maxOutputChars) + "\n[OUTPUT TRUNCATED]";
  }

  /**
   * Sleep helper
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
