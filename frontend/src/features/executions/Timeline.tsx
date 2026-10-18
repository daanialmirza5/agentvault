import clsx from "clsx";
import type { KeyboardEvent } from "react";

import { JsonView } from "../../components/JsonView";
import { OutcomeBadge } from "../../components/badges";
import { Mono } from "../../components/ui";
import { formatTime } from "../../services/format";
import type { AuditEvent, DecisionRecord } from "../../types/api";
import { describeEvent, eventTone, toneDot } from "./eventStyle";

export function Timeline({ events, selectedId, onSelect }: {
  events: AuditEvent[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const onKey = (e: KeyboardEvent<HTMLOListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const index = events.findIndex((ev) => ev.id === selectedId);
    const next = events[Math.min(events.length - 1, Math.max(0, index + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) onSelect(next.id);
  };
  const stepOf = (e: AuditEvent | undefined) => (e && typeof e.data.step === "number" ? e.data.step : null);
  return (
    <ol aria-label="Execution timeline" tabIndex={0} onKeyDown={onKey} className="relative space-y-0.5 focus:outline-none">
      {events.map((e, i) => {
        const step = stepOf(e);
        const previousStep = events.slice(0, i).reverse().map(stepOf).find((s) => s !== null) ?? null;
        const header = step !== null && step !== previousStep ? step : null;
        const tone = eventTone(e);
        return (
          <li key={e.id}>
            {header !== null && (
              <div className="mt-2 px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Step {header}{typeof e.data.label === "string" ? ` · ${e.data.label}` : ""}
              </div>
            )}
            <button
              type="button"
              aria-current={selectedId === e.id || undefined}
              onClick={() => onSelect(e.id)}
              className={clsx(
                "flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm",
                selectedId === e.id ? "bg-accent-50 ring-1 ring-accent-100" : "hover:bg-slate-50",
              )}
            >
              <span className="w-6 shrink-0 text-right font-mono text-[11px] text-slate-400">{e.sequence}</span>
              <span className={clsx("h-2.5 w-2.5 shrink-0 rounded-full", toneDot[tone])} aria-hidden />
              <span className="flex-1 truncate text-slate-700">{describeEvent(e)}</span>
              <span className="hidden font-mono text-[11px] text-slate-400 md:inline">{e.event_type}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function EventDetail({ event, decision }: { event: AuditEvent; decision?: DecisionRecord }) {
  return (
    <div className="space-y-3">
      <div>
        <div className="text-xs text-slate-500">Event #{event.sequence}</div>
        <h3 className="text-sm font-semibold text-slate-900">{describeEvent(event)}</h3>
      </div>
      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-slate-500">Event ID</dt><dd><Mono>{event.id}</Mono></dd>
        <dt className="text-slate-500">Type</dt><dd><Mono>{event.event_type}</Mono></dd>
        <dt className="text-slate-500">Outcome</dt><dd><OutcomeBadge outcome={event.outcome} /></dd>
        <dt className="text-slate-500">Tool</dt><dd>{event.tool_id ? <Mono>{event.tool_id}</Mono> : "—"}</dd>
        <dt className="text-slate-500">Policy version</dt><dd>{event.policy_version ? <Mono>{event.policy_version}</Mono> : "—"}</dd>
        <dt className="text-slate-500">Timestamp</dt><dd>{formatTime(event.timestamp)}</dd>
        <dt className="text-slate-500">Hash</dt><dd><Mono>{event.hash.slice(0, 24)}…</Mono></dd>
        <dt className="text-slate-500">Previous hash</dt><dd><Mono>{event.prev_hash.slice(0, 24)}…</Mono></dd>
      </dl>
      <div>
        <div className="mb-1 text-xs font-medium uppercase text-slate-500">Recorded data</div>
        <JsonView value={event.data} label="Event data" />
      </div>
      {decision && (
        <section aria-label="Associated policy decision" className="rounded-md border border-slate-200 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-xs font-semibold uppercase text-slate-500">Associated policy decision</div>
            <OutcomeBadge outcome={decision.outcome} />
          </div>
          <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-slate-500">Decision ID</dt><dd><Mono>{decision.id}</Mono></dd>
            <dt className="text-slate-500">Policy</dt><dd><Mono>{decision.policy_id}@v{decision.policy_version}</Mono></dd>
            <dt className="text-slate-500">Deciding rule</dt><dd><Mono>{decision.deciding_rule}</Mono></dd>
            <dt className="text-slate-500">Reason</dt><dd className="text-slate-700">{decision.reason}</dd>
            <dt className="text-slate-500">Matched rules</dt>
            <dd className="flex flex-wrap gap-1">
              {decision.matched_rules.length === 0 ? "none" : decision.matched_rules.map((r) => (
                <span key={r.rule_id} className="inline-flex items-center gap-1"><Mono>{r.rule_id}</Mono><OutcomeBadge outcome={r.effect} /></span>
              ))}
            </dd>
            <dt className="text-slate-500">Latency</dt><dd>{decision.latency_us.toFixed(1)} µs</dd>
          </dl>
          <div className="mt-2">
            <div className="mb-1 text-[11px] font-medium uppercase text-slate-500">Validated arguments (redacted)</div>
            <JsonView value={decision.arguments_redacted} label="Decision arguments" maxHeight="10rem" />
          </div>
        </section>
      )}
    </div>
  );
}
