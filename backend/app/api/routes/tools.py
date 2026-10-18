from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams
from app.core.db import get_read_session, get_session
from app.core.errors import NotFoundError
from app.models import ToolDefinition
from app.repositories.queries import paginate
from app.schemas.common import Page
from app.schemas.resources import ToolOut
from app.services.tool_registry.implementations import IMPLEMENTATION_NOTES
from app.services.tool_registry.registry import ToolCreate, register_tool

router = APIRouter(prefix="/tools", tags=["tools"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


def _out(row: ToolDefinition) -> ToolOut:
    out = ToolOut.model_validate(row)
    out.implementation_notes = IMPLEMENTATION_NOTES.get(row.implementation, "")
    return out


@router.get("", response_model=Page[ToolOut], summary="List registered tools (all versions)")
def list_tools(
    session: ReadSession,
    page: PageParams,
    category: Annotated[str | None, Query(max_length=40)] = None,
    risk_level: Annotated[str | None, Query(max_length=16)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> Page[ToolOut]:
    query = select(ToolDefinition)
    if category:
        query = query.where(ToolDefinition.category == category)
    if risk_level:
        query = query.where(ToolDefinition.risk_level == risk_level)
    if q:
        query = query.where(ToolDefinition.tool_id.like(f"%{q}%") | ToolDefinition.name.like(f"%{q}%"))
    rows, total = paginate(
        session, query.order_by(ToolDefinition.tool_id, ToolDefinition.version), page.limit, page.offset
    )
    return Page(items=[_out(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/{tool_id}", response_model=list[ToolOut], summary="All versions of one tool, newest first")
def get_tool(tool_id: str, session: ReadSession) -> list[ToolOut]:
    rows = session.scalars(select(ToolDefinition).where(ToolDefinition.tool_id == tool_id)).all()
    if not rows:
        raise NotFoundError(f"tool '{tool_id}' not found")
    ordered = sorted(rows, key=lambda r: tuple(int(p) for p in r.version.split(".")), reverse=True)
    return [_out(r) for r in ordered]


@router.post(
    "", response_model=ToolOut, status_code=201, summary="Register a custom tool bound to a generic mock implementation"
)
def create_tool(payload: ToolCreate, session: WriteSession, _: Operator) -> ToolOut:
    row = register_tool(session, payload)
    session.commit()
    return _out(row)
