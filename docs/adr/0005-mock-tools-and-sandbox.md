# ADR 0005: Mock tools against a per-execution sandbox; no executable registration

**Status:** accepted

## Decision
* Every tool implementation is a built-in Python function that reads and writes only a
  per-execution dictionary (documents, customers, outbox, tickets…). Nothing touches the
  filesystem, network, subprocesses or real accounts.
* Tools run on a deep copy of the sandbox. The copy is adopted only if the tool succeeds within its
  timeout and its output validates against the output schema, so partial effects are never kept.
* Custom tools registered through the API bind to one of two generic mocks (`static_response`,
  `echo`). Their schemas must forbid extra properties and may not use regex keywords (`pattern`,
  `patternProperties`) because Python's `re` has no timeout (ReDoS).
* Randomness is seeded per `(seed, step, tool)`. One tool (`ops.fetch_exchange_rate`) is deliberately
  unseeded so that replay's handling of non-deterministic output can be shown and tested.

## Consequences
This is a controlled simulation for testing authorisation logic. It is **not** an isolation
boundary for hostile code: timed-out worker threads cannot be killed, and everything runs inside the
API process. Connecting real tools would need a separate, sandboxed executor process.
