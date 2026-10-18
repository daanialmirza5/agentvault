from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import db
from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.models import Approval, Execution
from app.services.agent_runtime.engine import ExecutionCreate, cancel_execution, start_execution
from app.services.approval_engine.service import ApprovalDecisionRequest, decide, expire_due
from app.services.audit.integrity import check_completeness
from app.services.audit.log import list_events, verify_chain
from app.services.seed import seed_all
from app.tests.factories import make_scenario, make_settings

SEND = {"label": "send", "tool_id": "email.send", "arguments": {"to": "ada@example.com", "subject": "Hi", "body": "Hello"}}


@pytest.fixture()
def settings() -> Settings:
    return make_settings()


@pytest.fixture()
def seeded(session: Session) -> Session:
    seed_all(session)
    make_scenario(session, "send", [SEND, {"kind": "finish", "label": "done", "summary": "Email sent."}])
    make_scenario(session, "send-continue", [{**SEND, "on_blocked": "continue"},
                                             {"label": "draft", "tool_id": "email.draft",
                                              "arguments": {"to": "ada@example.com", "subject": "Hi", "body": "x"}}])
    return session


def pause(session: Session, settings: Settings, scenario: str = "send") -> tuple[Execution, Approval]:
    execution = start_execution(session, settings, ExecutionCreate(scenario_id=scenario))
    approval = session.scalars(select(Approval).where(Approval.execution_id == execution.id)).one()
    return execution, approval


def body(approval: Approval, **kw: str) -> ApprovalDecisionRequest:
    return ApprovalDecisionRequest(execution_id=kw.get("execution_id", approval.execution_id),
                                   action_hash=kw.get("action_hash", approval.action_hash))


def event_types(session: Session, execution_id: str) -> list[str]:
    return [e.event_type for e in list_events(session, execution_id)]


def audit_ok(session: Session, execution: Execution) -> None:
    events = list_events(session, execution.id)
    assert verify_chain(events, execution.last_event_hash)["valid"]
    assert check_completeness(events, execution.status)["complete"]


def test_approve_executes_exactly_the_pending_action(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings)
    approval, execution, repeat = decide(seeded, settings, approval.id, "approve", body(approval), operator="alice")
    assert not repeat
    assert approval.status == "approved" and approval.decided_by == "alice" and approval.consumed_at is not None
    assert execution.status == "completed"
    assert execution.sandbox_state["outbox"][0]["to"] == "ada@example.com"
    t = event_types(seeded, execution.id)
    assert t.index("approval.requested") < t.index("approval.granted") < t.index("tool.executed")
    audit_ok(seeded, execution)


def test_rejected_action_is_never_executed(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings)
    _, execution, _ = decide(seeded, settings, approval.id, "reject", body(approval), operator="alice")
    assert execution.status == "blocked"
    assert execution.sandbox_state["outbox"] == []
    t = event_types(seeded, execution.id)
    assert "approval.rejected" in t and "tool.executed" not in t
    audit_ok(seeded, execution)


def test_rejection_lets_agent_continue_when_configured(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings, "send-continue")
    _, execution, _ = decide(seeded, settings, approval.id, "reject", body(approval), operator="alice")
    assert execution.status == "completed"
    assert execution.sandbox_state["outbox"] == [] and len(execution.sandbox_state["drafts"]) == 1


def test_same_decision_twice_is_idempotent_and_executes_once(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings)
    decide(seeded, settings, approval.id, "approve", body(approval), operator="alice")
    _, execution, repeat = decide(seeded, settings, approval.id, "approve", body(approval), operator="alice")
    assert repeat
    assert event_types(seeded, execution.id).count("tool.executed") == 1
    with pytest.raises(ConflictError) as exc:
        decide(seeded, settings, approval.id, "reject", body(approval), operator="bob")
    assert exc.value.code == "approval_approved"


def test_wrong_execution_binding_refused_and_recorded(seeded: Session, settings: Settings) -> None:
    exec_a, approval_a = pause(seeded, settings)
    exec_b, _ = pause(seeded, settings)
    with pytest.raises(ConflictError) as exc:
        decide(seeded, settings, approval_a.id, "approve", body(approval_a, execution_id=exec_b.id), operator="mallory")
    assert exc.value.code == "approval_binding_mismatch"
    seeded.refresh(exec_a)
    assert exec_a.status == "waiting_for_approval"
    assert "approval.binding_mismatch" in event_types(seeded, exec_a.id)
    assert exec_a.sandbox_state["outbox"] == []


def test_tampered_action_hash_refused(seeded: Session, settings: Settings) -> None:
    _, approval = pause(seeded, settings)
    with pytest.raises(ConflictError) as exc:
        decide(seeded, settings, approval.id, "approve", body(approval, action_hash="0" * 64), operator="mallory")
    assert exc.value.code == "approval_binding_mismatch"


def test_approval_of_other_execution_cannot_unlock_this_one(seeded: Session, settings: Settings) -> None:
    """Approving A must never execute anything in B, even though both request the same action."""
    exec_a, approval_a = pause(seeded, settings)
    exec_b, approval_b = pause(seeded, settings)
    assert approval_a.action_hash != approval_b.action_hash
    decide(seeded, settings, approval_a.id, "approve", body(approval_a), operator="alice")
    seeded.refresh(exec_b)
    assert exec_b.status == "waiting_for_approval" and exec_b.sandbox_state["outbox"] == []


def test_expired_approval_cannot_be_used(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings)
    later = approval.expires_at + timedelta(seconds=1)
    with pytest.raises(ConflictError) as exc:
        decide(seeded, settings, approval.id, "approve", body(approval), operator="alice", now=later)
    assert exc.value.code == "approval_expired"
    seeded.refresh(execution)
    seeded.refresh(approval)
    assert approval.status == "expired" and execution.status == "blocked"
    assert execution.sandbox_state["outbox"] == []
    assert "approval.expired" in event_types(seeded, execution.id)
    audit_ok(seeded, execution)


def test_sweep_expires_due_approvals_only(seeded: Session, settings: Settings) -> None:
    _, approval = pause(seeded, settings)
    assert expire_due(seeded, settings) == []
    assert expire_due(seeded, settings, now=approval.expires_at + timedelta(seconds=1)) == [approval.id]


def test_cancelled_execution_approval_cannot_be_approved(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings)
    cancel_execution(seeded, settings, execution, "operator cancelled")
    with pytest.raises(ConflictError):
        decide(seeded, settings, approval.id, "approve", body(approval), operator="alice")
    assert execution.sandbox_state["outbox"] == []


def test_concurrent_approvals_execute_the_action_once(seeded: Session, settings: Settings) -> None:
    execution, approval = pause(seeded, settings)
    request = body(approval)
    seeded.commit()  # release this session's transaction (and its write lock) before the race
    barrier = threading.Barrier(4)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(verdict: str) -> None:
        s = db.session_factory()()
        try:
            barrier.wait()
            _, _, repeat = decide(s, settings, approval.id, verdict, request, operator=f"op-{verdict}")  # type: ignore[arg-type]
            result = "repeat" if repeat else "decided"
        except AppError as exc:
            result = exc.code
        finally:
            s.close()
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=worker, args=(v,)) for v in ("approve", "approve", "approve", "reject")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Every thread must finish with a well-defined outcome (no raw "database is locked" errors).
    assert len(outcomes) == 4, outcomes
    assert set(outcomes) <= {"decided", "repeat", "approval_approved", "approval_rejected"}, outcomes
    assert outcomes.count("decided") == 1, outcomes
    seeded.expire_all()
    final = seeded.get(Execution, execution.id)
    assert final is not None
    executed = event_types(seeded, execution.id).count("tool.executed")
    assert executed in (0, 1)
    assert len(final.sandbox_state["outbox"]) == executed
    audit_ok(seeded, final)
