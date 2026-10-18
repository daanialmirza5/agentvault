"""Data retention: purge finished executions older than a cutoff.

Audit rows are protected by database triggers. A purge first records a ``retention_purges`` row
for the execution (which is what the triggers check), then deletes that execution's events,
decisions, approvals and replays. The purge record itself is kept, so the deletion is auditable.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.utils import new_id, utcnow
from app.models import Approval, AuditEvent, Execution, PolicyDecisionRecord, Replay, RetentionPurge
from app.models.execution import TERMINAL_STATUSES


def purge_older_than(session: Session, days: int, *, dry_run: bool = False) -> dict[str, Any]:
    if days <= 0:
        return {"purged": 0, "execution_ids": [], "dry_run": dry_run, "note": "retention disabled (days <= 0)"}
    cutoff = utcnow() - timedelta(days=days)
    candidates = session.scalars(
        select(Execution.id).where(Execution.status.in_(sorted(TERMINAL_STATUSES)), Execution.finished_at < cutoff)
    ).all()
    if dry_run:
        return {"purged": 0, "would_purge": len(candidates), "execution_ids": list(candidates), "dry_run": True}
    for execution_id in candidates:
        count = session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.execution_id == execution_id)
        )
        session.add(
            RetentionPurge(
                id=new_id("pur"),
                execution_id=execution_id,
                event_count=count or 0,
                reason=f"retention policy: finished more than {days} days ago",
            )
        )
        session.flush()
        # Bulk deletes bypass ORM append-only guards; the DB triggers allow them only after the purge row exists.
        session.execute(delete(AuditEvent).where(AuditEvent.execution_id == execution_id))
        session.execute(delete(PolicyDecisionRecord).where(PolicyDecisionRecord.execution_id == execution_id))
        session.execute(delete(Approval).where(Approval.execution_id == execution_id))
        session.execute(delete(Replay).where(Replay.execution_id == execution_id))
        session.execute(delete(Execution).where(Execution.id == execution_id))
        session.commit()
    return {"purged": len(candidates), "execution_ids": list(candidates), "dry_run": False}
