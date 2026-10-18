# ADR 0004: Append-only, hash-chained audit events with stated limits

**Status:** accepted

## Decision
* Every execution event gets a per-execution sequence number and
  `hash = sha256(prev_hash || canonical_json(event))`.
* Three layers prevent ordinary code paths from rewriting history: an ORM guard (`before_update` /
  `before_delete` raise), SQLite triggers that abort `UPDATE` and `DELETE`, and a unique
  `(execution_id, sequence)` constraint. Retention deletion is possible only after a
  `retention_purges` record authorises it, and that record is kept.
* `GET /executions/{id}/audit/verify` recomputes the chain and checks structural completeness. For
  example, every executed tool must have an `allow` decision or a prior `approval.granted`.

## Limits (deliberately documented)
Hash chaining detects edits, deletions and re-ordering made **without** recomputing hashes. It does
**not** protect against someone with write access to the database file who rewrites events and
recomputes the chain. A test demonstrates exactly this. Defeating that attacker requires anchoring
the head hash somewhere they cannot write, such as an exported report, a WORM store or a
transparency log. That is not implemented.
