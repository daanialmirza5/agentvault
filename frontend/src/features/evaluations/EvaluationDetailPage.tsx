import { Fragment, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ReportExport } from "../../components/ReportExport";
import { OutcomeBadge, StatusBadge } from "../../components/badges";
import { Alert, Button, Card, ErrorState, LoadingState, Mono, PageHeader } from "../../components/ui";
import { useEvaluation } from "../../hooks/queries";
import { formatPct, formatTime } from "../../services/format";
import type { EvaluationMetrics, EvaluationRun, Rate } from "../../types/api";

const RATE_ROWS: { key: keyof EvaluationMetrics; label: string; better: "higher" | "lower" }[] = [
  { key: "scenario_pass_rate", label: "Scenario pass rate", better: "higher" },
  { key: "unsafe_action_block_rate", label: "Unsafe actions blocked", better: "higher" },
  { key: "legitimate_false_block_rate", label: "Legitimate actions falsely blocked", better: "lower" },
  { key: "legitimate_action_completion_rate", label: "Legitimate actions completed", better: "higher" },
  { key: "approval_enforcement_rate", label: "Approval enforcement correctness", better: "higher" },
  { key: "task_completion_rate", label: "Task completion", better: "higher" },
  { key: "replay_consistency_rate", label: "Replay consistency", better: "higher" },
  { key: "audit_completeness_rate", label: "Audit completeness", better: "higher" },
  { key: "tool_failure_rate", label: "Tool failure rate", better: "lower" },
];
const COLORS = ["#4f46e5", "#e11d48", "#0d9488", "#d97706"];

function RateCell({ rate }: { rate: Rate }) {
  return (
    <span className="tabular-nums">
      {formatPct(rate.value)} <span className="text-xs text-slate-400">({rate.numerator}/{rate.denominator})</span>
    </span>
  );
}

function RunsTable({ runs }: { runs: EvaluationRun[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs uppercase text-slate-500">
        <tr><th className="px-4 py-2">Scenario</th><th className="px-2 py-2">Category</th><th className="px-2 py-2">Status</th><th className="px-2 py-2">Result</th><th className="px-2 py-2">Execution</th><th className="px-2 py-2" /></tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {runs.map((r) => (
          <Fragment key={r.execution_id}>
            <tr className="hover:bg-slate-50">
              <td className="px-4 py-2">{r.scenario_name}</td>
              <td className="px-2 text-xs text-slate-500">{r.category.replaceAll("_", " ")}</td>
              <td className="px-2"><StatusBadge status={r.status} /></td>
              <td className="px-2">{r.passed ? <span className="text-xs font-medium text-emerald-700">pass</span> : <span className="text-xs font-medium text-rose-700">fail ({r.failures.length})</span>}</td>
              <td className="px-2"><Link className="font-mono text-[11px] text-accent-700 hover:underline" to={`/executions/${r.execution_id}`}>{r.execution_id}</Link></td>
              <td className="px-2 text-right">
                <Button size="sm" variant="ghost" aria-expanded={open === r.execution_id} onClick={() => setOpen(open === r.execution_id ? null : r.execution_id)}>
                  {open === r.execution_id ? "Hide" : "Inspect"}
                </Button>
              </td>
            </tr>
            {open === r.execution_id && (
              <tr className="bg-slate-50/70">
                <td colSpan={6} className="space-y-2 px-4 py-3">
                  {r.failures.length > 0 && <Alert tone="error">{r.failures.map((f) => <div key={f}>{f}</div>)}</Alert>}
                  <table className="w-full text-xs">
                    <thead className="text-left text-slate-500"><tr><th className="py-1">Action</th><th>Tool</th><th>Decision</th><th>Executed</th><th>Expected</th><th>Evidence</th></tr></thead>
                    <tbody>
                      {r.actions.map((a) => (
                        <tr key={a.step} className={a.correct ? "" : "text-rose-700"}>
                          <td className="py-1">{a.label}</td>
                          <td><Mono>{a.tool_id}</Mono></td>
                          <td><OutcomeBadge outcome={a.decision} /></td>
                          <td>{a.executed ? "yes" : "no"}</td>
                          <td>{a.expectation ? `${a.expectation.safety}, ${a.expectation.expected_execution ? "execute" : "do not execute"}${a.expectation.requires_approval ? ", needs approval" : ""}` : "unlabelled"}</td>
                          <td><Mono>{a.decision_event_id}</Mono></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {r.approval_attacks.length > 0 && (
                    <div className="text-xs">Approval attacks: {r.approval_attacks.map((a) => (
                      <span key={a.attack} className="mr-3">{a.attack}: <strong className={a.refused ? "text-emerald-700" : "text-rose-700"}>{a.refused ? "refused" : "NOT refused"}</strong> {a.error_code && <Mono>{a.error_code}</Mono>}</span>
                    ))}</div>
                  )}
                  <div className="text-xs text-slate-500">
                    Audit: chain {r.audit.chain_valid ? "valid" : "INVALID"}, {r.audit.complete ? "complete" : "incomplete"} ·
                    Replay: {r.replay ? (r.replay.consistent ? "consistent" : "diverged") : "not checked"} · {r.steps} steps · {r.latency_ms.toFixed(1)} ms
                  </div>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

export function EvaluationDetailPage() {
  const { evaluationId = "" } = useParams();
  const evaluation = useEvaluation(evaluationId);
  if (evaluation.isLoading) return <LoadingState />;
  if (evaluation.error || !evaluation.data) return <ErrorState error={evaluation.error} onRetry={() => void evaluation.refetch()} />;
  const ev = evaluation.data;
  if (ev.status !== "completed") {
    return <ErrorState error={new Error(`Evaluation is ${ev.status}${ev.error ? `: ${ev.error}` : ""}`)} />;
  }
  const labels = Object.keys(ev.results.metrics);
  const chartData = ["unsafe_action_block_rate", "legitimate_false_block_rate", "legitimate_action_completion_rate", "task_completion_rate", "approval_enforcement_rate"].map((k) => {
    const row: Record<string, string | number> = { metric: RATE_ROWS.find((r) => r.key === k)?.label ?? k };
    for (const l of labels) {
      const v = (ev.results.metrics[l]![k as keyof EvaluationMetrics] as Rate).value;
      row[l] = v === null ? 0 : Math.round(v * 1000) / 10;
    }
    return row;
  });

  return (
    <div className="space-y-6">
      <PageHeader title={ev.name} description={`Evaluation ${ev.id} · ${formatTime(ev.created_at)}`}
        actions={<ReportExport kind="evaluation" subjectId={ev.id} label="Results" />} />
      <Alert tone="info">{ev.results.methodology} Blocking more actions is not automatically safer: compare unsafe-action blocking with legitimate-task disruption.</Alert>

      <Card title="Metrics by policy version" padded={false}>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr><th className="px-4 py-2">Metric</th>{labels.map((l) => <th key={l} className="px-2 py-2"><Mono>{l}</Mono></th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {RATE_ROWS.map((row) => (
              <tr key={row.key}>
                <td className="px-4 py-2">{row.label} <span className="text-xs text-slate-400">({row.better} is better)</span></td>
                {labels.map((l) => <td key={l} className="px-2"><RateCell rate={ev.results.metrics[l]![row.key] as Rate} /></td>)}
              </tr>
            ))}
            <tr><td className="px-4 py-2">Decisions (allow / deny / approval)</td>{labels.map((l) => { const d = ev.results.metrics[l]!.decisions; return <td key={l} className="px-2 tabular-nums">{d.allow} / {d.deny} / {d.require_approval}</td>; })}</tr>
            <tr><td className="px-4 py-2">Average steps per execution</td>{labels.map((l) => <td key={l} className="px-2 tabular-nums">{ev.results.metrics[l]!.average_steps}</td>)}</tr>
            <tr><td className="px-4 py-2">Policy evaluation latency p50 / p95</td>{labels.map((l) => { const x = ev.results.metrics[l]!.policy_evaluation_latency_us; return <td key={l} className="px-2 tabular-nums">{x.p50} / {x.p95} µs</td>; })}</tr>
            <tr><td className="px-4 py-2">Execution latency mean / p95</td>{labels.map((l) => { const x = ev.results.metrics[l]!.execution_latency_ms; return <td key={l} className="px-2 tabular-nums">{x.mean} / {x.p95} ms</td>; })}</tr>
            <tr><td className="px-4 py-2">Estimated cost</td>{labels.map((l) => <td key={l} className="px-2 text-xs text-slate-500">${ev.results.metrics[l]!.estimated_cost_usd.value.toFixed(2)} — {ev.results.metrics[l]!.estimated_cost_usd.note}</td>)}</tr>
          </tbody>
        </table>
      </Card>

      <Card title="Safety vs. disruption">
        <div className="h-72" aria-label="Grouped bar chart comparing key rates per policy">
          <ResponsiveContainer>
            <BarChart data={chartData} margin={{ left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="metric" tick={{ fontSize: 11 }} interval={0} />
              <YAxis unit="%" domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => `${v}%`} />
              <Legend />
              {labels.map((l, i) => <Bar key={l} dataKey={l} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {ev.results.differences.length > 0 && (
        <Card title="Why the policies differ (with evidence)" padded={false}>
          <ul className="divide-y divide-slate-100 text-sm">
            {ev.results.differences.map((d) => (
              <li key={`${d.scenario_id}-${d.compared_policy}`} className="px-4 py-3">
                <div className="font-medium text-slate-800">{d.scenario_id}</div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {Object.entries(d.status).map(([p, s]) => (
                    <span key={p} className="mr-3"><Mono>{p}</Mono> <StatusBadge status={s} /> <Link to={`/executions/${d.execution_ids[p]}`} className="text-accent-700 hover:underline">open</Link></span>
                  ))}
                </div>
                <ul className="mt-1 space-y-0.5 text-xs">
                  {d.changed_actions.map((c) => (
                    <li key={c.label}>
                      <Mono>{c.label}</Mono> ({c.tool_id}):{" "}
                      {[d.baseline_policy, d.compared_policy].map((p) => {
                        const v = c[p] as { decision: string; executed: boolean; event_id: string } | undefined;
                        return v ? <span key={p} className="mr-3">{p} → <OutcomeBadge outcome={v.decision} /> executed={String(v.executed)} <Mono>{v.event_id}</Mono></span> : null;
                      })}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {labels.map((l) => (
        <Card key={l} title={`Runs under ${l}`} padded={false}>
          <RunsTable runs={ev.results.runs[l] ?? []} />
        </Card>
      ))}
    </div>
  );
}
