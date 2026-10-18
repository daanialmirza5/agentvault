import clsx from "clsx";

const base = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap";

const statusStyles: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  running: "bg-sky-50 text-sky-700 ring-sky-200",
  pending: "bg-slate-50 text-slate-600 ring-slate-200",
  waiting_for_approval: "bg-amber-50 text-amber-800 ring-amber-200",
  failed: "bg-rose-50 text-rose-700 ring-rose-200",
  blocked: "bg-orange-50 text-orange-800 ring-orange-200",
  cancelled: "bg-slate-100 text-slate-600 ring-slate-300",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={clsx(base, statusStyles[status] ?? statusStyles.pending)}>{status.replaceAll("_", " ")}</span>;
}

const outcomeStyles: Record<string, string> = {
  allow: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  deny: "bg-rose-50 text-rose-700 ring-rose-200",
  require_approval: "bg-amber-50 text-amber-800 ring-amber-200",
  approved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  rejected: "bg-rose-50 text-rose-700 ring-rose-200",
  expired: "bg-slate-100 text-slate-600 ring-slate-300",
  cancelled: "bg-slate-100 text-slate-600 ring-slate-300",
  pending: "bg-amber-50 text-amber-800 ring-amber-200",
};

export function OutcomeBadge({ outcome }: { outcome: string | null | undefined }) {
  if (!outcome) return <span className="text-xs text-slate-400">—</span>;
  const label = outcome === "require_approval" ? "approval required" : outcome.replaceAll("_", " ");
  return <span className={clsx(base, outcomeStyles[outcome] ?? "bg-slate-50 text-slate-600 ring-slate-200")}>{label}</span>;
}

const riskStyles: Record<string, string> = {
  low: "bg-slate-50 text-slate-600 ring-slate-200",
  medium: "bg-sky-50 text-sky-700 ring-sky-200",
  high: "bg-amber-50 text-amber-800 ring-amber-200",
  critical: "bg-rose-50 text-rose-700 ring-rose-200",
};

export function RiskBadge({ risk }: { risk: string }) {
  return <span className={clsx(base, riskStyles[risk] ?? riskStyles.low)}>{risk} risk</span>;
}

const sourceStyles: Record<string, string> = {
  recorded: "bg-slate-100 text-slate-700 ring-slate-300",
  live: "bg-slate-100 text-slate-700 ring-slate-300",
  reconstructed: "bg-violet-50 text-violet-700 ring-violet-200",
  "re-evaluated": "bg-sky-50 text-sky-700 ring-sky-200",
  simulated: "bg-sky-50 text-sky-700 ring-sky-200",
  unavailable: "bg-rose-50 text-rose-700 ring-rose-200",
};

export function SourceBadge({ source }: { source: string }) {
  return <span className={clsx(base, sourceStyles[source] ?? sourceStyles.simulated)}>{source}</span>;
}

export function Pill({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "indigo" | "rose" | "emerald" | "amber" }) {
  const tones = {
    slate: "bg-slate-50 text-slate-600 ring-slate-200",
    indigo: "bg-accent-50 text-accent-700 ring-accent-100",
    rose: "bg-rose-50 text-rose-700 ring-rose-200",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
  };
  return <span className={clsx(base, tones[tone])}>{children}</span>;
}
