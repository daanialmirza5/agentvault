// Smoke-checks a deployed AgentVault UI: every page renders and the console has no errors
// (including Content-Security-Policy violations).
// Usage: node e2e/smoke-deployed.mjs http://127.0.0.1:8090
import { chromium } from "@playwright/test";

const base = (process.argv[2] ?? "http://127.0.0.1:8090").replace(/\/$/, "");
const pages = ["/", "/executions", "/approvals", "/replay", "/policies", "/tools", "/evaluations", "/audit"];
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on("console", (msg) => msg.type() === "error" && errors.push(`${page.url()}: ${msg.text()}`));
page.on("pageerror", (err) => errors.push(`${page.url()}: ${err.message}`));

for (const path of pages) {
  await page.goto(base + path, { waitUntil: "networkidle" });
  const heading = await page.locator("main h1").first().textContent({ timeout: 15000 });
  console.log(`${path.padEnd(14)} -> ${heading}`);
}
// The execution detail page uses the flow-graph library (inline styles under CSP).
const first = await page.request.get(`${base}/api/v1/executions?limit=1`).then((r) => r.json());
if (first.items?.length) {
  await page.goto(`${base}/executions/${first.items[0].id}`, { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: "Flow graph" }).click();
  await page.locator(".react-flow__node").first().waitFor({ timeout: 15000 });
  console.log(`flow graph     -> ${await page.locator(".react-flow__node").count()} nodes rendered`);
}
await browser.close();
if (errors.length) {
  console.error("Console errors:\n" + errors.join("\n"));
  process.exit(1);
}
console.log("No console errors.");
