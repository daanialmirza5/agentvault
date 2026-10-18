import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { OutcomeBadge, StatusBadge } from "../../components/badges";
import { Card, EmptyState, ErrorState, LoadingState, Mono, PageHeader, Stat } from "../../components/ui";
import { useStats } from "../../hooks/queries";
import { formatPct, formatTime } from "../../services/format";

const OUTCOME_COLORS: Record<string, string> = { allow: "#10b981", deny: "#e11d48", require_approval: "#f59e0b" };
const STATUS_COLORS: Record<string, string> = {
  completed: "#10b981", failed: "#e11d48", blocked: "#f97316", waiting_for_approval: "#f59e0b",
  cancelled: "#94a3b8", running: "#0ea5e9", pending: "#cbd5e1",
};

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useStats();
  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const s = data.executions.by_status;
  const decisions = (["allow", "deny", "require_approval"] as const).map((k) => ({ name: k, value: data.decisions[k] ?? 0 }));
  const statuses = Object.entries(s).map(([name, value]) => ({ name, value }));
  const hasActivity = data.executions.total > 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Live counts from the AgentVault database: executions, policy decisions, approvals and evaluations."
        actions={
          <>
            <Link to="/executions" className="rounded-md bg-accent-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-700">
              Launch a scenario
            </Link>
            <Link to="/evaluations" className="rounded-md bg-white px-3.5 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
              Run an evaluation
            </Link>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Executions" value={data.executions.total} hint={`${data.executions.manual} manual · ${data.executions.evaluation} evaluation`} />
        <Stat label="Completed" value={s.completed ?? 0} tone="good" />
        <Stat label="Failed / blocked" value={(s.failed ?? 0) + (s.blocked ?? 0)} tone={(s.failed ?? 0) + (s.blocked ?? 0) ? "bad" : "default"} />
        <Stat label="Blocked actions" value={data.blocked_actions} hint="tool.blocked events" tone="warn" />
        <Link to="/approvals" className="block rounded-lg focus:outline-none">
          <Stat label="Pending approvals" value={data.pending_approvals} hint="Open the approval queue →" tone={data.pending_approvals ? "warn" : "default"} />
        </Link>
      </div>

      {!hasActivity ? (
        <Card>
          <EmptyState
            title="No executions yet"
            description="Launch a scenario to see policy decisions, approvals and the audit trail, or run the evaluation suite."
            action={<Link className="text-sm font-medium text-accent-600 hover:underline" to="/executions">Go to executions</Link>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Policy decisions">
            <div className="h-56" aria-label="Bar chart of policy decision outcomes">
              <ResponsiveContainer>
                <BarChart data={decisions} margin={{ left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} tickFormatter={(v: string) => (v === "require_approval" ? "approval" : v)} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="value" name="decisions" radius={[4, 4, 0, 0]}>
                    {decisions.map((d) => <Cell key={d.name} fill={OUTCOME_COLORS[d.name]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card title="Executions by status">
            <div className="h-56" aria-label="Bar chart of executions by status">
              <ResponsiveContainer>
                <BarChart data={statuses} margin={{ left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.replaceAll("_", " ")} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="value" name="executions" radius={[4, 4, 0, 0]}>
                    {statuses.map((d) => <Cell key={d.name} fill={STATUS_COLORS[d.name] ?? "#64748b"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Recent executions" className="lg:col-span-2" padded={false}>
          {data.recent_executions.length === 0 ? (
            <EmptyState title="Nothing here yet" />
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="px-4 py-2">Execution</th><th className="px-4 py-2">Scenario</th><th className="px-4 py-2">Policy</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Created</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.recent_executions.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2"><Link className="font-mono text-xs text-accent-700 hover:underline" to={`/executions/${e.id}`}>{e.id}</Link></td>
                    <td className="px-4 py-2">{e.scenario_id}{e.origin === "evaluation" && <span className="ml-1 text-xs text-slate-400">(eval)</span>}</td>
                    <td className="px-4 py-2"><Mono>{e.policy}</Mono></td>
                    <td className="px-4 py-2"><StatusBadge status={e.status} /></td>
                    <td className="px-4 py-2 text-xs text-slate-500">{formatTime(e.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Decisions by policy" padded={false}>
            {Object.keys(data.policy_summary).length === 0 ? (
              <EmptyState title="No decisions recorded" />
            ) : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr><th className="px-4 py-2">Policy</th><th className="px-2 py-2">Allow</th><th className="px-2 py-2">Deny</th><th className="px-2 py-2">Approval</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 tabular-nums">
                  {Object.entries(data.policy_summary).map(([pid, c]) => (
                    <tr key={pid}><td className="px-4 py-2">{pid}</td><td className="px-2">{c.allow}</td><td className="px-2">{c.deny}</td><td className="px-2">{c.require_approval}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Most frequent deciding rules" padded={false}>
            {data.top_rules.length === 0 ? <EmptyState title="No decisions recorded" /> : (
              <ul className="divide-y divide-slate-100 text-sm">
                {data.top_rules.map((r) => (
                  <li key={`${r.rule}-${r.outcome}`} className="flex items-center justify-between gap-2 px-4 py-2">
                    <Mono>{r.rule}</Mono>
                    <span className="flex items-center gap-2"><OutcomeBadge outcome={r.outcome} /><span className="tabular-nums text-slate-500">{r.count}</span></span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Card title="Recent safety evaluations" padded={false}>
        {data.recent_evaluations.length === 0 ? (
          <EmptyState title="No evaluations yet" action={<Link className="text-sm font-medium text-accent-600 hover:underline" to="/evaluations">Open the evaluation lab</Link>} />
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">Evaluation</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Scenario pass rate by policy</th><th className="px-4 py-2">Created</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.recent_evaluations.map((ev) => (
                <tr key={ev.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2"><Link className="text-accent-700 hover:underline" to={`/evaluations/${ev.id}`}>{ev.name}</Link></td>
                  <td className="px-4 py-2"><StatusBadge status={ev.status} /></td>
                  <td className="px-4 py-2 text-xs">
                    {Object.entries(ev.pass_rates).map(([p, v]) => <span key={p} className="mr-3"><Mono>{p}</Mono> {formatPct(v)}</span>)}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">{formatTime(ev.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
