import { useMutation } from "@tanstack/react-query";
import { GitCompare } from "lucide-react";
import { useState } from "react";

import { ReportExport } from "../../components/ReportExport";
import { OutcomeBadge, RiskBadge } from "../../components/badges";
import { Alert, Button, Card, Mono, SelectInput } from "../../components/ui";
import { usePolicy } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import type { PolicySummary } from "../../types/api";

function RefPicker({ label, policies, value, onChange }: {
  label: string;
  policies: PolicySummary[];
  value: { policy_id: string; version: number };
  onChange: (v: { policy_id: string; version: number }) => void;
}) {
  const detail = usePolicy(value.policy_id);
  return (
    <div className="grid grid-cols-2 gap-2">
      <SelectInput label={`${label} policy`} value={value.policy_id}
        onChange={(e) => onChange({ policy_id: e.target.value, version: policies.find((p) => p.id === e.target.value)?.latest_version ?? 1 })}>
        {policies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </SelectInput>
      <SelectInput label={`${label} version`} value={value.version} onChange={(e) => onChange({ ...value, version: Number(e.target.value) })}>
        {(detail.data?.versions ?? [{ version: value.version }]).map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
      </SelectInput>
    </div>
  );
}

export function PolicyCompare({ policies }: { policies: PolicySummary[] }) {
  const first = policies[0];
  const second = policies[1] ?? first;
  const [left, setLeft] = useState({ policy_id: first?.id ?? "", version: first?.latest_version ?? 1 });
  const [right, setRight] = useState({ policy_id: second?.id ?? "", version: second?.latest_version ?? 1 });
  const compare = useMutation({ mutationFn: () => api.comparePolicies(left, right) });
  const r = compare.data;

  return (
    <div className="space-y-4">
      <Card title="Compare two policy versions">
        <div className="grid gap-4 md:grid-cols-2">
          <RefPicker label="Left" policies={policies} value={left} onChange={setLeft} />
          <RefPicker label="Right" policies={policies} value={right} onChange={setRight} />
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-500">For scenario-level evidence (blocked unsafe actions vs. disrupted legitimate work) use the evaluation lab.</p>
          <div className="flex items-center gap-2">
            {r && <ReportExport kind="policy_comparison" subjectId={`${left.policy_id}@v${left.version}..${right.policy_id}@v${right.version}`} label="Report" />}
            <Button variant="primary" icon={<GitCompare className="h-4 w-4" />} loading={compare.isPending} onClick={() => compare.mutate()}>Compare</Button>
          </div>
        </div>
        {compare.isError && <div className="mt-3"><Alert tone="error">{describeError(compare.error)}</Alert></div>}
      </Card>
      {r && (
        <>
          <Card title={`Rule changes: ${r.left} → ${r.right}`}>
            <div className="space-y-2 text-sm">
              <div>Default effect: <OutcomeBadge outcome={r.diff.default_effect.before} /> → <OutcomeBadge outcome={r.diff.default_effect.after} />
                {!r.diff.default_effect.changed && <span className="ml-2 text-xs text-slate-400">(unchanged)</span>}</div>
              <div><span className="font-medium text-emerald-700">Added ({r.diff.added.length}):</span> {r.diff.added.map((x) => <Mono key={x.id} className="mr-1">{x.id}</Mono>)}</div>
              <div><span className="font-medium text-rose-700">Removed ({r.diff.removed.length}):</span> {r.diff.removed.map((x) => <Mono key={x.id} className="mr-1">{x.id}</Mono>)}</div>
              <div><span className="font-medium text-amber-700">Changed ({r.diff.changed.length}):</span> {r.diff.changed.map((x) => <span key={x.rule_id} className="mr-2"><Mono>{x.rule_id}</Mono> <span className="text-xs text-slate-500">({x.fields.join(", ")})</span></span>)}</div>
            </div>
          </Card>
          <Card title="Static decision matrix" padded={false}>
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="px-4 py-2">Tool</th><th className="px-2 py-2">Risk</th><th className="px-2 py-2">{r.left}</th><th className="px-2 py-2">{r.right}</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {r.matrix.map((row) => {
                  const [a, b] = Object.values(row.outcomes);
                  const differs = a?.outcome !== b?.outcome;
                  return (
                    <tr key={row.tool_id} className={differs ? "bg-amber-50/50" : undefined}>
                      <td className="px-4 py-2"><Mono>{row.tool_id}</Mono></td>
                      <td className="px-2"><RiskBadge risk={row.risk_level} /></td>
                      <td className="px-2"><OutcomeBadge outcome={a?.outcome} /> <span className="text-[11px] text-slate-400">{a?.rule}</span></td>
                      <td className="px-2"><OutcomeBadge outcome={b?.outcome} /> <span className="text-[11px] text-slate-400">{b?.rule}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="px-4 py-2 text-xs text-slate-500">{r.note}</p>
          </Card>
        </>
      )}
    </div>
  );
}
