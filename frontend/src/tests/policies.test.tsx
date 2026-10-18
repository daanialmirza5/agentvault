import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { normaliseDocument, parseConditionValue } from "../features/policies/policyDocument";
import { PoliciesPage } from "../features/policies/PoliciesPage";
import type { PolicyComparison } from "../types/api";
import { policy, tool } from "./fixtures";
import { mockApi, page, renderRoute } from "./utils";

const strict = policy({ id: "strict-lockdown", name: "Strict lockdown", description: "Over-restrictive." });

function routes(extra: Record<string, (url: URL, init: RequestInit) => unknown> = {}) {
  return mockApi({
    "GET /policies": () => page([policy(), strict]),
    "GET /policies/:id": (url) => (url.pathname.endsWith("strict-lockdown") ? strict : policy()),
    "GET /tools": () => page([tool()]),
    ...extra,
  });
}

describe("Policy editor", () => {
  it("edits a rule, validates, and saves a new version bound to the base version", async () => {
    const { calls } = routes({
      "POST /policies/validate": () => ({ valid: true, issues: [{ severity: "info", code: "overlapping_rules", message: "Rules overlap; deny wins.", rule_ids: [] }] }),
      "POST /policies/:id/versions": () => ({ ...policy().versions[0], version: 2 }),
    });
    renderRoute(<PoliciesPage />);
    await screen.findByText("Editing Baseline support policy — based on v1");
    await userEvent.selectOptions(screen.getAllByLabelText("Effect")[0]!, "deny");

    await userEvent.click(screen.getByRole("button", { name: "Validate" }));
    expect(await screen.findByText(/Rules overlap; deny wins/)).toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Save as v2" });
    expect(save).toBeDisabled(); // a change note is required
    await userEvent.type(screen.getByLabelText("Change note"), "Deny reads for audit");
    await userEvent.click(save);
    expect(await screen.findByText("Saved baseline v2.")).toBeInTheDocument();

    const post = calls.find((c) => c.path === "/policies/baseline/versions");
    const body = post?.body as { base_version: number; change_note: string; document: { rules: { effect: string }[] } };
    expect(body.base_version).toBe(1);
    expect(body.change_note).toBe("Deny reads for audit");
    expect(body.document.rules[0]!.effect).toBe("deny");
  });

  it("shows the conflict when someone else saved first", async () => {
    routes({
      "POST /policies/:id/versions": () => ({ __status: 409, body: { error: { code: "stale_policy_version", message: "policy was modified: latest version is 2, not 1" } } }),
    });
    renderRoute(<PoliciesPage />);
    await screen.findByText(/based on v1/);
    await userEvent.type(screen.getByLabelText("Change note"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save as v2" }));
    expect(await screen.findByText(/latest version is 2/)).toBeInTheDocument();
  });

  it("compares two policies and highlights differing tools", async () => {
    const comparison: PolicyComparison = {
      left: "baseline@v1", right: "strict-lockdown@v1",
      diff: { default_effect: { before: "deny", after: "deny", changed: false },
        added: [{ id: "approve-all-writes", description: "", effect: "require_approval", priority: 50, enabled: true, match: {} }],
        removed: [], changed: [] },
      matrix: [{ tool_id: "kb.search", risk_level: "low", outcomes: { "baseline@v1": { outcome: "allow", rule: "allow-low-risk-reads" }, "strict-lockdown@v1": { outcome: "deny", rule: "builtin:default_effect" } } }],
      note: "static",
    };
    const { calls } = routes({ "POST /policies/compare": () => comparison });
    renderRoute(<PoliciesPage />);
    await screen.findByText(/based on v1/);
    await userEvent.click(screen.getByRole("tab", { name: "Compare" }));
    await userEvent.click(await screen.findByRole("button", { name: "Compare" }));
    expect(await screen.findByText("approve-all-writes")).toBeInTheDocument();
    const row = screen.getByText("kb.search").closest("tr")!;
    expect(row).toHaveClass("bg-amber-50/50");
    expect(calls.find((c) => c.path === "/policies/compare")?.body).toEqual({
      left: { policy_id: "baseline", version: 1 }, right: { policy_id: "strict-lockdown", version: 1 },
    });
  });

  it("simulates a decision in the playground", async () => {
    routes({
      "POST /policies/simulate": () => ({ decision: { outcome: "deny", reason: "Unknown tool", deciding_rule: "builtin:unknown_tool", matched_rules: [], policy_id: "baseline", policy_version: 1, trace: ["tool 'shell.exec' is not registered"] }, argument_errors: [], tool_registered: false }),
    });
    renderRoute(<PoliciesPage />);
    await screen.findByText(/based on v1/);
    await userEvent.click(screen.getByRole("tab", { name: "Playground" }));
    const toolField = await screen.findByLabelText("Tool ID");
    await userEvent.clear(toolField);
    await userEvent.type(toolField, "shell.exec");
    await userEvent.click(screen.getByRole("button", { name: "Evaluate" }));
    const result = await screen.findByLabelText("Simulated decision");
    expect(result).toHaveTextContent("builtin:unknown_tool");
    expect(result).toHaveTextContent("not in the registry");
  });

  it("normalises documents and parses condition values", () => {
    expect(parseConditionValue('["a","b"]')).toEqual(["a", "b"]);
    expect(parseConditionValue("42")).toBe(42);
    expect(parseConditionValue("p0")).toBe("p0");
    const doc = normaliseDocument({ default_effect: "deny", rules: [{ id: "r", description: "", effect: "deny", priority: 1, enabled: true, match: { tool_ids: null, categories: [], arguments: [] } }] });
    expect(doc.rules[0]!.match).toEqual({ arguments: [] });
  });
});

describe("Approval queue", () => {
  it("lists pending approvals and shows history", async () => {
    const { approval } = await import("./fixtures");
    mockApi({
      "GET /approvals": (url) => (url.searchParams.get("status") === "pending"
        ? page([approval()])
        : page([approval({ id: "apr_2", status: "rejected", decided_by: "local-operator", decision_note: "no" })])),
    });
    const { ApprovalsPage } = await import("../features/approvals/ApprovalsPage");
    renderRoute(<ApprovalsPage />);
    expect(await screen.findByRole("article", { name: /Approval request for email.send/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Pending (1)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    await waitFor(() => expect(screen.getByText("local-operator")).toBeInTheDocument());
  });
});
