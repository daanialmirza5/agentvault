# Runs every check that CI runs. Add -E2E to also run the Playwright suite (starts its own servers
# on ports 8000/5179 unless they are already running).
param([switch]$E2E)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
.\.venv\Scripts\ruff check .;            if ($LASTEXITCODE) { throw "ruff check failed" }
.\.venv\Scripts\ruff format --check .;   if ($LASTEXITCODE) { throw "ruff format failed" }
.\.venv\Scripts\mypy app;                if ($LASTEXITCODE) { throw "mypy failed" }
.\.venv\Scripts\python -m pytest;        if ($LASTEXITCODE) { throw "pytest failed" }
Pop-Location

Push-Location "$root\frontend"
npm run lint;      if ($LASTEXITCODE) { throw "eslint failed" }
npm run typecheck; if ($LASTEXITCODE) { throw "tsc failed" }
npm test;          if ($LASTEXITCODE) { throw "vitest failed" }
npm run build;     if ($LASTEXITCODE) { throw "build failed" }
if ($E2E) { npx playwright test e2e/workflow.spec.ts; if ($LASTEXITCODE) { throw "e2e failed" } }
Pop-Location
Write-Host "All checks passed."
