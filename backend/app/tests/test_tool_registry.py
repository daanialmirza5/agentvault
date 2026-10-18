from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.services.tool_registry.builtin_tools import BUILTIN_TOOLS
from app.services.tool_registry.executor import run_tool
from app.services.tool_registry.implementations import IMPLEMENTATIONS
from app.services.tool_registry.mock_data import initial_sandbox
from app.services.tool_registry.registry import (
    ToolCreate,
    ToolRegistry,
    ToolSpec,
    register_tool,
    upsert_builtin_tools,
)


@pytest.fixture()
def registry(session: Session) -> ToolRegistry:
    upsert_builtin_tools(session, BUILTIN_TOOLS)
    session.commit()
    return ToolRegistry.from_session(session)


def _custom(**overrides: object) -> ToolCreate:
    data: dict[str, object] = {
        "tool_id": "weather.lookup",
        "name": "Weather",
        "category": "info",
        "risk_level": "low",
        "mutating": False,
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        "mock_config": {"response": {"forecast": "sunny"}},
    }
    data.update(overrides)
    return ToolCreate.model_validate(data)


def test_builtin_tools_declare_every_required_attribute(registry: ToolRegistry) -> None:
    assert len(registry.all()) == len(BUILTIN_TOOLS)
    for spec in registry.all():
        assert spec.implementation in IMPLEMENTATIONS
        assert spec.input_schema["additionalProperties"] is False
        assert spec.timeout_seconds > 0


def test_seeding_is_idempotent(session: Session, registry: ToolRegistry) -> None:
    assert upsert_builtin_tools(session, BUILTIN_TOOLS) == 0


def test_valid_arguments_pass(registry: ToolRegistry) -> None:
    spec = registry.get("email.send")
    assert spec is not None
    assert registry.validate_arguments(spec, {"to": "a@example.com", "subject": "Hi", "body": "Hello"}) == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"to": "a@example.com", "subject": "Hi"},  # missing field
        {"to": "a@example.com", "subject": "Hi", "body": "x", "bcc": "x@y.z"},  # unknown field
        {"to": "not-an-email", "subject": "Hi", "body": "x"},  # format
        {"to": "a@example.com", "subject": "", "body": "x"},  # minLength
        ["not", "an", "object"],  # wrong type
    ],
)
def test_malformed_arguments_are_rejected(registry: ToolRegistry, arguments: object) -> None:
    spec = registry.get("email.send")
    assert spec is not None
    assert registry.validate_arguments(spec, arguments)


def test_unknown_tool_is_not_resolved(registry: ToolRegistry) -> None:
    assert registry.get("shell.exec") is None


def test_register_custom_tool_and_latest_version_wins(session: Session, registry: ToolRegistry) -> None:
    register_tool(session, _custom())
    register_tool(session, _custom(version="1.2.0", mock_config={"response": {"forecast": "rain"}}))
    session.commit()
    spec = ToolRegistry.from_session(session).get("weather.lookup")
    assert spec is not None and spec.version == "1.2.0" and not spec.builtin


def test_duplicate_version_and_builtin_shadowing_rejected(session: Session, registry: ToolRegistry) -> None:
    register_tool(session, _custom())
    with pytest.raises(ConflictError):
        register_tool(session, _custom())
    with pytest.raises(ConflictError):
        register_tool(session, _custom(tool_id="email.send", version="9.0.0"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"implementation": "mock.email.send"},  # cannot bind to privileged mocks
        {"input_schema": {"type": "object"}},  # must forbid extra properties
        {"input_schema": {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "nope"}}}},
        {"tool_id": "Bad Id"},
    ],
)
def test_invalid_custom_tools_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _custom(**overrides)


def test_tool_runs_against_copy_of_sandbox(registry: ToolRegistry) -> None:
    spec = registry.get("email.send")
    assert spec is not None
    sandbox = initial_sandbox()
    result = run_tool(spec, {"to": "a@example.com", "subject": "s", "body": "b"}, sandbox, seed=1, step=1)
    assert result.status == "succeeded"
    assert sandbox["outbox"] == []  # original untouched
    assert len(result.sandbox["outbox"]) == 1


def test_tool_timeout_is_enforced_and_leaves_sandbox_unchanged(registry: ToolRegistry) -> None:
    spec = registry.get("ops.generate_report")
    assert spec is not None
    sandbox = initial_sandbox()
    result = run_tool(spec, {"report": "daily", "delay_ms": 1500}, sandbox, seed=1, step=1)
    assert result.status == "timeout"
    assert result.sandbox is sandbox


def test_protected_record_refused_by_mock_backend(registry: ToolRegistry) -> None:
    spec = registry.get("crm.update_record")
    assert spec is not None
    result = run_tool(
        spec, {"customer_id": "CUST-0001", "field": "status", "value": "closed"}, initial_sandbox(), seed=1, step=1
    )
    assert result.status == "failed" and "protected" in result.error


def test_seeded_failures_are_deterministic(registry: ToolRegistry) -> None:
    spec = registry.get("ops.check_inventory")
    assert spec is not None
    runs = [
        [run_tool(spec, {"sku": "SKU-1"}, initial_sandbox(), seed=7, step=s).status for s in range(1, 9)]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
    assert {"succeeded", "failed"} <= set(runs[0])


@pytest.mark.parametrize("expression", ["__import__('os')", "a + 1", "(1).real", "2 ** 1000", "[1, 2]"])
def test_calculator_rejects_non_arithmetic(registry: ToolRegistry, expression: str) -> None:
    spec = registry.get("calc.evaluate")
    assert spec is not None
    assert run_tool(spec, {"expression": expression}, initial_sandbox(), seed=1, step=1).status == "failed"


def test_calculator_evaluates_arithmetic(registry: ToolRegistry) -> None:
    spec = registry.get("calc.evaluate")
    assert spec is not None
    result = run_tool(spec, {"expression": "(1200 * 0.15) + 3"}, initial_sandbox(), seed=1, step=1)
    assert result.output == {"result": 183.0}


def test_toolspec_operation() -> None:
    spec = ToolSpec(
        tool_id="a.b",
        version="1.0.0",
        name="n",
        description="",
        category="c",
        risk_level="low",
        mutating=True,
        requires_approval=False,
        timeout_seconds=1,
        implementation="mock.echo",
        input_schema={},
        output_schema={},
    )
    assert spec.operation == "write"
