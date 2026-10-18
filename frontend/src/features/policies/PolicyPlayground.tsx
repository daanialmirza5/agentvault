import { useMutation } from "@tanstack/react-query";
import { FlaskRound } from "lucide-react";
import { useState } from "react";

import { OutcomeBadge } from "../../components/badges";
import { Alert, Button, Card, Mono, SelectInput, TextArea, TextInput } from "../../components/ui";
import { useTools } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import type { JsonObject, PolicyDetail } from "../../types/api";

export function PolicyPlayground({ policy }: { policy: PolicyDetail }) {
  const tools = useTools();
  const [toolId, setToolId] = useState("email.send");
  const [args, setArgs] = useState('{\n  "to": "ada@example.com",\n  "subject": "Hello",\n  "body": "Hi"\n}');
  const [environment, setEnvironment] = useState("sandbox");
  const [tags, setTags] = useState("");
  const [version, setVersion] = useState(policy.latest_version);
  const [parseError, setParseError] = useState<string | null>(null);
  const simulate = useMutation({
    mutationFn: (parsed: JsonObject) => api.simulateDecision({
      policy: { policy_id: policy.id, version }, tool_id: toolId, arguments: parsed, environment,
      scenario_tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
    }),
  });
  const run = () => {
    try {
      setParseError(null);
      simulate.mutate(JSON.parse(args) as JsonObject);
    } catch (e) {
      setParseError(`Invalid JSON: ${(e as Error).message}`);
    }
  };
  const toolIds = [...new Set((tools.data?.items ?? []).map((t) => t.tool_id))];

  return (
    <Card title="Decision playground">
      <p className="mb-3 text-sm text-slate-500">Evaluate a hypothetical tool call against a saved policy version. Nothing executes and nothing is stored.</p>
      <div className="grid gap-3 md:grid-cols-4">
        <SelectInput label="Policy version" value={version} onChange={(e) => setVersion(Number(e.target.value))}>
          {policy.versions.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
        </SelectInput>
        <div>
          <TextInput label="Tool ID" list="playground-tools" value={toolId} onChange={(e) => setToolId(e.target.value)} hint="try an unregistered ID too" />
          <datalist id="playground-tools">{toolIds.map((t) => <option key={t} value={t} />)}</datalist>
        </div>
        <SelectInput label="Environment" value={environment} onChange={(e) => setEnvironment(e.target.value)}>
          <option>sandbox</option><option>staging</option><option>production</option>
        </SelectInput>
        <TextInput label="Scenario tags" value={tags} placeholder="comma-separated" onChange={(e) => setTags(e.target.value)} />
      </div>
      <div className="mt-3">
        <TextArea label="Arguments (JSON)" rows={6} value={args} onChange={(e) => setArgs(e.target.value)} spellCheck={false} />
      </div>
      <div className="mt-3 flex justify-end">
        <Button variant="primary" icon={<FlaskRound className="h-4 w-4" />} loading={simulate.isPending} onClick={run}>Evaluate</Button>
      </div>
      {parseError && <div className="mt-3"><Alert tone="error">{parseError}</Alert></div>}
      {simulate.isError && <div className="mt-3"><Alert tone="error">{describeError(simulate.error)}</Alert></div>}
      {simulate.data && (
        <div className="mt-4 space-y-2 rounded-md border border-slate-200 p-3 text-sm" aria-label="Simulated decision">
          <div className="flex items-center gap-2">Outcome <OutcomeBadge outcome={simulate.data.decision.outcome} /> via <Mono>{simulate.data.decision.deciding_rule}</Mono></div>
          <div className="text-slate-700">{simulate.data.decision.reason}</div>
          {!simulate.data.tool_registered && <Alert tone="warning">This tool is not in the registry, so it is denied before any rule runs.</Alert>}
          {simulate.data.argument_errors.length > 0 && <Alert tone="warning">Schema errors: {simulate.data.argument_errors.join("; ")}</Alert>}
          <ol className="list-decimal pl-5 text-xs text-slate-500">{simulate.data.decision.trace.map((t, i) => <li key={i}>{t}</li>)}</ol>
        </div>
      )}
    </Card>
  );
}
