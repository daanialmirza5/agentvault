from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams, SettingsDep
from app.core.db import get_read_session, get_session
from app.models import Evaluation
from app.repositories.queries import paginate
from app.schemas.common import Page
from app.schemas.resources import EvaluationOut, EvaluationSummaryOut
from app.services.evaluation.evaluator import EvaluationCreate, get_evaluation, run_evaluation

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


@router.post(
    "",
    response_model=EvaluationOut,
    status_code=201,
    summary="Run scenarios under 1-4 policy versions and score them (synchronous)",
)
def create(payload: EvaluationCreate, session: WriteSession, settings: SettingsDep, _: Operator) -> EvaluationOut:
    return EvaluationOut.model_validate(run_evaluation(session, settings, payload))


@router.get("", response_model=Page[EvaluationSummaryOut], summary="List evaluations")
def list_evaluations(session: ReadSession, page: PageParams) -> Page[EvaluationSummaryOut]:
    rows, total = paginate(session, select(Evaluation).order_by(Evaluation.created_at.desc()), page.limit, page.offset)
    return Page(
        items=[EvaluationSummaryOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{evaluation_id}", response_model=EvaluationOut)
def get(evaluation_id: str, session: ReadSession) -> EvaluationOut:
    return EvaluationOut.model_validate(get_evaluation(session, evaluation_id))
