from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams
from app.core.db import get_read_session, get_session
from app.core.errors import NotFoundError
from app.models import Scenario
from app.repositories.queries import paginate
from app.schemas.common import Page
from app.schemas.resources import ScenarioOut
from app.services.agent_runtime.scenario import ScenarioFile, save_scenario

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


@router.get("", response_model=Page[ScenarioOut], summary="List scenarios (all versions)")
def list_scenarios(
    session: ReadSession,
    page: PageParams,
    source: Annotated[str | None, Query(max_length=20)] = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
) -> Page[ScenarioOut]:
    query = select(Scenario)
    if source:
        query = query.where(Scenario.source == source)
    if category:
        query = query.where(Scenario.category == category)
    rows, total = paginate(
        session,
        query.order_by(Scenario.source.desc(), Scenario.scenario_id, Scenario.version.desc()),
        page.limit,
        page.offset,
    )
    return Page(items=[ScenarioOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/{scenario_id}", response_model=list[ScenarioOut], summary="All versions of one scenario")
def get_scenario(scenario_id: str, session: ReadSession) -> list[ScenarioOut]:
    rows = session.scalars(
        select(Scenario).where(Scenario.scenario_id == scenario_id).order_by(Scenario.version.desc())
    ).all()
    if not rows:
        raise NotFoundError(f"scenario '{scenario_id}' not found")
    return [ScenarioOut.model_validate(r) for r in rows]


@router.post("", response_model=ScenarioOut, status_code=201, summary="Create a custom scenario version")
def create_scenario(payload: ScenarioFile, session: WriteSession, _: Operator) -> ScenarioOut:
    row = save_scenario(session, payload, "custom")
    session.commit()
    return ScenarioOut.model_validate(row)
