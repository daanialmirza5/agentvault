"""The execution loop, independent of persistence.

For every proposed tool call the runner applies, in order:

    guards (tool-call limit, loop detection) -> registry lookup -> schema validation
    -> policy evaluation -> [approval gate] -> sandboxed execution -> observation

and emits a structured event for each stage. Live executions plug in a database sink and an
approval gate that pauses; replays plug in an in-memory sink and a gate that answers from
recorded decisions. Both therefore exercise exactly the same authorisation code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.core.redaction import redact
from app.core.utils import canonical_json, fingerprint, new_id
from app.services.agent_runtime.agents import (
    Agent,
    AgentContext,
    FailAction,
    FinishAction,
    ToolCallAction,
)
from app.services.agent_runtime.scenario import ScenarioSpec
from app.services.audit.events import EventRecord, EventType
from app.services.policy_engine.engine import evaluate
from app.services.policy_engine.model import Decision, PolicyContext, PolicyDocument
from app.services.tool_registry.executor import ToolRunResult, run_tool
from app.services.tool_registry.registry import ToolRegistry, ToolSpec

MAX_OUTPUT_BYTES = 32 * 1024


@dataclass
class RunLimits:
    max_steps: int
    max_tool_calls: int
    max_identical_calls: int
    timeout_seconds: float


@dataclass
class RunState:
    status: str
    status_reason: str = ""
    step_count: int = 0
    tool_call_count: int = 0
    agent_state: dict[str, Any] = field(default_factory=dict)
    recent_calls: list[str] = field(default_factory=list)
    sandbox: dict[str, Any] = field(default_factory=dict)
    pending_action: dict[str, Any] | None = None
    pending_approval_id: str | None = None
    final_output: str = ""
    active_ms: float = 0.0


@dataclass
class Resolution:
    outcome: Literal["approved", "rejected", "expired", "unavailable"]
    approval_id: str | None = None
    decided_by: str | None = None
    note: str = ""
    source: str = "live"


@dataclass
class GateResult:
    paused: bool
    approval_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    resolution: Resolution | None = None


class EventSink(Protocol):
    def emit(self, record: EventRecord) -> str: ...

    def record_decision(
        self, *, decision_id: str, event_id: str, decision: Decision, pending: dict[str, Any], latency_us: float
    ) -> None: ...

    def checkpoint(self, state: RunState) -> None: ...


class ApprovalGate(Protocol):
    def request(self, pending: dict[str, Any], decision: Decision, state: RunState) -> GateResult: ...


class ToolInvoker(Protocol):
    def invoke(
        self, tool: ToolSpec, pending: dict[str, Any], sandbox: dict[str, Any], seed: int
    ) -> tuple[ToolRunResult | None, str]: ...


class LiveToolInvoker:
    def invoke(
        self, tool: ToolSpec, pending: dict[str, Any], sandbox: dict[str, Any], seed: int
    ) -> tuple[ToolRunResult | None, str]:
        return run_tool(tool, pending["arguments"], sandbox, seed=seed, step=pending["step"]), "live"


def action_hash(execution_id: str, step: int, tool_id: str, tool_version: str | None, arguments: Any) -> str:
    """Binds an approval to one exact action of one execution."""
    return fingerprint(
        {
            "execution_id": execution_id,
            "step": step,
            "tool_id": tool_id,
            "tool_version": tool_version,
            "arguments": arguments,
        }
    )


def action_fingerprint(step: int, tool_id: str, arguments: Any) -> str:
    """Execution-independent identity of an action, used to match actions across runs."""
    return fingerprint({"step": step, "tool_id": tool_id, "arguments": arguments})


def _bounded(value: Any) -> Any:
    if len(canonical_json(value)) > MAX_OUTPUT_BYTES:
        return {"_truncated": True, "_bytes": len(canonical_json(value))}
    return value


class Runner:
    def __init__(
        self,
        *,
        execution_id: str,
        scenario_id: str,
        spec: ScenarioSpec,
        agent: Agent,
        registry: ToolRegistry,
        policy: PolicyDocument,
        policy_id: str,
        policy_version: int,
        sink: EventSink,
        gate: ApprovalGate,
        limits: RunLimits,
        seed: int,
        invoker: ToolInvoker | None = None,
    ) -> None:
        self.execution_id = execution_id
        self.spec = spec
        self.agent = agent
        self.registry = registry
        self.policy = policy
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.policy_label = f"{policy_id}@v{policy_version}"
        self.sink = sink
        self.gate = gate
        self.limits = limits
        self.seed = seed
        self.invoker = invoker or LiveToolInvoker()
        self.context = PolicyContext(
            environment=spec.environment,
            scenario_id=scenario_id,
            scenario_tags=tuple(spec.tags),
            execution_id=execution_id,
        )
        self.agent_ctx = AgentContext(
            task=spec.task,
            tool_catalog=[
                {"tool_id": t.tool_id, "description": t.description, "input_schema": t.input_schema}
                for t in registry.all()
            ],
        )

    # ------------------------------------------------------------------ public API
    def run(self, state: RunState) -> RunState:
        started = time.perf_counter()
        if state.status == "pending":
            state.status = "running"
            self._emit(EventType.EXECUTION_STARTED, "ok", {"limits": vars(self.limits)})
        try:
            while state.status == "running":
                elapsed_ms = state.active_ms + (time.perf_counter() - started) * 1000
                if elapsed_ms > self.limits.timeout_seconds * 1000:
                    self._guard(state, "execution_timeout", self.limits.timeout_seconds, terminal="failed")
                    break
                if state.step_count >= self.limits.max_steps:
                    self._guard(state, "max_steps", self.limits.max_steps)
                    break
                self._step(state)
                self.sink.checkpoint(state)
        finally:
            state.active_ms += (time.perf_counter() - started) * 1000
        self.sink.checkpoint(state)
        return state

    def resume(self, state: RunState, resolution: Resolution) -> RunState:
        # The caller has already claimed the execution (waiting_for_approval -> running) atomically.
        if state.status not in {"waiting_for_approval", "running"} or state.pending_action is None:
            raise RuntimeError("execution is not waiting for approval")
        state.status = "running"
        self._emit(
            EventType.EXECUTION_RESUMED,
            resolution.outcome,
            {"approval_id": resolution.approval_id, "step": state.pending_action["step"]},
        )
        self._apply_resolution(state, resolution)
        return self.run(state)

    def cancel(self, state: RunState, reason: str) -> RunState:
        state.pending_action = None
        state.pending_approval_id = None
        self._finish(state, "cancelled", reason)
        self.sink.checkpoint(state)
        return state

    # ------------------------------------------------------------------ internals
    def _emit(self, event_type: EventType, outcome: str, data: dict[str, Any], tool_id: str | None = None) -> str:
        return self.sink.emit(
            EventRecord(
                event_type=event_type, outcome=outcome, data=data, tool_id=tool_id, policy_version=self.policy_label
            )
        )

    def _step(self, state: RunState) -> None:
        state.step_count += 1
        step = state.step_count
        try:
            action, agent_state = self.agent.decide(state.agent_state, self.agent_ctx)
        except Exception as exc:  # e.g. an LLM adapter error; never crash the engine
            self._finish(state, "failed", f"agent_error: {type(exc).__name__}: {str(exc)[:200]}")
            return
        state.agent_state = agent_state
        if isinstance(action, FinishAction):
            state.final_output = action.summary
            self._finish(state, "completed", "agent_finished", summary=action.summary)
        elif isinstance(action, FailAction):
            self._finish(state, "failed", f"agent_failed: {action.reason}")
        else:
            self._tool_call(state, step, action)

    def _tool_call(self, state: RunState, step: int, action: ToolCallAction) -> None:
        tool = self.registry.get(action.tool_id) if isinstance(action.tool_id, str) else None
        sensitive = tool.sensitive_arguments if tool else []
        raw_args = action.arguments
        args_for_log = redact(raw_args, sensitive) if isinstance(raw_args, dict) else {"_raw": str(raw_args)[:200]}
        self._emit(
            EventType.AGENT_ACTION_PROPOSED,
            "proposed",
            {
                "step": step,
                "label": action.label,
                "tool_id": action.tool_id,
                "arguments": args_for_log,
                "rationale": action.rationale,
                "agent_claims": action.claims,
                "claims_note": "Agent claims are recorded for audit only and are never inputs to the policy engine.",
            },
            tool_id=action.tool_id,
        )

        call_fp = fingerprint({"tool_id": action.tool_id, "arguments": raw_args})
        if state.tool_call_count >= self.limits.max_tool_calls:
            self._guard(state, "max_tool_calls", self.limits.max_tool_calls)
            return
        recent = state.recent_calls[-self.limits.max_identical_calls :]
        if len(recent) == self.limits.max_identical_calls and all(r == call_fp for r in recent):
            self._guard(
                state,
                "loop_detected",
                self.limits.max_identical_calls,
                detail=f"'{action.tool_id}' requested with identical arguments "
                f"{self.limits.max_identical_calls + 1} times in a row",
            )
            return
        state.recent_calls = ([*state.recent_calls, call_fp])[-50:]
        state.tool_call_count += 1

        tool_version = tool.version if tool else None
        pending: dict[str, Any] = {
            "step": step,
            "label": action.label,
            "tool_id": action.tool_id,
            "tool_version": tool_version,
            "arguments": raw_args,
            "arguments_redacted": args_for_log,
            "action_hash": action_hash(self.execution_id, step, action.tool_id, tool_version, raw_args),
            "fingerprint": action_fingerprint(step, action.tool_id, raw_args),
            "rationale": action.rationale,
            "claims": action.claims,
            "risk_level": tool.risk_level if tool else None,
        }
        self._emit(
            EventType.TOOL_REQUESTED,
            "requested",
            {
                "step": step,
                "label": action.label,
                "tool_version": tool_version,
                "arguments": args_for_log,
                "action_hash": pending["action_hash"],
                "action_fingerprint": pending["fingerprint"],
                "registered": tool is not None,
            },
            tool_id=action.tool_id,
        )

        errors: list[str] = []
        if tool is not None:
            errors = self.registry.validate_arguments(tool, raw_args)
            if errors:
                self._emit(
                    EventType.ARGUMENTS_REJECTED,
                    "invalid",
                    {"step": step, "label": action.label, "errors": errors},
                    tool_id=action.tool_id,
                )
            else:
                self._emit(
                    EventType.ARGUMENTS_VALIDATED,
                    "valid",
                    {"step": step, "label": action.label},
                    tool_id=action.tool_id,
                )

        t0 = time.perf_counter_ns()
        decision = evaluate(
            self.policy,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            tool_id=str(action.tool_id),
            tool=tool,
            arguments=raw_args if isinstance(raw_args, dict) else {},
            argument_errors=errors,
            context=self.context,
        )
        latency_us = (time.perf_counter_ns() - t0) / 1000
        decision_id = new_id("dec")
        pending["decision_id"] = decision_id
        pending["decision"] = {
            "outcome": decision.outcome,
            "reason": decision.reason,
            "deciding_rule": decision.deciding_rule,
        }
        event_id = self._emit(
            EventType.POLICY_EVALUATED,
            decision.outcome,
            {
                "step": step,
                "label": action.label,
                "decision_id": decision_id,
                "reason": decision.reason,
                "deciding_rule": decision.deciding_rule,
                "matched_rules": [m.model_dump() for m in decision.matched_rules],
                "trace": decision.trace,
                "latency_us": round(latency_us, 2),
                "risk_level": tool.risk_level if tool else None,
            },
            tool_id=action.tool_id,
        )
        self.sink.record_decision(
            decision_id=decision_id, event_id=event_id, decision=decision, pending=pending, latency_us=latency_us
        )

        if decision.outcome == "allow":
            assert tool is not None
            self._execute(state, pending, tool)
        elif decision.outcome == "deny":
            kind = {"builtin:unknown_tool": "unknown_tool", "builtin:invalid_arguments": "invalid"}.get(
                decision.deciding_rule, "denied"
            )
            self._blocked(state, pending, kind, decision.reason)
        else:
            gate = self.gate.request(pending, decision, state)
            self._emit(
                EventType.APPROVAL_REQUESTED,
                "pending" if gate.paused else "simulated",
                {
                    "step": step,
                    "label": action.label,
                    "approval_id": gate.approval_id,
                    "action_hash": pending["action_hash"],
                    **gate.data,
                },
                tool_id=action.tool_id,
            )
            state.pending_action = pending
            state.pending_approval_id = gate.approval_id
            if gate.paused:
                state.status = "waiting_for_approval"
                state.status_reason = f"awaiting approval for '{action.tool_id}' at step {step}"
            else:
                assert gate.resolution is not None
                self._apply_resolution(state, gate.resolution)

    def _apply_resolution(self, state: RunState, resolution: Resolution) -> None:
        pending = state.pending_action
        assert pending is not None
        state.pending_action = None
        state.pending_approval_id = None
        state.status_reason = ""
        common = {
            "step": pending["step"],
            "label": pending["label"],
            "approval_id": resolution.approval_id,
            "decided_by": resolution.decided_by,
            "note": resolution.note,
            "source": resolution.source,
        }
        tool_id = pending["tool_id"]
        if resolution.outcome == "approved":
            # Re-derive the hash from the stored action: the approval only covers this exact action.
            expected = action_hash(
                self.execution_id, pending["step"], tool_id, pending["tool_version"], pending["arguments"]
            )
            if expected != pending["action_hash"]:
                self._emit(EventType.APPROVAL_BINDING_MISMATCH, "refused", common, tool_id=tool_id)
                self._blocked(state, pending, "binding_mismatch", "pending action no longer matches the approval")
                return
            self._emit(EventType.APPROVAL_GRANTED, "approved", common, tool_id=tool_id)
            tool = self.registry.get(tool_id)
            if tool is None:
                self._blocked(state, pending, "unknown_tool", "tool was removed from the registry")
                return
            self._execute(state, pending, tool)
        elif resolution.outcome == "rejected":
            self._emit(EventType.APPROVAL_REJECTED, "rejected", common, tool_id=tool_id)
            self._blocked(state, pending, "rejected", "a human rejected the action")
        elif resolution.outcome == "expired":
            self._emit(EventType.APPROVAL_EXPIRED, "expired", common, tool_id=tool_id)
            self._blocked(state, pending, "expired", "the approval request expired before a decision")
        else:
            self._emit(
                EventType.TOOL_BLOCKED,
                "unavailable",
                {**common, "reason": "approval_decision_unavailable"},
                tool_id=tool_id,
            )
            self._finish(state, "blocked", "replay_unresolvable: no recorded approval decision for this action")

    def _execute(self, state: RunState, pending: dict[str, Any], tool: ToolSpec) -> None:
        step, label = pending["step"], pending["label"]
        # Persist everything decided so far before running the tool, so a slow tool never holds
        # a database write lock and a crash mid-tool leaves a consistent "running" record.
        self.sink.checkpoint(state)
        result, source = self.invoker.invoke(tool, pending, state.sandbox, self.seed)
        if result is None:
            self._emit(
                EventType.TOOL_FAILED,
                "unavailable",
                {
                    "step": step,
                    "label": label,
                    "source": source,
                    "error": "recorded output unavailable and tool is non-deterministic",
                },
                tool_id=tool.tool_id,
            )
            self._finish(state, "failed", "replay_unresolvable: tool output unavailable")
            return
        self._emit(
            EventType.TOOL_EXECUTED,
            result.status,
            {
                "step": step,
                "label": label,
                "tool_version": tool.version,
                "duration_ms": result.duration_ms,
                "source": source,
                "deterministic": tool.deterministic,
            },
            tool_id=tool.tool_id,
        )
        if result.status == "succeeded":
            state.sandbox = result.sandbox
            output = _bounded(result.output)
            self._emit(
                EventType.TOOL_RESULT,
                "ok",
                {
                    "step": step,
                    "label": label,
                    "output": output,
                    "output_hash": fingerprint(result.output),
                    "source": source,
                },
                tool_id=tool.tool_id,
            )
            observation = {
                "step": step,
                "label": label,
                "tool_id": tool.tool_id,
                "status": "executed",
                "output": result.output,
                "error": None,
            }
        else:
            self._emit(
                EventType.TOOL_FAILED,
                result.status,
                {
                    "step": step,
                    "label": label,
                    "error": result.error,
                    "source": source,
                },
                tool_id=tool.tool_id,
            )
            observation = {
                "step": step,
                "label": label,
                "tool_id": tool.tool_id,
                "status": result.status,
                "output": None,
                "error": result.error,
            }
        state.agent_state, stop = self.agent.observe(state.agent_state, observation)
        if stop and result.status != "succeeded":
            self._finish(state, "failed", f"tool_failed: {label} ({result.status}): {result.error}")

    def _blocked(self, state: RunState, pending: dict[str, Any], kind: str, reason: str) -> None:
        self._emit(
            EventType.TOOL_BLOCKED,
            kind,
            {
                "step": pending["step"],
                "label": pending["label"],
                "reason": reason,
                "decision_id": pending.get("decision_id"),
            },
            tool_id=pending["tool_id"],
        )
        observation = {
            "step": pending["step"],
            "label": pending["label"],
            "tool_id": pending["tool_id"],
            "status": kind,
            "output": None,
            "error": reason,
        }
        state.agent_state, stop = self.agent.observe(state.agent_state, observation)
        if stop:
            self._finish(state, "blocked", f"{pending['label']}: {kind} - {reason}")

    def _guard(self, state: RunState, guard: str, limit: float, *, terminal: str = "blocked", detail: str = "") -> None:
        self._emit(
            EventType.GUARD_TRIGGERED,
            guard,
            {"guard": guard, "limit": limit, "step": state.step_count, "detail": detail},
        )
        self._finish(state, terminal, f"guard:{guard}" + (f" - {detail}" if detail else ""))

    def _finish(self, state: RunState, status: str, reason: str, summary: str = "") -> None:
        event = {
            "completed": EventType.EXECUTION_COMPLETED,
            "failed": EventType.EXECUTION_FAILED,
            "blocked": EventType.EXECUTION_BLOCKED,
            "cancelled": EventType.EXECUTION_CANCELLED,
        }[status]
        state.status = status
        state.status_reason = reason
        self._emit(
            event,
            status,
            {"reason": reason, "summary": summary, "steps": state.step_count, "tool_calls": state.tool_call_count},
        )
