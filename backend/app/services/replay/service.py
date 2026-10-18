"""Replay engine.

Modes
-----
``recorded``
    Reconstructs the run purely from stored events. Nothing executes. Every frame is labelled
    ``recorded``.
``simulate``
    Re-runs the same scenario spec, seed and recorded tool versions through the real runner -
    optionally under a different policy version - in memory, against a fresh copy of the mock
    sandbox. Nothing is persisted except the replay report, approval rows are never touched,
    and no tool ever reaches anything outside the per-replay sandbox.

    * Deterministic mock tools are re-executed in the isolated sandbox -> ``reconstructed``.
    * Non-deterministic tools reuse the recorded output for the identical action
      -> ``recorded``; without one the step is ``unavailable`` and the simulation stops.
    * Approvals reuse the recorded human decision for the identical action (``recorded``),
      or follow an explicit what-if strategy (``approve_all`` / ``reject_all``). A required
      decision that was never recorded makes the step ``unavailable``.
    * Agents that are not deterministic (the optional LLM adapter) are replayed from their
      recorded proposals instead of being called again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.utils import fingerprint, new_id
from app.models import Execution, Replay, ToolDefinition
from app.services.agent_runtime.agents import Action, Agent, AgentContext, FinishAction, ToolCallAction
from app.services.agent_runtime.engine import make_agent
from app.services.agent_runtime.runner import GateResult, Resolution, Runner, RunLimits, RunState
from app.services.agent_runtime.scenario import ScenarioSpec
from app.services.audit.events import EventRecord
from app.services.audit.log import list_events
from app.services.policy_engine.model import Decision
from app.services.policy_engine.store import get_version, load_document
from app.services.replay.divergence import first_divergence, tool_call_table
from app.services.tool_registry.executor import ToolRunResult, run_tool
from app.services.tool_registry.mock_data import initial_sandbox
from app.services.tool_registry.registry import ToolRegistry, ToolSpec, to_spec

ApprovalStrategy = Literal["recorded", "approve_all", "reject_all"]


class ReplayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(max_length=40)
    mode: Literal["recorded", "simulate"] = "recorded"
    policy_id: str | None = Field(default=None, max_length=64)
    policy_version: int | None = Field(default=None, ge=1)
    approval_strategy: ApprovalStrategy = "recorded"


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_execution_id: str = Field(max_length=40)
    right_execution_id: str = Field(max_length=40)


@dataclass
class SimEvent:
    sequence: int
    event_type: str
    tool_id: str | None
    outcome: str
    data: dict[str, Any]
    policy_version: str | None
    id: str


class MemorySink:
    def __init__(self) -> None:
        self.events: list[SimEvent] = []
        self.decisions: list[dict[str, Any]] = []

    def emit(self, record: EventRecord) -> str:
        event_id = f"sim-{len(self.events) + 1}"
        self.events.append(SimEvent(sequence=len(self.events) + 1, event_type=str(record.event_type),
                                    tool_id=record.tool_id, outcome=record.outcome, data=dict(record.data),
                                    policy_version=record.policy_version, id=event_id))
        return event_id

    def record_decision(self, *, decision_id: str, event_id: str, decision: Decision,
                        pending: dict[str, Any], latency_us: float) -> None:
        self.decisions.append({"event_id": event_id, "outcome": decision.outcome, "rule": decision.deciding_rule})

    def checkpoint(self, state: RunState) -> None:
        return None


class RecordedApprovalGate:
    def __init__(self, recorded: dict[str, Resolution], strategy: ApprovalStrategy) -> None:
        self.recorded = recorded
        self.strategy = strategy

    def request(self, pending: dict[str, Any], decision: Decision, state: RunState) -> GateResult:
        if self.strategy == "approve_all":
            res = Resolution(outcome="approved", decided_by="what-if:approve_all", source="simulated")
        elif self.strategy == "reject_all":
            res = Resolution(outcome="rejected", decided_by="what-if:reject_all", source="simulated")
        else:
            found = self.recorded.get(pending["fingerprint"])
            res = (Resolution(outcome=found.outcome, decided_by=found.decided_by, note=found.note, source="recorded")
                   if found else Resolution(outcome="unavailable", source="unavailable"))
        return GateResult(paused=False, data={"replay_source": res.source}, resolution=res)


class ReplayToolInvoker:
    def __init__(self, recorded_outputs: dict[str, dict[str, Any]]) -> None:
        self.recorded = recorded_outputs

    def invoke(self, tool: ToolSpec, pending: dict[str, Any], sandbox: dict[str, Any],
               seed: int) -> tuple[ToolRunResult | None, str]:
        if tool.deterministic:
            return run_tool(tool, pending["arguments"], sandbox, seed=seed, step=pending["step"]), "reconstructed"
        rec = self.recorded.get(pending["fingerprint"])
        if rec is None:
            return None, "unavailable"
        if rec["status"] == "succeeded":
            return ToolRunResult(status="succeeded", output=rec["output"], sandbox=sandbox), "recorded"
        return ToolRunResult(status=rec["status"], error=rec.get("error", ""), sandbox=sandbox), "recorded"


class RecordedAgent:
    """Replays a non-deterministic agent's recorded proposals verbatim."""

    deterministic = False
    agent_type = "recorded"

    def __init__(self, proposals: list[ToolCallAction], summary: str) -> None:
        self.proposals = proposals
        self.summary = summary

    def initial_state(self) -> dict[str, Any]:
        return {"cursor": 0, "observations": []}

    def decide(self, state: dict[str, Any], ctx: AgentContext) -> tuple[Action, dict[str, Any]]:
        cursor = state["cursor"]
        if cursor >= len(self.proposals):
            return FinishAction(self.summary or "Recorded run finished."), state
        return self.proposals[cursor], {**state, "cursor": cursor + 1}

    def observe(self, state: dict[str, Any], observation: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return {**state, "observations": [*state["observations"], observation]}, False


def recorded_frames(events: list[Any]) -> list[dict[str, Any]]:
    """Frames for step-through navigation with cumulative reconstructed state."""
    frames = []
    state: dict[str, Any] = {"status": "pending", "tool_calls": 0, "executed": [], "blocked": [],
                             "awaiting_approval": None}
    for index, e in enumerate(events):
        t, d = e.event_type, e.data
        if t == "execution.started":
            state["status"] = "running"
        elif t == "tool.requested":
            state["tool_calls"] += 1
        elif t == "approval.requested" and e.outcome == "pending":
            state["status"], state["awaiting_approval"] = "waiting_for_approval", d.get("label")
        elif t in {"approval.granted", "approval.rejected", "approval.expired", "execution.resumed"}:
            state["status"], state["awaiting_approval"] = "running", None
        elif t == "tool.result":
            state["executed"] = [*state["executed"], d.get("label")]
        elif t == "tool.blocked":
            state["blocked"] = [*state["blocked"], d.get("label")]
        elif t.startswith("execution.") and t not in {"execution.created", "execution.started", "execution.resumed"}:
            state["status"] = e.outcome
        frames.append({
            "index": index, "sequence": e.sequence, "event_id": getattr(e, "id", None), "event_type": t,
            "tool_id": e.tool_id, "outcome": e.outcome, "data": d, "policy_version": e.policy_version,
            "timestamp": e.timestamp.isoformat() if getattr(e, "timestamp", None) else None,
            "source": d.get("source", "recorded") if t in {"tool.executed", "tool.result", "tool.failed"} else "recorded",
            "state": {k: (list(v) if isinstance(v, list) else v) for k, v in state.items()},
        })
    return frames


def _recorded_inputs(events: list[Any]) -> tuple[dict[str, Resolution], dict[str, dict[str, Any]],
                                                 list[ToolCallAction], dict[str, str]]:
    fp_by_step: dict[int, str] = {}
    approvals: dict[str, Resolution] = {}
    outputs: dict[str, dict[str, Any]] = {}
    proposals: list[ToolCallAction] = []
    versions: dict[str, str] = {}
    for e in events:
        d, step = e.data, e.data.get("step")
        if e.event_type == "agent.action_proposed":
            proposals.append(ToolCallAction(label=d.get("label", ""), tool_id=d.get("tool_id", ""),
                                            arguments=d.get("arguments"), rationale=d.get("rationale", ""),
                                            claims=d.get("agent_claims", {})))
        elif e.event_type == "tool.requested" and isinstance(step, int):
            fp_by_step[step] = d["action_fingerprint"]
            if d.get("tool_version") and e.tool_id:
                versions[e.tool_id] = d["tool_version"]
        elif e.event_type in {"approval.granted", "approval.rejected", "approval.expired"} and step in fp_by_step:
            outcome = {"approval.granted": "approved", "approval.rejected": "rejected",
                       "approval.expired": "expired"}[e.event_type]
            approvals[fp_by_step[step]] = Resolution(outcome=outcome, decided_by=d.get("decided_by"),  # type: ignore[arg-type]
                                                     note=d.get("note", ""), source="recorded")
        elif e.event_type == "tool.result" and step in fp_by_step:
            outputs[fp_by_step[step]] = {"status": "succeeded", "output": d.get("output")}
        elif e.event_type == "tool.failed" and step in fp_by_step:
            outputs[fp_by_step[step]] = {"status": e.outcome, "error": d.get("error", "")}
    return approvals, outputs, proposals, versions


def _registry_for(session: Session, versions: dict[str, str]) -> ToolRegistry:
    """Current registry, but with the exact tool versions the recording used."""
    current = {t.tool_id: t for t in ToolRegistry.from_session(session).all()}
    for tool_id, version in versions.items():
        row = session.scalar(select(ToolDefinition).where(ToolDefinition.tool_id == tool_id,
                                                          ToolDefinition.version == version))
        if row is not None:
            current[tool_id] = to_spec(row)
    return ToolRegistry(current.values())


def simulate(session: Session, settings: Settings, execution: Execution, *, policy_id: str, policy_version: int | None,
             approval_strategy: ApprovalStrategy) -> dict[str, Any]:
    events = list_events(session, execution.id)
    if not events:
        raise ValidationFailedError("execution has no recorded events")
    created = events[0].data
    spec = ScenarioSpec.model_validate(execution.spec)
    approvals, outputs, proposals, versions = _recorded_inputs(events)
    warnings: list[str] = []
    agent: Agent = make_agent(spec, settings)
    if not agent.deterministic:
        agent = RecordedAgent(proposals, execution.final_output)
        warnings.append("Agent is non-deterministic: its recorded proposals are replayed instead of calling it again.")
        if any("[REDACTED]" in str(p.arguments) for p in proposals):
            warnings.append("Some recorded arguments were redacted; those steps cannot be reproduced exactly.")
    sandbox = initial_sandbox()
    if fingerprint(sandbox) != execution.initial_sandbox_hash:
        warnings.append("The mock sandbox fixture changed since this run was recorded; results may differ.")
    policy_row = get_version(session, policy_id, policy_version)
    limits = RunLimits(**created.get("limits", {})) if created.get("limits") else RunLimits(
        settings.max_steps, settings.max_tool_calls, settings.max_identical_calls, settings.execution_timeout_seconds)
    sink = MemorySink()
    runner = Runner(
        execution_id=execution.id, scenario_id=execution.scenario_id, spec=spec, agent=agent,
        registry=_registry_for(session, versions), policy=load_document(policy_row), policy_id=policy_row.policy_id,
        policy_version=policy_row.version, sink=sink, gate=RecordedApprovalGate(approvals, approval_strategy),
        limits=limits, seed=execution.seed, invoker=ReplayToolInvoker(outputs),
    )
    sink.emit(EventRecord(event_type="execution.created", outcome="simulated",  # type: ignore[arg-type]
                          data={"replay_of": execution.id}, policy_version=runner.policy_label))
    state = runner.run(RunState(status="pending", agent_state=agent.initial_state(), sandbox=sandbox))
    frames = []
    for index, e in enumerate(sink.events):
        source = e.data.get("source") or ("re-evaluated" if e.event_type == "policy.evaluated" else "simulated")
        frames.append({"index": index, "sequence": e.sequence, "event_id": e.id, "event_type": e.event_type,
                       "tool_id": e.tool_id, "outcome": e.outcome, "data": e.data,
                       "policy_version": e.policy_version, "timestamp": None, "source": source})
    unavailable = [f["index"] for f in frames if f["source"] == "unavailable" or f["outcome"] == "unavailable"]
    return {
        "frames": frames, "final_status": state.status, "status_reason": state.status_reason,
        "warnings": warnings, "unavailable_frames": unavailable,
        "divergence": first_divergence(events, sink.events),
        "tool_calls": {"original": tool_call_table(events), "replay": tool_call_table(sink.events)},
        "sandbox_effects": {k: len(state.sandbox.get(k, [])) for k in ("outbox", "drafts", "tickets",
                                                                       "record_changes", "export_attempts")},
    }


def create_replay(session: Session, settings: Settings, request: ReplayCreate) -> Replay:
    execution = session.get(Execution, request.execution_id)
    if execution is None:
        raise NotFoundError(f"execution '{request.execution_id}' not found")
    if execution.status in {"pending", "running"}:
        raise ValidationFailedError("execution is still running")
    events = list_events(session, execution.id)
    policy_id = request.policy_id or execution.policy_id
    policy_version = request.policy_version or (execution.policy_version if policy_id == execution.policy_id else None)
    if request.mode == "recorded":
        result: dict[str, Any] = {
            "frames": recorded_frames(events), "final_status": execution.status,
            "status_reason": execution.status_reason, "warnings": [], "unavailable_frames": [],
            "divergence": None, "tool_calls": {"original": tool_call_table(events), "replay": None},
        }
        pv = execution.policy_version
    else:
        result = simulate(session, settings, execution, policy_id=policy_id, policy_version=policy_version,
                          approval_strategy=request.approval_strategy)
        pv = get_version(session, policy_id, policy_version).version
    result["original"] = {"execution_id": execution.id, "status": execution.status,
                          "policy": f"{execution.policy_id}@v{execution.policy_version}",
                          "scenario": f"{execution.scenario_id}@v{execution.scenario_version}",
                          "event_count": len(events), "seed": execution.seed}
    result["approval_strategy"] = request.approval_strategy
    replay = Replay(id=new_id("rpl"), execution_id=execution.id, mode=request.mode, policy_id=policy_id,
                    policy_version=pv, result=result)
    session.add(replay)
    session.commit()
    return replay


def compare_executions(session: Session, request: CompareRequest) -> dict[str, Any]:
    left = session.get(Execution, request.left_execution_id)
    right = session.get(Execution, request.right_execution_id)
    if left is None or right is None:
        raise NotFoundError("both executions must exist")
    le, re_ = list_events(session, left.id), list_events(session, right.id)
    return {
        "left": {"execution_id": left.id, "policy": f"{left.policy_id}@v{left.policy_version}",
                 "scenario": f"{left.scenario_id}@v{left.scenario_version}", "status": left.status, "seed": left.seed},
        "right": {"execution_id": right.id, "policy": f"{right.policy_id}@v{right.policy_version}",
                  "scenario": f"{right.scenario_id}@v{right.scenario_version}", "status": right.status,
                  "seed": right.seed},
        "same_scenario": (left.scenario_id, left.scenario_version) == (right.scenario_id, right.scenario_version),
        "divergence": first_divergence(le, re_),
        "tool_calls": {"left": tool_call_table(le), "right": tool_call_table(re_)},
    }
