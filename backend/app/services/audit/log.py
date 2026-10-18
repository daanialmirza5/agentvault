"""Append-only, hash-chained audit log.

Each event stores ``prev_hash`` and ``hash = sha256(prev_hash || canonical(event))`` where the
canonical form covers the execution ID, sequence number, type, tool, policy version, outcome,
data and timestamp. Guarantees and limits:

* Detects edits, deletions, insertions and re-ordering made *without* recomputing the chain.
* Does NOT stop someone with write access to the database file from rewriting events and
  recomputing every hash. Anchoring ``last_event_hash`` externally (e.g. exporting reports
  or shipping hashes to a separate store) is required for that; it is not implemented here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.utils import GENESIS_HASH, canonical_json, new_id, sha256_hex, utcnow
from app.models import AuditEvent, Execution
from app.services.audit.events import EventRecord


def normalise(data: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON so the hashed form equals what is read back from the database."""
    result: dict[str, Any] = json.loads(canonical_json(data))
    return result


def event_hash(
    prev_hash: str,
    *,
    execution_id: str,
    sequence: int,
    event_type: str,
    tool_id: str | None,
    policy_version: str | None,
    outcome: str,
    data: dict[str, Any],
    timestamp: datetime,
) -> str:
    body = canonical_json(
        {
            "execution_id": execution_id,
            "sequence": sequence,
            "event_type": event_type,
            "tool_id": tool_id,
            "policy_version": policy_version,
            "outcome": outcome,
            "data": data,
            "timestamp": timestamp.isoformat(),
        }
    )
    return sha256_hex(prev_hash + body)


def append_event(session: Session, execution: Execution, record: EventRecord) -> AuditEvent:
    """Append one event. Sequence numbers come from the execution row, which is only ever
    advanced by the single writer currently holding that execution (see approval locking)."""
    sequence = execution.event_count + 1
    data = normalise(record.data)
    timestamp = utcnow()
    digest = event_hash(
        execution.last_event_hash,
        execution_id=execution.id,
        sequence=sequence,
        event_type=str(record.event_type),
        tool_id=record.tool_id,
        policy_version=record.policy_version,
        outcome=record.outcome,
        data=data,
        timestamp=timestamp,
    )
    event = AuditEvent(
        id=new_id("evt"),
        execution_id=execution.id,
        sequence=sequence,
        event_type=str(record.event_type),
        tool_id=record.tool_id,
        policy_version=record.policy_version,
        outcome=record.outcome,
        data=data,
        timestamp=timestamp,
        prev_hash=execution.last_event_hash,
        hash=digest,
    )
    session.add(event)
    execution.event_count = sequence
    execution.last_event_hash = digest
    execution.updated_at = timestamp
    session.flush()
    return event


def list_events(session: Session, execution_id: str) -> list[AuditEvent]:
    return list(
        session.scalars(select(AuditEvent).where(AuditEvent.execution_id == execution_id).order_by(AuditEvent.sequence))
    )


def verify_chain(events: Sequence[AuditEvent], expected_head: str | None = None) -> dict[str, Any]:
    problems: list[str] = []
    prev = GENESIS_HASH
    for index, event in enumerate(events, start=1):
        if event.sequence != index:
            problems.append(f"sequence gap or reorder at position {index} (found {event.sequence})")
        if event.prev_hash != prev:
            problems.append(f"event {event.sequence}: prev_hash does not link to the previous event")
        recomputed = event_hash(
            event.prev_hash,
            execution_id=event.execution_id,
            sequence=event.sequence,
            event_type=event.event_type,
            tool_id=event.tool_id,
            policy_version=event.policy_version,
            outcome=event.outcome,
            data=event.data,
            timestamp=event.timestamp,
        )
        if recomputed != event.hash:
            problems.append(f"event {event.sequence}: content hash mismatch")
        prev = event.hash
    if expected_head is not None and prev != expected_head:
        problems.append("chain head does not match the execution's recorded last_event_hash")
    return {"valid": not problems, "event_count": len(events), "head": prev, "problems": problems}
