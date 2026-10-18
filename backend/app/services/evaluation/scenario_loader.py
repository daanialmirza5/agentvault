"""Loads scenario fixtures from ``scenarios/<source>/*.json`` into the database."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.agent_runtime.scenario import ScenarioFile, save_scenario

MAX_FIXTURE_BYTES = 256 * 1024


def load_scenario_files(root: Path) -> list[tuple[str, ScenarioFile]]:
    found: list[tuple[str, ScenarioFile]] = []
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*/*.json")):
        if path.stat().st_size > MAX_FIXTURE_BYTES:
            raise ValueError(f"{path.name} exceeds {MAX_FIXTURE_BYTES} bytes")
        data = json.loads(path.read_text(encoding="utf-8"))
        found.append((path.parent.name, ScenarioFile.model_validate(data)))
    ids = [s.id for _, s in found]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate scenario ids: {sorted(duplicates)}")
    return found


def seed_scenarios(session: Session, root: Path) -> int:
    """Idempotently register every fixture; returns how many fixtures were found."""
    files = load_scenario_files(root)
    for source, scenario in files:
        save_scenario(session, scenario, source)
    session.commit()
    return len(files)
