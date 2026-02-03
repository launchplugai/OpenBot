/**
 * Standalone usage example
 *
 * Run with:
 *   npx ts-node examples/standalone.ts
 *
 * Or after building:
 *   node dist/examples/standalone.js
 *
 * Requires AWS credentials in environment or ~/.aws/credentials
 */

import { createTool } from "../src/index.js";

async function main() {
  console.log("=== OpenBot SSM Tool - Standalone Example ===\n");

  // Create tool with default config (or pass overrides)
  const tool = createTool({
    // Uncomment to override defaults:
    // instanceId: "i-0dd3b26129b0681ce",
    // region: "us-east-2",
    // timeoutSeconds: 120,
  });

  console.log("Config:", tool.getConfig());
  console.log("");

  // --- Status ---
  console.log("--- Checking Status ---");
  const status = await tool.status();
  console.log("OK:", status.ok);
  console.log("Severity:", status.severity);
  console.log("SSM Status:", status.ssmStatus);
  console.log("Duration:", status.durationMs, "ms");
  if (status.error) {
    console.log("Error:", status.error);
  } else {
    // Parse and display bridge output
    try {
      const data = JSON.parse(status.stdout);
      console.log("Doctor Status:", data.doctor?.data?.overall_status);
      console.log("Service State:", data.service?.state);
      console.log("Latest Receipt:", data.latest_receipt?.data?.overall_status);
      console.log("Triage Severity:", data.triage?.severity);
    } catch {
      console.log("Raw Output:", status.stdout.substring(0, 500));
    }
  }
  console.log("");

  // --- Logs ---
  console.log("--- Fetching Logs (10 lines) ---");
  const logs = await tool.logs({ lines: 10 });
  console.log("OK:", logs.ok);
  console.log("Lines:", logs.stdout.split("\n").length);
  console.log("Duration:", logs.durationMs, "ms");
  console.log("");

  // --- Summary ---
  console.log("=== Summary ===");
  console.log(`Status: ${status.severity}`);
  console.log(`Should Notify: ${status.severity !== "OK"}`);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
