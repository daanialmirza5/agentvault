import type {
  Approval,
  ApprovalDecisionResult,
  AuditEvent,
  AuditVerification,
  DashboardStats,
  Decision,
  DecisionRecord,
  Evaluation,
  EvaluationSummary,
  Execution,
  ExecutionComparison,
  ExecutionDetail,
  JsonObject,
  Page,
  PolicyComparison,
  PolicyDetail,
  PolicyDocument,
  PolicyIssue,
  PolicySummary,
  PolicyVersion,
  Replay,
  ReportMeta,
  Scenario,
  Tool,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "agentvault.apiToken";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly details?: unknown,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getApiToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setApiToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token simply is not remembered */
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}/api/v1${path}${qs ? `?${qs}` : ""}`;
}

async function raw(path: string, init: { method?: string; body?: unknown; query?: Query } = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getApiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let response: Response;
  try {
    response = await fetch(buildUrl(path, init.query), {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ApiError("Cannot reach the AgentVault API. Is the backend running?", 0, "network_error");
  }
  if (!response.ok) {
    let body: Partial<{ error: { code: string; message: string; details?: unknown; request_id?: string } }> = {};
    try {
      body = await response.json();
    } catch {
      /* non-JSON error body */
    }
    const err = body.error;
    throw new ApiError(
      err?.message ?? `Request failed with status ${response.status}`,
      response.status,
      err?.code ?? "http_error",
      err?.details,
      err?.request_id ?? response.headers.get("x-request-id") ?? undefined,
    );
  }
  return response;
}

async function request<T>(path: string, init: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const response = await raw(path, init);
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  ready: () => request<{ status: string; checks: JsonObject; auth_mode: string; llm_adapter_enabled: boolean }>("/ready"),
  stats: () => request<DashboardStats>("/stats"),

  tools: (query?: Query) => request<Page<Tool>>("/tools", { query: { limit: 200, ...query } }),
  toolVersions: (toolId: string) => request<Tool[]>(`/tools/${encodeURIComponent(toolId)}`),
  createTool: (body: JsonObject) => request<Tool>("/tools", { method: "POST", body }),

  policies: () => request<Page<PolicySummary>>("/policies", { query: { limit: 200 } }),
  policy: (id: string) => request<PolicyDetail>(`/policies/${encodeURIComponent(id)}`),
  createPolicy: (body: { id: string; name: string; description: string; document: PolicyDocument; change_note: string }) =>
    request<PolicyDetail>("/policies", { method: "POST", body }),
  createPolicyVersion: (id: string, body: { document: PolicyDocument; change_note: string; base_version: number }) =>
    request<PolicyVersion>(`/policies/${encodeURIComponent(id)}/versions`, { method: "POST", body }),
  validatePolicy: (document: PolicyDocument) =>
    request<{ valid: boolean; issues: PolicyIssue[] }>("/policies/validate", { method: "POST", body: { document } }),
  comparePolicies: (left: { policy_id: string; version: number }, right: { policy_id: string; version: number }) =>
    request<PolicyComparison>("/policies/compare", { method: "POST", body: { left, right } }),
  simulateDecision: (body: {
    document?: PolicyDocument;
    policy?: { policy_id: string; version?: number };
    tool_id: string;
    arguments: JsonObject;
    environment: string;
    scenario_tags: string[];
  }) => request<{ decision: Decision; argument_errors: string[]; tool_registered: boolean }>("/policies/simulate", {
    method: "POST",
    body,
  }),

  scenarios: () => request<Page<Scenario>>("/scenarios", { query: { limit: 200 } }),

  executions: (query?: Query) => request<Page<Execution>>("/executions", { query }),
  execution: (id: string) => request<ExecutionDetail>(`/executions/${encodeURIComponent(id)}`),
  launchExecution: (body: {
    scenario_id: string;
    policy_id: string;
    policy_version?: number;
    seed?: number;
    environment?: string;
  }) => request<ExecutionDetail>("/executions", { method: "POST", body }),
  executionEvents: (id: string) =>
    request<Page<AuditEvent>>(`/executions/${encodeURIComponent(id)}/events`, { query: { limit: 1000 } }),
  executionDecisions: (id: string) => request<DecisionRecord[]>(`/executions/${encodeURIComponent(id)}/decisions`),
  verifyAudit: (id: string) => request<AuditVerification>(`/executions/${encodeURIComponent(id)}/audit/verify`),
  cancelExecution: (id: string, reason: string) =>
    request<ExecutionDetail>(`/executions/${encodeURIComponent(id)}/cancel`, { method: "POST", body: { reason } }),

  approvals: (query?: Query) => request<Page<Approval>>("/approvals", { query }),
  decideApproval: (approval: Approval, verdict: "approve" | "reject", note: string) =>
    request<ApprovalDecisionResult>(`/approvals/${encodeURIComponent(approval.id)}/${verdict}`, {
      method: "POST",
      body: { execution_id: approval.execution_id, action_hash: approval.action_hash, note },
    }),

  createReplay: (body: {
    execution_id: string;
    mode: "recorded" | "simulate";
    policy_id?: string;
    policy_version?: number;
    approval_strategy?: string;
  }) => request<Replay>("/replays", { method: "POST", body }),
  replay: (id: string) => request<Replay>(`/replays/${encodeURIComponent(id)}`),
  replays: (query?: Query) => request<Page<Replay>>("/replays", { query }),
  compareExecutions: (left: string, right: string) =>
    request<ExecutionComparison>("/replays/compare", {
      method: "POST",
      body: { left_execution_id: left, right_execution_id: right },
    }),

  evaluations: () => request<Page<EvaluationSummary>>("/evaluations", { query: { limit: 50 } }),
  evaluation: (id: string) => request<Evaluation>(`/evaluations/${encodeURIComponent(id)}`),
  runEvaluation: (body: {
    name: string;
    scenario_ids: string[] | null;
    policies: { policy_id: string; version?: number }[];
    include_replay_check: boolean;
  }) => request<Evaluation>("/evaluations", { method: "POST", body }),

  auditEvents: (query?: Query) => request<Page<AuditEvent>>("/audit/events", { query }),
  auditDecisions: (query?: Query) => request<Page<DecisionRecord>>("/audit/decisions", { query }),

  reports: () => request<Page<ReportMeta>>("/reports", { query: { limit: 100 } }),
  createReport: (kind: ReportMeta["kind"], subjectId: string) =>
    request<ReportMeta>("/reports", { method: "POST", body: { kind, subject_id: subjectId } }),
  downloadReport: async (id: string, format: "json" | "markdown"): Promise<void> => {
    const response = await raw(`/reports/${encodeURIComponent(id)}`, { query: { format, download: true } });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${id}.${format === "markdown" ? "md" : "json"}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },
};

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Array.isArray(error.details)
      ? (error.details as { loc?: string[]; msg?: string }[])
          .slice(0, 3)
          .map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
          .join("; ")
      : "";
    return `${error.message}${details ? ` — ${details}` : ""}${error.code !== "network_error" ? ` (${error.code})` : ""}`;
  }
  return error instanceof Error ? error.message : String(error);
}
