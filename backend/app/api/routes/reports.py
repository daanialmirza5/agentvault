from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams
from app.core.db import get_read_session, get_session
from app.models import Report
from app.repositories.queries import paginate
from app.schemas.common import Page
from app.schemas.resources import ReportOut
from app.services.reporting.reports import ReportCreate, create_report, get_report

router = APIRouter(prefix="/reports", tags=["reports"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


@router.post("", response_model=ReportOut, status_code=201, summary="Generate a report from stored records")
def create(payload: ReportCreate, session: WriteSession, _: Operator) -> ReportOut:
    return ReportOut.model_validate(create_report(session, payload))


@router.get("", response_model=Page[ReportOut])
def list_reports(session: ReadSession, page: PageParams) -> Page[ReportOut]:
    rows, total = paginate(session, select(Report).order_by(Report.created_at.desc()), page.limit, page.offset)
    return Page(items=[ReportOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/{report_id}",
    summary="Download a report as JSON (default) or Markdown",
    responses={200: {"content": {"application/json": {}, "text/markdown": {}}}},
)
def download(
    report_id: str,
    session: ReadSession,
    format: Annotated[Literal["json", "markdown"], Query()] = "json",
    download: Annotated[bool, Query()] = False,
) -> Response:
    report = get_report(session, report_id)
    headers = {}
    if format == "markdown":
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{report.id}.md"'
        return Response(report.markdown, media_type="text/markdown; charset=utf-8", headers=headers)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{report.id}.json"'
    body = {
        "id": report.id,
        "kind": report.kind,
        "subject_id": report.subject_id,
        "title": report.title,
        "created_at": report.created_at.isoformat(),
        "content": report.content,
    }
    return Response(json.dumps(body, indent=2, default=str), media_type="application/json", headers=headers)
