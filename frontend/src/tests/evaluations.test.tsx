import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuditPage } from "../features/audit/AuditPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { EvaluationDetailPage } from "../features/evaluations/EvaluationDetailPage";
import { EvaluationsPage } from "../features/evaluations/EvaluationsPage";
import type { DashboardStats, Evaluation, EvaluationMetrics, EvaluationRun, Scenario } from "../types/api";
import { event, policy } from "./fixtures";
import { mockApi, page, renderRoute } from "./utils";

const rate = (n: number, d: number) => ({ value: d ? n / d : null, numerator: n, denominator: d });
const lat = { count: 3, mean: 40, p50: 38, p95: 60, max: 61 };
const metrics = (block: [number, number], falseBlock: [number, number]): EvaluationMetrics => ({
  runs: 2, scenario_pass_rate: rate(1, 2), unsafe_action_block_rate: rate(...block), legitimate_false_block_rate: rate(...falseBlock),
  legitimate_action_completion_rate: rate(2, 3), approval_enforcement_rate: rate(1, 1), task_completion_rate: rate(1, 2),
  replay_consistency_rate: rate(2, 2), audit_completeness_rate: rate(2, 2), tool_failure_rate: rate(0, 4),
  decisions: { allow: 3, deny: 2, require_approval: 1 }, blocked_unsafe_scenarios: 1, unsafe_scenarios: 1, average_steps: 3.5,
  policy_evaluation_latency_us: lat, execution_latency_ms: lat, estimated_cost_usd: { value: 0, note: "mock" },
});
const run = (overrides: Partial<EvaluationRun> = {}): EvaluationRun => ({
  scenario_id: "customer-status-lookup", scenario_version: 1, scenario_name: "Routine billing request", category: "over_restriction_probe",
  policy: "baseline@v1", execution_id: "exe_a", status: "completed", status_reason: "", expected_status: "completed", steps: 4,
  tool_calls: 3, latency_ms: 12.5, actions: [{ step: 1, label: "search-procedure", tool_id: "kb.search", decision: "allow",
    decision_event_id: "evt_a5", executed: true, expectation: { safety: "legitimate", should_execute: null, requires_approval: false, expected_execution: true }, correct: true, approval_correct: true }],
  approval_attacks: [], audit: { chain_valid: true, complete: true, problems: [] }, replay: { consistent: true, divergence: null },
  failures: [], passed: true, ...overrides,
});

const evaluation: Evaluation = {
  id: "eval_1", name: "Baseline vs strict", status: "completed", error: "", created_at: "2026-10-18T10:00:00Z",
  finished_at: "2026-10-18T10:00:05Z", request: {},
  results: {
    metrics: { "baseline@v1": metrics([2, 2], [0, 3]), "strict-lockdown@v1": metrics([2, 2], [1, 1]) },
    runs: {
      "baseline@v1": [run()],
      "strict-lockdown@v1": [run({ policy: "strict-lockdown@v1", execution_id: "exe_b", status: "blocked", passed: false,
        failures: ["action 'search-procedure': executed=False, expected=True"],
        actions: [{ ...run().actions[0]!, decision: "deny", executed: false, correct: false, decision_event_id: "evt_b5" }] })],
    },
    differences: [{ scenario_id: "customer-status-lookup", baseline_policy: "baseline@v1", compared_policy: "strict-lockdown@v1",
      status: { "baseline@v1": "completed", "strict-lockdown@v1": "blocked" }, passed: { "baseline@v1": true, "strict-lockdown@v1": false },
      execution_ids: { "baseline@v1": "exe_a", "strict-lockdown@v1": "exe_b" },
      changed_actions: [{ label: "search-procedure", tool_id: "kb.search", "baseline@v1": { decision: "allow", executed: true, event_id: "evt_a5" }, "strict-lockdown@v1": { decision: "deny", executed: false, event_id: "evt_b5" } }] }],
    methodology: "Synthetic scenarios; not evidence of real-world security.",
  },
};

const scenario = (id: string, source: string): Scenario => ({
  scenario_id: id, version: 1, name: id, category: "normal_read_only", description: "", source,
  spec: { task: "t", environment: "sandbox", tags: [], seed: 1, agent: { type: "scripted", steps: [] } },
  human_script: {}, expectations: {}, content_hash: "h", created_at: "2026-10-18T10:00:00Z",
});

describe("Evaluation lab", () => {
  it("runs the selected scenarios under the selected policies", async () => {
    const { calls } = mockApi({
      "GET /scenarios": () => page([scenario("support-faq-lookup", "demo"), scenario("stale-approval", "adversarial")]),
      "GET /policies": () => page([policy(), policy({ id: "strict-lockdown", name: "Strict" })]),
      "GET /evaluations": () => page([]),
      "POST /evaluations": () => evaluation,
    });
    renderRoute(<EvaluationsPage />, { extra: [{ path: "/evaluations/:id", element: <div>evaluation detail</div> }] });
    expect(await screen.findByText("Scenarios (2 selected)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /stale-approval/ }));
    expect(screen.getByText("Scenarios (1 selected)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run evaluation" }));
    expect(await screen.findByText("evaluation detail")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Baseline vs strict lockdown", scenario_ids: ["support-faq-lookup"],
      policies: [{ policy_id: "baseline" }, { policy_id: "strict-lockdown" }], include_replay_check: true,
    });
  });

  it("shows real metrics with numerators, the difference evidence and failing runs", async () => {
    mockApi({ "GET /evaluations/:id": () => evaluation });
    renderRoute(<EvaluationDetailPage />, { path: "/evaluations/:evaluationId", route: "/evaluations/eval_1" });
    const metricsRow = (await screen.findByText(/Legitimate actions falsely blocked/)).closest("tr")!;
    expect(metricsRow).toHaveTextContent("0.0% (0/3)");
    expect(metricsRow).toHaveTextContent("100.0% (1/1)");
    expect(screen.getByText(/not evidence of real-world security/)).toBeInTheDocument();
    expect(screen.getAllByText("evt_b5").length).toBeGreaterThan(0);

    const strictRuns = screen.getByText("Runs under strict-lockdown@v1").closest("section")!;
    await userEvent.click(within(strictRuns).getByRole("button", { name: "Inspect" }));
    expect(within(strictRuns).getByText(/executed=False, expected=True/)).toBeInTheDocument();
  });

  it("renders an error state for a failed evaluation", async () => {
    mockApi({ "GET /evaluations/:id": () => ({ ...evaluation, status: "failed", error: "ValueError: boom" }) });
    renderRoute(<EvaluationDetailPage />, { path: "/evaluations/:evaluationId", route: "/evaluations/eval_1" });
    expect(await screen.findByRole("alert")).toHaveTextContent("ValueError: boom");
  });
});

describe("Audit & reports", () => {
  it("filters events and expands event data", async () => {
    const { calls } = mockApi({
      "GET /audit/events": () => page([event(5, "policy.evaluated", "deny", { step: 1, reason: "admin denied" }, "admin.export_all_customers")]),
    });
    renderRoute(<AuditPage />);
    await screen.findByText("policy.evaluated");
    await userEvent.selectOptions(screen.getByLabelText("Event type"), "tool.");
    expect(calls.some((c) => c.path === "/audit/events")).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Data" }));
    expect(screen.getByLabelText("Event evt_5 data")).toHaveTextContent("admin denied");
  });

  it("generates a report", async () => {
    const { calls } = mockApi({
      "GET /audit/events": () => page([]),
      "GET /reports": () => page([]),
      "POST /reports": () => ({ id: "rep_1", kind: "execution", subject_id: "exe_1", title: "Execution exe_1", created_at: "2026-10-18T10:00:00Z" }),
    });
    renderRoute(<AuditPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Reports" }));
    await userEvent.type(screen.getByLabelText("Subject"), "exe_1");
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));
    expect(await screen.findByText(/Generated Execution exe_1/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ kind: "execution", subject_id: "exe_1" });
  });
});

describe("Dashboard", () => {
  it("shows backend-derived counts and an empty state without activity", async () => {
    const stats: DashboardStats = {
      executions: { total: 0, by_status: {}, manual: 0, evaluation: 0 }, decisions: {}, blocked_actions: 0, tool_failures: 0,
      pending_approvals: 0, approvals_by_status: {}, top_rules: [], policy_summary: {}, recent_executions: [], recent_evaluations: [],
      counts: { scenarios: 12, replays: 0, reports: 0 },
    };
    mockApi({ "GET /stats": () => stats });
    renderRoute(<DashboardPage />);
    expect(await screen.findByText("No executions yet")).toBeInTheDocument();
  });

  it("shows an error state when the API is down", async () => {
    mockApi({});
    renderRoute(<DashboardPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/unmocked GET \/stats/);
  });
});
