# ADR 0003: Approvals are bound, single-use and serialized in the database

**Status:** accepted

## Context
Approving the wrong thing is worse than not approving: a stale approval, an approval replayed
against another execution, or two simultaneous approvals that execute an email twice.

## Decision
* Each approval stores `action_hash = sha256(execution_id, step, tool_id, tool_version, arguments)`.
  The decision request must echo `execution_id` and `action_hash`. A mismatch is refused (409) and
  recorded as `approval.binding_mismatch`.
* Decisions run in a `BEGIN IMMEDIATE` transaction. They claim the approval with
  `UPDATE … WHERE status='pending'` and the execution with
  `UPDATE … WHERE status='waiting_for_approval' AND pending_approval_id=…`, then mark the approval
  consumed. Only one decision can move the execution forward. An identical repeated decision is
  idempotent; a contradictory one gets 409.
* Approvals expire (`AGENTVAULT_APPROVAL_TTL_SECONDS`, default 15 min). Expiry is checked on every
  decision and by a background sweep. An expired action is blocked, never executed.
* The runner re-derives the hash from the stored pending action before executing.

## Consequences
* Correct under concurrent requests on a single SQLite database (tested with four threads).
* The scheme assumes one application process per database file. A multi-instance deployment would
  need PostgreSQL row locks (`SELECT … FOR UPDATE`) and a distributed sweep.
* Single-user mode records the configured operator name. With `AGENTVAULT_API_TOKEN` there is a
  shared-secret gate, but it is not per-user authentication.
