import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Rewind, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { JsonView } from "../../components/JsonView";
import { ReportExport } from "../../components/ReportExport";
import { OutcomeBadge, StatusBadge } from "../../components/badges";
import { Alert, Button, Card, EmptyState, ErrorState, LoadingState, Mono, PageHeader, Tabs } from "../../components/ui";
import { useExecution, useExecutionDecisions, useExecutionEvents } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import { formatTime } from "../../services/format";
import { ApprovalCard } from "../approvals/ApprovalCard";
import { useStickyApprovals } from "../approvals/useStickyApprovals";
import { decisionFor } from "./eventStyle";
import { FlowGraph } from "./FlowGraph";
import { EventDetail, Timeline } from "./Timeline";

type Tab = "timeline" | "graph" | "decisions" | "effects" | "integrity";

export function ExecutionDetailPage() {
  const { executionId = "" } = useParams();
  const qc = useQueryClient();
  const execution = useExecution(executionId);
  const version = execution.data?.event_count;
  const events = useExecutionEvents(executionId, version);
  const decisions = useExecutionDecisions(executionId, version);
  const pendingApproval = useQuery({
    queryKey: ["approvals", { execution_id: executionId, status: "pending", v: version }],
    queryFn: () => api.approvals({ execution_id: executionId, status: "pending" }),
    enabled: execution.data?.status === "waiting_for_approval",
  });
  const [approvalCards, onDecided] = useStickyApprovals(
    execution.data?.status === "waiting_for_approval" ? (pendingApproval.data?.items ?? []) : [],
  );
  const [tab, setTab] = useState<Tab>("timeline");
  const [selected, setSelected] = useState<string | null>(null);
  const [verifyRequested, setVerifyRequested] = useState(false);
  const verification = useQuery({
    queryKey: ["verify", executionId, version],
    queryFn: () => api.verifyAudit(executionId),
    enabled: verifyRequested || tab === "integrity",
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelExecution(executionId, "cancelled from the execution workspace"),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["execution", executionId] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (execution.isLoading) return <LoadingState />;
  if (execution.error || !execution.data) return <ErrorState error={execution.error} onRetry={() => void execution.refetch()} />;
  const ex = execution.data;
  const evs = events.data?.items ?? [];
  const decs = decisions.data ?? [];
  const current = evs.find((e) => e.id === selected) ?? evs[evs.length - 1];
  const cancellable = ex.status === "pending" || ex.status === "waiting_for_approval";
  const effects = Object.entries(ex.sandbox_effects);

  return (
    <div className="space-y-5">
      <PageHeader
        title={`Execution ${ex.id}`}
        description={ex.task}
        actions={
          <>
            <Link to={`/replay?execution=${ex.id}`} className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
              <Rewind className="h-4 w-4" aria-hidden /> Replay
            </Link>
            <Button size="sm" icon={<ShieldCheck className="h-3.5 w-3.5" />} onClick={() => { setVerifyRequested(true); setTab("integrity"); }}>
              Verify audit trail
            </Button>
            {cancellable && (
              <Button size="sm" variant="danger" icon={<Ban className="h-3.5 w-3.5" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
                Cancel execution
              </Button>
            )}
            <ReportExport kind="execution" subjectId={ex.id} label="Report" />
          </>
        }
      />
      {cancel.isError && <Alert tone="error">{describeError(cancel.error)}</Alert>}

      <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm sm:grid-cols-3 lg:grid-cols-6">
        <div><div className="text-xs text-slate-500">Status</div><StatusBadge status={ex.status} /></div>
        <div><div className="text-xs text-slate-500">Scenario</div>{ex.scenario_id} <span className="text-xs text-slate-400">v{ex.scenario_version}</span></div>
        <div><div className="text-xs text-slate-500">Policy</div><Mono>{ex.policy_id}@v{ex.policy_version}</Mono></div>
        <div><div className="text-xs text-slate-500">Agent · seed · env</div>{ex.agent_type} · {ex.seed} · {ex.environment}</div>
        <div><div className="text-xs text-slate-500">Steps / tool calls / events</div><span className="tabular-nums">{ex.step_count} / {ex.tool_call_count} / {ex.event_count}</span></div>
        <div><div className="text-xs text-slate-500">Created</div>{formatTime(ex.created_at)}</div>
        {ex.status_reason && <div className="sm:col-span-3 lg:col-span-6 text-xs text-slate-600"><span className="font-medium">Reason:</span> {ex.status_reason}</div>}
        {ex.final_output && <div className="sm:col-span-3 lg:col-span-6 text-xs text-slate-600"><span className="font-medium">Agent output:</span> {ex.final_output}</div>}
      </div>

      {approvalCards.map((a) => (
        <ApprovalCard key={a.id} approval={a} showExecutionLink={false} onDecided={onDecided} />
      ))}

      <Tabs<Tab>
        label="Execution views"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "timeline", label: "Timeline" },
          { id: "graph", label: "Flow graph" },
          { id: "decisions", label: `Policy decisions (${decs.length})` },
          { id: "effects", label: "Sandbox effects" },
          { id: "integrity", label: "Audit integrity" },
        ]}
      />

      {events.error && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}
      {tab === "timeline" && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-2" title="Events" padded>
            {evs.length === 0 ? <EmptyState title="No events" /> : <Timeline events={evs} selectedId={current?.id ?? null} onSelect={setSelected} />}
          </Card>
          <Card className="lg:col-span-3" title="Event details">
            {current ? <EventDetail event={current} decision={decisionFor(current, evs, decs)} /> : <EmptyState title="Select an event" />}
          </Card>
        </div>
      )}
      {tab === "graph" && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3" title="Authorisation flow per step">
            <FlowGraph events={evs} onSelect={setSelected} />
          </Card>
          <Card className="lg:col-span-2" title="Selected event">
            {current ? <EventDetail event={current} decision={decisionFor(current, evs, decs)} /> : <EmptyState title="Click a node" />}
          </Card>
        </div>
      )}
      {tab === "decisions" && (
        <Card padded={false}>
          {decs.length === 0 ? <EmptyState title="No policy decisions" /> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="px-4 py-2">Decision</th><th className="px-2 py-2">Tool</th><th className="px-2 py-2">Outcome</th><th className="px-2 py-2">Rule</th><th className="px-2 py-2">Reason</th><th className="px-2 py-2">µs</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {decs.map((d) => (
                  <tr key={d.id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-2">
                      <button type="button" className="font-mono text-[11px] text-accent-700 hover:underline"
                        onClick={() => { setSelected(d.event_id); setTab("timeline"); }}>{d.id}</button>
                    </td>
                    <td className="px-2 py-2"><Mono>{d.tool_id}</Mono></td>
                    <td className="px-2 py-2"><OutcomeBadge outcome={d.outcome} /></td>
                    <td className="px-2 py-2"><Mono>{d.deciding_rule}</Mono></td>
                    <td className="px-2 py-2 text-xs text-slate-600">{d.reason}</td>
                    <td className="px-2 py-2 tabular-nums text-xs">{d.latency_us.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {tab === "effects" && (
        <div className="grid gap-4 md:grid-cols-2">
          {effects.map(([key, items]) => (
            <Card key={key} title={`${key.replaceAll("_", " ")} (${items.length})`}>
              {items.length === 0 ? <p className="text-sm text-slate-500">Nothing recorded in this execution's sandbox.</p> : <JsonView value={items} label={key} maxHeight="14rem" />}
            </Card>
          ))}
          <p className="text-xs text-slate-500 md:col-span-2">
            Effects exist only in this execution's isolated mock sandbox. No real email, ticket, record or export is ever created.
          </p>
        </div>
      )}
      {tab === "integrity" && (
        <Card title="Hash chain and completeness">
          {verification.isLoading && <LoadingState label="Verifying…" />}
          {verification.error && <ErrorState error={verification.error} />}
          {verification.data && (
            <div className="space-y-3 text-sm">
              <Alert tone={verification.data.chain.valid ? "success" : "error"}>
                Hash chain {verification.data.chain.valid ? "valid" : "INVALID"} across {verification.data.chain.event_count} events · head <Mono>{verification.data.chain.head.slice(0, 20)}…</Mono>
                {verification.data.chain.problems.map((p) => <div key={p}>{p}</div>)}
              </Alert>
              <Alert tone={verification.data.completeness.complete ? "success" : "error"}>
                Audit completeness: {verification.data.completeness.complete ? "all structural invariants hold" : "problems found"}
                {verification.data.completeness.problems.map((p) => <div key={p}>{p}</div>)}
              </Alert>
              <p className="text-xs text-slate-500">{verification.data.limitations}</p>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
