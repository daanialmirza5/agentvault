import { useMutation, useQuery } from "@tanstack/react-query";
import { GitCompare, Rewind } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { StatusBadge } from "../../components/badges";
import { Alert, Button, Card, EmptyState, Mono, PageHeader, SelectInput } from "../../components/ui";
import { useExecutions, usePolicies, usePolicy } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import { formatTime } from "../../services/format";
import type { Replay } from "../../types/api";
import { ReplayViewer, ToolCallTable } from "./ReplayViewer";

function ComparePanel({ options }: { options: { id: string; label: string }[] }) {
  const [left, setLeft] = useState(options[0]?.id ?? "");
  const [right, setRight] = useState(options[1]?.id ?? "");
  const compare = useMutation({ mutationFn: () => api.compareExecutions(left, right) });
  const r = compare.data;
  return (
    <Card title="Compare two recorded executions">
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <SelectInput label="Left execution" value={left} onChange={(e) => setLeft(e.target.value)}>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </SelectInput>
        <SelectInput label="Right execution" value={right} onChange={(e) => setRight(e.target.value)}>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </SelectInput>
        <Button variant="primary" icon={<GitCompare className="h-4 w-4" />} loading={compare.isPending} disabled={!left || !right} onClick={() => compare.mutate()}>
          Find first divergence
        </Button>
      </div>
      {compare.isError && <div className="mt-3"><Alert tone="error">{describeError(compare.error)}</Alert></div>}
      {r && (
        <div className="mt-4 space-y-3">
          {!r.same_scenario && <Alert tone="warning">These executions ran different scenarios; divergence is expected.</Alert>}
          <Alert tone={r.divergence.diverged ? "warning" : "success"}>
            {r.divergence.diverged ? (
              <>First divergence at comparable position {r.divergence.index}: {r.divergence.explanation} (left event <Mono>{r.divergence.left?.event_id ?? "—"}</Mono>, right event <Mono>{r.divergence.right?.event_id ?? "—"}</Mono>)</>
            ) : r.divergence.explanation}
          </Alert>
          <div className="overflow-hidden rounded-md border border-slate-200">
            <ToolCallTable left={r.tool_calls.left} right={r.tool_calls.right} leftLabel={`${r.left.execution_id} (${r.left.policy})`} rightLabel={`${r.right.execution_id} (${r.right.policy})`} />
          </div>
        </div>
      )}
    </Card>
  );
}

export function ReplayPage() {
  const [params, setParams] = useSearchParams();
  const executions = useExecutions({ limit: 100 });
  const policies = usePolicies();
  const items = (executions.data?.items ?? []).filter((e) => !["pending", "running"].includes(e.status));
  const executionId = params.get("execution") ?? items[0]?.id ?? "";
  const [mode, setMode] = useState<"recorded" | "simulate">("recorded");
  const [policyId, setPolicyId] = useState("");
  const [version, setVersion] = useState("");
  const [strategy, setStrategy] = useState("recorded");
  const [replay, setReplay] = useState<Replay | null>(null);
  const policy = usePolicy(policyId || undefined);
  const previous = useQuery({ queryKey: ["replays", executionId, replay?.id], queryFn: () => api.replays({ execution_id: executionId, limit: 10 }), enabled: Boolean(executionId) });

  const create = useMutation({
    mutationFn: () => api.createReplay({
      execution_id: executionId, mode,
      policy_id: mode === "simulate" && policyId ? policyId : undefined,
      policy_version: mode === "simulate" && version ? Number(version) : undefined,
      approval_strategy: mode === "simulate" ? strategy : undefined,
    }),
    onSuccess: setReplay,
  });
  const options = items.map((e) => ({ id: e.id, label: `${e.id} · ${e.scenario_id} · ${e.policy_id}@v${e.policy_version} · ${e.status}` }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Replay workspace"
        description="Step through a recorded execution, or re-run it in an isolated simulation under any policy version. Replays never repeat side effects: deterministic mock tools re-run against a fresh sandbox, non-deterministic outputs and human decisions come from the recording."
      />
      <Card title="Open a replay">
        {items.length === 0 ? (
          <EmptyState title="No finished or paused executions to replay" description="Launch a scenario first." />
        ) : (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              <div className="xl:col-span-2">
                <SelectInput label="Execution" value={executionId} onChange={(e) => { setParams({ execution: e.target.value }); setReplay(null); }}>
                  {!options.some((o) => o.id === executionId) && executionId && <option value={executionId}>{executionId}</option>}
                  {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                </SelectInput>
              </div>
              <SelectInput label="Mode" value={mode} onChange={(e) => setMode(e.target.value as "recorded" | "simulate")}>
                <option value="recorded">Recorded timeline</option>
                <option value="simulate">Simulate (isolated re-run)</option>
              </SelectInput>
              <SelectInput label="Policy for simulation" value={policyId} disabled={mode !== "simulate"} onChange={(e) => { setPolicyId(e.target.value); setVersion(""); }}>
                <option value="">same as original</option>
                {(policies.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </SelectInput>
              <div className="grid grid-cols-2 gap-2">
                <SelectInput label="Version" value={version} disabled={mode !== "simulate" || !policyId} onChange={(e) => setVersion(e.target.value)}>
                  <option value="">latest</option>
                  {(policy.data?.versions ?? []).map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
                </SelectInput>
                <SelectInput label="Approvals" value={strategy} disabled={mode !== "simulate"} onChange={(e) => setStrategy(e.target.value)}>
                  <option value="recorded">recorded</option>
                  <option value="approve_all">what-if: approve all</option>
                  <option value="reject_all">what-if: reject all</option>
                </SelectInput>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                {(previous.data?.items ?? []).length > 0 && <span>Earlier replays:</span>}
                {(previous.data?.items ?? []).map((r) => (
                  <button key={r.id} type="button" onClick={() => setReplay(r)} className="rounded border border-slate-200 px-1.5 py-0.5 hover:bg-slate-50">
                    {r.mode} · {r.policy_id}@v{r.policy_version} · {formatTime(r.created_at)}
                  </button>
                ))}
              </div>
              <Button variant="primary" icon={<Rewind className="h-4 w-4" />} loading={create.isPending} disabled={!executionId} onClick={() => create.mutate()}>
                Start replay
              </Button>
            </div>
            {create.isError && <Alert tone="error">{describeError(create.error)}</Alert>}
          </div>
        )}
      </Card>
      {replay && <ReplayViewer key={replay.id} replay={replay} />}
      {options.length >= 2 && <ComparePanel options={options} />}
      {items.length > 0 && !replay && (
        <p className="text-xs text-slate-500">Selected execution status: <StatusBadge status={items.find((e) => e.id === executionId)?.status ?? "pending"} /></p>
      )}
    </div>
  );
}
