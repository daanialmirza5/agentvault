import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, RotateCcw, Save } from "lucide-react";
import { useState } from "react";

import { Alert, Button, Card, SelectInput, TextArea, TextInput } from "../../components/ui";
import { api, describeError } from "../../services/api";
import type { Effect, PolicyDetail, PolicyDocument, PolicyIssue } from "../../types/api";
import { normaliseDocument } from "./policyDocument";
import { RuleEditor } from "./RuleEditor";

const NEW_RULE = (n: number) => ({ id: `new-rule-${n}`, description: "", effect: "deny" as Effect, priority: 100, enabled: true, match: {} });

export function PolicyEditor({ policy, initial, onSaved }: { policy: PolicyDetail; initial: PolicyDocument; onSaved: (version: number) => void }) {
  const qc = useQueryClient();
  const [doc, setDoc] = useState<PolicyDocument>(initial);
  const [mode, setMode] = useState<"form" | "json">("form");
  const [jsonText, setJsonText] = useState(JSON.stringify(initial, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [issues, setIssues] = useState<PolicyIssue[] | null>(null);

  const currentDoc = (): PolicyDocument | null => {
    if (mode === "form") return normaliseDocument(doc);
    try {
      setJsonError(null);
      return JSON.parse(jsonText) as PolicyDocument;
    } catch (e) {
      setJsonError(`Invalid JSON: ${(e as Error).message}`);
      return null;
    }
  };

  const validate = useMutation({
    mutationFn: (d: PolicyDocument) => api.validatePolicy(d),
    onSuccess: (r) => setIssues(r.issues),
  });
  const save = useMutation({
    mutationFn: (d: PolicyDocument) =>
      api.createPolicyVersion(policy.id, { document: d, change_note: note, base_version: policy.latest_version }),
    onSuccess: (v) => {
      void qc.invalidateQueries({ queryKey: ["policy", policy.id] });
      void qc.invalidateQueries({ queryKey: ["policies"] });
      setNote("");
      onSaved(v.version);
    },
  });

  const switchMode = (next: "form" | "json") => {
    if (next === mode) return;
    if (next === "json") {
      setJsonText(JSON.stringify(normaliseDocument(doc), null, 2));
    } else {
      try {
        setDoc(JSON.parse(jsonText) as PolicyDocument);
        setJsonError(null);
      } catch (e) {
        setJsonError(`Fix the JSON before switching: ${(e as Error).message}`);
        return;
      }
    }
    setMode(next);
  };

  const updateRule = (i: number, rule: PolicyDocument["rules"][number]) => setDoc((d) => ({ ...d, rules: d.rules.map((r, j) => (j === i ? rule : r)) }));
  const moveRule = (i: number, delta: -1 | 1) => setDoc((d) => {
    const rules = [...d.rules];
    const [r] = rules.splice(i, 1);
    if (r) rules.splice(i + delta, 0, r);
    return { ...d, rules };
  });

  return (
    <Card
      title={`Editing ${policy.name} — based on v${policy.latest_version}`}
      actions={
        <div className="flex gap-1 rounded-md bg-slate-100 p-0.5 text-xs" role="group" aria-label="Editor mode">
          {(["form", "json"] as const).map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => switchMode(m)}
              className={`rounded px-2 py-1 ${mode === m ? "bg-white shadow-sm" : "text-slate-500"}`}>{m === "form" ? "Rule form" : "JSON"}</button>
          ))}
        </div>
      }
    >
      <div className="space-y-4">
        <Alert>
          Conflicts resolve as <strong>deny-overrides</strong>: deny beats require-approval beats allow. Unknown tools and
          invalid arguments are always denied first, and a tool that declares <em>requires approval</em> can never be relaxed
          to a plain allow. Saving creates a new immutable version.
        </Alert>
        {mode === "form" ? (
          <>
            <div className="w-64">
              <SelectInput label="Default effect (no rule matched)" value={doc.default_effect}
                onChange={(e) => setDoc({ ...doc, default_effect: e.target.value as Effect })}>
                <option value="deny">deny (recommended)</option>
                <option value="require_approval">require approval</option>
                <option value="allow">allow</option>
              </SelectInput>
            </div>
            <div className="space-y-2">
              {doc.rules.map((rule, i) => (
                <RuleEditor key={i} rule={rule} index={i} total={doc.rules.length} onChange={(r) => updateRule(i, r)}
                  onRemove={() => setDoc((d) => ({ ...d, rules: d.rules.filter((_, j) => j !== i) }))} onMove={(delta) => moveRule(i, delta)} />
              ))}
            </div>
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setDoc((d) => ({ ...d, rules: [...d.rules, NEW_RULE(d.rules.length + 1)] }))}>
              Add rule
            </Button>
          </>
        ) : (
          <TextArea label="Policy document (JSON)" rows={22} value={jsonText} onChange={(e) => setJsonText(e.target.value)} spellCheck={false} />
        )}
        {jsonError && <Alert tone="error">{jsonError}</Alert>}

        <div className="flex flex-wrap items-end gap-3 border-t border-slate-100 pt-4">
          <div className="min-w-64 flex-1">
            <TextInput label="Change note" value={note} maxLength={500} placeholder="What changed and why?" onChange={(e) => setNote(e.target.value)} />
          </div>
          <Button icon={<RotateCcw className="h-4 w-4" />} onClick={() => { setDoc(initial); setJsonText(JSON.stringify(initial, null, 2)); setIssues(null); }}>
            Reset
          </Button>
          <Button icon={<CheckCircle2 className="h-4 w-4" />} loading={validate.isPending} onClick={() => { const d = currentDoc(); if (d) validate.mutate(d); }}>
            Validate
          </Button>
          <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={save.isPending} disabled={!note.trim()}
            onClick={() => { const d = currentDoc(); if (d) save.mutate(d); }}>
            Save as v{policy.latest_version + 1}
          </Button>
        </div>
        {validate.isError && <Alert tone="error">{describeError(validate.error)}</Alert>}
        {issues && (
          <div aria-label="Validation results" className="space-y-2">
            {issues.length === 0 ? <Alert tone="success">No issues found.</Alert> : issues.map((i, n) => (
              <Alert key={n} tone={i.severity === "error" ? "error" : i.severity === "warning" ? "warning" : "info"}>
                <span className="font-mono text-xs">{i.code}</span> — {i.message}
              </Alert>
            ))}
          </div>
        )}
        {save.isError && <Alert tone="error">{describeError(save.error)}</Alert>}
        {save.isSuccess && <Alert tone="success">Saved {policy.id} v{save.data.version}.</Alert>}
      </div>
    </Card>
  );
}
