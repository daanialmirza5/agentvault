from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.migrations import schema_is_current
from app.core.utils import GENESIS_HASH, new_id
from app.models import AuditEvent, Execution
from app.models.audit import AppendOnlyViolation


def _execution(session: Session) -> Execution:
    execution = Execution(
        id=new_id("exe"),
        scenario_id="s",
        scenario_version=1,
        policy_id="p",
        policy_version=1,
        agent_type="scripted",
        environment="sandbox",
        seed=1,
        status="pending",
        task="t",
        spec={},
        agent_state={},
        sandbox_state={},
        initial_sandbox_hash="x",
        last_event_hash=GENESIS_HASH,
    )
    session.add(execution)
    session.flush()
    return execution


def _event(execution_id: str, seq: int) -> AuditEvent:
    return AuditEvent(
        id=new_id("evt"),
        execution_id=execution_id,
        sequence=seq,
        event_type="execution.created",
        outcome="ok",
        data={},
        timestamp=datetime.now(UTC),
        prev_hash=GENESIS_HASH,
        hash="h" * 64,
    )


def test_migrations_reach_head(engine: Engine) -> None:
    assert schema_is_current(engine)


def test_datetimes_round_trip_as_utc(session: Session) -> None:
    execution = _execution(session)
    session.commit()
    session.expire_all()
    loaded = session.get(Execution, execution.id)
    assert loaded is not None and loaded.created_at.tzinfo is UTC


def test_orm_refuses_to_update_audit_events(session: Session) -> None:
    execution = _execution(session)
    event = _event(execution.id, 1)
    session.add(event)
    session.commit()
    event.outcome = "tampered"
    with pytest.raises(AppendOnlyViolation):
        session.flush()


def test_database_trigger_blocks_raw_update_and_delete(session: Session) -> None:
    execution = _execution(session)
    session.add(_event(execution.id, 1))
    session.commit()
    with pytest.raises(Exception, match="append-only"):
        session.execute(text("UPDATE audit_events SET outcome = 'x'"))
    session.rollback()
    with pytest.raises(Exception, match="retention purge"):
        session.execute(text("DELETE FROM audit_events"))
    session.rollback()


def test_sequence_numbers_are_unique_per_execution(session: Session) -> None:
    execution = _execution(session)
    session.add(_event(execution.id, 1))
    session.add(_event(execution.id, 1))
    with pytest.raises(IntegrityError):
        session.commit()
