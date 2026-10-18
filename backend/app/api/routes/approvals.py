from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams, SettingsDep
from app.core.db import get_read_session, get_session
from app.core.errors import NotFoundError
from app.models import Approval
from app.schemas.common import Page
from app.schemas.resources import ApprovalDecisionOut, ApprovalOut, ExecutionOut
from app.services.approval_engine.service import (
    ApprovalDecisionRequest,
    Verdict,
    decide,
    expire_due,
    list_approvals,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


@router.get("", response_model=Page[ApprovalOut], summary="Approval queue and history (expires overdue requests first)")
def list_(
    session: WriteSession,
    settings: SettingsDep,
    page: PageParams,
    status: Annotated[str | None, Query(pattern="^(pending|approved|rejected|expired|cancelled)$")] = None,
    execution_id: Annotated[str | None, Query(max_length=40)] = None,
) -> Page[ApprovalOut]:
    expire_due(session, settings)
    rows, total = list_approvals(
        session, status=status, execution_id=execution_id, limit=page.limit, offset=page.offset
    )
    return Page(items=[ApprovalOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: str, session: ReadSession) -> ApprovalOut:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise NotFoundError(f"approval '{approval_id}' not found")
    return ApprovalOut.model_validate(approval)


def _decide(
    verdict: Verdict,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    session: Session,
    settings: SettingsDep,
    operator: str,
) -> ApprovalDecisionOut:
    approval, execution, repeat = decide(session, settings, approval_id, verdict, payload, operator=operator)
    return ApprovalDecisionOut(
        approval=ApprovalOut.model_validate(approval),
        execution=ExecutionOut.model_validate(execution),
        idempotent_repeat=repeat,
    )


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalDecisionOut,
    summary="Approve the exact pending action (body must echo execution_id and action_hash)",
)
def approve(
    approval_id: str, payload: ApprovalDecisionRequest, session: WriteSession, settings: SettingsDep, operator: Operator
) -> ApprovalDecisionOut:
    return _decide("approve", approval_id, payload, session, settings, operator)


@router.post("/{approval_id}/reject", response_model=ApprovalDecisionOut, summary="Reject the pending action")
def reject(
    approval_id: str, payload: ApprovalDecisionRequest, session: WriteSession, settings: SettingsDep, operator: Operator
) -> ApprovalDecisionOut:
    return _decide("reject", approval_id, payload, session, settings, operator)
