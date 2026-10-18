from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams, SettingsDep
from app.core.db import get_read_session, get_session
from app.core.errors import NotFoundError
from app.models import Execution
from app.repositories.queries import decisions_query, events_query, executions_query, paginate
from app.schemas.common import Page
from app.schemas.resources import DecisionOut, EventOut, ExecutionDetailOut, ExecutionOut
from app.services.agent_runtime.engine import ExecutionCreate, cancel_execution, start_execution
from app.services.audit.integrity import check_completeness
from app.services.audit.log import list_events, verify_chain

router = APIRouter(prefix="/executions", tags=["executions"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]
EFFECT_KEYS = ("outbox", "drafts", "tickets", "record_changes", "export_attempts")


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="cancelled by operator", max_length=500)


def _get(session: Session, execution_id: str) -> Execution:
    execution = session.get(Execution, execution_id)
    if execution is None:
        raise NotFoundError(f"execution '{execution_id}' not found")
    return execution


def _detail(execution: Execution) -> ExecutionDetailOut:
    out = ExecutionDetailOut.model_validate(
        {**ExecutionOut.model_validate(execution).model_dump(), "spec": execution.spec, "sandbox_effects": {}}
    )
    out.sandbox_effects = {k: list(execution.sandbox_state.get(k, []))[:50] for k in EFFECT_KEYS}
    return out


@router.post(
    "",
    response_model=ExecutionDetailOut,
    status_code=201,
    summary="Launch a scenario; runs until it completes, fails, is blocked or waits for approval",
)
def launch(payload: ExecutionCreate, session: WriteSession, settings: SettingsDep, _: Operator) -> ExecutionDetailOut:
    execution = start_execution(session, settings, payload)
    return _detail(execution)


@router.get("", response_model=Page[ExecutionOut], summary="Search executions")
def list_executions(
    session: ReadSession,
    page: PageParams,
    status: Annotated[str | None, Query(max_length=24)] = None,
    scenario_id: Annotated[str | None, Query(max_length=80)] = None,
    policy_id: Annotated[str | None, Query(max_length=64)] = None,
    origin: Annotated[str | None, Query(max_length=20)] = None,
    evaluation_id: Annotated[str | None, Query(max_length=40)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> Page[ExecutionOut]:
    rows, total = paginate(
        session,
        executions_query(
            status=status, scenario_id=scenario_id, policy_id=policy_id, origin=origin, evaluation_id=evaluation_id, q=q
        ),
        page.limit,
        page.offset,
    )
    return Page(items=[ExecutionOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/{execution_id}", response_model=ExecutionDetailOut)
def get_execution(execution_id: str, session: ReadSession) -> ExecutionDetailOut:
    return _detail(_get(session, execution_id))


@router.get("/{execution_id}/events", response_model=Page[EventOut], summary="Ordered audit events")
def get_events(
    execution_id: str,
    session: ReadSession,
    event_type: Annotated[str | None, Query(max_length=48)] = None,
    tool_id: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EventOut]:
    _get(session, execution_id)
    rows, total = paginate(
        session, events_query(execution_id=execution_id, event_type=event_type, tool_id=tool_id), limit, offset
    )
    return Page(items=[EventOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{execution_id}/decisions", response_model=list[DecisionOut], summary="Policy decision records")
def get_decisions(execution_id: str, session: ReadSession) -> list[DecisionOut]:
    _get(session, execution_id)
    rows = session.scalars(decisions_query(execution_id=execution_id)).all()
    return sorted((DecisionOut.model_validate(r) for r in rows), key=lambda d: d.created_at)


@router.get("/{execution_id}/audit/verify", summary="Verify the hash chain and audit completeness")
def verify(execution_id: str, session: ReadSession) -> dict[str, Any]:
    execution = _get(session, execution_id)
    events = list_events(session, execution_id)
    return {
        "chain": verify_chain(events, execution.last_event_hash),
        "completeness": check_completeness(events, execution.status),
        "limitations": "Detects modification without hash recomputation. A party with database write access "
        "can rewrite and re-hash events; compare against an exported head hash to detect that.",
    }


@router.post("/{execution_id}/cancel", response_model=ExecutionDetailOut, summary="Cancel a pending/waiting execution")
def cancel(
    execution_id: str,
    session: WriteSession,
    settings: SettingsDep,
    operator: Operator,
    payload: CancelRequest | None = None,
) -> ExecutionDetailOut:
    execution = _get(session, execution_id)
    reason = (payload or CancelRequest()).reason
    return _detail(cancel_execution(session, settings, execution, f"{reason} (by {operator})"))
