"""Provider-independent agent interface and the deterministic built-in agents.

An agent is a pure state machine: ``decide(state, ctx)`` returns the next action and the new
state; ``observe(state, observation)`` folds a tool outcome back in. State is plain JSON so
executions can pause for approval, resume in another request, and be replayed exactly.
Agents never execute tools themselves - they only *propose* actions to the runner.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.agent_runtime.scenario import AgentSpec, StepSpec
from app.services.policy_engine.engine import condition_holds
from app.services.policy_engine.model import ArgumentCondition

INSTRUCTION_MARKER = "AGENT-INSTRUCTION:"


@dataclass
class ToolCallAction:
    label: str
    tool_id: str
    arguments: Any
    rationale: str = ""
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinishAction:
    summary: str


@dataclass
class FailAction:
    reason: str


Action = ToolCallAction | FinishAction | FailAction


@dataclass
class AgentContext:
    task: str
    tool_catalog: list[dict[str, Any]]


class Agent(Protocol):
    agent_type: str
    deterministic: bool

    def initial_state(self) -> dict[str, Any]: ...

    def decide(self, state: dict[str, Any], ctx: AgentContext) -> tuple[Action, dict[str, Any]]: ...

    def observe(self, state: dict[str, Any], observation: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Return the new state and whether the agent stops (gives up) after this outcome."""
        ...


def latest_observation(state: dict[str, Any], label: str) -> dict[str, Any] | None:
    for obs in reversed(state.get("observations", [])):
        if obs["label"] == label:
            return dict(obs)
    return None


def _lookup(obs: dict[str, Any], path: str) -> Any:
    current: Any = obs
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def render_arguments(value: Any, state: dict[str, Any]) -> Any:
    """Substitute whole-string templates ``{{label.output.field}}`` from earlier observations."""
    if isinstance(value, dict):
        return {k: render_arguments(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [render_arguments(v, state) for v in value]
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        label, _, path = value[2:-2].strip().partition(".")
        obs = latest_observation(state, label)
        if obs is not None and obs.get("status") == "executed":
            found = _lookup(obs, path)
            if found is not None:
                return found
    return value


def parse_embedded_instruction(output: Any) -> dict[str, Any] | None:
    """Find an ``AGENT-INSTRUCTION: {...}`` payload in retrieved content.

    This models a *naive* agent that obeys instructions found in untrusted data. The point
    of the scenarios that use it is to show that the policy layer still stops the action.
    """
    if isinstance(output, str):
        text = output
    elif isinstance(output, dict):
        text = "\n".join(str(v) for v in output.values())
    else:
        text = json.dumps(output, default=str)
    idx = text.find(INSTRUCTION_MARKER)
    if idx < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[idx + len(INSTRUCTION_MARKER) :].lstrip())
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_id"), str):
        return None
    return payload


class ScriptAgent:
    """Interprets a scenario's step list. ``scripted`` agents are linear; ``reactive`` agents
    may branch on observed results and follow instructions found in tool output."""

    deterministic = True

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self.agent_type: str = spec.type

    def initial_state(self) -> dict[str, Any]:
        return {
            "queue": [s.model_dump(mode="json") for s in self.spec.steps],
            "observations": [],
            "attempts": {},
            "current": None,
        }

    def decide(self, state: dict[str, Any], ctx: AgentContext) -> tuple[Action, dict[str, Any]]:
        state = copy.deepcopy(state)
        queue: list[dict[str, Any]] = state["queue"]
        while queue:
            step = StepSpec.model_validate(queue.pop(0))
            if step.kind == "finish":
                return FinishAction(step.summary or "Task complete."), state
            if step.kind == "fail":
                return FailAction(step.summary or "Agent gave up."), state
            if step.kind == "branch":
                assert step.condition is not None
                obs = latest_observation(state, step.condition.label) or {"status": "missing"}
                cond = ArgumentCondition(path=step.condition.path, op=step.condition.op, value=step.condition.value)
                chosen = step.then if condition_holds(cond, obs) else step.otherwise
                queue[0:0] = [s.model_dump(mode="json") for s in chosen]
                continue
            if step.kind == "follow_instructions":
                assert step.source is not None
                source_obs = latest_observation(state, step.source)
                payload = (
                    parse_embedded_instruction(source_obs.get("output"))
                    if source_obs and source_obs["status"] == "executed"
                    else None
                )
                if payload is None:
                    continue
                action = ToolCallAction(
                    label=step.label,
                    tool_id=payload["tool_id"],
                    arguments=payload.get("arguments", {}),
                    rationale=f"Following an instruction found in the output of '{step.source}'.",
                    claims=payload.get("claims", {}) if isinstance(payload.get("claims"), dict) else {},
                )
                state["current"] = step.model_dump(mode="json")
                return action, state
            if step.kind == "repeat" and step.times > 1:
                again = step.model_copy(update={"times": step.times - 1})
                queue.insert(0, again.model_dump(mode="json"))
            assert step.tool_id is not None
            state["current"] = step.model_dump(mode="json")
            return ToolCallAction(
                label=step.label,
                tool_id=step.tool_id,
                arguments=render_arguments(copy.deepcopy(step.arguments), state),
                rationale=step.rationale,
                claims=dict(step.claims),
            ), state
        return FinishAction("All planned steps finished."), state

    def observe(self, state: dict[str, Any], observation: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        state = copy.deepcopy(state)
        state["observations"].append(observation)
        step = StepSpec.model_validate(state["current"]) if state.get("current") else None
        state["current"] = None
        if step is None:
            return state, False
        status = observation["status"]
        if status == "executed":
            return state, False
        if status in {"failed", "timeout"}:
            attempts = state["attempts"].get(step.label, 0)
            if attempts < step.max_retries:
                state["attempts"][step.label] = attempts + 1
                retry = step.model_copy(update={"kind": "tool", "times": 1})
                state["queue"].insert(0, retry.model_dump(mode="json"))
                return state, False
            return state, step.on_failure == "stop"
        return state, step.on_blocked == "stop"


def build_agent(spec: AgentSpec, *, llm_factory: Any = None) -> Agent:
    if spec.type == "llm":
        if llm_factory is None:
            raise ValueError("the LLM adapter is not configured (set AGENTVAULT_LLM_* variables)")
        agent: Agent = llm_factory(spec)
        return agent
    return ScriptAgent(spec)
