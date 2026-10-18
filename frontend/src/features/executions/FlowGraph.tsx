import { Background, Controls, type Edge, MarkerType, type Node, ReactFlow } from "@xyflow/react";
import { useMemo } from "react";

import type { AuditEvent } from "../../types/api";
import { eventTone, toneBorder } from "./eventStyle";

const STAGES: { key: string; label: string; types: string[] }[] = [
  { key: "proposed", label: "Proposed", types: ["agent.action_proposed"] },
  { key: "validated", label: "Validated", types: ["tool.arguments_validated", "tool.arguments_rejected"] },
  { key: "policy", label: "Policy", types: ["policy.evaluated"] },
  { key: "approval", label: "Approval", types: ["approval.granted", "approval.rejected", "approval.expired", "approval.requested"] },
  { key: "outcome", label: "Outcome", types: ["tool.result", "tool.failed", "tool.blocked", "guard.triggered"] },
];

/** One row per agent step, one column per authorisation stage. Clicking a node selects its event. */
export function FlowGraph({ events, onSelect }: { events: AuditEvent[]; onSelect: (eventId: string) => void }) {
  const { nodes, edges } = useMemo(() => {
    const steps = new Map<number, AuditEvent[]>();
    for (const e of events) {
      if (typeof e.data.step === "number") steps.set(e.data.step, [...(steps.get(e.data.step) ?? []), e]);
    }
    const ns: Node[] = [];
    const es: Edge[] = [];
    let previousTail: string | null = null;
    const rows = [...steps.keys()].sort((a, b) => a - b);
    rows.forEach((step, row) => {
      const stepEvents = steps.get(step) ?? [];
      let prev: string | null = null;
      STAGES.forEach((stage, col) => {
        const matches = stepEvents.filter((e) => stage.types.includes(e.event_type));
        // Prefer the resolving event (granted/rejected) over the request for the approval column.
        const e = matches.find((m) => m.event_type !== "approval.requested") ?? matches[0];
        if (!e) return;
        const id = `n-${e.id}`;
        const tone = eventTone(e);
        const label = stage.key === "proposed" ? `${e.tool_id ?? "?"}` : stage.key === "policy" ? e.outcome.replaceAll("_", " ") : e.outcome;
        ns.push({
          id, position: { x: col * 170, y: row * 86 },
          data: { label: <div className="text-[11px] leading-tight"><div className="text-slate-400">{stage.label} · step {step}</div><div className="font-medium text-slate-800">{label}</div></div>, eventId: e.id },
          style: { border: `1.5px solid ${toneBorder[tone]}`, borderRadius: 8, width: 150, padding: 6, background: "#fff" },
          draggable: false,
        });
        if (prev) es.push({ id: `${prev}-${id}`, source: prev, target: id, markerEnd: { type: MarkerType.ArrowClosed } });
        if (!prev && previousTail) es.push({ id: `${previousTail}-${id}`, source: previousTail, target: id, style: { strokeDasharray: "4 4" } });
        prev = id;
      });
      if (prev) previousTail = prev;
    });
    return { nodes: ns, edges: es };
  }, [events]);

  if (nodes.length === 0) return <p className="p-4 text-sm text-slate-500">No tool calls in this execution.</p>;
  return (
    <div className="h-[28rem] rounded-md border border-slate-200" aria-label="Execution flow graph">
      <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false} elementsSelectable
        onNodeClick={(_, node) => onSelect(String(node.data.eventId))} proOptions={{ hideAttribution: true }}>
        <Background gap={16} color="#e2e8f0" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
