import { spawn } from "node:child_process";

const NODE_BIN = "/usr/bin/node";
const DSH_BIN = "/usr/bin/dsh";
const COOKIE_HOOK = "/usr/lib/deepseek-harness/relax-cookie.mjs";
const PORT = process.env.DSH_WEB_PORT;

if (!PORT || !/^\d+$/.test(PORT)) {
  throw new Error(`dsh-web: DSH_WEB_PORT must be a valid port number, got: ${String(PORT)}`);
}

const child = spawn(NODE_BIN, [
  "--import",
  COOKIE_HOOK,
  DSH_BIN,
  "--profile",
  "web",
  "--no-open",
  "--port",
  PORT,
], {
  env: process.env,
  stdio: "inherit",
});

const forward = (signal) => {
  child.kill(signal);
};
process.on("SIGTERM", () => forward("SIGTERM"));
process.on("SIGINT", () => forward("SIGINT"));

child.on("error", (error) => {
  throw new Error(`dsh-web: failed to start dsh: ${error.message}`);
});

child.on("exit", (code, signal) => {
  if (code !== null) process.exit(code);
  if (signal === null) throw new Error("dsh-web: dsh exited without a status");
  process.removeAllListeners(signal);
  process.kill(process.pid, signal);
});
