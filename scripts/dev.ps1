# Starts the backend (http://127.0.0.1:8000) and the frontend dev server (http://127.0.0.1:5173)
# in two new windows. Ports can be changed if they are already taken on your machine.
param([int]$ApiPort = 8000, [int]$WebPort = 5173)
$root = Split-Path -Parent $PSScriptRoot
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }

Start-Process $shell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port $ApiPort --reload"
Start-Process $shell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$root\frontend'; `$env:AGENTVAULT_API_PROXY='http://127.0.0.1:$ApiPort'; npm run dev -- --host 127.0.0.1 --port $WebPort --strictPort"

Write-Host "API:      http://127.0.0.1:$ApiPort/api/docs"
Write-Host "Web UI:   http://127.0.0.1:$WebPort"
