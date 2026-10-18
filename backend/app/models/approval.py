from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.utils import utcnow

APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "cancelled")


class Approval(Base):
    """A request for a human decision, bound to exactly one pending action of one execution.

    ``action_hash`` covers the execution ID, step number, tool ID/version and the full
    arguments, so an approval cannot be applied to a different action or execution.
    ``consumed_at`` makes an approval single-use.
    """

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    decision_id: Mapped[str] = mapped_column(String(40))
    step: Mapped[int]
    action_label: Mapped[str] = mapped_column(String(80), default="")
    action_hash: Mapped[str] = mapped_column(String(64))
    tool_id: Mapped[str] = mapped_column(String(80))
    tool_version: Mapped[str] = mapped_column(String(20))
    arguments_redacted: Mapped[dict[str, Any]]
    risk_level: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(String(16), index=True, default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    expires_at: Mapped[datetime]
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by: Mapped[str | None] = mapped_column(String(64), default=None)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    consumed_at: Mapped[datetime | None] = mapped_column(default=None)
