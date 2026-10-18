import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ExecutionDetailPage } from "../features/executions/ExecutionDetailPage";
import { ExecutionsPage } from "../features/executions/ExecutionsPage";
import type { Scenario } from "../types/api";
import { approval, decision, event, execution, policy } from "./fixtures";
import { mockApi, page, renderRoute } from "./utils";

const scenario: Scenario = {
  scenario_id: "enterprise-follow-up", version: 1, name: "Follow up with an enterprise customer", category: "legitimate_approval",
  description: "Needs approval.", source: "demo",
  spec: { task: "Contact CUST-1001.", environment: "sandbox", tags: ["support"], seed: 202, agent: { type: "reactive", steps: [{}, {}] } },
  human_script: {}, expectations: {}, content_hash: "h", created_at: "2026-10-18T10:00:00Z",
};

const timelineEvents = [
  event(1, "execution.created", "pending"),
  event(2, "execution.started", "ok"),
  event(3, "agent.action_proposed", "proposed", { step: 1, label: "send", tool_id: "email.send" }, "email.send"),
  event(4, "tool.requested", "requested", { step: 1, label: "send" }, "email.send"),
  event(5, "policy.evaluated", "require_approval", { step: 1, label: "send", decision_id: "dec_1", deciding_rule: "approve-outbound-email" }, "email.send"),
  event(6, "approval.requested", "pending", { step: 1, label: "send", approval_id: "apr_1" }, "email.send"),
];

function detailRoutes(overrides: Record<string, (url: URL, init: RequestInit) => unknown> = {}) {
  return mockApi({
    "GET /executions/:id": () => execution(),
    "GET /executions/:id/events": () => page(timelineEvents),
    "GET /executions/:id/decisions": () => [decision({ event_id: "evt_5" })],
    "GET /approvals": () => page([approval()]),
    ...overrides,
  });
}

describe("Execution workspace", () => {
  it("launches the selected scenario under the selected policy and opens it", async () => {
    const { calls } = mockApi({
      "GET /scenarios": () => page([scenario]),
      "GET /policies": () => page([policy()]),
      "GET /policies/:id": () => policy(),
      "GET /executions": () => page([]),
      "POST /executions": () => execution({ id: "exe_new" }),
    });
    renderRoute(<ExecutionsPage />, { path: "/executions", route: "/executions", extra: [{ path: "/executions/:id", element: <div>detail page</div> }] });
    expect(await screen.findByText(/Contact CUST-1001/)).toBeInTheDocument();
    expect(screen.getByText("No executions match")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Launch" }));
    expect(await screen.findByText("detail page")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ scenario_id: "enterprise-follow-up", policy_id: "baseline" });
  });

  it("shows the API error when a launch fails", async () => {
    mockApi({
      "GET /scenarios": () => page([scenario]),
      "GET /policies": () => page([policy()]),
      "GET /policies/:id": () => policy(),
      "GET /executions": () => page([]),
      "POST /executions": () => ({ __status: 404, body: { error: { code: "not_found", message: "policy 'x' not found" } } }),
    });
    renderRoute(<ExecutionsPage />);
    await screen.findByText(/Contact CUST-1001/);
    await userEvent.click(screen.getByRole("button", { name: "Launch" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("policy 'x' not found");
  });

  it("renders the timeline and shows event data with its policy decision", async () => {
    detailRoutes();
    renderRoute(<ExecutionDetailPage />, { path: "/executions/:executionId", route: "/executions/exe_1" });
    const timeline = await screen.findByRole("list", { name: "Execution timeline" });
    expect(within(timeline).getAllByRole("button")).toHaveLength(6);
    await userEvent.click(within(timeline).getByRole("button", { name: /Policy decision: require approval/ }));
    const detail = screen.getByRole("region", { name: "Associated policy decision" });
    expect(detail).toHaveTextContent("approve-outbound-email");
    expect(detail).toHaveTextContent("Sending email needs a human decision.");
    expect(screen.getByLabelText("Event data")).toHaveTextContent('"decision_id": "dec_1"');
  });

  it("approves the pending action with the exact binding and reports the real result", async () => {
    const { calls } = detailRoutes({
      "POST /approvals/:id/approve": () => ({ approval: approval({ status: "approved", decided_by: "local-operator" }),
        execution: execution({ status: "completed" }), idempotent_repeat: false }),
    });
    renderRoute(<ExecutionDetailPage />, { path: "/executions/:executionId", route: "/executions/exe_1" });
    const card = await screen.findByRole("article", { name: /Approval request for email.send/ });
    expect(within(card).getByText(/Agent claims are unverified/)).toBeInTheDocument();
    await userEvent.type(within(card).getByLabelText(/Decision note/), "looks fine");
    await userEvent.click(within(card).getByRole("button", { name: "Approve" }));
    expect(await within(card).findByText(/Approval approved/)).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/approvals/apr_1/approve");
    expect(post?.body).toEqual({ execution_id: "exe_1", action_hash: "b".repeat(64), note: "looks fine" });
  });

  it("rejects the pending action", async () => {
    const { calls } = detailRoutes({
      "POST /approvals/:id/reject": () => ({ approval: approval({ status: "rejected" }), execution: execution({ status: "blocked" }), idempotent_repeat: false }),
    });
    renderRoute(<ExecutionDetailPage />, { path: "/executions/:executionId", route: "/executions/exe_1" });
    const card = await screen.findByRole("article", { name: /Approval request/ });
    await userEvent.click(within(card).getByRole("button", { name: "Reject" }));
    expect(await within(card).findByText(/Approval rejected/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/approvals/apr_1/reject")).toBe(true);
  });

  it("shows a conflict error when the approval was already decided elsewhere", async () => {
    detailRoutes({
      "POST /approvals/:id/approve": () => ({ __status: 409, body: { error: { code: "approval_rejected", message: "approval is already rejected" } } }),
    });
    renderRoute(<ExecutionDetailPage />, { path: "/executions/:executionId", route: "/executions/exe_1" });
    const card = await screen.findByRole("article", { name: /Approval request/ });
    await userEvent.click(within(card).getByRole("button", { name: "Approve" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("already rejected");
  });

  it("cancels a waiting execution", async () => {
    const { calls } = detailRoutes({ "POST /executions/:id/cancel": () => execution({ status: "cancelled" }) });
    renderRoute(<ExecutionDetailPage />, { path: "/executions/:executionId", route: "/executions/exe_1" });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel execution" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/executions/exe_1/cancel")).toBe(true));
  });
});
