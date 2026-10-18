"""Live execution engine: wires the runner to the database."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import write_transaction
from app.core.errors import ConflictError, ValidationFailedError
from app.core.utils import fingerprint, new_id, utcnow
from app.models import Approval, Execution, PolicyDecisionRecord
from app.models.execution import TERMINAL_STATUSES
from app.services.agent_runtime.agents import Agent, build_agent
from app.services.agent_runtime.runner import GateResult, Resolution, Runner, RunLimits, RunState
from app.services.agent_runtime.scenario import ScenarioSpec, get_scenario
from app.services.audit.events import EventRecord, EventType
from app.services.audit.log import append_event
from app.services.policy_engine.model import Decision
from app.services.policy_engine.store import get_version, load_document
from app.services.tool_registry.mock_data import initial_sandbox
from app.services.tool_registry.registry import ToolRegistry


class ExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(max_length=80)
    scenario_version: int | None = Field(default=None, ge=1)
    policy_id: str = Field(default="baseline", max_length=64)
    policy_version: int | None = Field(default=None, ge=1)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    environment: Literal["sandbox", "staging", "production"] | None = None


class DbSink:
    def __init__(self, session: Session, execution: Execution) -> None:
        self.session = session
        self.execution = execution

    def emit(self, record: EventRecord) -> str:
        return append_event(self.session, self.execution, record).id

    def record_decision(self, *, decision_id: str, event_id: str, decision: Decision,
                        pending: dict[str, Any], latency_us: float) -> None:
        self.session.add(PolicyDecisionRecord(
            id=decision_id, execution_id=self.execution.id, event_id=event_id, policy_id=decision.policy_id,
            policy_version=decision.policy_version, tool_id=pending["tool_id"], tool_version=pending["tool_version"],
            arguments_redacted=pending["arguments_redacted"], action_hash=pending["action_hash"],
            outcome=decision.outcome, reason=decision.reason,
            matched_rules=[m.model_dump() for m in decision.matched_rules], deciding_rule=decision.deciding_rule,
            latency_us=latency_us, created_at=utcnow(),
        ))

    def checkpoint(self, state: RunState) -> None:
        write_state(self.execution, state)
        self.session.commit()


class LiveApprovalGate:
    """Creates a pending approval bound to the exact action, then pauses the execution."""

    def __init__(self, session: Session, execution: Execution, ttl_seconds: int, task: str) -> None:
        self.session = session
        self.execution = execution
        self.ttl = ttl_seconds
        self.task = task

    def request(self, pending: dict[str, Any], decision: Decision, state: RunState) -> GateResult:
        now = utcnow()
        tool_id = pending["tool_id"]
        recent = [
            {k: o.get(k) for k in ("step", "label", "tool_id", "status")}
            for o in state.agent_state.get("agent", {}).get("observations", [])[-5:]
        ]
        approval = Approval(
            id=new_id("apr"), execution_id=self.execution.id, decision_id=pending["decision_id"],
            step=pending["step"], action_label=pending["label"], action_hash=pending["action_hash"],
            tool_id=tool_id, tool_version=pending["tool_version"] or "",
            arguments_redacted=pending["arguments_redacted"],
            risk_level=pending.get("risk_level") or "unknown", reason=decision.reason,
            context={"task": self.task, "rationale": pending["rationale"], "agent_claims": pending["claims"],
                     "deciding_rule": decision.deciding_rule, "recent_observations": recent,
                     "environment": self.execution.environment,
                     "policy": f"{decision.policy_id}@v{decision.policy_version}"},
            status="pending", created_at=now, expires_at=now + timedelta(seconds=self.ttl),
        )
        self.session.add(approval)
        self.session.flush()
        self.execution.pending_approval_id = approval.id
        return GateResult(paused=True, approval_id=approval.id,
                          data={"expires_at": approval.expires_at.isoformat(), "ttl_seconds": self.ttl})


def read_state(execution: Execution) -> RunState:
    return RunState(
        status=execution.status, status_reason=execution.status_reason, step_count=execution.step_count,
        tool_call_count=execution.tool_call_count, agent_state=execution.agent_state.get("agent", {}),
        recent_calls=list(execution.agent_state.get("recent_calls", [])), sandbox=execution.sandbox_state,
        pending_action=execution.pending_action, pending_approval_id=execution.pending_approval_id,
        final_output=execution.final_output, active_ms=execution.active_ms,
    )


def write_state(execution: Execution, state: RunState) -> None:
    execution.status = state.status
    execution.status_reason = state.status_reason
    execution.step_count = state.step_count
    execution.tool_call_count = state.tool_call_count
    execution.agent_state = {"agent": state.agent_state, "recent_calls": state.recent_calls}
    execution.sandbox_state = state.sandbox
    execution.pending_action = state.pending_action
    execution.pending_approval_id = state.pending_approval_id
    execution.final_output = state.final_output
    execution.active_ms = round(state.active_ms, 3)
    execution.updated_at = utcnow()
    if state.status in TERMINAL_STATUSES and execution.finished_at is None:
        execution.finished_at = utcnow()


def effective_limits(settings: Settings, spec: ScenarioSpec) -> RunLimits:
    return RunLimits(
        max_steps=min(settings.max_steps, spec.limits.max_steps or settings.max_steps),
        max_tool_calls=min(settings.max_tool_calls, spec.limits.max_tool_calls or settings.max_tool_calls),
        max_identical_calls=settings.max_identical_calls,
        timeout_seconds=settings.execution_timeout_seconds,
    )


def make_agent(spec: ScenarioSpec, settings: Settings) -> Agent:
    try:
        return build_agent(spec.agent, llm_factory=None)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), code="agent_unavailable") from exc


def build_runner(session: Session, settings: Settings, execution: Execution) -> Runner:
    spec = ScenarioSpec.model_validate(execution.spec)
    registry = ToolRegistry.from_session(session)
    policy_row = get_version(session, execution.policy_id, execution.policy_version)
    sink = DbSink(session, execution)
    gate = LiveApprovalGate(session, execution, settings.approval_ttl_seconds, spec.task)
    return Runner(
        execution_id=execution.id, scenario_id=execution.scenario_id, spec=spec,
        agent=make_agent(spec, settings), registry=registry, policy=load_document(policy_row),
        policy_id=execution.policy_id, policy_version=execution.policy_version, sink=sink, gate=gate,
        limits=effective_limits(settings, spec), seed=execution.seed,
    )


def create_execution(session: Session, settings: Settings, request: ExecutionCreate, *,
                     origin: str = "manual", evaluation_id: str | None = None) -> Execution:
    scenario = get_scenario(session, request.scenario_id, request.scenario_version)
    spec = ScenarioSpec.model_validate(scenario.spec)
    if request.environment:
        spec = spec.model_copy(update={"environment": request.environment})
    if request.seed is not None:
        spec = spec.model_copy(update={"seed": request.seed})
    policy_row = get_version(session, request.policy_id, request.policy_version)
    agent = make_agent(spec, settings)
    sandbox = initial_sandbox()
    execution = Execution(
        id=new_id("exe"), scenario_id=scenario.scenario_id, scenario_version=scenario.version,
        policy_id=policy_row.policy_id, policy_version=policy_row.version, agent_type=spec.agent.type,
        environment=spec.environment, seed=spec.seed, origin=origin, evaluation_id=evaluation_id,
        status="pending", task=spec.task, spec=spec.model_dump(mode="json"),
        agent_state={"agent": agent.initial_state(), "recent_calls": []}, sandbox_state=sandbox,
        initial_sandbox_hash=fingerprint(sandbox), last_event_hash="0" * 64,
    )
    session.add(execution)
    session.flush()
    append_event(session, execution, EventRecord(
        event_type=EventType.EXECUTION_CREATED, outcome="pending", policy_version=f"{policy_row.policy_id}@v{policy_row.version}",
        data={"scenario_id": scenario.scenario_id, "scenario_version": scenario.version,
              "scenario_hash": scenario.content_hash, "policy_hash": policy_row.content_hash,
              "agent_type": spec.agent.type, "deterministic_agent": agent.deterministic,
              "environment": spec.environment, "seed": spec.seed, "task": spec.task, "origin": origin,
              "initial_sandbox_hash": execution.initial_sandbox_hash,
              "limits": vars(effective_limits(settings, spec))},
    ))
    session.commit()
    return execution


def start_execution(session: Session, settings: Settings, request: ExecutionCreate, *,
                    origin: str = "manual", evaluation_id: str | None = None) -> Execution:
    execution = create_execution(session, settings, request, origin=origin, evaluation_id=evaluation_id)
    execution.started_at = utcnow()
    build_runner(session, settings, execution).run(read_state(execution))
    return execution


def resume_execution(session: Session, settings: Settings, execution: Execution, resolution: Resolution) -> Execution:
    """Continue a paused execution. Callers must hold the execution (see approvals service)."""
    runner = build_runner(session, settings, execution)
    runner.resume(read_state(execution), resolution)
    return execution


def cancel_execution(session: Session, settings: Settings, execution: Execution, reason: str) -> Execution:
    """Cancel a pending or waiting execution. Takes the write lock so it cannot race an approval."""
    with write_transaction(session):
        session.refresh(execution)
        if execution.status in TERMINAL_STATUSES:
            raise ConflictError(f"execution is already {execution.status}", code="execution_finished")
        if execution.status == "running":
            raise ConflictError("execution is running; it can be cancelled once it pauses", code="execution_running")
        if execution.pending_approval_id:
            changed = session.execute(
                update(Approval)
                .where(Approval.id == execution.pending_approval_id, Approval.status == "pending")
                .values(status="cancelled", decided_at=utcnow(), decision_note="execution cancelled")
            ).rowcount  # type: ignore[attr-defined]
            if changed != 1:
                raise ConflictError("the pending approval was decided concurrently", code="approval_already_decided")
        build_runner(session, settings, execution).cancel(read_state(execution), reason)
    return execution
