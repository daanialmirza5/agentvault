from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams, SettingsDep
from app.core.db import get_read_session, get_session
from app.core.errors import NotFoundError
from app.models import Replay
from app.repositories.queries import paginate
from app.schemas.common import Page
from app.schemas.resources import ReplayOut
from app.services.replay.service import CompareRequest, ReplayCreate, compare_executions, create_replay

router = APIRouter(prefix="/replays", tags=["replay"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


@router.post(
    "",
    response_model=ReplayOut,
    status_code=201,
    summary="Replay an execution (recorded timeline, or isolated simulation under any policy version)",
)
def create(payload: ReplayCreate, session: WriteSession, settings: SettingsDep, _: Operator) -> ReplayOut:
    return ReplayOut.model_validate(create_replay(session, settings, payload))


@router.post("/compare", summary="Compare two recorded executions and locate the first divergent event")
def compare(payload: CompareRequest, session: ReadSession) -> dict[str, Any]:
    return compare_executions(session, payload)


@router.get("", response_model=Page[ReplayOut], summary="List replays")
def list_replays(
    session: ReadSession, page: PageParams, execution_id: Annotated[str | None, Query(max_length=40)] = None
) -> Page[ReplayOut]:
    query = select(Replay)
    if execution_id:
        query = query.where(Replay.execution_id == execution_id)
    rows, total = paginate(session, query.order_by(Replay.created_at.desc()), page.limit, page.offset)
    return Page(items=[ReplayOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/{replay_id}", response_model=ReplayOut)
def get_replay(replay_id: str, session: ReadSession) -> ReplayOut:
    row = session.get(Replay, replay_id)
    if row is None:
        raise NotFoundError(f"replay '{replay_id}' not found")
    return ReplayOut.model_validate(row)
