"""Scenario models.

A scenario file has three parts with strictly separated audiences:

* ``spec``          - the task, environment and agent script. The ONLY part the engine sees.
* ``human_script``  - how the simulated human answers approval requests (evaluator only).
* ``expectations``  - ground-truth labels used to score a run (evaluator only).

The engine's entry points accept :class:`ScenarioSpec`, which forbids extra fields, so
expectations cannot be passed to the policy engine even by accident.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.utils import fingerprint, new_id
from app.models import Scenario
from app.services.policy_engine.model import ConditionOp

LABEL = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class StepCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern=LABEL, description="Label of an earlier step.")
    path: str = Field(
        default="status", max_length=200, description="`status` or `output.<field>` of that step's latest observation."
    )
    op: ConditionOp = "eq"
    value: Any = None


class StepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool", "repeat", "follow_instructions", "branch", "finish", "fail"] = "tool"
    label: str = Field(pattern=LABEL)
    tool_id: str | None = Field(default=None, max_length=80)
    arguments: Any = None
    rationale: str = Field(default="", max_length=500)
    claims: dict[str, Any] = Field(
        default_factory=dict, description="Assertions the agent makes (e.g. 'safe'). Recorded, never trusted."
    )
    times: int = Field(default=1, ge=1, le=1000)
    source: str | None = Field(default=None, pattern=LABEL)
    condition: StepCondition | None = None
    then: list[StepSpec] = Field(default_factory=list, max_length=50)
    otherwise: list[StepSpec] = Field(default_factory=list, max_length=50)
    on_blocked: Literal["continue", "stop"] = "stop"
    on_failure: Literal["continue", "stop"] = "stop"
    max_retries: int = Field(default=0, ge=0, le=3)
    summary: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _shape(self) -> StepSpec:
        if self.kind in {"tool", "repeat"} and not self.tool_id:
            raise ValueError(f"'{self.kind}' steps need a tool_id")
        if self.kind == "follow_instructions" and not self.source:
            raise ValueError("'follow_instructions' steps need a source label")
        if self.kind == "branch" and self.condition is None:
            raise ValueError("'branch' steps need a condition")
        return self


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["scripted", "reactive", "llm"] = "scripted"
    steps: list[StepSpec] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _scripted_is_linear(self) -> AgentSpec:
        if self.type == "scripted":
            for s in self.steps:
                if s.kind in {"branch", "follow_instructions"}:
                    raise ValueError("scripted agents are linear; use type 'reactive' for branch/follow_instructions")
        if self.type != "llm" and not self.steps:
            raise ValueError("scripted and reactive agents need at least one step")
        return self


class ScenarioLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int | None = Field(default=None, ge=1, le=500)
    max_tool_calls: int | None = Field(default=None, ge=1, le=200)


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=2000)
    environment: Literal["sandbox", "staging", "production"] = "sandbox"
    tags: list[str] = Field(default_factory=list, max_length=20)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    agent: AgentSpec
    limits: ScenarioLimits = Field(default_factory=ScenarioLimits)


HumanDecision = Literal["approve", "reject", "expire", "approve_wrong_execution", "approve_tampered_action"]


class HumanScript(BaseModel):
    """Simulated human answers keyed by step label. A list is tried in order (for attacks)."""

    model_config = ConfigDict(extra="forbid")

    decisions: dict[str, list[HumanDecision]] = Field(default_factory=dict)
    default: Literal["approve", "reject"] = "reject"


class ActionExpectation(BaseModel):
    """Ground truth for one labelled action.

    * ``safety`` - ``unsafe`` means a correct platform must never execute it (unauthorised,
      policy-violating, malformed or injected); ``legitimate`` means it is a valid part of the task.
    * ``should_execute`` - whether, given the scenario's scripted human decisions, it should
      end up executed. Defaults to True for legitimate and False for unsafe actions. (A
      legitimate action whose approval the human rejects or lets expire should NOT execute.)
    * ``requires_approval`` - a correct platform must obtain a human approval before executing it.
    """

    model_config = ConfigDict(extra="forbid")

    safety: Literal["unsafe", "legitimate"]
    should_execute: bool | None = None
    requires_approval: bool = False

    @property
    def expected_execution(self) -> bool:
        return self.should_execute if self.should_execute is not None else self.safety == "legitimate"


class Expectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_status: str | None = None
    expected_guard: str | None = None
    expected_events: list[str] = Field(default_factory=list)
    actions: dict[str, ActionExpectation] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)


class ScenarioFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    version: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=2000)
    spec: ScenarioSpec
    human_script: HumanScript = Field(default_factory=HumanScript)
    expectations: Expectations = Field(default_factory=Expectations)


def scenario_hash(s: ScenarioFile) -> str:
    return fingerprint(s.model_dump(mode="json"))


def save_scenario(session: Session, scenario: ScenarioFile, source: str) -> Scenario:
    existing = session.scalar(
        select(Scenario).where(Scenario.scenario_id == scenario.id, Scenario.version == scenario.version)
    )
    digest = scenario_hash(scenario)
    if existing is not None:
        if existing.content_hash != digest:
            raise ConflictError(
                f"scenario {scenario.id} v{scenario.version} exists with different content; bump the version",
                code="scenario_version_conflict",
            )
        return existing
    row = Scenario(
        id=new_id("scn"),
        scenario_id=scenario.id,
        version=scenario.version,
        name=scenario.name,
        category=scenario.category,
        description=scenario.description,
        source=source,
        spec=scenario.spec.model_dump(mode="json"),
        human_script=scenario.human_script.model_dump(mode="json"),
        expectations=scenario.expectations.model_dump(mode="json"),
        content_hash=digest,
    )
    session.add(row)
    session.flush()
    return row


def get_scenario(session: Session, scenario_id: str, version: int | None = None) -> Scenario:
    query = select(Scenario).where(Scenario.scenario_id == scenario_id)
    query = query.where(Scenario.version == version) if version else query.order_by(Scenario.version.desc())
    row = session.scalars(query.limit(1)).first()
    if row is None:
        raise NotFoundError(f"scenario '{scenario_id}'" + (f" v{version}" if version else "") + " not found")
    return row
