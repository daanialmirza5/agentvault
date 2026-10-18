import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Pill } from "../../components/badges";
import { Alert, Button, Card, SelectInput, TextInput } from "../../components/ui";
import { usePolicies, usePolicy, useScenarios } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import type { Scenario } from "../../types/api";

export function LaunchPanel() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const scenarios = useScenarios();
  const policies = usePolicies();
  const [scenarioId, setScenarioId] = useState("");
  const [policyId, setPolicyId] = useState("baseline");
  const [version, setVersion] = useState("");
  const [environment, setEnvironment] = useState("");
  const [seed, setSeed] = useState("");
  const policy = usePolicy(policyId || undefined);

  const latest = useMemo(() => {
    const seen = new Map<string, Scenario>();
    for (const s of scenarios.data?.items ?? []) if (!seen.has(s.scenario_id)) seen.set(s.scenario_id, s);
    return [...seen.values()];
  }, [scenarios.data]);
  const selected = latest.find((s) => s.scenario_id === scenarioId) ?? latest[0];

  const launch = useMutation({
    mutationFn: () =>
      api.launchExecution({
        scenario_id: selected?.scenario_id ?? "",
        policy_id: policyId,
        policy_version: version ? Number(version) : undefined,
        environment: environment || undefined,
        seed: seed === "" ? undefined : Number(seed),
      }),
    onSuccess: (execution) => {
      void qc.invalidateQueries({ queryKey: ["executions"] });
      void qc.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/executions/${execution.id}`);
    },
  });

  return (
    <Card title="Launch a scenario">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <div className="xl:col-span-2">
          <SelectInput label="Scenario" value={selected?.scenario_id ?? ""} onChange={(e) => setScenarioId(e.target.value)}>
            {latest.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.name} ({s.source})
              </option>
            ))}
          </SelectInput>
        </div>
        <SelectInput label="Policy" value={policyId} onChange={(e) => { setPolicyId(e.target.value); setVersion(""); }}>
          {(policies.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        <SelectInput label="Policy version" value={version} onChange={(e) => setVersion(e.target.value)}>
          <option value="">latest{policy.data ? ` (v${policy.data.latest_version})` : ""}</option>
          {(policy.data?.versions ?? []).map((v) => <option key={v.version} value={v.version}>v{v.version} — {v.change_note || "no note"}</option>)}
        </SelectInput>
        <div className="grid grid-cols-2 gap-2">
          <SelectInput label="Environment" value={environment} onChange={(e) => setEnvironment(e.target.value)}>
            <option value="">scenario default</option>
            <option value="sandbox">sandbox</option>
            <option value="staging">staging</option>
            <option value="production">production (simulated)</option>
          </SelectInput>
          <TextInput label="Seed" type="number" min={0} placeholder={selected ? String(selected.spec.seed) : ""} value={seed}
            onChange={(e) => setSeed(e.target.value)} />
        </div>
      </div>
      {selected && (
        <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-600">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone="indigo">{selected.category.replaceAll("_", " ")}</Pill>
            <Pill>{selected.spec.agent.type} agent</Pill>
            <Pill>{selected.spec.agent.steps.length} planned steps</Pill>
            {selected.spec.tags.map((t) => <Pill key={t}>#{t}</Pill>)}
          </div>
          <p className="mt-2"><span className="font-medium text-slate-800">Task:</span> {selected.spec.task}</p>
          <p className="mt-1 text-xs text-slate-500">{selected.description}</p>
        </div>
      )}
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          Runs synchronously against the backend until the execution completes, fails, is blocked or pauses for approval.
        </p>
        <Button variant="primary" icon={<Play className="h-4 w-4" />} loading={launch.isPending} disabled={!selected} onClick={() => launch.mutate()}>
          Launch
        </Button>
      </div>
      {launch.isError && <div className="mt-3"><Alert tone="error">{describeError(launch.error)}</Alert></div>}
    </Card>
  );
}
