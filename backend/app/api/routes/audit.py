from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import PageParams
from app.core.db import get_read_session
from app.repositories.queries import decisions_query, events_query, paginate
from app.schemas.common import Page
from app.schemas.resources import DecisionOut, EventOut

router = APIRouter(prefix="/audit", tags=["audit"])
ReadSession = Annotated[Session, Depends(get_read_session)]


@router.get("/events", response_model=Page[EventOut], summary="Search audit events across executions")
def search_events(
    session: ReadSession,
    page: PageParams,
    execution_id: Annotated[str | None, Query(max_length=40)] = None,
    event_type: Annotated[str | None, Query(max_length=48, description="Exact type, or a prefix ending in '.'")] = None,
    tool_id: Annotated[str | None, Query(max_length=80)] = None,
    outcome: Annotated[str | None, Query(max_length=40)] = None,
) -> Page[EventOut]:
    rows, total = paginate(
        session,
        events_query(execution_id=execution_id, event_type=event_type, tool_id=tool_id, outcome=outcome),
        page.limit,
        page.offset,
    )
    return Page(items=[EventOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/decisions", response_model=Page[DecisionOut], summary="Search policy decision history")
def search_decisions(
    session: ReadSession,
    page: PageParams,
    outcome: Annotated[str | None, Query(pattern="^(allow|deny|require_approval)$")] = None,
    tool_id: Annotated[str | None, Query(max_length=80)] = None,
) -> Page[DecisionOut]:
    rows, total = paginate(session, decisions_query(outcome=outcome, tool_id=tool_id), page.limit, page.offset)
    return Page(items=[DecisionOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)
