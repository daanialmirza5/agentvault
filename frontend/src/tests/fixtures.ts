import type { Approval, AuditEvent, DecisionRecord, ExecutionDetail, PolicyDetail, Tool } from "../types/api";

export const tool = (overrides: Partial<Tool> = {}): Tool => ({
  tool_id: "email.send", version: "1.0.0", name: "Send email", description: "Send via simulated outbox.",
  category: "communication", risk_level: "high", mutating: true, requires_approval: true, timeout_seconds: 2,
  implementation: "mock.email.send", implementation_notes: "Appends to the sandbox outbox.",
  input_schema: { type: "object", properties: { to: { type: "string" } }, additionalProperties: false },
  output_schema: { type: "object" }, mock_config: {}, deterministic: true, sensitive_arguments: [], builtin: true,
  enabled: true, created_at: "2026-10-18T10:00:00Z", ...overrides,
});

export const policy = (overrides: Partial<PolicyDetail> = {}): PolicyDetail => ({
  id: "baseline", name: "Baseline support policy", description: "Least privilege.", latest_version: 1, builtin: true,
  created_at: "2026-10-18T10:00:00Z", updated_at: "2026-10-18T10:00:00Z",
  versions: [{
    policy_id: "baseline", version: 1, content_hash: "abc", change_note: "Seeded", created_at: "2026-10-18T10:00:00Z",
    document: {
      default_effect: "deny",
      rules: [
        { id: "allow-low-risk-reads", description: "Reads ok", effect: "allow", priority: 100, enabled: true, match: { operations: ["read"] } },
        { id: "approve-outbound-email", description: "Email needs approval", effect: "require_approval", priority: 50, enabled: true, match: { tool_ids: ["email.send"] } },
      ],
    },
  }],
  ...overrides,
});

export const execution = (overrides: Partial<ExecutionDetail> = {}): ExecutionDetail => ({
  id: "exe_1", scenario_id: "enterprise-follow-up", scenario_version: 1, policy_id: "baseline", policy_version: 1,
  agent_type: "reactive", environment: "sandbox", seed: 202, origin: "manual", evaluation_id: null,
  status: "waiting_for_approval", status_reason: "awaiting approval for 'email.send' at step 4", task: "Follow up",
  step_count: 4, tool_call_count: 3, event_count: 6, last_event_hash: "f".repeat(64), final_output: "", active_ms: 12,
  pending_approval_id: "apr_1", created_at: "2026-10-18T10:00:00Z", started_at: "2026-10-18T10:00:00Z", finished_at: null,
  spec: { task: "Follow up", environment: "sandbox", tags: [], seed: 202, agent: { type: "reactive", steps: [] } },
  sandbox_effects: { outbox: [], drafts: [], tickets: [], record_changes: [], export_attempts: [] },
  ...overrides,
});

export const event = (sequence: number, event_type: string, outcome: string, data: AuditEvent["data"] = {}, tool_id: string | null = null): AuditEvent => ({
  id: `evt_${sequence}`, execution_id: "exe_1", sequence, event_type, tool_id, policy_version: "baseline@v1", outcome, data,
  timestamp: "2026-10-18T10:00:00Z", prev_hash: "0".repeat(64), hash: "a".repeat(64),
});

export const decision = (overrides: Partial<DecisionRecord> = {}): DecisionRecord => ({
  id: "dec_1", execution_id: "exe_1", event_id: "evt_3", policy_id: "baseline", policy_version: 1, tool_id: "email.send",
  tool_version: "1.0.0", arguments_redacted: { to: "ada@example.com" }, action_hash: "b".repeat(64), outcome: "require_approval",
  reason: "Sending email needs a human decision.", matched_rules: [], deciding_rule: "approve-outbound-email", latency_us: 40,
  created_at: "2026-10-18T10:00:00Z", ...overrides,
});

export const approval = (overrides: Partial<Approval> = {}): Approval => ({
  id: "apr_1", execution_id: "exe_1", decision_id: "dec_1", step: 4, action_label: "send", action_hash: "b".repeat(64),
  tool_id: "email.send", tool_version: "1.0.0", arguments_redacted: { to: "ada@example.com", subject: "Hi" }, risk_level: "high",
  reason: "Sending email needs a human decision.",
  context: { task: "Follow up", rationale: "Send the drafted email.", agent_claims: { safe: true }, deciding_rule: "approve-outbound-email", environment: "sandbox", policy: "baseline@v1", recent_observations: [] },
  status: "pending", created_at: "2026-10-18T10:00:00Z", expires_at: "2999-01-01T00:00:00Z", decided_at: null, decided_by: null,
  decision_note: "", consumed_at: null, ...overrides,
});
