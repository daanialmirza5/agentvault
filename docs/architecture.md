# Architecture

AgentVault is a FastAPI backend with a React frontend. Authorization, execution, persistence and presentation
are separate layers, and a single execution loop (the **runner**) is shared by live runs, replays and
evaluations.

## Component view

```mermaid
flowchart LR
  subgraph Browser
    UI[React SPA<br/>dashboard · executions · approvals · replay · policies · tools · evaluations · audit]
  end
  subgraph API["FastAPI (backend/app)"]
    MW[Middleware<br/>request IDs · body limit · CORS · security headers]
    R[Routes /api/v1]
    MW --> R
  end
  subgraph Services
    ENG[Live engine<br/>agent_runtime/engine.py]
    RUN[Runner<br/>agent_runtime/runner.py]
    AG[Agents<br/>scripted · reactive · optional LLM]
    REG[Tool registry<br/>schemas · versions · mocks]
    POL[Policy engine<br/>pure, deterministic]
    APR[Approval service]
    AUD[Audit log<br/>hash chain · integrity]
    REP[Replay engine]
    EVAL[Evaluator + metrics]
    RPT[Reports]
  end
  DB[(SQLite<br/>append-only triggers)]
  SB[[Per-execution mock sandbox]]

  UI -- JSON over HTTP --> MW
  R --> ENG & APR & REP & EVAL & RPT & REG & POL
  ENG --> RUN
  REP --> RUN
  EVAL --> ENG & APR & REP
  RUN --> AG & REG & POL
  RUN -- events --> AUD
  RUN -- tool calls --> SB
  ENG & APR & AUD & RPT --> DB
```

| Module | Responsibility | Never does |
|---|---|---|
| `services/tool_registry` | Versioned tool definitions, JSON Schema validation, timeout-bounded mock execution on a copy of the sandbox | Run real side effects, register executable code |
| `services/policy_engine` | Pure `evaluate(document, tool, arguments, context) -> Decision`; static analysis (conflicts, shadowing, diffs) | Read agent claims, expectations or the database |
| `services/agent_runtime` | Agents (pure state machines), the runner, and the live engine that persists state | Execute a tool without a policy decision |
| `services/approval_engine` | Binding-checked, single-use, expiring human decisions with database-level serialization | Approve on behalf of a human |
| `services/audit` | Append-only hash-chained events, verification, completeness invariants | Update or delete events |
| `services/replay` | Recorded timelines and isolated simulations; first-divergence detection | Touch live executions, approvals or external systems |
| `services/evaluation` | Scenario loading, the simulated human, scoring and metrics | Pass expectations to the engine |

## How a tool call flows

```mermaid
sequenceDiagram
  autonumber
  participant A as Agent
  participant R as Runner
  participant T as Tool registry
  participant P as Policy engine
  participant G as Approval gate
  participant H as Human (UI/API)
  participant S as Mock sandbox
  participant L as Audit log

  R->>A: decide(state)
  A-->>R: ToolCall(tool_id, arguments, claims)
  R->>L: agent.action_proposed (claims recorded, not trusted)
  R->>R: guards: tool-call limit, identical-call loop detection
  R->>L: tool.requested (action_hash binds execution+step+tool+args)
  R->>T: lookup + JSON Schema validation
  R->>L: tool.arguments_validated / tool.arguments_rejected
  R->>P: evaluate(policy version, tool, arguments, context)
  P-->>R: allow | deny | require_approval (+ matched rules, trace)
  R->>L: policy.evaluated (+ immutable decision record)
  alt deny
    R->>L: tool.blocked
  else require_approval
    R->>G: request(pending action)
    G->>L: approval.requested — execution pauses (waiting_for_approval)
    H->>G: approve/reject {execution_id, action_hash}
    G->>G: BEGIN IMMEDIATE · binding check · expiry check · claim pending→decided
    G->>R: resume(resolution)
    R->>L: approval.granted / approval.rejected / approval.expired
  end
  opt allowed or approved
    R->>S: run mock on a copy of the sandbox (timeout)
    R->>L: tool.executed + tool.result / tool.failed
    R->>A: observe(result) — output marked untrusted for LLM agents
  end
  R->>L: execution.completed / failed / blocked / cancelled
```

## Policy evaluation flow

```mermaid
flowchart TD
  start([Tool call proposed]) --> known{Tool registered<br/>and enabled?}
  known -- no --> d1[DENY<br/>builtin:unknown_tool]
  known -- yes --> valid{Arguments match<br/>input schema?}
  valid -- no --> d2[DENY<br/>builtin:invalid_arguments]
  valid -- yes --> match[Collect every enabled rule whose<br/>tool · category · risk · operation ·<br/>environment · tags · argument conditions match]
  match --> any{Any match?}
  any -- no --> def[Policy default effect<br/>builtin:default_effect]
  any -- yes --> win[Deny-overrides:<br/>deny > require_approval > allow<br/>priority orders same-effect rules]
  win --> floor{Outcome allow and tool<br/>declares requires_approval?}
  def --> floor
  floor -- yes --> appr[REQUIRE APPROVAL<br/>builtin:tool_requires_approval]
  floor -- no --> out([Decision + matched rules + trace])
  appr --> out
```

Agent "claims" (for example `{"safe": true, "pre_approved": true}`) are not parameters of
`evaluate()`, so they cannot affect the outcome. A unit test and the prompt-injection scenario check this.

## Persistence model

* `tools`, `policies` / `policy_versions` (immutable, content-hashed), `scenarios` (versioned, content-hashed).
* `executions`: run state, including the serialized agent state and per-execution sandbox, so a
  paused run can resume in a different request.
* `audit_events` and `policy_decisions` are append-only. SQLite triggers abort `UPDATE` and only
  allow `DELETE` after a `retention_purges` row authorises it. An ORM guard also rejects mutation.
* `approvals`: bound by `action_hash` and made single-use by `consumed_at`.
* `replays`, `evaluations`, `reports`: derived artefacts that keep references to the IDs they cite.

## Concurrency model

SQLite with WAL mode. Write-capable sessions begin with `BEGIN IMMEDIATE`, so writers queue
instead of failing with `SQLITE_BUSY` on lock upgrade. Read-only endpoints use `DEFERRED`
transactions and never wait for writers. An approval decision claims the approval
(`status='pending'`) and then the execution (`status='waiting_for_approval'`) with conditional
updates, so of N concurrent decisions exactly one resumes the execution. A four-thread test
checks this.

The deployment model is **one application process per database**: startup recovery marks
executions left `running` by a crashed process as failed.
