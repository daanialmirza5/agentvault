from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.utils import utcnow


class Scenario(Base):
    """A reproducible agent task. ``spec`` is what the engine sees; ``expectations`` and
    ``human_script`` are only ever read by the evaluator and never passed to the engine."""

    __tablename__ = "scenarios"
    __table_args__ = (UniqueConstraint("scenario_id", "version", name="uq_scenarios_id_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int]
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20))
    spec: Mapped[dict[str, Any]]
    human_script: Mapped[dict[str, Any]]
    expectations: Mapped[dict[str, Any]]
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
