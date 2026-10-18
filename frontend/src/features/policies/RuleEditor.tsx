import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useId } from "react";

import { OutcomeBadge } from "../../components/badges";
import { Button, SelectInput, TextInput } from "../../components/ui";
import type { ArgumentCondition, ConditionOp, Effect, PolicyRule, RiskLevel, RuleMatch } from "../../types/api";
import { parseConditionValue } from "./policyDocument";

const OPS: ConditionOp[] = ["eq", "neq", "in", "not_in", "contains", "prefix", "suffix", "glob", "exists", "not_exists", "gt", "gte", "lt", "lte"];
const RISKS: RiskLevel[] = ["low", "medium", "high", "critical"];

const listToText = (v: string[] | null | undefined) => (v ?? []).join(", ");
const textToList = (v: string): string[] | null => {
  const items = v.split(",").map((s) => s.trim()).filter(Boolean);
  return items.length ? items : null;
};

function ListField({ label, value, onChange, hint }: { label: string; value: string[] | null | undefined; onChange: (v: string[] | null) => void; hint?: string }) {
  return <TextInput label={label} hint={hint} value={listToText(value)} placeholder="any" onChange={(e) => onChange(textToList(e.target.value))} />;
}

function CheckGroup<T extends string>({ label, options, value, onChange }: { label: string; options: T[]; value: T[] | null | undefined; onChange: (v: T[] | null) => void }) {
  const id = useId();
  const selected = new Set(value ?? []);
  return (
    <fieldset aria-labelledby={id}>
      <legend id={id} className="text-xs font-medium text-slate-600">{label}</legend>
      <div className="mt-1 flex flex-wrap gap-3 text-sm">
        {options.map((o) => (
          <label key={o} className="flex items-center gap-1">
            <input type="checkbox" checked={selected.has(o)} onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(o); else next.delete(o);
              onChange(next.size ? options.filter((x) => next.has(x)) : null);
            }} />
            {o}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function RuleEditor({ rule, index, total, onChange, onRemove, onMove }: {
  rule: PolicyRule;
  index: number;
  total: number;
  onChange: (rule: PolicyRule) => void;
  onRemove: () => void;
  onMove: (delta: -1 | 1) => void;
}) {
  const setMatch = (patch: Partial<RuleMatch>) => onChange({ ...rule, match: { ...rule.match, ...patch } });
  const conditions = rule.match.arguments ?? [];
  const setCondition = (i: number, patch: Partial<ArgumentCondition>) =>
    setMatch({ arguments: conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

  return (
    <details open={index === 0} className="group rounded-md border border-slate-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2">
        <span className="flex items-center gap-2 text-sm">
          <span className="font-mono text-xs text-slate-400">#{index + 1}</span>
          <span className="font-medium text-slate-800">{rule.id || "(unnamed rule)"}</span>
          <OutcomeBadge outcome={rule.effect} />
          {!rule.enabled && <span className="text-xs text-slate-400">disabled</span>}
        </span>
        <span className="flex items-center gap-1">
          <Button size="sm" variant="ghost" aria-label={`Move rule ${rule.id} up`} disabled={index === 0} onClick={(e) => { e.preventDefault(); onMove(-1); }}><ArrowUp className="h-3.5 w-3.5" /></Button>
          <Button size="sm" variant="ghost" aria-label={`Move rule ${rule.id} down`} disabled={index === total - 1} onClick={(e) => { e.preventDefault(); onMove(1); }}><ArrowDown className="h-3.5 w-3.5" /></Button>
          <Button size="sm" variant="ghost" aria-label={`Remove rule ${rule.id}`} onClick={(e) => { e.preventDefault(); onRemove(); }}><Trash2 className="h-3.5 w-3.5 text-rose-600" /></Button>
        </span>
      </summary>
      <div className="space-y-3 border-t border-slate-100 p-3">
        <div className="grid gap-3 md:grid-cols-4">
          <TextInput label="Rule ID" value={rule.id} onChange={(e) => onChange({ ...rule, id: e.target.value })} hint="lowercase, digits, dashes" />
          <SelectInput label="Effect" value={rule.effect} onChange={(e) => onChange({ ...rule, effect: e.target.value as Effect })}>
            <option value="allow">allow</option>
            <option value="require_approval">require approval</option>
            <option value="deny">deny</option>
          </SelectInput>
          <TextInput label="Priority" type="number" min={0} max={10000} value={rule.priority}
            onChange={(e) => onChange({ ...rule, priority: Number(e.target.value) })} hint="orders same-effect rules" />
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input type="checkbox" checked={rule.enabled} onChange={(e) => onChange({ ...rule, enabled: e.target.checked })} /> Enabled
          </label>
        </div>
        <TextInput label="Description" value={rule.description} onChange={(e) => onChange({ ...rule, description: e.target.value })} />
        <div className="grid gap-3 md:grid-cols-2">
          <ListField label="Tool IDs" hint="comma-separated; globs like email.* allowed" value={rule.match.tool_ids} onChange={(v) => setMatch({ tool_ids: v })} />
          <ListField label="Categories" value={rule.match.categories} onChange={(v) => setMatch({ categories: v })} />
          <ListField label="Environments" value={rule.match.environments} onChange={(v) => setMatch({ environments: v })} />
          <ListField label="Scenario tags (any)" value={rule.match.scenario_tags} onChange={(v) => setMatch({ scenario_tags: v })} />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <CheckGroup label="Risk levels" options={RISKS} value={rule.match.risk_levels} onChange={(v) => setMatch({ risk_levels: v })} />
          <CheckGroup label="Operations" options={["read", "write"] as ("read" | "write")[]} value={rule.match.operations} onChange={(v) => setMatch({ operations: v })} />
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium text-slate-600">Argument conditions (all must hold)</span>
            <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setMatch({ arguments: [...conditions, { path: "", op: "eq", value: "" }] })}>
              Add condition
            </Button>
          </div>
          {conditions.length === 0 && <p className="text-xs text-slate-400">No argument conditions.</p>}
          {conditions.map((c, i) => (
            <div key={i} className="mb-2 grid grid-cols-[1fr_8rem_1fr_auto] items-end gap-2">
              <TextInput label="Path" value={c.path} placeholder="field" onChange={(e) => setCondition(i, { path: e.target.value })} />
              <SelectInput label="Operator" value={c.op} onChange={(e) => setCondition(i, { op: e.target.value as ConditionOp })}>
                {OPS.map((op) => <option key={op}>{op}</option>)}
              </SelectInput>
              <TextInput label="Value (JSON or text)" value={c.value === undefined || c.value === null ? "" : typeof c.value === "string" ? c.value : JSON.stringify(c.value)}
                disabled={c.op === "exists" || c.op === "not_exists"}
                onChange={(e) => setCondition(i, { value: parseConditionValue(e.target.value) })} />
              <Button size="sm" variant="ghost" aria-label="Remove condition" onClick={() => setMatch({ arguments: conditions.filter((_, j) => j !== i) })}>
                <Trash2 className="h-3.5 w-3.5 text-rose-600" />
              </Button>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}
