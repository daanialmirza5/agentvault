import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FilePlus2 } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { JsonView } from "../../components/JsonView";
import { OutcomeBadge } from "../../components/badges";
import { Alert, Button, Card, EmptyState, ErrorState, LoadingState, Mono, PageHeader, Pagination, SelectInput, Tabs, TextInput } from "../../components/ui";
import { useAuditDecisions, useAuditEvents, useReports } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import { formatTime } from "../../services/format";
import type { ReportMeta } from "../../types/api";

type Tab = "events" | "decisions" | "reports";
const LIMIT = 25;
const EVENT_TYPES = [
  "", "execution.", "agent.action_proposed", "tool.", "tool.blocked", "tool.failed", "policy.evaluated", "approval.",
  "approval.binding_mismatch", "guard.triggered",
];

function EventsTab() {
  const [filters, setFilters] = useState({ execution_id: "", event_type: "", tool_id: "", outcome: "" });
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const events = useAuditEvents({ ...filters, limit: LIMIT, offset });
  const set = (k: keyof typeof filters, v: string) => { setFilters({ ...filters, [k]: v }); setOffset(0); };
  return (
    <Card padded={false}>
      <div className="grid gap-3 border-b border-slate-100 p-4 md:grid-cols-4">
        <TextInput label="Execution ID" value={filters.execution_id} onChange={(e) => set("execution_id", e.target.value.trim())} placeholder="exe_…" />
        <SelectInput label="Event type" value={filters.event_type} onChange={(e) => set("event_type", e.target.value)}>
          {EVENT_TYPES.map((t) => <option key={t} value={t}>{t ? (t.endsWith(".") ? `${t}*` : t) : "All types"}</option>)}
        </SelectInput>
        <TextInput label="Tool ID" value={filters.tool_id} onChange={(e) => set("tool_id", e.target.value.trim())} placeholder="email.send" />
        <TextInput label="Outcome" value={filters.outcome} onChange={(e) => set("outcome", e.target.value.trim())} placeholder="deny, denied, failed…" />
      </div>
      {events.isLoading && <LoadingState />}
      {events.error && <div className="p-4"><ErrorState error={events.error} /></div>}
      {events.data && events.data.items.length === 0 && <EmptyState title="No events match these filters" />}
      {events.data && events.data.items.length > 0 && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">Time</th><th className="px-2 py-2">Execution</th><th className="px-2 py-2">#</th><th className="px-2 py-2">Event</th><th className="px-2 py-2">Tool</th><th className="px-2 py-2">Outcome</th><th className="px-2 py-2" /></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {events.data.items.map((e) => (
                <Fragment key={e.id}>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-1.5 text-xs text-slate-500">{formatTime(e.timestamp)}</td>
                    <td className="px-2"><Link to={`/executions/${e.execution_id}`} className="font-mono text-[11px] text-accent-700 hover:underline">{e.execution_id}</Link></td>
                    <td className="px-2 font-mono text-xs">{e.sequence}</td>
                    <td className="px-2"><Mono>{e.event_type}</Mono></td>
                    <td className="px-2 text-xs">{e.tool_id ?? "—"}</td>
                    <td className="px-2"><OutcomeBadge outcome={e.outcome} /></td>
                    <td className="px-2 text-right"><Button size="sm" variant="ghost" aria-expanded={open === e.id} onClick={() => setOpen(open === e.id ? null : e.id)}>{open === e.id ? "Hide" : "Data"}</Button></td>
                  </tr>
                  {open === e.id && <tr><td colSpan={7} className="px-4 pb-3"><JsonView value={{ ...e.data, hash: e.hash, prev_hash: e.prev_hash }} label={`Event ${e.id} data`} maxHeight="14rem" /></td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
          <Pagination total={events.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}
    </Card>
  );
}

function DecisionsTab() {
  const [outcome, setOutcome] = useState("");
  const [toolId, setToolId] = useState("");
  const [offset, setOffset] = useState(0);
  const decisions = useAuditDecisions({ outcome, tool_id: toolId, limit: LIMIT, offset });
  return (
    <Card padded={false}>
      <div className="grid gap-3 border-b border-slate-100 p-4 md:grid-cols-4">
        <SelectInput label="Outcome" value={outcome} onChange={(e) => { setOutcome(e.target.value); setOffset(0); }}>
          <option value="">All outcomes</option><option value="allow">allow</option><option value="deny">deny</option><option value="require_approval">require approval</option>
        </SelectInput>
        <TextInput label="Tool ID" value={toolId} onChange={(e) => { setToolId(e.target.value.trim()); setOffset(0); }} />
      </div>
      {decisions.isLoading && <LoadingState />}
      {decisions.error && <div className="p-4"><ErrorState error={decisions.error} /></div>}
      {decisions.data && decisions.data.items.length === 0 && <EmptyState title="No decisions match" />}
      {decisions.data && decisions.data.items.length > 0 && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">Time</th><th className="px-2 py-2">Decision</th><th className="px-2 py-2">Policy</th><th className="px-2 py-2">Tool</th><th className="px-2 py-2">Outcome</th><th className="px-2 py-2">Rule</th><th className="px-2 py-2">Execution</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {decisions.data.items.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <td className="px-4 py-1.5 text-xs text-slate-500">{formatTime(d.created_at)}</td>
                  <td className="px-2"><Mono>{d.id}</Mono></td>
                  <td className="px-2"><Mono>{d.policy_id}@v{d.policy_version}</Mono></td>
                  <td className="px-2"><Mono>{d.tool_id}</Mono></td>
                  <td className="px-2"><OutcomeBadge outcome={d.outcome} /></td>
                  <td className="px-2 text-xs">{d.deciding_rule}</td>
                  <td className="px-2"><Link to={`/executions/${d.execution_id}`} className="font-mono text-[11px] text-accent-700 hover:underline">{d.execution_id}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination total={decisions.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}
    </Card>
  );
}

function ReportsTab() {
  const qc = useQueryClient();
  const reports = useReports();
  const [kind, setKind] = useState<ReportMeta["kind"]>("execution");
  const [subject, setSubject] = useState("");
  const create = useMutation({
    mutationFn: () => api.createReport(kind, subject.trim()),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports"] }),
  });
  const download = useMutation({ mutationFn: ({ id, format }: { id: string; format: "json" | "markdown" }) => api.downloadReport(id, format) });
  const placeholder = { execution: "exe_…", replay: "rpl_…", evaluation: "eval_…", policy_comparison: "baseline@v1..strict-lockdown@v1" }[kind];
  return (
    <div className="space-y-4">
      <Card title="Generate a report">
        <div className="grid gap-3 md:grid-cols-[12rem_1fr_auto] md:items-end">
          <SelectInput label="Kind" value={kind} onChange={(e) => setKind(e.target.value as ReportMeta["kind"])}>
            <option value="execution">Execution</option><option value="replay">Replay</option><option value="evaluation">Evaluation</option><option value="policy_comparison">Policy comparison</option>
          </SelectInput>
          <TextInput label="Subject" value={subject} placeholder={placeholder} onChange={(e) => setSubject(e.target.value)} />
          <Button variant="primary" icon={<FilePlus2 className="h-4 w-4" />} loading={create.isPending} disabled={!subject.trim()} onClick={() => create.mutate()}>Generate</Button>
        </div>
        {create.isError && <div className="mt-3"><Alert tone="error">{describeError(create.error)}</Alert></div>}
        {create.isSuccess && <div className="mt-3"><Alert tone="success">Generated {create.data.title} ({create.data.id}).</Alert></div>}
      </Card>
      <Card title="Reports" padded={false}>
        {reports.isLoading && <LoadingState />}
        {reports.error && <div className="p-4"><ErrorState error={reports.error} /></div>}
        {reports.data && reports.data.items.length === 0 && <EmptyState title="No reports yet" description="Generate one above or use the Export buttons on executions, replays and evaluations." />}
        {reports.data && reports.data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">Title</th><th className="px-2 py-2">Kind</th><th className="px-2 py-2">Created</th><th className="px-2 py-2">Download</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {reports.data.items.map((r) => (
                <tr key={r.id}>
                  <td className="px-4 py-2">{r.title} <span className="font-mono text-[11px] text-slate-400">{r.id}</span></td>
                  <td className="px-2 text-xs">{r.kind.replace("_", " ")}</td>
                  <td className="px-2 text-xs text-slate-500">{formatTime(r.created_at)}</td>
                  <td className="space-x-2 px-2 py-1">
                    <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download.mutate({ id: r.id, format: "json" })}>JSON</Button>
                    <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download.mutate({ id: r.id, format: "markdown" })}>Markdown</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {download.isError && <div className="p-4"><Alert tone="error">{describeError(download.error)}</Alert></div>}
      </Card>
    </div>
  );
}

export function AuditPage() {
  const [tab, setTab] = useState<Tab>("events");
  return (
    <div className="space-y-4">
      <PageHeader title="Audit & reports"
        description="Search the append-only event log and decision history across executions, and export JSON or Markdown reports built from stored records." />
      <Tabs<Tab> label="Audit views" value={tab} onChange={setTab}
        tabs={[{ id: "events", label: "Events" }, { id: "decisions", label: "Decision history" }, { id: "reports", label: "Reports" }]} />
      {tab === "events" && <EventsTab />}
      {tab === "decisions" && <DecisionsTab />}
      {tab === "reports" && <ReportsTab />}
    </div>
  );
}
