"""Test helpers for building scenarios and settings."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.agent_runtime.scenario import ScenarioFile, save_scenario


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"environment": "test", "database_url": "sqlite://", "seed_on_startup": False}
    base.update(overrides)
    return Settings(**base)


def make_scenario(
    session: Session,
    scenario_id: str,
    steps: list[dict[str, Any]],
    *,
    agent_type: str = "scripted",
    environment: str = "sandbox",
    tags: list[str] | None = None,
    seed: int = 7,
    human: dict[str, Any] | None = None,
    expectations: dict[str, Any] | None = None,
    version: int = 1,
) -> str:
    scenario = ScenarioFile.model_validate(
        {
            "id": scenario_id,
            "version": version,
            "name": scenario_id,
            "category": "test",
            "spec": {
                "task": f"Test task for {scenario_id}",
                "environment": environment,
                "tags": tags or [],
                "seed": seed,
                "agent": {"type": agent_type, "steps": steps},
            },
            "human_script": human or {},
            "expectations": expectations or {},
        }
    )
    save_scenario(session, scenario, "test")
    session.commit()
    return scenario_id
