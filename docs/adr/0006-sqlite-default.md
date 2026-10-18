# ADR 0006: SQLite by default, Alembic migrations, one process per database

**Status:** accepted

## Context
The target is a laptop with about 8 GB of RAM and no mandatory services.

## Decision
* SQLite in WAL mode with foreign keys enabled. Write sessions use `BEGIN IMMEDIATE`; reads use
  `DEFERRED`.
* The schema is created only through Alembic migrations, including the append-only triggers.
  Tests run the real migrations against a temporary file, not `create_all`.
* uvicorn runs with one worker. Startup recovery marks orphaned `running` executions as failed.

## Consequences
* Zero setup: no database server.
* Throughput is bounded by SQLite's single writer, which is adequate for a developer tool.
* Moving to PostgreSQL needs dialect-specific triggers (PL/pgSQL), row locks for approvals and a
  connection pool. SQLAlchemy keeps the query code portable.
