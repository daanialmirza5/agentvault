import { expect, test } from "@playwright/test";

// Full user journey against the real backend:
// launch -> tool request -> policy evaluation -> pause for approval -> approve -> verify result
// -> inspect audit trail -> replay -> compare policies -> export a report.
test("approval workflow, audit, replay, policy comparison and export", async ({ page }) => {
  // 1. Launch a deterministic scenario that needs approval.
  await page.goto("/executions");
  await page.getByLabel("Scenario").selectOption("enterprise-follow-up");
  await page.getByLabel("Policy", { exact: true }).selectOption("baseline");
  await page.getByRole("button", { name: "Launch" }).click();
  await expect(page).toHaveURL(/\/executions\/exe_/);
  const executionId = page.url().split("/").pop()!;

  // 2-4. The tool call was requested, evaluated by policy and the execution paused.
  await expect(page.getByText("waiting for approval").first()).toBeVisible();
  const timeline = page.getByRole("list", { name: "Execution timeline" });
  await expect(timeline.getByText("Tool requested: email.send")).toBeVisible();
  await expect(timeline.getByText("Policy decision: require approval")).toBeVisible();
  await expect(timeline.getByText("Paused — waiting for human approval")).toBeVisible();

  // 5-6. Approve the exact action and verify the result.
  const card = page.getByRole("article", { name: /Approval request for email.send/ });
  await expect(card.getByText(/Agent claims are unverified/)).toBeVisible();
  await card.getByLabel(/Decision note/).fill("Reviewed in e2e test");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByText(/Approval approved/)).toBeVisible();
  await expect(page.getByText("completed").first()).toBeVisible();
  await page.getByRole("tab", { name: "Sandbox effects" }).click();
  await expect(page.getByText("outbox (1)")).toBeVisible();

  // 7. Inspect the audit trail and its integrity.
  await page.getByRole("tab", { name: "Timeline" }).click();
  await timeline.getByText("Approval granted").click();
  await expect(page.getByLabel("Event data")).toContainText("Reviewed in e2e test");
  await page.getByRole("button", { name: "Verify audit trail" }).click();
  await expect(page.getByText(/Hash chain valid/)).toBeVisible();
  await expect(page.getByText(/all structural invariants hold/)).toBeVisible();

  // 8. Replay the recorded execution in an isolated simulation.
  await page.getByRole("main").getByRole("link", { name: "Replay" }).click();
  await expect(page).toHaveURL(new RegExp(`/replay\\?execution=${executionId}`));
  await page.getByLabel("Mode").selectOption("simulate");
  await page.getByRole("button", { name: "Start replay" }).click();
  await expect(page.getByText("The event streams are semantically identical.")).toBeVisible();
  await page.getByRole("button", { name: "Next frame" }).click();
  await expect(page.getByText(/Frame 2 \//)).toBeVisible();

  // 8b. Replay the same execution under the strict policy to find the first divergence.
  await page.getByLabel("Policy for simulation").selectOption("strict-lockdown");
  await page.getByRole("button", { name: "Start replay" }).click();
  await expect(page.getByText(/First divergence at comparable position/)).toBeVisible();
  await page.getByRole("button", { name: "Jump to divergence" }).click();
  await expect(page.getByLabel("Frame data")).toContainText("deciding_rule");

  // 9. Compare policy versions on the same scenarios in the evaluation lab.
  await page.goto("/evaluations");
  await page.getByRole("button", { name: "None" }).click();
  await page.getByRole("checkbox", { name: /Routine billing request/ }).check();
  await page.getByRole("checkbox", { name: /Attempt to modify protected records/ }).check();
  await page.getByRole("button", { name: "Run evaluation" }).click();
  await expect(page).toHaveURL(/\/evaluations\/eval_/);
  await expect(page.getByText("Why the policies differ (with evidence)")).toBeVisible();
  const falseBlocks = page.getByRole("row", { name: /Legitimate actions falsely blocked/ });
  await expect(falseBlocks).toContainText("%");

  // 10. Export a report.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Results Markdown" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^rep_.*\.md$/);
});

test("unauthorised tool calls are denied and visible in the audit log", async ({ page }) => {
  await page.goto("/executions");
  await page.getByLabel("Scenario").selectOption("unauthorized-tool-call");
  await page.getByRole("button", { name: "Launch" }).click();
  await expect(page).toHaveURL(/\/executions\/exe_/);
  const timeline = page.getByRole("list", { name: "Execution timeline" });
  await expect(timeline.getByText("Tool requested: shell.exec (not registered)")).toBeVisible();
  await expect(timeline.getByText("Action blocked (unknown tool)")).toBeVisible();
  await expect(timeline.getByText("Action blocked (denied)")).toBeVisible();
  await page.getByRole("tab", { name: /Policy decisions/ }).click();
  await expect(page.getByText("builtin:unknown_tool")).toBeVisible();
  await expect(page.getByText("deny-admin-tools")).toBeVisible();
});

test("rejecting an approval means the action never runs", async ({ page }) => {
  await page.goto("/executions");
  await page.getByLabel("Scenario").selectOption("stale-approval");
  await page.getByRole("button", { name: "Launch" }).click();
  await page.goto("/approvals");
  const card = page.getByRole("article", { name: /Approval request for email.send/ }).first();
  await card.getByRole("button", { name: "Reject" }).click();
  await expect(card.getByText(/Approval rejected/)).toBeVisible();
  await card.getByRole("link").first().click();
  await expect(page.getByText("blocked").first()).toBeVisible();
  await page.getByRole("tab", { name: "Sandbox effects" }).click();
  await expect(page.getByText("outbox (0)")).toBeVisible();
});
