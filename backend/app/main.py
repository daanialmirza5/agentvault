"""FastAPI application factory."""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.deps import require_read_access
from app.api.errors import install_error_handlers
from app.api.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.api.routes import (
    approvals,
    audit,
    evaluations,
    executions,
    policies,
    replays,
    reports,
    scenarios,
    system,
    tools,
)
from app.core import db
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, logger
from app.core.migrations import upgrade_to_head
from app.services.agent_runtime.engine import recover_interrupted
from app.services.approval_engine.service import expire_due
from app.services.seed import seed_all


def _sweeper(settings: Settings, stop: threading.Event) -> None:
    """Expires overdue approvals in the background (they are also expired lazily on access)."""
    while not stop.wait(settings.approval_sweep_interval_seconds):
        session = db.session_factory()()
        try:
            expired = expire_due(session, settings)
            if expired:
                logger.info("expired %d approval(s)", len(expired))
        except Exception:
            logger.exception("approval sweep failed")
        finally:
            session.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        engine = db.init_engine(settings.database_url)
        upgrade_to_head(engine)
        session = db.session_factory()()
        try:
            recovered = recover_interrupted(session)
            if recovered:
                logger.warning("marked %d interrupted execution(s) as failed", recovered)
            if settings.seed_on_startup:
                logger.info("seed: %s", seed_all(session, settings.scenarios_dir))
        finally:
            session.close()
        stop = threading.Event()
        worker = None
        if settings.approval_sweep_interval_seconds > 0:
            worker = threading.Thread(target=_sweeper, args=(settings, stop), daemon=True, name="approval-sweeper")
            worker.start()
        yield
        stop.set()
        if worker is not None:
            worker.join(timeout=5)

    docs = settings.environment != "production"
    app = FastAPI(
        title="AgentVault API",
        version=__version__,
        lifespan=lifespan,
        description="Tool permissions, human approvals, execution tracing, deterministic replay and safety "
        "evaluations for AI agents.",
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    install_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(system.router)  # health/ready stay public; /stats is protected below
    for module in (tools, policies, scenarios, executions, approvals, replays, evaluations, reports, audit):
        api.include_router(module.router, dependencies=[Depends(require_read_access)])
    app.include_router(api)

    # Order: the last added middleware runs first.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
