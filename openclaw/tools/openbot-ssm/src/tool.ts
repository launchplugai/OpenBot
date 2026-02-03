/**
 * OpenBot SSM Tool
 *
 * OpenClaw tool that controls OpenBot on EC2 via AWS SSM.
 * Only executes allowlisted bridge commands.
 */

import {
  type ToolConfig,
  type ToolResponse,
  type Severity,
  type BridgeOutput,
  type LogsParams,
  DEFAULT_CONFIG,
} from "./types.js";
import { SSMClientWrapper } from "./ssm-client.js";

/**
 * Allowed bridge commands (whitelist)
 */
const ALLOWED_COMMANDS = new Set(["status", "night-run", "logs", "service"]);

/**
 * OpenBot SSM Tool implementation
 */
export class OpenBotSSMTool {
  private config: ToolConfig;
  private ssmClient: SSMClientWrapper;

  constructor(config: Partial<ToolConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.ssmClient = new SSMClientWrapper(this.config);
  }

  /**
   * Get combined status: doctor + service + latest receipt + triage
   */
  async status(): Promise<ToolResponse> {
    const command = this.buildCommand("bridge", "status");
    return this.execute(command, "status");
  }

  /**
   * Trigger a test run and return results with triage
   */
  async nightRun(): Promise<ToolResponse> {
    const command = this.buildCommand("bridge", "night-run");
    return this.execute(command, "night-run");
  }

  /**
   * Get journal logs for openbot-run.service
   */
  async logs(params: LogsParams = {}): Promise<ToolResponse> {
    const lines = params.lines ?? 120;

    // Validate lines parameter
    if (lines < 1 || lines > 1000) {
      return this.errorResponse(
        "logs",
        `Invalid lines parameter: ${lines}. Must be 1-1000.`
      );
    }

    // Try with --lines flag first, fallback to positional
    const command = this.buildCommand("bridge", "logs", `-n ${lines}`);
    return this.execute(command, `logs -n ${lines}`);
  }

  /**
   * Restart the openbot-run.service
   */
  async restart(): Promise<ToolResponse> {
    const command = this.buildCommand("bridge", "service", "restart");
    return this.execute(command, "service restart");
  }

  /**
   * Build a command string with proper escaping
   */
  private buildCommand(group: string, subcommand: string, args?: string): string {
    // Validate subcommand is in allowlist
    if (!ALLOWED_COMMANDS.has(subcommand)) {
      throw new Error(`Command not allowed: ${subcommand}`);
    }

    const parts = [
      "sudo", "-n",
      this.config.openbotPath,
      group,
      subcommand,
    ];

    if (args) {
      parts.push(args);
    }

    return parts.join(" ");
  }

  /**
   * Execute a command and return structured response
   */
  private async execute(command: string, displayCommand: string): Promise<ToolResponse> {
    const result = await this.ssmClient.executeCommand(command);

    const combined = this.combineOutput(result.stdout, result.stderr);
    const severity = this.parseSeverity(result.stdout, result.stderr, result.status);
    const ok = result.status === "Success" && severity !== "ERROR";

    return {
      ok,
      ssmStatus: result.status,
      severity,
      command: `openbot ${displayCommand}`,
      stdout: result.stdout,
      stderr: result.stderr,
      combined,
      commandId: result.commandId,
      durationMs: result.durationMs,
      error: result.error,
    };
  }

  /**
   * Combine stdout and stderr with capping
   */
  private combineOutput(stdout: string, stderr: string): string {
    const combined = stdout + (stderr ? `\n--- stderr ---\n${stderr}` : "");
    if (combined.length > this.config.maxOutputChars) {
      return combined.substring(0, this.config.maxOutputChars) + "\n[OUTPUT TRUNCATED]";
    }
    return combined;
  }

  /**
   * Parse severity from bridge output or use heuristics
   */
  private parseSeverity(stdout: string, stderr: string, ssmStatus: string): Severity {
    // SSM-level failures
    if (ssmStatus !== "Success") {
      return "ERROR";
    }

    // Try to parse bridge JSON output
    try {
      const data = JSON.parse(stdout) as BridgeOutput;

      // Explicit triage severity
      if (data.triage?.severity) {
        const s = data.triage.severity.toUpperCase();
        if (s === "OK") return "OK";
        if (s === "WARN") return "WARN";
        if (s === "FAIL" || s === "ERROR") return "ERROR";
      }

      // Check ok field
      if (data.ok === false) {
        return "ERROR";
      }

      if (data.ok === true) {
        return "OK";
      }

    } catch {
      // Not valid JSON - use heuristics
    }

    // Heuristic fallbacks
    const combined = (stdout + stderr).toUpperCase();

    if (combined.includes("ERROR") || combined.includes("FAIL") || combined.includes("FATAL")) {
      return "ERROR";
    }

    if (combined.includes("WARN")) {
      return "WARN";
    }

    // If we have stdout and no obvious errors, assume OK
    if (stdout.trim().length > 0) {
      return "OK";
    }

    return "UNKNOWN";
  }

  /**
   * Create an error response without executing
   */
  private errorResponse(command: string, error: string): ToolResponse {
    return {
      ok: false,
      ssmStatus: "Unknown",
      severity: "ERROR",
      command: `openbot bridge ${command}`,
      stdout: "",
      stderr: "",
      combined: "",
      commandId: "",
      durationMs: 0,
      error,
    };
  }

  /**
   * Get current configuration (for debugging)
   */
  getConfig(): Readonly<ToolConfig> {
    return { ...this.config };
  }
}

/**
 * Create a tool instance with configuration from environment
 */
export function createTool(overrides: Partial<ToolConfig> = {}): OpenBotSSMTool {
  const config: Partial<ToolConfig> = {
    instanceId: process.env.OPENBOT_INSTANCE_ID || DEFAULT_CONFIG.instanceId,
    region: process.env.OPENBOT_REGION || process.env.AWS_REGION || DEFAULT_CONFIG.region,
    timeoutSeconds: parseInt(process.env.OPENBOT_TIMEOUT_SECONDS || "", 10) || DEFAULT_CONFIG.timeoutSeconds,
    pollIntervalMs: parseInt(process.env.OPENBOT_POLL_INTERVAL_MS || "", 10) || DEFAULT_CONFIG.pollIntervalMs,
    maxOutputChars: parseInt(process.env.OPENBOT_MAX_OUTPUT_CHARS || "", 10) || DEFAULT_CONFIG.maxOutputChars,
    openbotPath: process.env.OPENBOT_PATH || DEFAULT_CONFIG.openbotPath,
    ...overrides,
  };

  return new OpenBotSSMTool(config);
}
