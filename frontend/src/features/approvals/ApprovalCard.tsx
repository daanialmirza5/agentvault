import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Clock, ShieldAlert, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { JsonView } from "../../components/JsonView";
import { RiskBadge, StatusBadge } from "../../components/badges";
import { Alert, Button, Mono, TextInput } from "../../components/ui";
import { api, describeError } from "../../services/api";
import type { Approval } from "../../types/api";

function useCountdown(expiresAt: string): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const ms = new Date(expiresAt).getTime() - now;
  if (ms <= 0) return "expired";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}m ${s.toString().padStart(2, "0")}s left`;
}

export function ApprovalCard({ approval, showExecutionLink = true }: { approval: Approval; showExecutionLink?: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const countdown = useCountdown(approval.expires_at);
  const decide = useMutation({
    mutationFn: (verdict: "approve" | "reject") => api.decideApproval(approval, verdict, note),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["execution", approval.execution_id] });
      void qc.invalidateQueries({ queryKey: ["execution-events", approval.execution_id] });
      void qc.invalidateQueries({ queryKey: ["execution-decisions", approval.execution_id] });
      void qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
  const claims = approval.context.agent_claims ?? {};
  const pending = approval.status === "pending" && !decide.isSuccess;

  return (
    <article aria-label={`Approval request for ${approval.tool_id}`} className="rounded-lg border border-amber-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-100 bg-amber-50/60 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-amber-600" aria-hidden />
          <span className="text-sm font-semibold text-slate-900">{approval.tool_id}</span>
          <Mono>v{approval.tool_version}</Mono>
          <RiskBadge risk={approval.risk_level} />
          <StatusBadge status={approval.status} />
        </div>
        <div className="flex items-center gap-1 text-xs text-slate-500">
          <Clock className="h-3.5 w-3.5" aria-hidden /> {approval.status === "pending" ? countdown : `decided by ${approval.decided_by ?? "system"}`}
        </div>
      </header>
      <div className="grid gap-4 p-4 lg:grid-cols-2">
        <div className="space-y-3 text-sm">
          <div>
            <div className="text-xs font-medium uppercase text-slate-500">Why approval is required</div>
            <p className="mt-0.5 text-slate-700">{approval.reason}</p>
            <div className="mt-1 text-xs text-slate-500">
              Deciding rule <Mono>{approval.context.deciding_rule ?? "—"}</Mono> · policy <Mono>{approval.context.policy ?? "—"}</Mono> ·
              env <Mono>{approval.context.environment ?? "—"}</Mono>
            </div>
          </div>
          <div>
            <div className="text-xs font-medium uppercase text-slate-500">Task</div>
            <p className="mt-0.5 text-slate-700">{approval.context.task}</p>
          </div>
          <div>
            <div className="text-xs font-medium uppercase text-slate-500">Agent rationale (step {approval.step}, “{approval.action_label}”)</div>
            <p className="mt-0.5 text-slate-700">{approval.context.rationale || "—"}</p>
          </div>
          {Object.keys(claims).length > 0 && (
            <Alert tone="warning">
              The agent claims <Mono>{JSON.stringify(claims)}</Mono>. Agent claims are unverified and are never used by the
              policy engine.
            </Alert>
          )}
          {(approval.context.recent_observations ?? []).length > 0 && (
            <div>
              <div className="text-xs font-medium uppercase text-slate-500">Recent steps</div>
              <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                {(approval.context.recent_observations ?? []).map((o) => (
                  <li key={o.step}>#{o.step} {o.label} · <Mono>{o.tool_id}</Mono> · {o.status}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="space-y-3">
          <div>
            <div className="mb-1 text-xs font-medium uppercase text-slate-500">Arguments (as validated, sensitive keys redacted)</div>
            <JsonView value={approval.arguments_redacted} label="Approval arguments" maxHeight="12rem" />
          </div>
          <div className="text-xs text-slate-500">
            Bound to execution {showExecutionLink ? (
              <Link to={`/executions/${approval.execution_id}`} className="font-mono text-accent-700 hover:underline">{approval.execution_id}</Link>
            ) : <Mono>{approval.execution_id}</Mono>} · action hash <Mono>{approval.action_hash.slice(0, 16)}…</Mono>
          </div>
        </div>
      </div>
      {pending && (
        <footer className="flex flex-wrap items-end gap-3 border-t border-slate-100 px-4 py-3">
          <div className="min-w-56 flex-1">
            <TextInput label="Decision note (optional)" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          </div>
          <Button variant="danger" icon={<X className="h-4 w-4" />} loading={decide.isPending && decide.variables === "reject"}
            disabled={decide.isPending} onClick={() => decide.mutate("reject")}>Reject</Button>
          <Button variant="success" icon={<Check className="h-4 w-4" />} loading={decide.isPending && decide.variables === "approve"}
            disabled={decide.isPending} onClick={() => decide.mutate("approve")}>Approve</Button>
        </footer>
      )}
      {(decide.isError || decide.isSuccess) && (
        <div className="px-4 pb-4">
          {decide.isError && <Alert tone="error">{describeError(decide.error)}</Alert>}
          {decide.isSuccess && (
            <Alert tone="success">
              Approval {decide.data.approval.status}. Execution is now <StatusBadge status={decide.data.execution.status} />
              {decide.data.idempotent_repeat && " (repeat of an earlier identical decision — nothing executed again)"}.
            </Alert>
          )}
        </div>
      )}
    </article>
  );
}
