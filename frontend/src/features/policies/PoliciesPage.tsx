import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Plus } from "lucide-react";
import { useState } from "react";

import { JsonView } from "../../components/JsonView";
import { Modal } from "../../components/Modal";
import { OutcomeBadge, Pill } from "../../components/badges";
import { Alert, Button, Card, EmptyState, ErrorState, LoadingState, Mono, PageHeader, SelectInput, Tabs, TextInput } from "../../components/ui";
import { usePolicies, usePolicy } from "../../hooks/queries";
import { api, describeError } from "../../services/api";
import { formatTime } from "../../services/format";
import type { PolicyDetail, PolicyDocument, PolicySummary } from "../../types/api";
import { PolicyCompare } from "./PolicyCompare";
import { PolicyEditor } from "./PolicyEditor";
import { PolicyPlayground } from "./PolicyPlayground";

type Tab = "editor" | "versions" | "compare" | "playground";

function NewPolicyDialog({ open, onClose, policies, onCreated }: {
  open: boolean;
  onClose: () => void;
  policies: PolicySummary[];
  onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [id, setId] = useState("my-policy");
  const [name, setName] = useState("My policy");
  const [description, setDescription] = useState("");
  const [base, setBase] = useState(policies[0]?.id ?? "");
  const create = useMutation({
    mutationFn: async () => {
      const source: PolicyDocument = base
        ? (await api.policy(base)).versions.sort((a, b) => b.version - a.version)[0]!.document
        : { default_effect: "deny", rules: [] };
      return api.createPolicy({ id, name, description, document: source, change_note: base ? `Copied from ${base}` : "Empty policy" });
    },
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["policies"] });
      onCreated(p.id);
      onClose();
    },
  });
  return (
    <Modal open={open} title="Create a policy" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}>Create</Button></>}>
      <TextInput label="Policy ID" value={id} onChange={(e) => setId(e.target.value)} hint="lowercase letters, digits and dashes" />
      <TextInput label="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <TextInput label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
      <SelectInput label="Start from" value={base} onChange={(e) => setBase(e.target.value)}>
        <option value="">Empty policy (default deny)</option>
        {policies.map((p) => <option key={p.id} value={p.id}>Copy of {p.name} (v{p.latest_version})</option>)}
      </SelectInput>
      {create.isError && <Alert tone="error">{describeError(create.error)}</Alert>}
    </Modal>
  );
}

function Versions({ policy, onLoad }: { policy: PolicyDetail; onLoad: (doc: PolicyDocument) => void }) {
  const [selected, setSelected] = useState(policy.latest_version);
  const version = policy.versions.find((v) => v.version === selected) ?? policy.versions[0];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Version history" padded={false}>
        <ul className="divide-y divide-slate-100">
          {policy.versions.map((v) => (
            <li key={v.version}>
              <button type="button" onClick={() => setSelected(v.version)} aria-current={v.version === selected || undefined}
                className={clsx("w-full px-4 py-2 text-left text-sm", v.version === selected ? "bg-accent-50" : "hover:bg-slate-50")}>
                <div className="flex items-center justify-between"><span className="font-medium">v{v.version}</span>
                  {v.version === policy.latest_version && <Pill tone="indigo">latest</Pill>}</div>
                <div className="text-xs text-slate-500">{v.change_note || "no note"} · {formatTime(v.created_at)}</div>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {version && (
        <Card className="lg:col-span-2" title={`v${version.version} document`}
          actions={<Button size="sm" onClick={() => onLoad(version.document)}>Load into editor</Button>}>
          <div className="mb-2 text-xs text-slate-500">Content hash <Mono>{version.content_hash.slice(0, 20)}…</Mono> · {version.document.rules.length} rules · default <OutcomeBadge outcome={version.document.default_effect} /></div>
          <JsonView value={version.document} label="Policy version document" maxHeight="32rem" />
        </Card>
      )}
    </div>
  );
}

export function PoliciesPage() {
  const policies = usePolicies();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("editor");
  const [newOpen, setNewOpen] = useState(false);
  const [draft, setDraft] = useState<{ key: string; doc: PolicyDocument } | null>(null);
  const items = policies.data?.items ?? [];
  const activeId = selectedId ?? items[0]?.id;
  const policy = usePolicy(activeId);
  const latest = policy.data?.versions.find((v) => v.version === policy.data?.latest_version);
  const editorKey = `${activeId}-${policy.data?.latest_version}-${draft?.key ?? "latest"}`;

  return (
    <div>
      <PageHeader
        title="Policies"
        description="Deterministic, versioned authorisation rules. The policy engine is independent of any model: an agent's claim that an action is safe never overrides a decision."
        actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New policy</Button>}
      />
      {policies.isLoading && <LoadingState />}
      {policies.error && <ErrorState error={policies.error} onRetry={() => void policies.refetch()} />}
      {policies.data && (
        <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
          <nav aria-label="Policies" className="space-y-2">
            {items.map((p) => (
              <button key={p.id} type="button" onClick={() => { setSelectedId(p.id); setDraft(null); }} aria-current={p.id === activeId || undefined}
                className={clsx("w-full rounded-lg border p-3 text-left", p.id === activeId ? "border-accent-500 bg-white shadow-sm" : "border-slate-200 bg-white hover:border-slate-300")}>
                <div className="flex items-center justify-between"><span className="text-sm font-medium text-slate-900">{p.name}</span><Mono>v{p.latest_version}</Mono></div>
                <div className="mt-1 line-clamp-2 text-xs text-slate-500">{p.description}</div>
                {p.builtin && <div className="mt-1"><Pill>built-in example</Pill></div>}
              </button>
            ))}
          </nav>
          <div className="min-w-0 space-y-4">
            <Tabs<Tab> label="Policy views" value={tab} onChange={setTab} tabs={[
              { id: "editor", label: "Editor" }, { id: "versions", label: "Versions" },
              { id: "compare", label: "Compare" }, { id: "playground", label: "Playground" },
            ]} />
            {policy.isLoading && <LoadingState />}
            {policy.error && <ErrorState error={policy.error} />}
            {policy.data && latest && tab === "editor" && (
              <>
                {draft && <Alert tone="warning">Editor loaded from an earlier version. Saving creates v{policy.data.latest_version + 1}.</Alert>}
                <PolicyEditor key={editorKey} policy={policy.data} initial={draft?.doc ?? latest.document} onSaved={() => setDraft(null)} />
              </>
            )}
            {policy.data && tab === "versions" && (
              <Versions policy={policy.data} onLoad={(doc) => { setDraft({ key: String(Date.now()), doc }); setTab("editor"); }} />
            )}
            {tab === "compare" && (items.length ? <PolicyCompare policies={items} /> : <EmptyState title="No policies" />)}
            {policy.data && tab === "playground" && <PolicyPlayground policy={policy.data} />}
          </div>
        </div>
      )}
      <NewPolicyDialog open={newOpen} onClose={() => setNewOpen(false)} policies={items} onCreated={(id) => { setSelectedId(id); setTab("editor"); }} />
    </div>
  );
}
