"""Human approval workflow.

Safety properties enforced here (and covered by tests):

* **Binding** - a decision must present the approval's ``execution_id`` and ``action_hash``.
  A mismatch is refused and recorded as ``approval.binding_mismatch``, so an approval cannot
  be replayed against another execution or a modified action.
* **Single use / no double execution** - the decision claims the approval with a conditional
  ``UPDATE ... WHERE status='pending'`` inside a ``BEGIN IMMEDIATE`` transaction, and the
  execution with ``WHERE status='waiting_for_approval'``. Concurrent decisions serialize; only
  one can move the execution forward. Repeating the *same* decision is idempotent.
* **Expiry** - a pending approval past ``expires_at`` can no longer be approved; it is marked
  expired and the action is blocked. Expiry is enforced on every decision and by a sweep.
* **Rejection** - a rejected action is never executed; the execution continues or stops
  according to the agent's ``on_blocked`` behaviour.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import write_transaction
from app.core.errors import ConflictError, NotFoundError
from app.core.utils import utcnow
from app.models import Approval, Execution
from app.services.agent_runtime.engine import resume_execution
from app.services.agent_runtime.runner import Resolution
from app.services.audit.events import EventRecord, EventType
from app.services.audit.log import append_event


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(max_length=40, description="Must equal the approval's execution.")
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$", description="Must equal the approval's action hash.")
    note: str = Field(default="", max_length=1000)


Verdict = Literal["approve", "reject"]
_TARGET = {"approve": "approved", "reject": "rejected"}


def list_approvals(
    session: Session, *, status: str | None, execution_id: str | None, limit: int, offset: int
) -> tuple[list[Approval], int]:
    query: Select[Approval] = select(Approval)
    if status:
        query = query.where(Approval.status == status)
    if execution_id:
        query = query.where(Approval.execution_id == execution_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(Approval.created_at.desc()).limit(limit).offset(offset)).all()
    return list(rows), total


def _claim_execution(session: Session, approval: Approval) -> Execution:
    claimed = session.execute(
        update(Execution)
        .where(
            Execution.id == approval.execution_id,
            Execution.status == "waiting_for_approval",
            Execution.pending_approval_id == approval.id,
        )
        .values(status="running")
    ).rowcount  # type: ignore[attr-defined]
    if claimed != 1:
        raise ConflictError("execution is no longer waiting for this approval", code="execution_not_waiting")
    execution = session.get(Execution, approval.execution_id, populate_existing=True)
    assert execution is not None
    return execution


def _transition(session: Session, approval: Approval, status: str, *, by: str | None, note: str, now: datetime) -> None:
    changed = session.execute(
        update(Approval)
        .where(Approval.id == approval.id, Approval.status == "pending")
        .values(status=status, decided_at=now, decided_by=by, decision_note=note)
    ).rowcount  # type: ignore[attr-defined]
    if changed != 1:
        raise ConflictError("approval was decided concurrently", code="approval_already_decided")


def _expire_locked(session: Session, settings: Settings, approval: Approval, now: datetime) -> Execution:
    _transition(session, approval, "expired", by="system", note="expired before a decision", now=now)
    execution = _claim_execution(session, approval)
    session.commit()
    return resume_execution(
        session, settings, execution, Resolution(outcome="expired", approval_id=approval.id, decided_by="system")
    )


def decide(
    session: Session,
    settings: Settings,
    approval_id: str,
    verdict: Verdict,
    request: ApprovalDecisionRequest,
    *,
    operator: str,
    now: datetime | None = None,
) -> tuple[Approval, Execution, bool]:
    """Apply a human decision. Returns (approval, execution, idempotent_repeat)."""
    now = now or utcnow()
    target = _TARGET[verdict]
    with write_transaction(session):
        approval = session.get(Approval, approval_id, populate_existing=True)
        if approval is None:
            raise NotFoundError(f"approval '{approval_id}' not found")
        execution = session.get(Execution, approval.execution_id, populate_existing=True)
        assert execution is not None

        if request.execution_id != approval.execution_id or request.action_hash != approval.action_hash:
            if approval.status == "pending":
                # Safe to append: a waiting execution has no other writer.
                append_event(
                    session,
                    execution,
                    EventRecord(
                        event_type=EventType.APPROVAL_BINDING_MISMATCH,
                        outcome="refused",
                        tool_id=approval.tool_id,
                        policy_version=f"{execution.policy_id}@v{execution.policy_version}",
                        data={
                            "step": approval.step,
                            "approval_id": approval.id,
                            "attempted_verdict": verdict,
                            "presented_execution_id": request.execution_id[:40],
                            "execution_matches": request.execution_id == approval.execution_id,
                            "action_hash_matches": request.action_hash == approval.action_hash,
                            "operator": operator,
                        },
                    ),
                )
                session.commit()
            raise ConflictError(
                "decision does not match the approval's execution and action", code="approval_binding_mismatch"
            )

        if approval.status != "pending":
            if approval.status == target:
                return approval, execution, True
            raise ConflictError(f"approval is already {approval.status}", code=f"approval_{approval.status}")

        if now >= approval.expires_at:
            _expire_locked(session, settings, approval, now)
            raise ConflictError("approval expired before the decision was made", code="approval_expired")

        _transition(session, approval, target, by=operator, note=request.note, now=now)
        execution = _claim_execution(session, approval)
        if verdict == "approve":
            consumed = session.execute(
                update(Approval)
                .where(Approval.id == approval.id, Approval.consumed_at.is_(None))
                .values(consumed_at=now)
            ).rowcount  # type: ignore[attr-defined]
            if consumed != 1:
                raise ConflictError("approval was already used", code="approval_consumed")
    # Lock released; the execution row is claimed (status=running), so no other decision can resume it.
    resolution = Resolution(
        outcome="approved" if verdict == "approve" else "rejected",
        approval_id=approval.id,
        decided_by=operator,
        note=request.note,
    )
    resume_execution(session, settings, execution, resolution)
    session.refresh(approval)
    return approval, execution, False


def expire_due(
    session: Session, settings: Settings, *, now: datetime | None = None, approval_id: str | None = None
) -> list[str]:
    """Expire pending approvals whose deadline has passed and unblock their executions."""
    now = now or utcnow()
    query = select(Approval.id).where(Approval.status == "pending", Approval.expires_at <= now)
    if approval_id:
        query = query.where(Approval.id == approval_id)
    expired: list[str] = []
    for aid in session.scalars(query.limit(200)).all():
        try:
            with write_transaction(session):
                approval = session.get(Approval, aid, populate_existing=True)
                if approval is None or approval.status != "pending":
                    continue
                _expire_locked(session, settings, approval, now)
                expired.append(aid)
        except ConflictError:
            session.rollback()
    return expired
