# Contributing

Thanks for helping improve AgentVault.

## Development setup (Windows PowerShell)
```powershell
.\scripts\setup.ps1     # venv, pinned dependencies, migrations, seed data
.\scripts\dev.ps1       # API on :8000, UI on :5173 (use -ApiPort/-WebPort if those are taken)
.\scripts\test.ps1      # everything CI runs; add -E2E for Playwright
```
macOS/Linux: the same steps work with `python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.

## Ground rules
* **Authorisation code stays pure.** `services/policy_engine` must not read the database, agent
  claims or scenario expectations. If you need new policy inputs, add them to `PolicyContext` and
  explain in the PR why the agent cannot control them.
* **Every tool call goes through the runner.** Never add a path that executes a tool without a policy
  decision and audit events. `check_completeness` will catch it.
* **Audit tables are append-only.** Schema changes need an Alembic migration. Don't weaken the triggers.
* **No real side effects.** New tools are mocks over the per-execution sandbox.
* **Tests first for safety properties.** A change to approvals, policy precedence or replay needs a
  test that fails without it. Do not relax an existing test to make a change pass.
* **Report measured numbers only.** Regenerate `benchmarks/results` with `python -m app.cli evaluate`
  rather than editing them by hand.

## Style
* Backend: `ruff check`, `ruff format`, `mypy --strict` (configured in `backend/pyproject.toml`).
* Frontend: ESLint (`--max-warnings 0`), TypeScript strict, accessible components (labels, roles, keyboard support).

## Adding a scenario
Create `scenarios/<demo|adversarial>/NN-name.json` (see existing files). Label every action in
`expectations` and keep `human_script` separate from `spec`. Bump `version` when you change an
existing scenario: content hashes are checked.

## Commits and pull requests
Small, focused commits with imperative messages (`Add loop guard for identical tool calls`). Describe
the safety impact of the change in the PR.
