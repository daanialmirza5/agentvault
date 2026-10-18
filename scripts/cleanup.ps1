# Removes local build artefacts and data. Add -All to also remove installed dependencies,
# the Playwright browser cache and the Docker images/volume created by docker compose.
param([switch]$All)
$root = Split-Path -Parent $PSScriptRoot
$paths = @(
  "$root\backend\data", "$root\backend\.pytest_cache", "$root\backend\.mypy_cache", "$root\backend\.ruff_cache",
  "$root\frontend\dist", "$root\frontend\test-results", "$root\frontend\playwright-report"
)
if ($All) { $paths += @("$root\backend\.venv", "$root\frontend\node_modules") }
foreach ($p in $paths) { if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Host "removed $p" } }
Get-ChildItem $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
if ($All) {
  if (Get-Command npx -ErrorAction SilentlyContinue) { Push-Location "$root\frontend"; npx playwright uninstall 2>$null; Pop-Location }
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    Push-Location $root; docker compose down -v --rmi local 2>$null; Pop-Location
  }
}
Write-Host "Cleanup complete."
