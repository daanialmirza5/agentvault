# One-time local setup on Windows (PowerShell 7+ or Windows PowerShell 5.1).
# Creates backend/.venv, installs pinned Python and Node dependencies, applies migrations and seeds data.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "==> Backend (Python 3.12+)"
Push-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m app.cli seed
Pop-Location

Write-Host "==> Frontend (Node 22+)"
Push-Location "$root\frontend"
npm ci --no-audit --no-fund
Pop-Location

Write-Host "Setup complete. Start the app with: .\scripts\dev.ps1"
