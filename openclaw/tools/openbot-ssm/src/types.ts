/**
 * OpenBot SSM Tool Types
 */

/**
 * Severity levels for tool responses
 */
export type Severity = "OK" | "WARN" | "ERROR" | "UNKNOWN";

/**
 * SSM command execution status
 */
export type SSMStatus =
  | "Pending"
  | "InProgress"
  | "Success"
  | "Failed"
  | "TimedOut"
  | "Cancelled"
  | "Terminated"
  | "Undeliverable";

/**
 * Terminal states for SSM command invocations
 */
export const TERMINAL_STATES: Set<SSMStatus> = new Set([
  "Success",
  "Failed",
  "TimedOut",
  "Cancelled",
  "Terminated",
  "Undeliverable",
]);

/**
 * Tool configuration (from environment/config, not user input)
 */
export interface ToolConfig {
  /** EC2 instance ID */
  instanceId: string;
  /** AWS region */
  region: string;
  /** Command timeout in seconds */
  timeoutSeconds: number;
  /** Polling interval in milliseconds */
  pollIntervalMs: number;
  /** Maximum output characters to return */
  maxOutputChars: number;
  /** SSM document name */
  documentName: string;
  /** Path to openbot CLI on EC2 */
  openbotPath: string;
}

/**
 * Default configuration values
 */
export const DEFAULT_CONFIG: ToolConfig = {
  instanceId: "i-0dd3b26129b0681ce",
  region: "us-east-2",
  timeoutSeconds: 180,
  pollIntervalMs: 1500,
  maxOutputChars: 50000,
  documentName: "AWS-RunShellScript",
  openbotPath: "/usr/local/bin/openbot",
};

/**
 * Tool response structure
 */
export interface ToolResponse {
  /** Whether the operation succeeded */
  ok: boolean;
  /** SSM invocation status */
  ssmStatus: SSMStatus | "Unknown";
  /** Severity level parsed from output */
  severity: Severity;
  /** The exact command invoked */
  command: string;
  /** Standard output (capped) */
  stdout: string;
  /** Standard error (capped) */
  stderr: string;
  /** Combined stdout + stderr (capped) */
  combined: string;
  /** SSM command ID for reference */
  commandId: string;
  /** Execution duration in milliseconds */
  durationMs: number;
  /** Error message if applicable */
  error?: string;
}

/**
 * Allowed actions for the tool
 */
export type ToolAction = "status" | "night_run" | "logs" | "restart";

/**
 * Parameters for logs action
 */
export interface LogsParams {
  lines?: number;
}

/**
 * Bridge output structure (subset of fields we care about)
 */
export interface BridgeOutput {
  ok?: boolean;
  action?: string;
  triage?: {
    severity?: string;
    notify?: boolean;
  };
  error?: {
    type?: string;
    message?: string;
  };
}
