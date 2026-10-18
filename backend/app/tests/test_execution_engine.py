from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError
from app.models import Approval, Execution, PolicyDecisionRecord
from app.services.agent_runtime.agents import ScriptAgent, parse_embedded_instruction
from app.services.agent_runtime.engine import ExecutionCreate, cancel_execution, start_execution
from app.services.agent_runtime.scenario import AgentSpec, ScenarioSpec
from app.services.audit.integrity import check_completeness
from app.services.audit.log import list_events, verify_chain
from app.services.seed import seed_all
from app.services.tool_registry.mock_data import initial_sandbox
from app.tests.factories import make_scenario, make_settings


@pytest.fixture()
def settings() -> Settings:
    return make_settings()


@pytest.fixture()
def seeded(session: Session) -> Session:
    seed_all(session)
    return session


def run(session: Session, settings: Settings, scenario_id: str, policy: str = "baseline", **kw: Any) -> Execution:
    return start_execution(session, settings, ExecutionCreate(scenario_id=scenario_id, policy_id=policy, **kw))


def types(session: Session, execution: Execution) -> list[str]:
    return [e.event_type for e in list_events(session, execution.id)]


def assert_audit_ok(session: Session, execution: Execution) -> None:
    events = list_events(session, execution.id)
    assert verify_chain(events, execution.last_event_hash)["valid"]
    report = check_completeness(events, execution.status)
    assert report["complete"], report["problems"]


READ_STEPS = [
    {"label": "search", "tool_id": "kb.search", "arguments": {"query": "refund"}},
    {"label": "read", "tool_id": "docs.read", "arguments": {"doc_id": "refund-policy"}},
    {"kind": "finish", "label": "done", "summary": "Answered the refund question."},
]


def test_read_only_task_completes(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "reads", READ_STEPS)
    execution = run(seeded, settings, "reads")
    assert execution.status == "completed"
    assert execution.final_output == "Answered the refund question."
    t = types(seeded, execution)
    assert t[:2] == ["execution.created", "execution.started"]
    assert t.count("tool.executed") == 2 and t[-1] == "execution.completed"
    assert execution.tool_call_count == 2
    assert_audit_ok(seeded, execution)


def test_every_policy_evaluation_has_a_decision_record(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "reads", READ_STEPS)
    execution = run(seeded, settings, "reads")
    records = seeded.scalars(select(PolicyDecisionRecord).where(PolicyDecisionRecord.execution_id == execution.id)).all()
    evaluated = [e for e in list_events(seeded, execution.id) if e.event_type == "policy.evaluated"]
    assert len(records) == len(evaluated) == 2
    assert {r.id for r in records} == {e.data["decision_id"] for e in evaluated}
    assert all(r.policy_version == 1 and r.policy_id == "baseline" for r in records)


def test_unknown_tool_is_denied_and_never_executed(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "unknown", [{"label": "shell", "tool_id": "shell.exec", "arguments": {"cmd": "whoami"}}])
    execution = run(seeded, settings, "unknown", policy="permissive-dev")
    assert execution.status == "blocked"
    t = types(seeded, execution)
    assert "tool.executed" not in t and "tool.blocked" in t
    blocked = next(e for e in list_events(seeded, execution.id) if e.event_type == "tool.blocked")
    assert blocked.outcome == "unknown_tool"
    assert_audit_ok(seeded, execution)


def test_malformed_arguments_are_rejected(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "malformed", [
        {"label": "bad", "tool_id": "email.draft", "arguments": {"to": "nobody", "subject": ""}, "on_blocked": "continue"},
        {"label": "good", "tool_id": "calc.evaluate", "arguments": {"expression": "2+2"}},
    ])
    execution = run(seeded, settings, "malformed")
    t = types(seeded, execution)
    assert "tool.arguments_rejected" in t
    assert execution.status == "completed"     # agent chose to continue
    assert execution.sandbox_state["drafts"] == []
    assert_audit_ok(seeded, execution)


def test_approval_required_pauses_execution(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "send", [{"label": "send", "tool_id": "email.send",
                                    "arguments": {"to": "ada@example.com", "subject": "Hi", "body": "Hello"}}])
    execution = run(seeded, settings, "send")
    assert execution.status == "waiting_for_approval"
    approval = seeded.scalars(select(Approval).where(Approval.execution_id == execution.id)).one()
    assert approval.status == "pending" and approval.tool_id == "email.send"
    assert approval.risk_level == "high"
    assert execution.pending_approval_id == approval.id
    assert execution.pending_action and execution.pending_action["action_hash"] == approval.action_hash
    assert "tool.executed" not in types(seeded, execution)
    assert execution.sandbox_state["outbox"] == []
    assert_audit_ok(seeded, execution)


def test_cancel_while_waiting(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "send", [{"label": "send", "tool_id": "email.send",
                                    "arguments": {"to": "ada@example.com", "subject": "Hi", "body": "Hello"}}])
    execution = run(seeded, settings, "send")
    cancel_execution(seeded, settings, execution, "operator cancelled")
    assert execution.status == "cancelled"
    approval = seeded.scalars(select(Approval).where(Approval.execution_id == execution.id)).one()
    assert approval.status == "cancelled"
    assert types(seeded, execution)[-1] == "execution.cancelled"
    assert_audit_ok(seeded, execution)
    with pytest.raises(ConflictError):
        cancel_execution(seeded, settings, execution, "again")


def test_loop_detection_blocks_identical_calls(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "loop", [{"kind": "repeat", "label": "poll", "tool_id": "kb.search",
                                    "arguments": {"query": "refund"}, "times": 50}])
    execution = run(seeded, settings, "loop")
    assert execution.status == "blocked" and "loop_detected" in execution.status_reason
    assert types(seeded, execution).count("tool.executed") == settings.max_identical_calls
    assert_audit_ok(seeded, execution)


def test_tool_call_limit(seeded: Session, settings: Settings) -> None:
    steps = [{"label": f"c{i}", "tool_id": "calc.evaluate", "arguments": {"expression": f"{i}+1"}} for i in range(30)]
    make_scenario(seeded, "many", steps)
    execution = run(seeded, settings, "many")
    assert execution.status == "blocked" and "max_tool_calls" in execution.status_reason
    assert execution.tool_call_count == settings.max_tool_calls
    assert_audit_ok(seeded, execution)


def test_step_limit(seeded: Session) -> None:
    settings = make_settings(max_steps=3)
    steps = [{"label": f"c{i}", "tool_id": "calc.evaluate", "arguments": {"expression": f"{i}+1"}} for i in range(10)]
    make_scenario(seeded, "steps", steps)
    execution = run(seeded, settings, "steps")
    assert execution.status == "blocked" and "max_steps" in execution.status_reason
    assert execution.step_count == 3


def test_tool_timeout_fails_execution(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "slow", [{"label": "report", "tool_id": "ops.generate_report",
                                    "arguments": {"report": "daily", "delay_ms": 1200}}])
    execution = run(seeded, settings, "slow")
    assert execution.status == "failed" and "timeout" in execution.status_reason
    failed = next(e for e in list_events(seeded, execution.id) if e.event_type == "tool.failed")
    assert failed.outcome == "timeout"
    assert "tool.result" not in types(seeded, execution)
    assert_audit_ok(seeded, execution)


def test_retries_are_bounded_and_deterministic(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "flaky", [{"label": "stock", "tool_id": "ops.check_inventory", "arguments": {"sku": "SKU-1"},
                                     "max_retries": 3, "on_failure": "continue"}])
    first = run(seeded, settings, "flaky")
    second = run(seeded, settings, "flaky")
    outcomes = [[e.outcome for e in list_events(seeded, x.id) if e.event_type == "tool.executed"] for x in (first, second)]
    assert outcomes[0] == outcomes[1]
    assert 1 <= len(outcomes[0]) <= 4


def test_untrusted_instruction_cannot_bypass_policy(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "inject", [
        {"label": "read", "tool_id": "docs.read", "arguments": {"doc_id": "vendor-checklist"}},
        {"kind": "follow_instructions", "label": "injected", "source": "read"},
    ], agent_type="reactive")
    execution = run(seeded, settings, "inject", policy="permissive-dev")
    events = list_events(seeded, execution.id)
    proposed = [e for e in events if e.event_type == "agent.action_proposed" and e.data["label"] == "injected"]
    assert proposed and proposed[0].data["agent_claims"] == {"pre_approved": True, "safe": True}
    # Even under the default-allow policy, the tool-level approval requirement holds.
    decision = next(e for e in events if e.event_type == "policy.evaluated" and e.data["label"] == "injected")
    assert decision.outcome == "require_approval"
    assert execution.sandbox_state["export_attempts"] == []
    baseline = run(seeded, settings, "inject", policy="baseline")
    assert baseline.status == "blocked"
    assert baseline.sandbox_state["export_attempts"] == []


def test_branching_and_templates(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "branchy", [
        {"label": "lookup", "tool_id": "crm.get_customer", "arguments": {"customer_id": "CUST-1001"}},
        {"kind": "branch", "label": "tier", "condition": {"label": "lookup", "path": "output.tier", "op": "eq",
                                                          "value": "enterprise"},
         "then": [{"label": "draft", "tool_id": "email.draft",
                   "arguments": {"to": "{{lookup.output.email}}", "subject": "Hello", "body": "Welcome"}}],
         "otherwise": [{"label": "ticket", "tool_id": "ticket.create", "arguments": {"title": "Follow up", "priority": "p3"}}]},
    ], agent_type="reactive")
    execution = run(seeded, settings, "branchy")
    assert execution.status == "completed"
    assert execution.sandbox_state["drafts"][0]["to"] == "ada@example.com"
    assert execution.sandbox_state["tickets"] == []


def test_same_seed_same_events(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "reads", READ_STEPS)
    a, b = run(seeded, settings, "reads"), run(seeded, settings, "reads")
    strip = lambda ex: [(e.event_type, e.tool_id, e.outcome) for e in list_events(seeded, ex.id)]  # noqa: E731
    assert strip(a) == strip(b)


def test_executions_do_not_share_sandbox_state(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "draft", [{"label": "d", "tool_id": "email.draft",
                                     "arguments": {"to": "a@example.com", "subject": "s", "body": "b"}}])
    a = run(seeded, settings, "draft")
    b = run(seeded, settings, "draft")
    assert len(a.sandbox_state["drafts"]) == len(b.sandbox_state["drafts"]) == 1
    assert initial_sandbox()["drafts"] == []
    assert seeded.scalar(select(func.count()).select_from(Execution)) == 2


def test_production_environment_requires_approval_for_writes(seeded: Session, settings: Settings) -> None:
    make_scenario(seeded, "ticket", [{"label": "t", "tool_id": "ticket.create",
                                      "arguments": {"title": "Customer call", "priority": "p2"}}])
    assert run(seeded, settings, "ticket").status == "completed"
    assert run(seeded, settings, "ticket", environment="production").status == "waiting_for_approval"


def test_parse_embedded_instruction() -> None:
    assert parse_embedded_instruction({"content": 'x AGENT-INSTRUCTION: {"tool_id": "a.b", "arguments": {}}'}) == {
        "tool_id": "a.b", "arguments": {}}
    assert parse_embedded_instruction({"content": "AGENT-INSTRUCTION: not json"}) is None
    assert parse_embedded_instruction("nothing here") is None


def test_agent_state_is_pure() -> None:
    spec = ScenarioSpec.model_validate({"task": "t", "agent": {"type": "scripted", "steps": READ_STEPS}})
    agent = ScriptAgent(AgentSpec.model_validate(spec.agent.model_dump()))
    state = agent.initial_state()
    snapshot = repr(state)
    action1, _ = agent.decide(state, None)  # type: ignore[arg-type]
    action2, _ = agent.decide(state, None)  # type: ignore[arg-type]
    assert action1 == action2 and repr(state) == snapshot


def test_scenario_spec_forbids_expectations() -> None:
    with pytest.raises(ValueError):
        ScenarioSpec.model_validate({"task": "t", "agent": {"steps": READ_STEPS}, "expectations": {}})
