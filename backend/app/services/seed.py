"""Idempotent seeding of built-in tools and policies."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.policy_engine.defaults import DEFAULT_POLICIES
from app.services.policy_engine.store import seed_policies
from app.services.tool_registry.builtin_tools import BUILTIN_TOOLS
from app.services.tool_registry.registry import upsert_builtin_tools


def seed_all(session: Session) -> dict[str, int]:
    result = {
        "tools": upsert_builtin_tools(session, BUILTIN_TOOLS),
        "policies": seed_policies(session, DEFAULT_POLICIES),
    }
    session.commit()
    return result
