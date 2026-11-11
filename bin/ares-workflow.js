#!/usr/bin/env node
// Runs the bundled workflow.py with python3, passing every argument through.
const { spawnSync } = require("child_process");
const path = require("path");

const python = process.env.PYTHON || "python3";
const script = path.join(__dirname, "..", "workflow.py");
const result = spawnSync(python, ["-B", script, ...process.argv.slice(2)], { stdio: "inherit" });
if (result.error) {
  console.error("ares-workflow needs Python 3.11+ (" + python + "): " + result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
