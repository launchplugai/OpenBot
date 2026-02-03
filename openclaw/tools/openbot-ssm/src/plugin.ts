/**
 * OpenClaw Plugin Registration
 *
 * Registers the openbot_ssm tool with OpenClaw.
 * Tool must be explicitly allowlisted in agent config to be available.
 */

import { OpenBotSSMTool, createTool } from "./tool.js";
import type { ToolConfig, ToolResponse, LogsParams } from "./types.js";

/**
 * OpenClaw tool definition interface
 */
export interface OpenClawToolDefinition {
  name: string;
  description: string;
  parameters: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
  execute: (params: Record<string, unknown>) => Promise<ToolResponse>;
}

/**
 * OpenClaw plugin interface
 */
export interface OpenClawPlugin {
  name: string;
  version: string;
  tools: OpenClawToolDefinition[];
}

/**
 * Create the OpenClaw plugin
 */
export function createPlugin(config: Partial<ToolConfig> = {}): OpenClawPlugin {
  const tool = createTool(config);

  return {
    name: "openbot-ssm",
    version: "0.1.0",
    tools: [
      {
        name: "openbot_ssm",
        description: `Control OpenBot automation runtime on EC2 via AWS SSM.
Available actions:
- status: Get combined health check (doctor + service + receipt + triage)
- night_run: Trigger a test run and return results with triage
- logs: Fetch journal logs for openbot-run.service
- restart: Restart the openbot-run.service

All commands execute on EC2 via SSM - no SSH or direct access required.
Output is JSON with severity levels (OK/WARN/ERROR) for notification decisions.`,
        parameters: {
          type: "object",
          properties: {
            action: {
              type: "string",
              enum: ["status", "night_run", "logs", "restart"],
              description: "The action to perform",
            },
            lines: {
              type: "number",
              description: "Number of log lines to fetch (1-1000, default 120). Only used with 'logs' action.",
            },
          },
          required: ["action"],
        },
        execute: async (params: Record<string, unknown>): Promise<ToolResponse> => {
          const action = params.action as string;

          switch (action) {
            case "status":
              return tool.status();

            case "night_run":
              return tool.nightRun();

            case "logs": {
              const logsParams: LogsParams = {};
              if (typeof params.lines === "number") {
                logsParams.lines = params.lines;
              }
              return tool.logs(logsParams);
            }

            case "restart":
              return tool.restart();

            default:
              return {
                ok: false,
                ssmStatus: "Unknown",
                severity: "ERROR",
                command: `unknown action: ${action}`,
                stdout: "",
                stderr: "",
                combined: "",
                commandId: "",
                durationMs: 0,
                error: `Unknown action: ${action}. Valid actions: status, night_run, logs, restart`,
              };
          }
        },
      },
    ],
  };
}

/**
 * Default export for direct import
 */
export default createPlugin;

/**
 * Tool instance factory for direct use (without OpenClaw)
 */
export { createTool, OpenBotSSMTool };
export type { ToolConfig, ToolResponse, LogsParams };
