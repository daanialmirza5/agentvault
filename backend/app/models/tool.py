from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.utils import utcnow


class ToolDefinition(Base):
    """A versioned tool that agents may request. Implementations are always built-in mocks."""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tool_id", "version", name="uq_tools_tool_id_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]]
    output_schema: Mapped[dict[str, Any]]
    category: Mapped[str] = mapped_column(String(40))
    risk_level: Mapped[str] = mapped_column(String(16))
    requires_approval: Mapped[bool]
    mutating: Mapped[bool]
    timeout_seconds: Mapped[float]
    implementation: Mapped[str] = mapped_column(String(80))
    mock_config: Mapped[dict[str, Any]]
    deterministic: Mapped[bool]
    sensitive_arguments: Mapped[list[Any]]
    builtin: Mapped[bool]
    enabled: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
