import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { JsonView } from "../../components/JsonView";
import { Modal } from "../../components/Modal";
import { Pill, RiskBadge } from "../../components/badges";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  SelectInput,
  TextArea,
  TextInput,
} from "../../components/ui";
import { keys, useTools } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import type { JsonObject, Tool } from "../../types/api";

const DEFAULT_SCHEMA = JSON.stringify(
  { type: "object", properties: { city: { type: "string", maxLength: 80 } }, required: ["city"], additionalProperties: false },
  null,
  2,
);

function RegisterToolDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    tool_id: "weather.lookup", name: "Weather lookup", description: "Returns a canned forecast (mock).",
    category: "info", risk_level: "low", mutating: false, requires_approval: false, timeout_seconds: 2,
    implementation: "mock.static_response", input_schema: DEFAULT_SCHEMA, response: '{\n  "forecast": "sunny"\n}',
  });
  const [parseError, setParseError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (body: JsonObject) => api.createTool(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.tools });
    },
  });

  const submit = () => {
    setParseError(null);
    let inputSchema: JsonObject;
    let response: JsonObject;
    try {
      inputSchema = JSON.parse(form.input_schema) as JsonObject;
      response = JSON.parse(form.response) as JsonObject;
    } catch (e) {
      setParseError(`Invalid JSON: ${(e as Error).message}`);
      return;
    }
    mutation.mutate({
      tool_id: form.tool_id, name: form.name, description: form.description, category: form.category,
      risk_level: form.risk_level, mutating: form.mutating, requires_approval: form.requires_approval,
      timeout_seconds: Number(form.timeout_seconds), implementation: form.implementation, input_schema: inputSchema,
      output_schema: { type: "object" }, mock_config: form.implementation === "mock.static_response" ? { response } : {},
    });
  };

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }));
  return (
    <Modal
      open={open}
      wide
      title="Register a custom tool"
      onClose={() => { mutation.reset(); onClose(); }}
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          <Button variant="primary" loading={mutation.isPending} onClick={submit}>Register tool</Button>
        </>
      }
    >
      <Alert>
        Custom tools can only bind to the generic mock implementations (<Mono>mock.static_response</Mono> or <Mono>mock.echo</Mono>).
        AgentVault never registers executable code. The input schema must forbid undeclared properties.
      </Alert>
      <div className="grid grid-cols-2 gap-3">
        <TextInput label="Tool ID" value={form.tool_id} onChange={(e) => set("tool_id", e.target.value)} hint="e.g. weather.lookup" />
        <TextInput label="Name" value={form.name} onChange={(e) => set("name", e.target.value)} />
        <TextInput label="Category" value={form.category} onChange={(e) => set("category", e.target.value)} />
        <SelectInput label="Risk level" value={form.risk_level} onChange={(e) => set("risk_level", e.target.value)}>
          {["low", "medium", "high", "critical"].map((r) => <option key={r}>{r}</option>)}
        </SelectInput>
        <SelectInput label="Implementation" value={form.implementation} onChange={(e) => set("implementation", e.target.value)}>
          <option value="mock.static_response">mock.static_response</option>
          <option value="mock.echo">mock.echo</option>
        </SelectInput>
        <TextInput label="Timeout (seconds)" type="number" min={0.1} max={10} step={0.1} value={form.timeout_seconds}
          onChange={(e) => set("timeout_seconds", Number(e.target.value))} />
      </div>
      <TextInput label="Description" value={form.description} onChange={(e) => set("description", e.target.value)} />
      <div className="flex gap-6 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.mutating} onChange={(e) => set("mutating", e.target.checked)} /> Mutating (write) tool</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.requires_approval} onChange={(e) => set("requires_approval", e.target.checked)} /> Always requires human approval</label>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <TextArea label="Input JSON Schema" rows={9} value={form.input_schema} onChange={(e) => set("input_schema", e.target.value)} />
        <TextArea label="Mock response (static_response only)" rows={9} value={form.response} onChange={(e) => set("response", e.target.value)}
          disabled={form.implementation !== "mock.static_response"} />
      </div>
      {parseError && <Alert tone="error">{parseError}</Alert>}
      {mutation.isError && <Alert tone="error">{describeError(mutation.error)}</Alert>}
      {mutation.isSuccess && <Alert tone="success">Registered {mutation.data.tool_id}@{mutation.data.version}.</Alert>}
    </Modal>
  );
}

function ToolDetail({ tool }: { tool: Tool }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold text-slate-900">{tool.name}</h2>
          <Mono>{tool.tool_id}@{tool.version}</Mono>
        </div>
        <p className="mt-1 text-sm text-slate-600">{tool.description}</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-slate-500">Permission category</dt><dd>{tool.category}</dd>
        <dt className="text-slate-500">Risk</dt><dd><RiskBadge risk={tool.risk_level} /></dd>
        <dt className="text-slate-500">Operation</dt><dd>{tool.mutating ? "write (mutating)" : "read-only"}</dd>
        <dt className="text-slate-500">Human approval</dt><dd>{tool.requires_approval ? "always required (tool-level)" : "per policy"}</dd>
        <dt className="text-slate-500">Timeout</dt><dd>{tool.timeout_seconds}s</dd>
        <dt className="text-slate-500">Deterministic</dt><dd>{tool.deterministic ? "yes (seeded)" : "no — replays reuse recorded output"}</dd>
        <dt className="text-slate-500">Implementation</dt><dd><Mono>{tool.implementation}</Mono></dd>
        <dt className="text-slate-500">Origin</dt><dd>{tool.builtin ? "built-in" : "custom"}</dd>
      </dl>
      {tool.implementation_notes && <Alert>{tool.implementation_notes}</Alert>}
      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Input schema</h3>
        <JsonView value={tool.input_schema} label="Input schema" />
      </div>
      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Output schema</h3>
        <JsonView value={tool.output_schema} label="Output schema" maxHeight="12rem" />
      </div>
      {Object.keys(tool.mock_config).length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Mock configuration</h3>
          <JsonView value={tool.mock_config} label="Mock configuration" maxHeight="10rem" />
        </div>
      )}
    </div>
  );
}

export function ToolsPage() {
  const { data, isLoading, error, refetch } = useTools();
  const [risk, setRisk] = useState("");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);

  const tools = useMemo(() => data?.items ?? [], [data]);
  const categories = useMemo(() => [...new Set(tools.map((t) => t.category))].sort(), [tools]);
  const filtered = tools.filter(
    (t) => (!risk || t.risk_level === risk) && (!category || t.category === category) &&
      (!search || `${t.tool_id} ${t.name}`.toLowerCase().includes(search.toLowerCase())),
  );
  const current = tools.find((t) => `${t.tool_id}@${t.version}` === selected) ?? filtered[0];

  return (
    <div>
      <PageHeader
        title="Tool registry"
        description="Every tool an agent can request, with its schema, permission category, risk and approval requirements. All implementations are local mocks."
        actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setRegisterOpen(true)}>Register tool</Button>}
      />
      {isLoading && <LoadingState />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {data && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3" padded={false}
            title={`${filtered.length} tool version${filtered.length === 1 ? "" : "s"}`}
            actions={
              <div className="flex gap-2">
                <input aria-label="Search tools" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)}
                  className="w-36 rounded-md border border-slate-300 px-2 py-1 text-xs" />
                <select aria-label="Filter by risk" value={risk} onChange={(e) => setRisk(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1 text-xs">
                  <option value="">All risks</option>
                  {["low", "medium", "high", "critical"].map((r) => <option key={r}>{r}</option>)}
                </select>
                <select aria-label="Filter by category" value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1 text-xs">
                  <option value="">All categories</option>
                  {categories.map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
            }>
            {filtered.length === 0 ? <EmptyState title="No tools match these filters" /> : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr><th className="px-4 py-2">Tool</th><th className="px-2 py-2">Category</th><th className="px-2 py-2">Risk</th><th className="px-2 py-2">Access</th><th className="px-2 py-2">Approval</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filtered.map((t) => {
                    const id = `${t.tool_id}@${t.version}`;
                    const active = current && `${current.tool_id}@${current.version}` === id;
                    return (
                      <tr key={id} aria-selected={active} className={active ? "bg-accent-50/60" : "hover:bg-slate-50"}>
                        <td className="px-4 py-2">
                          <button type="button" className="text-left" onClick={() => setSelected(id)}>
                            <div className="font-medium text-slate-900">{t.name}</div>
                            <div className="font-mono text-[11px] text-slate-500">{id}</div>
                          </button>
                        </td>
                        <td className="px-2">{t.category}</td>
                        <td className="px-2"><RiskBadge risk={t.risk_level} /></td>
                        <td className="px-2">{t.mutating ? <Pill tone="amber">write</Pill> : <Pill>read</Pill>}</td>
                        <td className="px-2">{t.requires_approval ? <Pill tone="rose">always</Pill> : <span className="text-xs text-slate-400">policy</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Card>
          <Card className="lg:col-span-2">{current ? <ToolDetail tool={current} /> : <EmptyState title="Select a tool" />}</Card>
        </div>
      )}
      <RegisterToolDialog open={registerOpen} onClose={() => setRegisterOpen(false)} />
    </div>
  );
}
