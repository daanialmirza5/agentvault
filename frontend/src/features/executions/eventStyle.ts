import type { AuditEvent, DecisionRecord } from "../../types/api";

/** The policy decision that belongs to an event: referenced directly, or via the event's step. */
export function decisionFor(event: AuditEvent, events: AuditEvent[], decisions: DecisionRecord[]): DecisionRecord | undefined {
  const direct = typeof event.data.decision_id === "string" ? event.data.decision_id : null;
  if (direct) return decisions.find((d) => d.id === direct);
  const step = event.data.step;
  if (typeof step !== "number") return undefined;
  const evaluated = events.find((e) => e.event_type === "policy.evaluated" && e.data.step === step);
  const id = evaluated && typeof evaluated.data.decision_id === "string" ? evaluated.data.decision_id : null;
  return id ? decisions.find((d) => d.id === id) : undefined;
}

export type Tone = "neutral" | "good" | "bad" | "warn" | "info";

export function eventTone(e: Pick<AuditEvent, "event_type" | "outcome">): Tone {
  const t = e.event_type;
  if (t === "policy.evaluated") return e.outcome === "allow" ? "good" : e.outcome === "deny" ? "bad" : "warn";
  if (t === "tool.executed") return e.outcome === "succeeded" ? "good" : "bad";
  if (t === "tool.result" || t === "approval.granted" || t === "execution.completed") return "good";
  if (t === "tool.failed" || t === "tool.blocked" || t === "approval.rejected" || t === "guard.triggered" ||
    t === "execution.failed" || t === "execution.blocked" || t === "approval.binding_mismatch" || t === "tool.arguments_rejected") return "bad";
  if (t === "approval.requested" || t === "approval.expired" || t === "execution.cancelled") return "warn";
  if (t === "agent.action_proposed" || t === "tool.requested") return "info";
  return "neutral";
}

export const toneDot: Record<Tone, string> = {
  neutral: "bg-slate-300",
  good: "bg-emerald-500",
  bad: "bg-rose-500",
  warn: "bg-amber-500",
  info: "bg-sky-500",
};

export const toneBorder: Record<Tone, string> = {
  neutral: "#cbd5e1",
  good: "#10b981",
  bad: "#f43f5e",
  warn: "#f59e0b",
  info: "#0ea5e9",
};

export function describeEvent(e: Pick<AuditEvent, "event_type" | "outcome" | "tool_id" | "data">): string {
  const label = typeof e.data.label === "string" ? ` “${e.data.label}”` : "";
  switch (e.event_type) {
    case "execution.created": return "Execution created";
    case "execution.started": return "Agent initialised and started";
    case "execution.resumed": return `Resumed after approval decision (${e.outcome})`;
    case "agent.action_proposed": return `Agent proposed ${e.tool_id ?? "a tool"}${label}`;
    case "tool.requested": return `Tool requested: ${e.tool_id}${e.data.registered === false ? " (not registered)" : ""}`;
    case "tool.arguments_validated": return "Arguments passed schema validation";
    case "tool.arguments_rejected": return "Arguments rejected by schema validation";
    case "policy.evaluated": return `Policy decision: ${e.outcome.replaceAll("_", " ")}`;
    case "approval.requested": return e.outcome === "pending" ? "Paused — waiting for human approval" : "Approval requested (simulated)";
    case "approval.granted": return "Approval granted";
    case "approval.rejected": return "Approval rejected";
    case "approval.expired": return "Approval expired";
    case "approval.binding_mismatch": return "Approval attempt refused (binding mismatch)";
    case "tool.executed": return `Tool executed (${e.outcome})`;
    case "tool.result": return "Result received";
    case "tool.failed": return `Tool failed (${e.outcome})`;
    case "tool.blocked": return `Action blocked (${e.outcome.replaceAll("_", " ")})`;
    case "guard.triggered": return `Runtime guard: ${e.outcome.replaceAll("_", " ")}`;
    default: return e.event_type.replace("execution.", "Execution ");
  }
}
