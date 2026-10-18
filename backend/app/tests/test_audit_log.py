from __future__ import annotations

import itertools
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.utils import GENESIS_HASH, new_id
from app.models import Execution
from app.services.audit.events import EventRecord, EventType
from app.services.audit.integrity import check_completeness
from app.services.audit.log import append_event, event_hash, list_events, verify_chain


def _execution(session: Session) -> Execution:
    e = Execution(
        id=new_id("exe"),
        scenario_id="s",
        scenario_version=1,
        policy_id="p",
        policy_version=1,
        agent_type="scripted",
        environment="sandbox",
        seed=1,
        status="running",
        task="t",
        spec={},
        agent_state={},
        sandbox_state={},
        initial_sandbox_hash="x",
        last_event_hash=GENESIS_HASH,
    )
    session.add(e)
    session.flush()
    return e


def _write(session: Session, execution: Execution, n: int = 5) -> None:
    append_event(session, execution, EventRecord(EventType.EXECUTION_CREATED, "ok"))
    for i in range(1, n):
        append_event(
            session,
            execution,
            EventRecord(EventType.TOOL_REQUESTED, "ok", {"step": i, "nested": {"x": 1.5}}, tool_id="kb.search"),
        )
    session.commit()


def test_events_are_ordered_and_chained(session: Session) -> None:
    execution = _execution(session)
    _write(session, execution)
    events = list_events(session, execution.id)
    assert [e.sequence for e in events] == [1, 2, 3, 4, 5]
    assert events[0].prev_hash == GENESIS_HASH
    assert all(b.prev_hash == a.hash for a, b in itertools.pairwise(events))
    assert verify_chain(events, execution.last_event_hash)["valid"]


def test_chain_detects_naive_tampering(session: Session) -> None:
    execution = _execution(session)
    _write(session, execution)
    # Simulate an attacker with raw DB access who bypasses the append-only trigger.
    session.execute(text("DROP TRIGGER audit_events_no_update"))
    session.execute(text("UPDATE audit_events SET outcome = 'tampered' WHERE sequence = 3"))
    session.commit()
    session.expire_all()
    result = verify_chain(list_events(session, execution.id), execution.last_event_hash)
    assert not result["valid"]
    assert any("event 3" in p for p in result["problems"])


def test_chain_detects_deleted_event(session: Session) -> None:
    execution = _execution(session)
    _write(session, execution)
    events = list_events(session, execution.id)
    result = verify_chain([e for e in events if e.sequence != 2], execution.last_event_hash)
    assert not result["valid"]


def test_documented_limitation_recomputed_chain_passes_without_external_anchor(session: Session) -> None:
    """If an attacker rewrites an event AND recomputes every later hash, verification against the
    database alone passes. Only an externally anchored head hash would expose it."""
    execution = _execution(session)
    _write(session, execution, n=3)
    original_head = execution.last_event_hash
    session.execute(text("DROP TRIGGER audit_events_no_update"))
    events = list_events(session, execution.id)
    prev = GENESIS_HASH
    forged = []
    for e in events:
        outcome = "forged" if e.sequence == 2 else e.outcome
        h = event_hash(
            prev,
            execution_id=e.execution_id,
            sequence=e.sequence,
            event_type=e.event_type,
            tool_id=e.tool_id,
            policy_version=e.policy_version,
            outcome=outcome,
            data=e.data,
            timestamp=e.timestamp,
        )
        forged.append(
            SimpleNamespace(
                **{
                    **{
                        c: getattr(e, c)
                        for c in (
                            "execution_id",
                            "sequence",
                            "event_type",
                            "tool_id",
                            "policy_version",
                            "data",
                            "timestamp",
                        )
                    },
                    "outcome": outcome,
                    "prev_hash": prev,
                    "hash": h,
                }
            )
        )
        prev = h
    assert verify_chain(forged)["valid"]  # self-consistent forgery
    assert not verify_chain(forged, original_head)["valid"]  # caught by an anchored head


def test_completeness_flags_unauthorised_execution() -> None:
    def ev(seq: int, t: str, outcome: str = "ok", step: int | None = None) -> SimpleNamespace:
        return SimpleNamespace(sequence=seq, event_type=t, outcome=outcome, data={} if step is None else {"step": step})

    good = [
        ev(1, "execution.created"),
        ev(2, "tool.requested", step=1),
        ev(3, "policy.evaluated", "allow", 1),
        ev(4, "tool.executed", step=1),
        ev(5, "execution.completed"),
    ]
    assert check_completeness(good, "completed")["complete"]

    denied_but_ran = [
        ev(1, "execution.created"),
        ev(2, "tool.requested", step=1),
        ev(3, "policy.evaluated", "deny", 1),
        ev(4, "tool.executed", step=1),
        ev(5, "execution.completed"),
    ]
    assert not check_completeness(denied_but_ran, "completed")["complete"]

    approval_skipped = [
        ev(1, "execution.created"),
        ev(2, "tool.requested", step=1),
        ev(3, "policy.evaluated", "require_approval", 1),
        ev(4, "tool.executed", step=1),
        ev(5, "execution.completed"),
    ]
    assert not check_completeness(approval_skipped, "completed")["complete"]

    no_terminal = good[:-1]
    assert not check_completeness(no_terminal, "completed")["complete"]
