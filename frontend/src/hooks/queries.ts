import { useQuery } from "@tanstack/react-query";

import { api } from "../services/api";
import type { ExecutionStatus } from "../types/api";

type Query = Record<string, string | number | boolean | null | undefined>;

export const keys = {
  stats: ["stats"] as const,
  ready: ["ready"] as const,
  tools: ["tools"] as const,
  policies: ["policies"] as const,
  policy: (id: string) => ["policy", id] as const,
  scenarios: ["scenarios"] as const,
  executions: (q: Query) => ["executions", q] as const,
  execution: (id: string) => ["execution", id] as const,
  events: (id: string) => ["execution-events", id] as const,
  decisions: (id: string) => ["execution-decisions", id] as const,
  approvals: (q: Query) => ["approvals", q] as const,
  evaluations: ["evaluations"] as const,
  evaluation: (id: string) => ["evaluation", id] as const,
  reports: ["reports"] as const,
  auditEvents: (q: Query) => ["audit-events", q] as const,
  auditDecisions: (q: Query) => ["audit-decisions", q] as const,
};

const ACTIVE: ExecutionStatus[] = ["pending", "running", "waiting_for_approval"];

export const useStats = () => useQuery({ queryKey: keys.stats, queryFn: api.stats, refetchInterval: 10_000 });
export const useReady = () => useQuery({ queryKey: keys.ready, queryFn: api.ready, refetchInterval: 30_000, retry: false });
export const useTools = () => useQuery({ queryKey: keys.tools, queryFn: () => api.tools() });
export const usePolicies = () => useQuery({ queryKey: keys.policies, queryFn: api.policies });
export const usePolicy = (id: string | undefined) =>
  useQuery({ queryKey: keys.policy(id ?? ""), queryFn: () => api.policy(id ?? ""), enabled: Boolean(id) });
export const useScenarios = () => useQuery({ queryKey: keys.scenarios, queryFn: api.scenarios });
export const useExecutions = (q: Query) => useQuery({ queryKey: keys.executions(q), queryFn: () => api.executions(q) });

export function useExecution(id: string | undefined) {
  return useQuery({
    queryKey: keys.execution(id ?? ""),
    queryFn: () => api.execution(id ?? ""),
    enabled: Boolean(id),
    // Poll only while the execution can still change (e.g. someone approves in another tab).
    refetchInterval: (query) => (query.state.data && ACTIVE.includes(query.state.data.status) ? 4000 : false),
  });
}

export const useExecutionEvents = (id: string | undefined, version?: number) =>
  useQuery({ queryKey: [...keys.events(id ?? ""), version], queryFn: () => api.executionEvents(id ?? ""), enabled: Boolean(id) });
export const useExecutionDecisions = (id: string | undefined, version?: number) =>
  useQuery({ queryKey: [...keys.decisions(id ?? ""), version], queryFn: () => api.executionDecisions(id ?? ""), enabled: Boolean(id) });
export const useApprovals = (q: Query) =>
  useQuery({ queryKey: keys.approvals(q), queryFn: () => api.approvals(q), refetchInterval: 5000 });
export const useEvaluations = () => useQuery({ queryKey: keys.evaluations, queryFn: api.evaluations });
export const useEvaluation = (id: string | undefined) =>
  useQuery({ queryKey: keys.evaluation(id ?? ""), queryFn: () => api.evaluation(id ?? ""), enabled: Boolean(id) });
export const useReports = () => useQuery({ queryKey: keys.reports, queryFn: api.reports });
export const useAuditEvents = (q: Query) => useQuery({ queryKey: keys.auditEvents(q), queryFn: () => api.auditEvents(q) });
export const useAuditDecisions = (q: Query) =>
  useQuery({ queryKey: keys.auditDecisions(q), queryFn: () => api.auditDecisions(q) });
