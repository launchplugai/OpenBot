/**
 * OpenBot SSM Tool for OpenClaw
 *
 * Controls OpenBot automation runtime on EC2 via AWS SSM.
 *
 * @example
 * // As OpenClaw plugin
 * import { createPlugin } from "@openbot/openclaw-ssm-tool";
 * const plugin = createPlugin();
 * // Register plugin.tools with OpenClaw
 *
 * @example
 * // Direct usage
 * import { createTool } from "@openbot/openclaw-ssm-tool";
 * const tool = createTool();
 * const result = await tool.status();
 */

// Plugin exports
export { createPlugin, default } from "./plugin.js";

// Tool exports
export { OpenBotSSMTool, createTool } from "./tool.js";

// SSM client exports
export { SSMClientWrapper } from "./ssm-client.js";

// Type exports
export type {
  ToolConfig,
  ToolResponse,
  Severity,
  SSMStatus,
  ToolAction,
  LogsParams,
  BridgeOutput,
} from "./types.js";

export { DEFAULT_CONFIG, TERMINAL_STATES } from "./types.js";
