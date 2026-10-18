// Types mirroring the AgentVault REST API (backend/app/schemas/resources.py).

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type RiskLevel = "low" | "medium" | "high" | "critical";
export type Effect = "allow" | "deny" | "require_approval";
export type ExecutionStatus =
  | "pending"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "failed"
  | "blocked"
  | "cancelled";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "cancelled";

export interface Tool {
  tool_id: string;
  version: string;
  name: string;
  description: string;
  category: string;
  risk_level: RiskLevel;
  mutating: boolean;
  requires_approval: boolean;
  timeout_seconds: number;
  implementation: string;
  implementation_notes: string;
  input_schema: JsonObject;
  output_schema: JsonObject;
  mock_config: JsonObject;
  deterministic: boolean;
  sensitive_arguments: string[];
  builtin: boolean;
  enabled: boolean;
  created_at: string;
}

export type ConditionOp =
  | "eq" | "neq" | "in" | "not_in" | "contains" | "prefix" | "suffix" | "glob"
  | "exists" | "not_exists" | "gt" | "gte" | "lt" | "lte";

export interface ArgumentCondition {
  path: string;
  op: ConditionOp;
  value?: Json;
}

export interface RuleMatch {
  tool_ids?: string[] | null;
  categories?: string[] | null;
  risk_levels?: RiskLevel[] | null;
  operations?: ("read" | "write")[] | null;
  environments?: string[] | null;
  scenario_tags?: string[] | null;
  arguments?: ArgumentCondition[];
}

export interface PolicyRule {
  id: string;
  description: string;
  effect: Effect;
  priority: number;
  enabled: boolean;
  match: RuleMatch;
}

export interface PolicyDocument {
  default_effect: Effect;
  rules: PolicyRule[];
}

export interface PolicyVersion {
  policy_id: string;
  version: number;
  document: PolicyDocument;
  content_hash: string;
  change_note: string;
  created_at: string;
}

export interface PolicySummary {
  id: string;
  name: string;
  description: string;
  latest_version: number;
  builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface PolicyDetail extends PolicySummary {
  versions: PolicyVersion[];
}

export interface PolicyIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  rule_ids: string[];
}

export interface MatchedRule {
  rule_id: string;
  effect: Effect;
  priority: number;
  description: string;
}

export interface Decision {
  outcome: Effect;
  reason: string;
  deciding_rule: string;
  matched_rules: MatchedRule[];
  policy_id: string;
  policy_version: number;
  trace: string[];
}

export interface PolicyComparison {
  left: string;
  right: string;
  diff: {
    default_effect: { before: Effect; after: Effect; changed: boolean };
    added: PolicyRule[];
    removed: PolicyRule[];
    changed: { rule_id: string; fields: string[]; before: PolicyRule; after: PolicyRule }[];
  };
  matrix: { tool_id: string; risk_level: RiskLevel; outcomes: Record<string, { outcome: Effect; rule: string }> }[];
  note: string;
}

export interface Scenario {
  scenario_id: string;
  version: number;
  name: string;
  category: string;
  description: string;
  source: string;
  spec: {
    task: string;
    environment: string;
    tags: string[];
    seed: number;
    agent: { type: string; steps: JsonObject[] };
  };
  human_script: JsonObject;
  expectations: JsonObject;
  content_hash: string;
  created_at: string;
}

export interface Execution {
  id: string;
  scenario_id: string;
  scenario_version: number;
  policy_id: string;
  policy_version: number;
  agent_type: string;
  environment: string;
  seed: number;
  origin: string;
  evaluation_id: string | null;
  status: ExecutionStatus;
  status_reason: string;
  task: string;
  step_count: number;
  tool_call_count: number;
  event_count: number;
  last_event_hash: string;
  final_output: string;
  active_ms: number;
  pending_approval_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ExecutionDetail extends Execution {
  spec: Scenario["spec"];
  sandbox_effects: Record<string, JsonObject[]>;
}

export interface AuditEvent {
  id: string;
  execution_id: string;
  sequence: number;
  event_type: string;
  tool_id: string | null;
  policy_version: string | null;
  outcome: string;
  data: { [key: string]: Json };
  timestamp: string;
  prev_hash: string;
  hash: string;
}

export interface DecisionRecord {
  id: string;
  execution_id: string;
  event_id: string;
  policy_id: string;
  policy_version: number;
  tool_id: string;
  tool_version: string | null;
  arguments_redacted: JsonObject;
  action_hash: string;
  outcome: Effect;
  reason: string;
  matched_rules: MatchedRule[];
  deciding_rule: string;
  latency_us: number;
  created_at: string;
}

export interface AuditVerification {
  chain: { valid: boolean; event_count: number; head: string; problems: string[] };
  completeness: { complete: boolean; problems: string[] };
  limitations: string;
}

export interface Approval {
  id: string;
  execution_id: string;
  decision_id: string;
  step: number;
  action_label: string;
  action_hash: string;
  tool_id: string;
  tool_version: string;
  arguments_redacted: JsonObject;
  risk_level: RiskLevel | "unknown";
  reason: string;
  context: {
    task?: string;
    rationale?: string;
    agent_claims?: JsonObject;
    deciding_rule?: string;
    environment?: string;
    policy?: string;
    recent_observations?: { step: number; label: string; tool_id: string; status: string }[];
  };
  status: ApprovalStatus;
  created_at: string;
  expires_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string;
  consumed_at: string | null;
}

export interface ApprovalDecisionResult {
  approval: Approval;
  execution: Execution;
  idempotent_repeat: boolean;
}

export interface EventSummary {
  sequence: number;
  event_type: string;
  tool_id: string | null;
  outcome: string;
  label: string | null;
  step: number | null;
  event_id: string | null;
}

export interface Divergence {
  diverged: boolean;
  index: number | null;
  left: EventSummary | null;
  right: EventSummary | null;
  explanation: string;
  left_count: number;
  right_count: number;
}

export interface ToolCallRow {
  step: number;
  label: string | null;
  tool_id: string | null;
  action_fingerprint: string | null;
  decision: Effect | null;
  deciding_rule: string | null;
  approval: string | null;
  status: string;
  output_hash: string | null;
  source: string | null;
}

export interface ReplayFrame {
  index: number;
  sequence: number;
  event_id: string | null;
  event_type: string;
  tool_id: string | null;
  outcome: string;
  data: { [key: string]: Json };
  policy_version: string | null;
  timestamp: string | null;
  source: string;
  state?: { status: string; tool_calls: number; executed: string[]; blocked: string[]; awaiting_approval: string | null };
}

export interface Replay {
  id: string;
  execution_id: string;
  mode: "recorded" | "simulate";
  policy_id: string;
  policy_version: number;
  created_at: string;
  result: {
    frames: ReplayFrame[];
    final_status: string;
    status_reason: string;
    warnings: string[];
    unavailable_frames: number[];
    divergence: Divergence | null;
    tool_calls: { original: ToolCallRow[]; replay: ToolCallRow[] | null };
    sandbox_effects?: Record<string, number>;
    original: { execution_id: string; status: string; policy: string; scenario: string; event_count: number; seed: number };
    approval_strategy: string;
  };
}

export interface ExecutionComparison {
  left: { execution_id: string; policy: string; scenario: string; status: string; seed: number };
  right: { execution_id: string; policy: string; scenario: string; status: string; seed: number };
  same_scenario: boolean;
  divergence: Divergence;
  tool_calls: { left: ToolCallRow[]; right: ToolCallRow[] };
}

export interface Rate {
  value: number | null;
  numerator: number;
  denominator: number;
}

export interface LatencySummary {
  count: number;
  mean: number | null;
  p50: number | null;
  p95: number | null;
  max: number | null;
}

export interface EvaluationMetrics {
  runs: number;
  scenario_pass_rate: Rate;
  unsafe_action_block_rate: Rate;
  legitimate_false_block_rate: Rate;
  legitimate_action_completion_rate: Rate;
  approval_enforcement_rate: Rate;
  task_completion_rate: Rate;
  replay_consistency_rate: Rate;
  audit_completeness_rate: Rate;
  tool_failure_rate: Rate;
  decisions: Record<Effect, number>;
  blocked_unsafe_scenarios: number;
  unsafe_scenarios: number;
  average_steps: number | null;
  policy_evaluation_latency_us: LatencySummary;
  execution_latency_ms: LatencySummary;
  estimated_cost_usd: { value: number; note: string };
}

export interface EvaluationAction {
  step: number;
  label: string | null;
  tool_id: string | null;
  decision: Effect;
  decision_event_id: string | null;
  executed: boolean;
  expectation: { safety: string; should_execute: boolean | null; requires_approval: boolean; expected_execution: boolean } | null;
  correct: boolean;
  approval_correct: boolean;
}

export interface EvaluationRun {
  scenario_id: string;
  scenario_version: number;
  scenario_name: string;
  category: string;
  policy: string;
  execution_id: string;
  status: string;
  status_reason: string;
  expected_status: string | null;
  steps: number;
  tool_calls: number;
  latency_ms: number;
  actions: EvaluationAction[];
  approval_attacks: { label: string; attack: string; refused: boolean; error_code: string | null }[];
  audit: { chain_valid: boolean; complete: boolean; problems: string[] };
  replay: { consistent: boolean; divergence: Divergence | null } | null;
  failures: string[];
  passed: boolean;
}

export interface EvaluationDifference {
  scenario_id: string;
  baseline_policy: string;
  compared_policy: string;
  status: Record<string, string>;
  passed: Record<string, boolean>;
  execution_ids: Record<string, string>;
  changed_actions: ({ label: string; tool_id: string } & Record<string, unknown>)[];
}

export interface EvaluationSummary {
  id: string;
  name: string;
  status: "running" | "completed" | "failed";
  error: string;
  created_at: string;
  finished_at: string | null;
  request: JsonObject;
}

export interface Evaluation extends EvaluationSummary {
  results: {
    metrics: Record<string, EvaluationMetrics>;
    runs: Record<string, EvaluationRun[]>;
    differences: EvaluationDifference[];
    methodology: string;
  };
}

export interface ReportMeta {
  id: string;
  kind: "execution" | "replay" | "evaluation" | "policy_comparison";
  subject_id: string;
  title: string;
  created_at: string;
}

export interface DashboardStats {
  executions: { total: number; by_status: Record<string, number>; manual: number; evaluation: number };
  decisions: Partial<Record<Effect, number>>;
  blocked_actions: number;
  tool_failures: number;
  pending_approvals: number;
  approvals_by_status: Record<string, number>;
  top_rules: { rule: string; outcome: Effect; count: number }[];
  policy_summary: Record<string, Record<Effect, number>>;
  recent_executions: { id: string; scenario_id: string; policy: string; status: ExecutionStatus; origin: string; created_at: string; tool_calls: number }[];
  recent_evaluations: { id: string; name: string; status: string; created_at: string; pass_rates: Record<string, number | null> }[];
  counts: { scenarios: number; replays: number; reports: number };
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown; request_id?: string };
}
