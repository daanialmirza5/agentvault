from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core import db
from app.core.migrations import upgrade_to_head


@pytest.fixture()
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A fresh SQLite file per test, created through the real Alembic migrations."""
    eng = db.init_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    upgrade_to_head(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    s = db.session_factory()()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
