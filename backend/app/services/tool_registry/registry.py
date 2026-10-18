"""The versioned tool registry: definitions, argument validation and registration."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationFailedError
from app.core.utils import canonical_json, new_id
from app.models import ToolDefinition
from app.services.tool_registry.implementations import GENERIC_IMPLEMENTATIONS, IMPLEMENTATIONS

RiskLevel = Literal["low", "medium", "high", "critical"]
RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
TOOL_ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$"
SEMVER_PATTERN = r"^\d{1,4}\.\d{1,4}\.\d{1,4}$"
MAX_SCHEMA_BYTES = 16 * 1024
_FORMAT_CHECKER = FormatChecker()


class ToolSpec(BaseModel):
    """Immutable, engine-facing view of a registered tool."""

    model_config = ConfigDict(frozen=True)

    tool_id: str
    version: str
    name: str
    description: str
    category: str
    risk_level: RiskLevel
    mutating: bool
    requires_approval: bool
    timeout_seconds: float
    implementation: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    mock_config: dict[str, Any] = Field(default_factory=dict)
    deterministic: bool = True
    sensitive_arguments: list[str] = Field(default_factory=list)
    builtin: bool = False

    @property
    def operation(self) -> Literal["read", "write"]:
        return "write" if self.mutating else "read"


class ToolCreate(BaseModel):
    """Payload for registering a custom tool (bound to a generic mock implementation)."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(pattern=TOOL_ID_PATTERN, max_length=80)
    version: str = Field(default="1.0.0", pattern=SEMVER_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    risk_level: RiskLevel
    mutating: bool
    requires_approval: bool = False
    timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    implementation: str = "mock.static_response"
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    mock_config: dict[str, Any] = Field(default_factory=dict)
    sensitive_arguments: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("implementation")
    @classmethod
    def _generic_only(cls, value: str) -> str:
        if value not in GENERIC_IMPLEMENTATIONS:
            raise ValueError(f"custom tools must use one of {list(GENERIC_IMPLEMENTATIONS)}")
        return value

    @field_validator("input_schema")
    @classmethod
    def _strict_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        _check_schema(value)
        if value.get("type") != "object" or value.get("additionalProperties") is not False:
            raise ValueError('input_schema must be {"type": "object", "additionalProperties": false, ...}')
        return value

    @field_validator("output_schema", "mock_config")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(canonical_json(value)) > MAX_SCHEMA_BYTES:
            raise ValueError("document is too large")
        return value

    @field_validator("output_schema")
    @classmethod
    def _valid_output_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        _check_schema(value)
        return value


def _check_schema(schema: dict[str, Any]) -> None:
    if len(canonical_json(schema)) > MAX_SCHEMA_BYTES:
        raise ValueError("schema is too large")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"invalid JSON Schema: {exc.message}") from exc


def validate_against(schema: dict[str, Any], value: Any) -> list[str]:
    """Return human-readable validation errors (empty list = valid)."""
    validator = Draft202012Validator(schema, format_checker=_FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path))
    out = []
    for err in errors[:10]:
        location = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{location}: {err.message[:200]}")
    return out


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def to_spec(row: ToolDefinition) -> ToolSpec:
    return ToolSpec(
        tool_id=row.tool_id, version=row.version, name=row.name, description=row.description,
        category=row.category, risk_level=row.risk_level,  # type: ignore[arg-type]
        mutating=row.mutating, requires_approval=row.requires_approval, timeout_seconds=row.timeout_seconds,
        implementation=row.implementation, input_schema=row.input_schema, output_schema=row.output_schema,
        mock_config=row.mock_config, deterministic=row.deterministic,
        sensitive_arguments=list(row.sensitive_arguments), builtin=row.builtin,
    )


class ToolRegistry:
    """An in-memory snapshot of the enabled tools (latest version per tool ID)."""

    def __init__(self, tools: Iterable[ToolSpec]) -> None:
        latest: dict[str, ToolSpec] = {}
        for spec in tools:
            current = latest.get(spec.tool_id)
            if current is None or _version_key(spec.version) > _version_key(current.version):
                latest[spec.tool_id] = spec
        self._tools = latest

    @classmethod
    def from_session(cls, session: Session) -> ToolRegistry:
        rows = session.scalars(select(ToolDefinition).where(ToolDefinition.enabled.is_(True))).all()
        return cls(to_spec(r) for r in rows)

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._tools.get(tool_id)

    def all(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.tool_id)

    def tool_ids(self) -> list[str]:
        return sorted(self._tools)

    @staticmethod
    def validate_arguments(spec: ToolSpec, arguments: Any) -> list[str]:
        if not isinstance(arguments, dict):
            return ["(root): arguments must be a JSON object"]
        if len(canonical_json(arguments)) > MAX_SCHEMA_BYTES:
            return ["(root): arguments exceed the 16 KiB limit"]
        return validate_against(spec.input_schema, arguments)


def register_tool(session: Session, payload: ToolCreate) -> ToolDefinition:
    if payload.implementation not in IMPLEMENTATIONS:
        raise ValidationFailedError("unknown implementation")
    existing = session.scalar(
        select(ToolDefinition).where(ToolDefinition.tool_id == payload.tool_id, ToolDefinition.version == payload.version)
    )
    if existing is not None:
        raise ConflictError(f"tool {payload.tool_id}@{payload.version} already exists; bump the version")
    builtin_ids = {r for r in session.scalars(select(ToolDefinition.tool_id).where(ToolDefinition.builtin.is_(True)))}
    if payload.tool_id in builtin_ids:
        raise ConflictError("built-in tool IDs cannot be redefined by custom tools")
    for key in payload.sensitive_arguments:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", key):
            raise ValidationFailedError("sensitive_arguments must be plain property names")
    row = ToolDefinition(
        id=new_id("tool"), builtin=False, enabled=True, deterministic=True,
        **payload.model_dump(),
    )
    session.add(row)
    session.flush()
    return row


def upsert_builtin_tools(session: Session, definitions: Iterable[dict[str, Any]]) -> int:
    created = 0
    for d in definitions:
        exists = session.scalar(
            select(ToolDefinition.id).where(ToolDefinition.tool_id == d["tool_id"], ToolDefinition.version == d["version"])
        )
        if exists:
            continue
        session.add(ToolDefinition(
            id=new_id("tool"), builtin=True, enabled=True,
            mock_config=d.get("mock_config", {}), deterministic=d.get("deterministic", True),
            sensitive_arguments=d.get("sensitive_arguments", []),
            **{k: v for k, v in d.items() if k not in {"mock_config", "deterministic", "sensitive_arguments"}},
        ))
        created += 1
    session.flush()
    return created
