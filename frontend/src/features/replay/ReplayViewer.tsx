import clsx from "clsx";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, Crosshair } from "lucide-react";
import { useEffect, useState } from "react";

import { JsonView } from "../../components/JsonView";
import { ReportExport } from "../../components/ReportExport";
import { OutcomeBadge, SourceBadge, StatusBadge } from "../../components/badges";
import { Alert, Button, Card, Mono } from "../../components/ui";
import type { Replay, ToolCallRow } from "../../types/api";
import { describeEvent, eventTone, toneDot } from "../executions/eventStyle";

export function ToolCallTable({ left, right, leftLabel, rightLabel }: {
  left: ToolCallRow[];
  right: ToolCallRow[] | null;
  leftLabel: string;
  rightLabel: string;
}) {
  const steps = [...new Set([...left.map((r) => r.step), ...(right ?? []).map((r) => r.step)])].sort((a, b) => a - b);
  const cell = (r: ToolCallRow | undefined) =>
    r ? (
      <div className="space-y-0.5">
        <div><Mono>{r.tool_id}</Mono> <span className="text-xs text-slate-400">{r.label}</span></div>
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <OutcomeBadge outcome={r.decision} />
          {r.approval && <OutcomeBadge outcome={r.approval} />}
          <span className="text-slate-500">{r.status.replaceAll("_", " ")}</span>
          {r.source && <SourceBadge source={r.source} />}
          {r.output_hash && <span className="font-mono text-[10px] text-slate-400">out {r.output_hash.slice(0, 8)}</span>}
        </div>
      </div>
    ) : <span className="text-xs text-slate-400">—</span>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs uppercase text-slate-500">
        <tr><th className="px-4 py-2">Step</th><th className="px-2 py-2">{leftLabel}</th>{right && <th className="px-2 py-2">{rightLabel}</th>}</tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {steps.map((s) => {
          const a = left.find((r) => r.step === s);
          const b = right?.find((r) => r.step === s);
          const differs = right !== null && (a?.decision !== b?.decision || a?.status !== b?.status || a?.output_hash !== b?.output_hash || a?.tool_id !== b?.tool_id);
          return (
            <tr key={s} className={clsx("align-top", differs && "bg-amber-50/60")}>
              <td className="px-4 py-2 font-mono text-xs text-slate-500">{s}</td>
              <td className="px-2 py-2">{cell(a)}</td>
              {right && <td className="px-2 py-2">{cell(b)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ReplayViewer({ replay }: { replay: Replay }) {
  const frames = replay.result.frames;
  const [index, setIndex] = useState(0);
  const frame = frames[Math.min(index, frames.length - 1)];
  const div = replay.result.divergence;
  // For simulations the divergence's "right" side is the replay stream; find its frame.
  const divergenceFrame = div?.diverged
    ? frames.findIndex((f) => f.event_id === (replay.mode === "simulate" ? div.right?.event_id : div.left?.event_id))
    : -1;
  const atEnd = divergenceFrame === -1 && div?.diverged ? frames.length - 1 : divergenceFrame;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement | null)?.closest("input, textarea, select")) return;
      if (e.key === "ArrowRight") setIndex((i) => Math.min(frames.length - 1, i + 1));
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [frames.length]);

  return (
    <div className="space-y-4">
      <Card
        title={`Replay ${replay.id}`}
        actions={<ReportExport kind="replay" subjectId={replay.id} label="Report" />}
      >
        <div className="grid gap-3 text-sm sm:grid-cols-4">
          <div><div className="text-xs text-slate-500">Mode</div>{replay.mode === "recorded" ? "Recorded timeline (nothing re-executed)" : "Isolated simulation"}</div>
          <div><div className="text-xs text-slate-500">Original</div><Mono>{replay.result.original.policy}</Mono> <StatusBadge status={replay.result.original.status} /></div>
          <div><div className="text-xs text-slate-500">Replay policy</div><Mono>{replay.policy_id}@v{replay.policy_version}</Mono> · approvals: {replay.result.approval_strategy}</div>
          <div><div className="text-xs text-slate-500">Replay result</div><StatusBadge status={replay.result.final_status} /></div>
        </div>
        {replay.result.warnings.map((w) => <div key={w} className="mt-3"><Alert tone="warning">{w}</Alert></div>)}
        {div && (
          <div className="mt-3">
            <Alert tone={div.diverged ? "warning" : "success"}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {div.diverged ? <>First divergence at comparable position {div.index}: {div.explanation}</> : div.explanation}
                </span>
                {div.diverged && atEnd >= 0 && (
                  <Button size="sm" icon={<Crosshair className="h-3.5 w-3.5" />} onClick={() => setIndex(atEnd)}>Jump to divergence</Button>
                )}
              </div>
              {div.diverged && (
                <div className="mt-1 text-xs">
                  original: <Mono>{div.left ? `#${div.left.sequence} ${div.left.event_type} ${div.left.outcome}` : "no further events"}</Mono>{" · "}
                  replay: <Mono>{div.right ? `#${div.right.sequence} ${div.right.event_type} ${div.right.outcome}` : "no further events"}</Mono>
                </div>
              )}
            </Alert>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2" title={`Frames (${frames.length})`} padded={false}>
          <ol aria-label="Replay frames" className="max-h-[32rem] overflow-y-auto py-1">
            {frames.map((f, i) => (
              <li key={`${f.event_id}-${i}`}>
                <button type="button" onClick={() => setIndex(i)} aria-current={i === index || undefined}
                  className={clsx("flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs",
                    i === index ? "bg-accent-50" : "hover:bg-slate-50", i === divergenceFrame && "ring-1 ring-inset ring-amber-400")}>
                  <span className="w-6 text-right font-mono text-slate-400">{i}</span>
                  <span className={clsx("h-2 w-2 rounded-full", toneDot[eventTone(f)])} aria-hidden />
                  <span className="flex-1 truncate text-slate-700">{describeEvent(f)}</span>
                  <SourceBadge source={f.source} />
                </button>
              </li>
            ))}
          </ol>
        </Card>
        <Card className="lg:col-span-3" title="Frame inspector">
          <div className="mb-4 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Replay step controls">
            <Button size="sm" aria-label="First frame" onClick={() => setIndex(0)} disabled={index === 0}><ChevronFirst className="h-4 w-4" /></Button>
            <Button size="sm" aria-label="Previous frame" onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0}><ChevronLeft className="h-4 w-4" /></Button>
            <Button size="sm" aria-label="Next frame" onClick={() => setIndex((i) => Math.min(frames.length - 1, i + 1))} disabled={index >= frames.length - 1}><ChevronRight className="h-4 w-4" /></Button>
            <Button size="sm" aria-label="Last frame" onClick={() => setIndex(frames.length - 1)} disabled={index >= frames.length - 1}><ChevronLast className="h-4 w-4" /></Button>
            <input type="range" min={0} max={Math.max(0, frames.length - 1)} value={index} aria-label="Jump to event"
              onChange={(e) => setIndex(Number(e.target.value))} className="mx-2 flex-1" />
            <span className="text-xs tabular-nums text-slate-500" aria-live="polite">Frame {index + 1} / {frames.length}</span>
          </div>
          {frame && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-slate-900">{describeEvent(frame)}</h3>
                <SourceBadge source={frame.source} />
                <OutcomeBadge outcome={frame.outcome} />
              </div>
              <div className="text-xs text-slate-500">
                <Mono>{frame.event_type}</Mono> · event <Mono>{frame.event_id}</Mono>{frame.tool_id && <> · tool <Mono>{frame.tool_id}</Mono></>}
                {frame.policy_version && <> · policy <Mono>{frame.policy_version}</Mono></>}
              </div>
              {frame.state && (
                <div className="rounded-md bg-slate-50 p-2 text-xs text-slate-600">
                  Reconstructed state after this event: <StatusBadge status={frame.state.status} /> · {frame.state.tool_calls} tool calls ·
                  executed [{frame.state.executed.join(", ")}] · blocked [{frame.state.blocked.join(", ")}]
                  {frame.state.awaiting_approval && <> · awaiting approval for “{frame.state.awaiting_approval}”</>}
                </div>
              )}
              <JsonView value={frame.data} label="Frame data" maxHeight="22rem" />
            </div>
          )}
        </Card>
      </div>

      <Card title="Tool calls: original vs replay" padded={false}>
        <ToolCallTable left={replay.result.tool_calls.original} right={replay.result.tool_calls.replay} leftLabel="Original (recorded)" rightLabel="Replay" />
      </Card>
    </div>
  );
}
