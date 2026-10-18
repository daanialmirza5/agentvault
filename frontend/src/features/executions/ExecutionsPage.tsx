import { useState } from "react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../../components/badges";
import { Card, EmptyState, ErrorState, LoadingState, Mono, PageHeader, Pagination } from "../../components/ui";
import { useExecutions } from "../../hooks/queries";
import { formatTime } from "../../services/format";
import { LaunchPanel } from "./LaunchPanel";

const STATUSES = ["", "completed", "waiting_for_approval", "blocked", "failed", "cancelled"];
const LIMIT = 20;

export function ExecutionsPage() {
  const [status, setStatus] = useState("");
  const [origin, setOrigin] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const executions = useExecutions({ status, origin, q, limit: LIMIT, offset });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Execution workspace"
        description="Launch deterministic scenarios against a policy version and inspect every tool call, decision and result."
      />
      <LaunchPanel />
      <Card
        title="Executions"
        padded={false}
        actions={
          <div className="flex flex-wrap gap-2">
            <input aria-label="Search executions" placeholder="Search ID, scenario or task…" value={q}
              onChange={(e) => { setQ(e.target.value); setOffset(0); }} className="w-56 rounded-md border border-slate-300 px-2 py-1 text-xs" />
            <select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs">
              {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replaceAll("_", " ") : "All statuses"}</option>)}
            </select>
            <select aria-label="Filter by origin" value={origin} onChange={(e) => { setOrigin(e.target.value); setOffset(0); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs">
              <option value="">All origins</option>
              <option value="manual">manual</option>
              <option value="evaluation">evaluation</option>
            </select>
          </div>
        }
      >
        {executions.isLoading && <LoadingState />}
        {executions.error && <div className="p-4"><ErrorState error={executions.error} onRetry={() => void executions.refetch()} /></div>}
        {executions.data && executions.data.items.length === 0 && (
          <EmptyState title="No executions match" description="Launch a scenario above to create one." />
        )}
        {executions.data && executions.data.items.length > 0 && (
          <>
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Execution</th><th className="px-2 py-2">Scenario</th><th className="px-2 py-2">Policy</th>
                  <th className="px-2 py-2">Status</th><th className="px-2 py-2">Steps / tools</th><th className="px-2 py-2">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {executions.data.items.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2">
                      <Link to={`/executions/${e.id}`} className="font-mono text-xs text-accent-700 hover:underline">{e.id}</Link>
                      {e.origin === "evaluation" && <span className="ml-2 text-[11px] text-slate-400">evaluation</span>}
                    </td>
                    <td className="px-2">{e.scenario_id} <span className="text-xs text-slate-400">v{e.scenario_version}</span></td>
                    <td className="px-2"><Mono>{e.policy_id}@v{e.policy_version}</Mono></td>
                    <td className="px-2"><StatusBadge status={e.status} /></td>
                    <td className="px-2 tabular-nums text-slate-600">{e.step_count} / {e.tool_call_count}</td>
                    <td className="px-2 text-xs text-slate-500">{formatTime(e.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination total={executions.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
    </div>
  );
}
