# ADR 0002: One runner for live execution, replay and evaluation

**Status:** accepted

## Context
A replay engine that re-implements authorisation can drift from the live path and give false
confidence ("the replay says it would have been blocked").

## Decision
The execution loop (`agent_runtime/runner.py`) knows nothing about persistence. It talks to three
small interfaces:

* `EventSink`: the database (live) or memory (replay);
* `ApprovalGate`: pause and create an approval (live), or answer from recorded decisions / a
  what-if strategy (replay);
* `ToolInvoker`: run the mock (live) or reconstruct it in an isolated sandbox / reuse recorded
  output for non-deterministic tools (replay).

Agents are pure state machines with JSON state, so a paused run can resume in another request
and a replay starts from exactly the same state.

## Consequences
* Replays exercise the real policy, schema validation and guard code.
* "Replay under policy B" is the same code path as "execute under policy B", except for the
  side-effect boundary.
* Frames are labelled `recorded`, `reconstructed`, `re-evaluated` or `unavailable`, so a viewer can
  always tell what was observed and what was recomputed.
