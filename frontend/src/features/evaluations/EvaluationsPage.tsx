import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Pill, StatusBadge } from "../../components/badges";
import { Alert, Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, SelectInput, TextInput } from "../../components/ui";
import { useEvaluations, usePolicies, useScenarios } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import { formatTime } from "../../services/format";
import type { Scenario } from "../../types/api";

function RunForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const scenarios = useScenarios();
  const policies = usePolicies();
  const [name, setName] = useState("Baseline vs strict lockdown");
  const [refs, setRefs] = useState<{ policy_id: string; version: string }[]>([
    { policy_id: "baseline", version: "" }, { policy_id: "strict-lockdown", version: "" },
  ]);
  const [replayCheck, setReplayCheck] = useState(true);
  const latest = useMemo(() => {
    const m = new Map<string, Scenario>();
    for (const s of scenarios.data?.items ?? []) if (!m.has(s.scenario_id)) m.set(s.scenario_id, s);
    return [...m.values()].filter((s) => s.source === "demo" || s.source === "adversarial" || s.source === "custom");
  }, [scenarios.data]);
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const chosen = selected ?? new Set(latest.filter((s) => s.source !== "custom").map((s) => s.scenario_id));

  const run = useMutation({
    mutationFn: () => api.runEvaluation({
      name,
      scenario_ids: [...chosen],
      policies: refs.map((r) => ({ policy_id: r.policy_id, version: r.version ? Number(r.version) : undefined })),
      include_replay_check: replayCheck,
    }),
    onSuccess: (ev) => {
      void qc.invalidateQueries({ queryKey: ["evaluations"] });
      void qc.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/evaluations/${ev.id}`);
    },
  });
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };

  if (scenarios.isLoading || policies.isLoading) return <LoadingState />;
  return (
    <Card title="Run a reproducible evaluation">
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <TextInput label="Evaluation name" value={name} onChange={(e) => setName(e.target.value)} />
          <div>
            <div className="mb-1 text-xs font-medium text-slate-600">Policy versions to compare (same scenario inputs for each)</div>
            {refs.map((r, i) => (
              <div key={i} className="mb-2 grid grid-cols-[1fr_7rem_auto] items-end gap-2">
                <SelectInput label={`Policy ${i + 1}`} value={r.policy_id} onChange={(e) => setRefs(refs.map((x, j) => (j === i ? { policy_id: e.target.value, version: "" } : x)))}>
                  {(policies.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </SelectInput>
                <TextInput label="Version" type="number" min={1} placeholder="latest" value={r.version}
                  onChange={(e) => setRefs(refs.map((x, j) => (j === i ? { ...x, version: e.target.value } : x)))} />
                <Button size="sm" variant="ghost" aria-label={`Remove policy ${i + 1}`} disabled={refs.length === 1}
                  onClick={() => setRefs(refs.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5 text-rose-600" /></Button>
              </div>
            ))}
            <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} disabled={refs.length >= 4}
              onClick={() => setRefs([...refs, { policy_id: "permissive-dev", version: "" }])}>Add policy</Button>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={replayCheck} onChange={(e) => setReplayCheck(e.target.checked)} />
            Replay every run in simulate mode to measure replay consistency
          </label>
        </div>
        <fieldset>
          <legend className="mb-1 flex w-full items-center justify-between text-xs font-medium text-slate-600">
            <span>Scenarios ({chosen.size} selected)</span>
            <span className="space-x-2">
              <button type="button" className="text-accent-600 hover:underline" onClick={() => setSelected(new Set(latest.map((s) => s.scenario_id)))}>All</button>
              <button type="button" className="text-accent-600 hover:underline" onClick={() => setSelected(new Set())}>None</button>
            </span>
          </legend>
          <div className="max-h-72 space-y-1 overflow-y-auto rounded-md border border-slate-200 p-2">
            {latest.map((s) => (
              <label key={s.scenario_id} className="flex items-start gap-2 rounded px-1 py-1 text-sm hover:bg-slate-50">
                <input type="checkbox" className="mt-0.5" checked={chosen.has(s.scenario_id)} onChange={() => toggle(s.scenario_id)} />
                <span className="flex-1">
                  <span className="text-slate-800">{s.name}</span>
                  <span className="ml-2"><Pill tone={s.source === "adversarial" ? "rose" : "slate"}>{s.category.replaceAll("_", " ")}</Pill></span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
        <p className="max-w-2xl text-xs text-slate-500">
          Runs real executions through the engine. Expected outcomes are used only for scoring and are never visible to the policy
          engine. Runs synchronously; a full suite takes a few seconds.
        </p>
        <Button variant="primary" icon={<FlaskConical className="h-4 w-4" />} loading={run.isPending} disabled={chosen.size === 0} onClick={() => run.mutate()}>
          Run evaluation
        </Button>
      </div>
      {run.isError && <div className="mt-3"><Alert tone="error">{describeError(run.error)}</Alert></div>}
    </Card>
  );
}

export function EvaluationsPage() {
  const evaluations = useEvaluations();
  return (
    <div className="space-y-6">
      <PageHeader
        title="Evaluation lab"
        description="Run deterministic safety scenarios under several policy versions and compare unsafe-action blocking against legitimate-task disruption."
      />
      <RunForm />
      <Card title="Evaluation history" padded={false}>
        {evaluations.isLoading && <LoadingState />}
        {evaluations.error && <div className="p-4"><ErrorState error={evaluations.error} /></div>}
        {evaluations.data && evaluations.data.items.length === 0 && <EmptyState title="No evaluations yet" />}
        {evaluations.data && evaluations.data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">Name</th><th className="px-2 py-2">Status</th><th className="px-2 py-2">Policies</th><th className="px-2 py-2">Created</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {evaluations.data.items.map((ev) => {
                const resolved = (ev.request.resolved_policies as { policy_id: string; version: number }[] | undefined) ?? [];
                return (
                  <tr key={ev.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2"><Link className="text-accent-700 hover:underline" to={`/evaluations/${ev.id}`}>{ev.name}</Link></td>
                    <td className="px-2"><StatusBadge status={ev.status} /></td>
                    <td className="px-2 text-xs text-slate-600">{resolved.map((p) => `${p.policy_id}@v${p.version}`).join(", ")}</td>
                    <td className="px-2 text-xs text-slate-500">{formatTime(ev.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
