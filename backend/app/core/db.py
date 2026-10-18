"""Database engine, sessions and the SQLAlchemy declarative base.

SQLite is the default. Three details matter for correctness:

* ``foreign_keys`` is enabled per connection (SQLite defaults it to off).
* Write-capable sessions start transactions with ``BEGIN IMMEDIATE``. In WAL mode a
  *deferred* transaction that reads and then tries to write fails instantly with
  ``SQLITE_BUSY`` if another writer committed in between; taking the write lock up front
  makes concurrent writers queue (``busy_timeout``) instead. It is also what serializes
  concurrent approval decisions.
* Read-only API endpoints use :func:`get_read_session`, which begins ``DEFERRED`` and
  therefore never waits for writers.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite stores naive values)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime, dict[str, Any]: JSON, list[Any]: JSON}


def _json_serializer(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    connect_args: dict[str, Any] = {}
    if is_sqlite:
        connect_args = {"check_same_thread": False, "timeout": 15}
        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:" and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args, json_serializer=_json_serializer, future=True)
    if is_sqlite:
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        # Disable pysqlite's implicit transaction handling; we emit BEGIN ourselves.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        mode = conn.get_execution_options().get("sqlite_begin", "IMMEDIATE")
        if mode not in {"DEFERRED", "IMMEDIATE"}:
            raise ValueError("invalid sqlite_begin mode")
        conn.exec_driver_sql(f"BEGIN {mode}")


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_read_session_factory: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    global _engine, _session_factory, _read_session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url or get_settings().database_url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    _read_session_factory = sessionmaker(
        bind=_engine.execution_options(sqlite_begin="DEFERRED"), expire_on_commit=False, autoflush=False
    )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def read_session_factory() -> sessionmaker[Session]:
    if _read_session_factory is None:
        init_engine()
    assert _read_session_factory is not None
    return _read_session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one write-capable session per request, rolled back on error."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_read_session() -> Iterator[Session]:
    """FastAPI dependency for read-only endpoints (never takes the write lock)."""
    session = read_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@contextmanager
def write_transaction(session: Session) -> Generator[Session, None, None]:
    """Run a block in a fresh transaction that holds the SQLite write lock from its first statement."""
    if session.in_transaction():
        session.commit()
    session.connection()  # begins the transaction now (IMMEDIATE for write-capable sessions)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
