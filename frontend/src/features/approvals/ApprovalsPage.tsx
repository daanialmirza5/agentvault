import { useState } from "react";
import { Link } from "react-router-dom";

import { RiskBadge, StatusBadge } from "../../components/badges";
import { Card, EmptyState, ErrorState, LoadingState, Mono, PageHeader, Pagination, Tabs } from "../../components/ui";
import { useApprovals } from "../../hooks/queries";
import { formatTime } from "../../services/format";
import { ApprovalCard } from "./ApprovalCard";

type Tab = "pending" | "history";
const LIMIT = 20;

function History() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const history = useApprovals({ status, limit: LIMIT, offset });
  return (
    <Card padded={false} title="Approval history"
      actions={
        <select aria-label="Filter approvals by status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs">
          <option value="">All statuses</option>
          {["pending", "approved", "rejected", "expired", "cancelled"].map((s) => <option key={s}>{s}</option>)}
        </select>
      }>
      {history.isLoading && <LoadingState />}
      {history.error && <div className="p-4"><ErrorState error={history.error} /></div>}
      {history.data && history.data.items.length === 0 && <EmptyState title="No approvals recorded" />}
      {history.data && history.data.items.length > 0 && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">Requested</th><th className="px-2 py-2">Tool</th><th className="px-2 py-2">Risk</th><th className="px-2 py-2">Status</th><th className="px-2 py-2">Decided by</th><th className="px-2 py-2">Execution</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {history.data.items.map((a) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 text-xs text-slate-500">{formatTime(a.created_at)}</td>
                  <td className="px-2"><Mono>{a.tool_id}</Mono> <span className="text-xs text-slate-400">“{a.action_label}”</span></td>
                  <td className="px-2"><RiskBadge risk={a.risk_level} /></td>
                  <td className="px-2"><StatusBadge status={a.status} /></td>
                  <td className="px-2 text-xs">{a.decided_by ?? "—"}{a.decision_note && <span className="text-slate-400"> · {a.decision_note}</span>}</td>
                  <td className="px-2"><Link className="font-mono text-xs text-accent-700 hover:underline" to={`/executions/${a.execution_id}`}>{a.execution_id}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination total={history.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}
    </Card>
  );
}

export function ApprovalsPage() {
  const [tab, setTab] = useState<Tab>("pending");
  const pending = useApprovals({ status: "pending", limit: 50 });
  return (
    <div className="space-y-4">
      <PageHeader
        title="Approval queue"
        description="Each request is bound to one exact pending action of one execution. Approving executes that action once; rejecting or letting it expire means it never runs. Single-user local mode: decisions are recorded under the configured operator name."
      />
      <Tabs<Tab> label="Approval views" value={tab} onChange={setTab}
        tabs={[{ id: "pending", label: `Pending (${pending.data?.total ?? 0})` }, { id: "history", label: "History" }]} />
      {tab === "pending" && (
        <div className="space-y-4">
          {pending.isLoading && <LoadingState />}
          {pending.error && <ErrorState error={pending.error} onRetry={() => void pending.refetch()} />}
          {pending.data && pending.data.items.length === 0 && (
            <Card><EmptyState title="No actions are waiting for approval"
              description="Launch the 'Follow up with an enterprise customer' scenario to create one."
              action={<Link className="text-sm font-medium text-accent-600 hover:underline" to="/executions">Go to executions</Link>} /></Card>
          )}
          {pending.data?.items.map((a) => <ApprovalCard key={a.id} approval={a} />)}
        </div>
      )}
      {tab === "history" && <History />}
    </div>
  );
}
