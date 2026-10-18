"""Idempotent seeding of built-in tools, policies and scenario fixtures."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.services.evaluation.scenario_loader import seed_scenarios
from app.services.policy_engine.defaults import DEFAULT_POLICIES
from app.services.policy_engine.store import seed_policies
from app.services.tool_registry.builtin_tools import BUILTIN_TOOLS
from app.services.tool_registry.registry import upsert_builtin_tools


def seed_all(session: Session, scenarios_dir: Path | None = None) -> dict[str, int]:
    result = {
        "tools": upsert_builtin_tools(session, BUILTIN_TOOLS),
        "policies": seed_policies(session, DEFAULT_POLICIES),
    }
    session.commit()
    if scenarios_dir is not None:
        result["scenarios"] = seed_scenarios(session, scenarios_dir)
    return result
