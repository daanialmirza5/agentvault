# Security model and limitations

## What AgentVault enforces (each item has tests)
* **Allowlisted tools only.** Unregistered tool IDs are denied before any policy rule runs.
* **Strict argument validation.** JSON Schema with `additionalProperties: false`, size limits, and
  format checks run before policy evaluation.
* **Model-independent authorisation.** Agent claims and retrieved text are never inputs to `evaluate()`.
* **Tool-level approval floor.** A tool marked `requires_approval` cannot be relaxed by policy.
* **Bound, expiring, single-use approvals** with database-serialized decisions (see ADR 0003).
* **Runtime guards.** Max steps, max tool calls, identical-call loop detection, per-tool timeouts and
  an active-time execution timeout.
* **No side effects outside the sandbox.** Every tool is a mock over a per-execution dictionary.
* **Append-only audit** with hash chaining and completeness checks (see ADR 0004 for the limits).
* **API hygiene.** Request size limit (256 KiB), restricted CORS (no wildcard, no credentials),
  validation errors that never echo submitted values, generic 500s with request IDs, security
  headers, a non-root container and a CSP on the web container.
* **Redaction.** Credential-like keys (`password`, `token`, `api_key`, `authorization`, …) and
  tool-declared `sensitive_arguments` are redacted before arguments reach audit events, decisions,
  approvals and logs.

## Known limitations (do not overclaim)
* **Not an isolation boundary.** Mocks run in-process in Python threads. A timed-out thread is
  abandoned, not killed. Do not plug real or untrusted tool code into this executor.
* **Single-user model.** Local mode has no authentication. The optional bearer token is one shared
  secret and every holder acts as the same operator. There is no RBAC and no separation of duties
  between the person who launches and the person who approves.
* **Audit tamper-evidence is partial.** Anyone who can write the SQLite file can rewrite and re-hash
  history. The head hash is not anchored externally.
* **Redaction is key-based.** Secrets inside free-text values (an email body, say) are not detected.
  Tool outputs are stored as returned by the mocks, which contain only fictional data.
* **Prompt injection is contained, not prevented.** The injection scenario shows the policy layer
  stopping an injected admin export. It does not show that a model cannot be manipulated into
  something the policy allows. Write policies assuming the agent is compromised.
* **Synthetic evaluation.** Passing all 12 scenarios means the configured controls behave as designed
  on those cases. It is not evidence of real-world agent security.
* **SQLite, one process.** Approval locking and crash recovery assume one API process per database file.
* **Public deployment without a token is unsafe**: reads expose audit data and mutations allow approvals.

## Data retention
`AGENTVAULT_RETENTION_DAYS` (default 30) defines when finished executions become eligible for
`python -m app.cli purge`. Nothing is deleted automatically. A purge writes a `retention_purges`
record first, which the database triggers require, then deletes that execution's events,
decisions, approvals and replays. Reports already exported are not touched.

## Reporting a vulnerability
Open a private security advisory on the repository rather than a public issue.
