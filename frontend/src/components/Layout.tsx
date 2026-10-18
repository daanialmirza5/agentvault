import clsx from "clsx";
import {
  Activity,
  ClipboardCheck,
  FileSearch,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  PlayCircle,
  Rewind,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useApprovals, useReady } from "../hooks/queries";
import { getApiToken, setApiToken } from "../services/api";
import { Modal } from "./Modal";
import { Button, TextInput } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/executions", label: "Executions", icon: PlayCircle },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
  { to: "/replay", label: "Replay", icon: Rewind },
  { to: "/policies", label: "Policies", icon: ShieldCheck },
  { to: "/tools", label: "Tool registry", icon: Wrench },
  { to: "/evaluations", label: "Evaluation lab", icon: FlaskConical },
  { to: "/audit", label: "Audit & reports", icon: FileSearch },
];

function ApiStatus() {
  const ready = useReady();
  const ok = ready.data?.status === "ready";
  const label = ready.isLoading ? "Checking API…" : ok ? "API ready" : "API unavailable";
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400" role="status" aria-live="polite">
      <span className={clsx("h-2 w-2 rounded-full", ready.isLoading ? "bg-slate-500" : ok ? "bg-emerald-400" : "bg-rose-400")} />
      {label}
      {ready.data && <span className="text-slate-500">· {ready.data.auth_mode === "bearer_token" ? "token auth" : "single-user"}</span>}
    </div>
  );
}

function TokenDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [value, setValue] = useState(getApiToken());
  return (
    <Modal
      open={open}
      title="API access token"
      onClose={onClose}
      footer={
        <>
          <Button onClick={() => { setApiToken(""); setValue(""); onClose(); }}>Clear</Button>
          <Button variant="primary" onClick={() => { setApiToken(value.trim()); onClose(); }}>Save</Button>
        </>
      }
    >
      <p className="text-sm text-slate-600">
        Only needed when the backend sets <code>AGENTVAULT_API_TOKEN</code>. The token is kept in this tab's session
        storage and sent as a bearer token on mutating requests.
      </p>
      <TextInput label="Token" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
    </Modal>
  );
}

export function Layout() {
  const pending = useApprovals({ status: "pending", limit: 1 });
  const [tokenOpen, setTokenOpen] = useState(false);
  const pendingCount = pending.data?.total ?? 0;
  return (
    <div className="flex min-h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-1">
        Skip to content
      </a>
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col bg-slate-900 text-slate-200">
        <div className="flex items-center gap-2 px-5 py-5">
          <ShieldCheck className="h-6 w-6 text-accent-500" aria-hidden />
          <div>
            <div className="text-sm font-semibold text-white">AgentVault</div>
            <div className="text-[11px] text-slate-400">Agent reliability & security</div>
          </div>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800/60 hover:text-white",
                )
              }
            >
              <Icon className="h-4 w-4" aria-hidden />
              <span className="flex-1">{label}</span>
              {to === "/approvals" && pendingCount > 0 && (
                <span className="rounded-full bg-amber-400 px-1.5 text-[10px] font-semibold text-slate-900" aria-label={`${pendingCount} pending`}>
                  {pendingCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-3 border-t border-slate-800 px-5 py-4">
          <ApiStatus />
          <button type="button" onClick={() => setTokenOpen(true)} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white">
            <KeyRound className="h-3.5 w-3.5" aria-hidden /> API token
          </button>
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <Activity className="h-3 w-3" aria-hidden /> Mock tools only · local sandbox
          </div>
        </div>
      </aside>
      <main id="main" className="min-w-0 flex-1 px-8 py-7">
        <Outlet />
      </main>
      <TokenDialog open={tokenOpen} onClose={() => setTokenOpen(false)} />
    </div>
  );
}
