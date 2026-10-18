import { expect, test, type Page } from "@playwright/test";

// Captures the screenshots used in the README from the real running application.
// Every number visible in them comes from activity this script creates through the UI and API.
// Run with: npm run screenshots   (expects a fresh database for clean images)

const OUT = "../docs/screenshots";
const API = `http://127.0.0.1:${process.env.AGENTVAULT_E2E_API_PORT ?? 8000}/api/v1`;

async function shot(page: Page, name: string, fullPage = false) {
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage });
}

async function launch(page: Page, scenario: string, policy = "baseline"): Promise<string> {
  const r = await page.request.post(`${API}/executions`, { data: { scenario_id: scenario, policy_id: policy } });
  expect(r.ok()).toBeTruthy();
  return (await r.json()).id as string;
}

test.describe.configure({ mode: "serial" });

test("capture product screenshots", async ({ page }) => {
  test.setTimeout(180_000);

  // Activity: a full three-policy evaluation plus a few manual runs.
  const evaluation = await page.request.post(`${API}/evaluations`, {
    data: { name: "Baseline vs strict vs permissive", policies: [{ policy_id: "baseline" }, { policy_id: "strict-lockdown" }, { policy_id: "permissive-dev" }], include_replay_check: true },
    timeout: 120_000,
  });
  expect(evaluation.ok()).toBeTruthy();
  const evaluationId = (await evaluation.json()).id as string;
  await launch(page, "support-faq-lookup");
  await launch(page, "unauthorized-tool-call");
  await launch(page, "untrusted-content-injection");
  const followUp = await launch(page, "enterprise-follow-up");
  await launch(page, "protected-resource-modification");

  // Approval queue with real pending requests.
  await page.goto("/approvals");
  await expect(page.getByRole("article").first()).toBeVisible();
  await shot(page, "approval-queue");

  // Approve the follow-up through the UI and show its timeline with the decision panel.
  await page.goto(`/executions/${followUp}`);
  await page.getByRole("article", { name: /Approval request/ }).getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Approval approved/)).toBeVisible();
  await page.reload();
  const timeline = page.getByRole("list", { name: "Execution timeline" });
  await timeline.getByText("Policy decision: require approval").click();
  await shot(page, "execution-timeline");
  await page.getByRole("tab", { name: "Flow graph" }).click();
  await expect(page.getByLabel("Execution flow graph")).toBeVisible();
  await shot(page, "execution-flow-graph");

  // Replay under a stricter policy with the first divergence highlighted.
  await page.goto(`/replay?execution=${followUp}`);
  await page.getByLabel("Mode").selectOption("simulate");
  await page.getByLabel("Policy for simulation").selectOption("strict-lockdown");
  await page.getByRole("button", { name: "Start replay" }).click();
  await page.getByRole("button", { name: "Jump to divergence" }).click();
  await shot(page, "replay-divergence");

  // Evaluation lab results.
  await page.goto(`/evaluations/${evaluationId}`);
  await expect(page.getByText("Metrics by policy version")).toBeVisible();
  await shot(page, "evaluation-results", true);

  // Policy editor and comparison.
  await page.goto("/policies");
  await expect(page.getByText(/Editing Baseline support policy/)).toBeVisible();
  await shot(page, "policy-editor");
  await page.getByRole("tab", { name: "Compare" }).click();
  await page.getByLabel("Right policy").selectOption("strict-lockdown");
  await page.getByRole("button", { name: "Compare" }).click();
  await expect(page.getByText("Static decision matrix")).toBeVisible();
  await shot(page, "policy-compare");

  // Tool registry, audit log and dashboard.
  await page.goto("/tools");
  await page.getByRole("button", { name: /Send email/ }).click();
  await shot(page, "tool-registry");
  await page.goto("/audit");
  await page.getByLabel("Event type").selectOption("tool.blocked");
  await expect(page.getByRole("cell", { name: "tool.blocked" }).first()).toBeVisible();
  await shot(page, "audit-log");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Policy decisions" })).toBeVisible();
  await page.waitForTimeout(800); // let the charts finish their entry animation
  await shot(page, "dashboard");
});
