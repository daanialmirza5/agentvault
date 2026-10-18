import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ReplayPage } from "../features/replay/ReplayPage";
import type { ExecutionComparison, Replay, ReplayFrame } from "../types/api";
import { execution, policy } from "./fixtures";
import { mockApi, page, renderRoute } from "./utils";

const frame = (index: number, event_type: string, outcome: string, source: string, data: ReplayFrame["data"] = {}): ReplayFrame => ({
  index, sequence: index + 1, event_id: `sim-${index + 1}`, event_type, tool_id: data.step ? "kb.search" : null, outcome, data,
  policy_version: "strict-lockdown@v1", timestamp: null, source,
});

const replay: Replay = {
  id: "rpl_1", execution_id: "exe_1", mode: "simulate", policy_id: "strict-lockdown", policy_version: 1, created_at: "2026-10-18T10:00:00Z",
  result: {
    frames: [
      frame(0, "execution.created", "simulated", "simulated"),
      frame(1, "execution.started", "ok", "simulated"),
      frame(2, "tool.requested", "requested", "simulated", { step: 1, label: "search" }),
      frame(3, "policy.evaluated", "deny", "re-evaluated", { step: 1, label: "search", deciding_rule: "builtin:default_effect" }),
      frame(4, "execution.blocked", "blocked", "simulated"),
    ],
    final_status: "blocked", status_reason: "search: denied", warnings: [], unavailable_frames: [],
    divergence: { diverged: true, index: 3, left: { sequence: 6, event_type: "policy.evaluated", tool_id: "kb.search", outcome: "allow", label: "search", step: 1, event_id: "evt_6" },
      right: { sequence: 4, event_type: "policy.evaluated", tool_id: "kb.search", outcome: "deny", label: "search", step: 1, event_id: "sim-4" },
      explanation: "Policy decided 'allow' vs 'deny' for 'search'.", left_count: 10, right_count: 5 },
    tool_calls: {
      original: [{ step: 1, label: "search", tool_id: "kb.search", action_fingerprint: "x", decision: "allow", deciding_rule: "allow-low-risk-reads", approval: null, status: "succeeded", output_hash: "abcd1234", source: "live" }],
      replay: [{ step: 1, label: "search", tool_id: "kb.search", action_fingerprint: "x", decision: "deny", deciding_rule: "builtin:default_effect", approval: null, status: "blocked:denied", output_hash: null, source: null }],
    },
    original: { execution_id: "exe_1", status: "completed", policy: "baseline@v1", scenario: "support-faq-lookup@v1", event_count: 10, seed: 101 },
    approval_strategy: "recorded",
  },
};

function routes(extra: Record<string, (url: URL, init: RequestInit) => unknown> = {}) {
  return mockApi({
    "GET /executions": () => page([execution({ id: "exe_1", status: "completed" }), execution({ id: "exe_2", status: "blocked", policy_id: "strict-lockdown" })]),
    "GET /policies": () => page([policy(), policy({ id: "strict-lockdown", name: "Strict lockdown" })]),
    "GET /policies/:id": () => policy({ id: "strict-lockdown", name: "Strict lockdown" }),
    "GET /replays": () => page([]),
    "POST /replays": () => replay,
    ...extra,
  });
}

describe("Replay workspace", () => {
  it("creates a simulated replay under another policy and steps through frames", async () => {
    const { calls } = routes();
    renderRoute(<ReplayPage />, { route: "/?execution=exe_1" });
    await userEvent.selectOptions(await screen.findByLabelText("Mode"), "simulate");
    await userEvent.selectOptions(screen.getByLabelText("Policy for simulation"), "strict-lockdown");
    await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
    expect(await screen.findByText("Frame 1 / 5")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ execution_id: "exe_1", mode: "simulate", policy_id: "strict-lockdown", approval_strategy: "recorded" });

    await userEvent.click(screen.getByRole("button", { name: "Next frame" }));
    expect(screen.getByText("Frame 2 / 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Last frame" }));
    expect(screen.getByText("Frame 5 / 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Previous frame" }));
    expect(screen.getByText("Frame 4 / 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "First frame" }));
    expect(screen.getByText("Frame 1 / 5")).toBeInTheDocument();
  });

  it("identifies the first divergence and jumps to it", async () => {
    routes();
    renderRoute(<ReplayPage />, { route: "/?execution=exe_1" });
    await userEvent.click(await screen.findByRole("button", { name: "Start replay" }));
    expect(await screen.findByText(/First divergence at comparable position 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Jump to divergence" }));
    expect(screen.getByText("Frame 4 / 5")).toBeInTheDocument();
    expect(screen.getByLabelText("Frame data")).toHaveTextContent("builtin:default_effect");
    // Labelled sources distinguish recomputed decisions from recorded data.
    expect(screen.getAllByText("re-evaluated").length).toBeGreaterThan(0);
  });

  it("compares two executions", async () => {
    const comparison: ExecutionComparison = {
      left: { execution_id: "exe_1", policy: "baseline@v1", scenario: "s@v1", status: "completed", seed: 1 },
      right: { execution_id: "exe_2", policy: "strict-lockdown@v1", scenario: "s@v1", status: "blocked", seed: 1 },
      same_scenario: true,
      divergence: replay.result.divergence!,
      tool_calls: { left: replay.result.tool_calls.original, right: replay.result.tool_calls.replay! },
    };
    const { calls } = routes({ "POST /replays/compare": () => comparison });
    renderRoute(<ReplayPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Find first divergence" }));
    expect(await screen.findByText(/left event/)).toHaveTextContent("evt_6");
    expect(calls.find((c) => c.path === "/replays/compare")?.body).toEqual({ left_execution_id: "exe_1", right_execution_id: "exe_2" });
  });
});
