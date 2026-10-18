from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppendOnlyViolation(RuntimeError):
    """Raised when application code tries to modify or delete an append-only record."""


class AuditEvent(Base):
    """One append-only, hash-chained execution event.

    Rows are protected against UPDATE/DELETE by ORM guards and by SQLite triggers (see the
    initial migration). The hash chain makes *undetected* edits harder for anyone who cannot
    recompute hashes; it does not stop a party with full database write access.
    """

    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("execution_id", "sequence", name="uq_audit_events_execution_seq"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    sequence: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    tool_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    policy_version: Mapped[str | None] = mapped_column(String(80), default=None)
    outcome: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]]
    timestamp: Mapped[datetime] = mapped_column(index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class PolicyDecisionRecord(Base):
    """An immutable record of one policy evaluation (also guarded by triggers)."""

    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(40))
    policy_id: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int]
    tool_id: Mapped[str] = mapped_column(String(80), index=True)
    tool_version: Mapped[str | None] = mapped_column(String(20), default=None)
    arguments_redacted: Mapped[dict[str, Any]]
    action_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(Text)
    matched_rules: Mapped[list[Any]]
    deciding_rule: Mapped[str] = mapped_column(String(80))
    latency_us: Mapped[float]
    created_at: Mapped[datetime]


def _reject_mutation(_mapper: object, _connection: object, target: object) -> None:
    raise AppendOnlyViolation(f"{type(target).__name__} records are append-only")


for _model in (AuditEvent, PolicyDecisionRecord):
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)
