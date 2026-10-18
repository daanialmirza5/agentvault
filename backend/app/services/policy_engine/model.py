"""Policy document model. Policies are pure data: no code, no regular expressions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Effect = Literal["allow", "deny", "require_approval"]
EFFECT_SEVERITY: dict[str, int] = {"allow": 0, "require_approval": 1, "deny": 2}

ConditionOp = Literal[
    "eq", "neq", "in", "not_in", "contains", "prefix", "suffix", "glob",
    "exists", "not_exists", "gt", "gte", "lt", "lte",
]


class ArgumentCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}(\.[A-Za-z0-9_]{1,64}){0,5}$",
                      description="Dotted path into the tool arguments, e.g. `field` or `address.country`.")
    op: ConditionOp
    value: Any = None

    @model_validator(mode="after")
    def _value_shape(self) -> ArgumentCondition:
        if self.op in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError(f"'{self.op}' requires a list value")
        if self.op in {"gt", "gte", "lt", "lte"} and not isinstance(self.value, int | float):
            raise ValueError(f"'{self.op}' requires a numeric value")
        if self.op in {"prefix", "suffix", "glob"} and not isinstance(self.value, str):
            raise ValueError(f"'{self.op}' requires a string value")
        if isinstance(self.value, str) and len(self.value) > 500:
            raise ValueError("condition value too long")
        return self


class RuleMatch(BaseModel):
    """All specified dimensions must match (AND). Lists within a dimension are OR.
    An omitted dimension matches anything."""

    model_config = ConfigDict(extra="forbid")

    tool_ids: list[str] | None = Field(default=None, description="Exact IDs or globs such as `email.*`.")
    categories: list[str] | None = None
    risk_levels: list[Literal["low", "medium", "high", "critical"]] | None = None
    operations: list[Literal["read", "write"]] | None = None
    environments: list[str] | None = None
    scenario_tags: list[str] | None = Field(default=None, description="Matches if the scenario has any of these tags.")
    arguments: list[ArgumentCondition] = Field(default_factory=list, max_length=20)

    @field_validator("tool_ids", "categories", "environments", "scenario_tags")
    @classmethod
    def _non_empty(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (not value or len(value) > 50 or any(not v or len(v) > 80 for v in value)):
            raise ValueError("lists must contain 1-50 non-empty values")
        return value


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    description: str = Field(default="", max_length=500)
    effect: Effect
    priority: int = Field(default=100, ge=0, le=10_000,
                          description="Lower runs first; only orders rules with the same effect.")
    enabled: bool = True
    match: RuleMatch = Field(default_factory=RuleMatch)


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_effect: Effect = "deny"
    rules: list[PolicyRule] = Field(default_factory=list, max_length=200)

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, rules: list[PolicyRule]) -> list[PolicyRule]:
        seen: set[str] = set()
        for rule in rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id '{rule.id}'")
            seen.add(rule.id)
        return rules


class PolicyContext(BaseModel):
    """Facts about the execution the policy may use. Deliberately contains nothing the agent controls
    except the requested tool and arguments, and nothing from scenario expectations."""

    model_config = ConfigDict(frozen=True)

    environment: str
    scenario_id: str
    scenario_tags: tuple[str, ...] = ()
    execution_id: str = ""


class MatchedRule(BaseModel):
    rule_id: str
    effect: Effect
    priority: int
    description: str = ""


class Decision(BaseModel):
    outcome: Effect
    reason: str
    deciding_rule: str
    matched_rules: list[MatchedRule]
    policy_id: str
    policy_version: int
    trace: list[str]
