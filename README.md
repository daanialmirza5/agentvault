# AgentVault

**Test every action. Control every tool. Replay every decision.**

AgentVault is an AI agent reliability and security platform. It covers tool permissions, human
approval workflows, execution tracing, deterministic replay and reproducible safety evaluations. It
sits between an agent and its tools. Every proposed tool call is checked against a versioned tool
registry and a deterministic policy, may pause for a human decision, runs only against a mock
sandbox, and is recorded in an append-only, hash-chained audit trail that can be replayed later.

It runs entirely on a laptop: no GPU, no paid API, no external services. The default agents are
deterministic scripts. An OpenAI-compatible LLM adapter is optional.

![Execution timeline with the policy decision behind an approval](docs/screenshots/execution-timeline.png)

## Contents
[Problem](#problem) · [Features](#features) · [Architecture](#architecture) · [Permission model](#tool-permission-model) ·
[Approvals](#approval-workflow) · [Events](#execution-event-model) · [Replay](#replay-semantics) ·
[Evaluation](#evaluation-methodology) · [Results](#actual-evaluation-results) · [Setup](#windows-setup) ·
[Docker](#docker) · [Configuration](#environment-variables) · [API](#api) · [Tests](#tests) ·
[Security](#security-and-privacy-limitations) · [Deployment](#deployment) · [Troubleshooting](#troubleshooting) · [Roadmap](#roadmap)

## Problem

Agents that can call tools fail in ways ordinary software doesn't. They follow instructions hidden in
documents they read. They retry forever. They pass malformed arguments. They confidently claim an
action is safe. They take irreversible actions without a person in the loop. Teams need to answer
four questions:

1. *Which actions may this agent take, and who decided?* (permissions, policy versions)
2. *Can a human stop a risky action before it happens?* (approvals that cannot be replayed or raced)
3. *What exactly happened?* (a complete, ordered, tamper-evident trace)
4. *Would a stricter policy have prevented it, and at what cost to legitimate work?* (replay and evaluation)

AgentVault is a working, tested platform for exploring those questions with deterministic agents and
mock tools.

## Features

| Area | What it does |
|---|---|
| **Tool registry** | 12 versioned built-in mock tools with input/output JSON Schemas, permission category, risk level, read/write flag, timeout and approval flag. Custom tools can be registered against generic mocks (never executable code). |
| **Policy engine** | Deterministic rules over tool ID/glob, category, risk, read/write, environment, scenario tags and argument conditions. Outcomes: allow, deny, require approval. Deny-overrides precedence. Immutable versions, conflict and shadowing analysis, diffs, a decision playground. |
| **Execution engine** | Provider-independent agent interface. Scripted, reactive (branching, templating, instruction-following) and optional LLM agents. Step and tool-call limits, loop detection, per-tool and per-execution timeouts, cancellation. |
| **Approvals** | Pausing approval queue. Decisions bound to an exact action hash and execution, single-use, expiring, safe under concurrent requests. Full history. |
| **Audit** | Append-only events (ORM guards + DB triggers) with per-execution sequence numbers and a hash chain, immutable decision records, verification and completeness checks. |
| **Replay** | Recorded step-through, or isolated re-execution under any policy version. Frames labelled recorded / reconstructed / re-evaluated / unavailable, first-divergence detection, execution-to-execution comparison, what-if approval strategies. |
| **Evaluation lab** | 12 deterministic scenarios (normal, approval, unauthorised tool, protected resource, malformed arguments, loop, timeout/failure, conflicting rules, stale approval, approval replay, prompt injection, over-restriction) run under 1–4 policy versions with precisely defined metrics and event-ID evidence. |
| **Reports** | JSON and Markdown exports for executions, replays, evaluations and policy comparisons. |
| **UI** | React + TypeScript dashboard, execution workspace (timeline + flow graph), approval queue, replay workspace, policy editor, tool registry, evaluation lab, audit and reports. |

| | |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Approval queue](docs/screenshots/approval-queue.png) |
| ![Replay with first divergence](docs/screenshots/replay-divergence.png) | ![Policy editor](docs/screenshots/policy-editor.png) |
| ![Execution flow graph](docs/screenshots/execution-flow-graph.png) | ![Policy comparison](docs/screenshots/policy-compare.png) |
| ![Tool registry](docs/screenshots/tool-registry.png) | ![Audit log](docs/screenshots/audit-log.png) |

All screenshots were captured from the running application by
[`frontend/e2e/screenshots.spec.ts`](frontend/e2e/screenshots.spec.ts); every number in them comes
from activity that script created.

## Architecture

```
agentvault/
  backend/app/
    api/            routes, middleware (request IDs, body limits), error envelope, auth dependency
    core/           config, database (WAL, BEGIN IMMEDIATE), migrations, redaction, hashing
    models/         SQLAlchemy models (append-only audit + decisions)
    repositories/   read-side queries, pagination, dashboard aggregates
    schemas/        response models
    services/
      tool_registry/   definitions, schema validation, mock implementations, timeout executor
      policy_engine/   model, pure evaluator, analysis (conflicts/diff/matrix), versioned store
      agent_runtime/   scenarios, agents, runner (shared loop), live engine, LLM adapter
      approval_engine/ bound, serialized, expiring decisions
      audit/           event schema, hash chain, completeness invariants
      replay/          recorded/simulated replay, divergence detection
      evaluation/      scenario loader, evaluator (simulated human), metrics
      reporting/       JSON + Markdown reports
    tests/          147 pytest tests
  backend/alembic/  migrations (incl. append-only triggers)
  frontend/src/     React app (features/*, components, hooks, services, types, tests)
  frontend/e2e/     Playwright end-to-end tests and screenshot capture
  scenarios/        demo + adversarial fixtures (JSON)
  benchmarks/       reproducible evaluation results
  docs/             architecture, ADRs, deployment, security, demo script, screenshots
  scripts/          setup, dev, test, demo, cleanup (PowerShell)
```

The key design choice: one **runner** drives live executions, replays and evaluations. Persistence,
approvals and tool execution are plugged in, so a replay exercises the same authorisation code as a
live run ([ADR 0002](docs/adr/0002-shared-runner-for-live-and-replay.md)).
[docs/architecture.md](docs/architecture.md) has the component diagram, the tool-call **sequence
diagram** and the **policy evaluation flow**.

## Tool permission model

Each proposed call passes, in order:

1. **Registry allowlist.** Unknown tool → `deny` (`builtin:unknown_tool`).
2. **Schema validation.** Malformed or extra arguments → `deny` (`builtin:invalid_arguments`).
3. **Policy rules.** All matching enabled rules are collected. **Deny > require approval > allow**;
   `priority` only orders rules with the same effect.
4. **Default effect** if nothing matched (seeded policies default to `deny`).
5. **Tool approval floor.** A tool that declares `requires_approval` never ends as a plain `allow`.

The agent's own statements (`"claims": {"safe": true}`) are logged but are not an input to the
evaluator ([ADR 0001](docs/adr/0001-deterministic-policy-engine.md)). Three example policies are seeded:

| Policy | Intent |
|---|---|
| `baseline` | Least privilege: low/medium-risk reads allowed, outbound email and CRM changes need approval, protected fields, system accounts, restricted documents, P0 tickets and admin tools denied, production writes need approval. |
| `strict-lockdown` | Deliberately over-strict: only document reads, every write needs approval. |
| `permissive-dev` | Deliberately weak: default allow, relying on tool-level approval flags. |

## Approval workflow

1. The policy returns `require_approval`; the runner creates an approval bound to
   `action_hash = sha256(execution, step, tool, version, arguments)` and the execution pauses.
2. The approval queue shows the tool, risk, redacted arguments, rationale, recent steps and any
   (unverified) agent claims, with an expiry countdown.
3. Approve or reject. The request must echo `execution_id` and `action_hash`. A mismatch is refused
   with `409 approval_binding_mismatch` and recorded in the target execution's audit log.
4. The decision is serialized (`BEGIN IMMEDIATE` + conditional updates), marked consumed, and the
   execution resumes. A rejected or expired action is never executed. Repeating the same decision is
   idempotent; a contradictory one gets 409.
5. Pending approvals expire after `AGENTVAULT_APPROVAL_TTL_SECONDS` (default 900 s), enforced on every
   decision and by a background sweep. Cancelling an execution cancels its approval.

Local mode is **single-user**: decisions are recorded under `AGENTVAULT_OPERATOR_NAME`. See
[ADR 0003](docs/adr/0003-approval-binding-and-concurrency.md).

## Execution event model

Every execution produces an ordered stream:

`execution.created → execution.started → agent.action_proposed → tool.requested →
tool.arguments_validated | tool.arguments_rejected → policy.evaluated → [approval.requested →
execution.resumed → approval.granted | approval.rejected | approval.expired] → tool.executed →
tool.result | tool.failed | tool.blocked → … → execution.completed | failed | blocked | cancelled`

plus `guard.triggered` (limits, loops, timeouts) and `approval.binding_mismatch`. Each event has an ID,
execution ID, sequence number, timestamp, type, tool ID, policy version (`policy@vN`), outcome, JSON
data and `prev_hash`/`hash`. Each `policy.evaluated` event has an immutable decision record (decision ID,
policy version, tool, redacted arguments, outcome, reason, matched rules, deciding rule, latency).
Events cannot be updated or deleted through the application or with plain SQL
([ADR 0004](docs/adr/0004-append-only-hash-chained-audit.md)).

## Replay semantics

| Mode | What runs | Labels |
|---|---|---|
| **Recorded** | Nothing. The stored events are reconstructed into frames with cumulative state. | `recorded` |
| **Simulate** | The same scenario, seed and recorded tool versions through the real runner, in memory, against a fresh mock sandbox, under the same or a different policy version. | `reconstructed` (deterministic mock re-run in isolation), `recorded` (non-deterministic output or human decision reused), `re-evaluated` (policy decision recomputed), `unavailable` (cannot be reproduced; the simulation stops there) |

Replays never touch live executions, approvals or audit rows, and never repeat side effects. A
decision the original run never needed (e.g. under a stricter policy) is `unavailable` unless you pick
a what-if strategy (`approve_all` / `reject_all`). Divergence is computed on a normalised fingerprint
of each event that ignores IDs, timestamps and latencies, and is reported with the first differing
event on both sides.

## Evaluation methodology

The evaluator starts a real execution for each (policy version, scenario version), passing **only
references**. The scenario's `expectations` and `human_script` stay in the evaluator, and the engine's
input type forbids extra fields. A test flips every expectation and checks that no decision changes.
The simulated human then answers approvals through the same service the API uses, including attacks:
approving after expiry, approving with another execution's ID, and approving a tampered action hash.

| Metric | Definition |
|---|---|
| Unsafe action block rate | proposed actions labelled `unsafe` that were not executed ÷ proposed unsafe actions |
| Legitimate false-block rate | proposed `legitimate` actions expected to run that did not ÷ such proposed actions |
| Legitimate action completion | expected legitimate actions that executed ÷ all expected legitimate actions (including ones never reached) |
| Approval enforcement | approval-required actions handled correctly (never executed without a prior grant, at most once, iff approved) **plus** approval attacks refused ÷ total |
| Task completion | scenarios expected to complete that completed ÷ those scenarios |
| Replay consistency | runs whose same-policy simulation shows no divergence ÷ replayed runs |
| Audit completeness | runs with a valid hash chain and all structural invariants ÷ runs |
| Policy evaluation latency | wall-clock time of the in-process `evaluate()` call (µs, p50/p95) |
| Execution latency | wall-clock time to drive a scenario to a terminal state (ms) |

**Passing synthetic scenarios is not proof of real-world agent security.** The suite shows that the
configured controls behave as designed on 12 hand-labelled cases with deterministic agents. It cannot
show that a real model won't find an action the policy allows but you didn't intend.

## Actual evaluation results

Produced by `python -m app.cli evaluate` on 2026-10-18 (full output:
[benchmarks/results/latest.md](benchmarks/results/latest.md)). Rates are deterministic; latencies are
from one Windows laptop run and will vary.

| Metric | baseline@v1 | strict-lockdown@v1 | permissive-dev@v1 |
|---|---|---|---|
| Scenario pass rate | 100.0% (12/12) | 25.0% (3/12) | 83.3% (10/12) |
| Unsafe actions blocked | 100.0% (11/11) | 100.0% (11/11) | 63.6% (7/11) |
| Legitimate actions falsely blocked | 0.0% (0/19) | 80.0% (8/10) | 0.0% (0/19) |
| Legitimate actions completed | 100.0% (17/17) | 11.8% (2/17) | 100.0% (17/17) |
| Approval enforcement | 100.0% (7/7) | 100.0% (6/6) | 85.7% (6/7) |
| Task completion | 100.0% (9/9) | 11.1% (1/9) | 100.0% (9/9) |
| Replay consistency | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) |
| Audit completeness | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) |
| Policy evaluation latency p50 | 83 µs | 65 µs | 51 µs |

Reading the table: *strict-lockdown* blocks every unsafe action but also 80% of the legitimate ones it
saw, and completes 1 of 9 tasks. *permissive-dev* completes everything but lets 4 of 11 unsafe
actions run (a credit-limit change, a system-account change, a restricted document read, a P0 ticket)
and runs a CRM update without approval. The baseline was written for these scenarios, so its 100% is
expected and is not evidence of generality.

## Technology stack

* **Backend:** Python 3.12–3.14, FastAPI, Pydantic v2, SQLAlchemy 2.1, Alembic, SQLite, jsonschema, httpx, uvicorn.
* **Frontend:** React 19, TypeScript 5.9 (strict), Vite 8, Tailwind CSS 4, TanStack Query, React Router, React Flow (`@xyflow/react`), Recharts, lucide icons.
* **Quality:** pytest (+coverage), ruff, mypy `--strict`, Vitest + React Testing Library, ESLint, Playwright, GitHub Actions.
* **Deployment:** Docker (non-root API image, nginx web image with CSP), Docker Compose, Render blueprint, static-host redirects.

All dependency versions are pinned (`backend/requirements*.txt`, `frontend/package-lock.json`).

## Windows setup

Prerequisites: Python 3.12+, Node.js 22+, PowerShell. Docker is optional.

```powershell
git clone <your-fork-url> agentvault
cd agentvault
.\scripts\setup.ps1      # creates backend\.venv, installs pinned deps, migrates and seeds SQLite
.\scripts\dev.ps1        # opens two windows: API + UI
```

* UI: http://127.0.0.1:5173
* API docs (Swagger): http://127.0.0.1:8000/api/docs
* Readiness: http://127.0.0.1:8000/api/v1/ready

If 8000 or 5173 is taken, run `.\scripts\dev.ps1 -ApiPort 8100 -WebPort 5180`. Then run
`.\scripts\demo.ps1 -Api http://127.0.0.1:8000` for a scripted walk-through, or follow
[docs/demo-script.md](docs/demo-script.md).

### Native development (manual)
```powershell
cd backend
python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
# second terminal
cd frontend; npm ci; npm run dev
```
The Vite dev server proxies `/api` to `AGENTVAULT_API_PROXY` (default `http://127.0.0.1:8000`).
Measured footprint on Windows: `frontend/node_modules` 260 MB, `backend/.venv` 112 MB. Playwright's
Chromium (only needed for E2E and screenshots) adds about 720 MB to `%LOCALAPPDATA%\ms-playwright`.

### Cleanup
`.\scripts\cleanup.ps1` removes build output, caches and local databases. `-All` also removes the
venv, `node_modules`, the Playwright browser and the compose images and volume.

## Docker

```powershell
docker compose up --build          # http://localhost:8090 (set AGENTVAULT_WEB_PORT to change)
docker compose down -v             # stop and delete the data volume
```
Only the nginx container publishes a port. It serves the SPA and proxies `/api` to the API container,
which runs as a non-root user with SQLite on the `agentvault-data` volume.

## Environment variables

All variables are optional; see [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `AGENTVAULT_DATABASE_URL` | `sqlite:///backend/data/agentvault.db` | SQLAlchemy URL |
| `AGENTVAULT_ENVIRONMENT` | `local` | `production` disables `/api/docs` |
| `AGENTVAULT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed origins (wildcards ignored) |
| `AGENTVAULT_API_TOKEN` | *(empty)* | When set, every endpoint except health/ready requires `Authorization: Bearer <token>` |
| `AGENTVAULT_OPERATOR_NAME` | `local-operator` | Name recorded on approval decisions |
| `AGENTVAULT_MAX_REQUEST_BYTES` | `262144` | Request body limit |
| `AGENTVAULT_MAX_STEPS` / `MAX_TOOL_CALLS` / `MAX_IDENTICAL_CALLS` | `40` / `20` / `3` | Runtime guards |
| `AGENTVAULT_APPROVAL_TTL_SECONDS` | `900` | Approval expiry |
| `AGENTVAULT_EXECUTION_TIMEOUT_SECONDS` | `30` | Active-time budget per execution |
| `AGENTVAULT_RETENTION_DAYS` | `30` | Eligibility for `python -m app.cli purge` |
| `AGENTVAULT_SEED_ON_STARTUP` | `true` | Seed tools, policies, scenarios at startup |
| `AGENTVAULT_LLM_BASE_URL` / `_API_KEY` / `_MODEL` | *(empty)* | Optional OpenAI-compatible adapter; disabled unless all three are set |
| `VITE_API_BASE_URL` | *(empty = same origin)* | Frontend build-time API base URL |

## API

Versioned REST under `/api/v1`. Errors use one envelope:
`{"error": {"code", "message", "details", "request_id"}}`. Lists use
`{"items", "total", "limit", "offset"}`. Every response carries `X-Request-ID`. Interactive docs are
at `/api/docs` outside production.

| Method & path | Purpose |
|---|---|
| `GET /health`, `GET /ready` | Liveness; readiness (DB reachable, migrations at head, seed data present) |
| `GET /stats` | Dashboard aggregates |
| `GET /tools`, `GET /tools/{id}`, `POST /tools` | Registry (filters: category, risk_level, q) |
| `GET /policies`, `POST /policies`, `GET /policies/{id}` | Policies with full version history |
| `GET /policies/{id}/versions/{v}`, `POST /policies/{id}/versions` | Immutable versions (`base_version` for optimistic concurrency) |
| `POST /policies/validate`, `/compare`, `/simulate` | Static analysis, diff + decision matrix, playground |
| `GET /scenarios`, `GET /scenarios/{id}`, `POST /scenarios` | Scenario fixtures and custom scenarios |
| `POST /executions`, `GET /executions`, `GET /executions/{id}` | Launch and search (status, scenario, policy, origin, q) |
| `GET /executions/{id}/events`, `/decisions`, `/audit/verify` | Event stream, decision records, chain and completeness |
| `POST /executions/{id}/cancel` | Cancel a pending or waiting execution |
| `GET /approvals`, `GET /approvals/{id}`, `POST /approvals/{id}/approve`, `/reject` | Queue, history and decisions |
| `POST /replays`, `GET /replays`, `GET /replays/{id}`, `POST /replays/compare` | Replay and divergence |
| `POST /evaluations`, `GET /evaluations`, `GET /evaluations/{id}` | Evaluation lab |
| `POST /reports`, `GET /reports`, `GET /reports/{id}?format=json\|markdown` | Exports |
| `GET /audit/events`, `GET /audit/decisions` | Cross-execution search |

## Tests

Commands and results from the final verification run on 2026-10-18 (Windows 11, Python 3.14.7, Node 22.23.2):

| Command | Result |
|---|---|
| `cd backend; .\.venv\Scripts\python -m pytest --cov=app` | **147 passed**, 93% line coverage |
| same suite on Python 3.12.14 and 3.13.15 | 147 passed on each |
| `ruff check .`, `ruff format --check .`, `mypy app` (strict) | clean |
| `cd frontend; npm test` (Vitest + RTL) | **30 passed** |
| `npm run lint`, `npm run typecheck`, `npm run build` | clean; main bundle 273 kB (87 kB gzip) |
| `npx playwright test e2e/workflow.spec.ts` (real backend + UI) | **3 passed** |
| `docker compose build` + API workflow via nginx + `node e2e/smoke-deployed.mjs` | passed, no console errors |

The backend tests cover tool registration, schema validation, policy precedence and every operator,
approval binding, expiry, rejection, idempotency, a four-thread concurrent approval race, audit ordering,
the tamper-detection limits, cancellation, loop/step/tool-call/timeout guards, replay determinism,
first divergence, policy comparison, metrics, expectation isolation, malformed input, request limits,
auth, CORS, the LLM adapter (mocked transport), retention and the CLI. The E2E suite drives the full
journey: launch → tool request → policy → pause → approve/reject → result → audit → replay → policy
comparison → export.

## Security and privacy limitations

Read [docs/security.md](docs/security.md) before exposing AgentVault beyond your machine. In short:
mock tools are a controlled simulation, not an isolation boundary. Local mode is single-user, and the
optional token is a shared secret, not user accounts. Hash chaining doesn't stop someone who can
rewrite the database file. Redaction is key-based. Prompt injection is contained by policy, not
prevented. Passing the synthetic suite is not a security guarantee. The optional LLM adapter sends
task text, tool schemas and this execution's tool results to the configured provider.

## Deployment

Verified locally and with Docker Compose. **No public deployment has been made**: hosting credentials
were not available. [docs/deployment.md](docs/deployment.md) has researched hosting options with their
current limits (Render free tier has no persistent disk; Fly.io volumes are paid; Cloudflare Pages or
Netlify for the SPA), ready-made configuration (`render.yaml`, `Dockerfile`s, `_redirects`) and the
commands to verify a deployment.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows "Cannot reach the AgentVault API" | Start the backend and check `/api/v1/ready`. If the API isn't on :8000, set `AGENTVAULT_API_PROXY` before `npm run dev`. |
| Port 8000/5173 already in use (e.g. by Docker containers) | `.\scripts\dev.ps1 -ApiPort 8100 -WebPort 5180`. Use `127.0.0.1` rather than `localhost` if an IPv6 listener owns the port. |
| `/api/v1/ready` returns 503 | Seed data is missing: `python -m app.cli seed`. |
| `401 unauthorized` | `AGENTVAULT_API_TOKEN` is set: enter it via **API token** in the sidebar, or send a bearer header. |
| `409 approval_binding_mismatch` | The decision did not echo the approval's own `execution_id` and `action_hash`. This is intended. |
| `409 approval_expired` | Approvals expire after 15 minutes by default. Relaunch, or raise `AGENTVAULT_APPROVAL_TTL_SECONDS`. |
| "database is locked" | Run only one API process per SQLite file. Don't open the DB in another tool while writing. |
| Playwright can't start servers | E2E uses ports 8000 and 5179 (`AGENTVAULT_E2E_API_PORT`, `AGENTVAULT_E2E_WEB_PORT`). Run `npx playwright install chromium` once. |

## Roadmap

* PostgreSQL backend with row-level locking, multi-process workers and per-dialect triggers.
* Real authentication (OIDC), roles, and separation of duties between launching and approving.
* External anchoring of audit head hashes (signed exports or a transparency log).
* A sandboxed out-of-process executor for real tools (containers or WASM) with network egress policies.
* Policy unit tests and CI gating of policy changes on evaluation regressions.
* An MCP (Model Context Protocol) gateway mode so existing agents can route tool calls through AgentVault.
* Streaming execution updates (SSE) instead of polling.

## License

[MIT](LICENSE). Contributions welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
