from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import SettingsDep, require_read_access
from app.core.db import get_engine, get_read_session
from app.core.migrations import schema_is_current
from app.models import Policy, Scenario, ToolDefinition
from app.repositories.queries import dashboard_stats

router = APIRouter(tags=["system"])
ReadSession = Annotated[Session, Depends(get_read_session)]


@router.get("/health", summary="Liveness: the process is serving requests")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready", summary="Readiness: database reachable, schema current, seed data present")
def ready(session: ReadSession, settings: SettingsDep) -> JSONResponse:
    checks: dict[str, Any] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        checks["migrations_current"] = schema_is_current(get_engine())
    except Exception:
        checks["migrations_current"] = False
    if checks["database"]:
        checks["tools"] = session.scalar(select(func.count()).select_from(ToolDefinition)) or 0
        checks["policies"] = session.scalar(select(func.count()).select_from(Policy)) or 0
        checks["scenarios"] = session.scalar(select(func.count()).select_from(Scenario)) or 0
    ok = bool(checks["database"] and checks["migrations_current"] and checks.get("tools") and checks.get("policies"))
    body = {
        "status": "ready" if ok else "not_ready",
        "checks": checks,
        "version": __version__,
        "auth_mode": "bearer_token" if settings.auth_required else "single_user_local",
        "llm_adapter_enabled": settings.llm_enabled,
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)


@router.get(
    "/stats", summary="Dashboard aggregates derived from stored records", dependencies=[Depends(require_read_access)]
)
def stats(session: ReadSession) -> dict[str, Any]:
    return dashboard_stats(session)
