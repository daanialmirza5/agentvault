from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.utils import utcnow

TERMINAL_STATUSES = frozenset({"completed", "failed", "blocked", "cancelled"})
EXECUTION_STATUSES = ("pending", "running", "waiting_for_approval", *sorted(TERMINAL_STATUSES))


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(80), index=True)
    scenario_version: Mapped[int]
    policy_id: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[int]
    agent_type: Mapped[str] = mapped_column(String(20))
    environment: Mapped[str] = mapped_column(String(20))
    seed: Mapped[int]
    origin: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    evaluation_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    status: Mapped[str] = mapped_column(String(24), index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    task: Mapped[str] = mapped_column(Text)
    spec: Mapped[dict[str, Any]]
    agent_state: Mapped[dict[str, Any]]
    sandbox_state: Mapped[dict[str, Any]]
    initial_sandbox_hash: Mapped[str] = mapped_column(String(64))
    pending_action: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    pending_approval_id: Mapped[str | None] = mapped_column(String(40), default=None)
    step_count: Mapped[int] = mapped_column(default=0)
    tool_call_count: Mapped[int] = mapped_column(default=0)
    event_count: Mapped[int] = mapped_column(default=0)
    last_event_hash: Mapped[str] = mapped_column(String(64))
    final_output: Mapped[str] = mapped_column(Text, default="")
    active_ms: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
