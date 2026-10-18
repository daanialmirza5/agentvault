# Reproducible API demo against a running backend. Prints each step of the approval workflow.
#   .\scripts\demo.ps1 [-Api http://127.0.0.1:8000] [-Token <bearer token if configured>]
param([string]$Api = "http://127.0.0.1:8000", [string]$Token = "")
$ErrorActionPreference = "Stop"
$base = "$Api/api/v1"
$headers = @{}
if ($Token) { $headers["Authorization"] = "Bearer $Token" }
function Post($path, $body) {
  Invoke-RestMethod "$base$path" -Method Post -ContentType "application/json" -Headers $headers -Body ($body | ConvertTo-Json -Depth 10)
}
function Get-Api($path) { Invoke-RestMethod "$base$path" -Headers $headers }

Write-Host "1. Readiness:" (Invoke-RestMethod "$base/ready").status

Write-Host "2. Unauthorised tools are denied (scenario: unauthorized-tool-call)"
$denied = Post "/executions" @{ scenario_id = "unauthorized-tool-call" }
(Get-Api "/executions/$($denied.id)/decisions") | ForEach-Object { "   {0,-28} {1,-17} {2}" -f $_.tool_id, $_.outcome, $_.deciding_rule }

Write-Host "3. A legitimate email pauses for approval (scenario: enterprise-follow-up)"
$exec = Post "/executions" @{ scenario_id = "enterprise-follow-up" }
Write-Host "   status:" $exec.status
$approval = (Get-Api "/approvals?execution_id=$($exec.id)&status=pending").items[0]
Write-Host "   pending approval:" $approval.id "for" $approval.tool_id "(risk" $approval.risk_level ")"

Write-Host "4. Replaying the approval against another execution is refused"
try { Post "/approvals/$($approval.id)/approve" @{ execution_id = $denied.id; action_hash = $approval.action_hash } | Out-Null }
catch { Write-Host "   refused:" ($_.ErrorDetails.Message | ConvertFrom-Json).error.code }

Write-Host "5. Approving the exact action resumes the execution"
$result = Post "/approvals/$($approval.id)/approve" @{ execution_id = $exec.id; action_hash = $approval.action_hash; note = "demo" }
Write-Host "   execution status:" $result.execution.status

Write-Host "6. Audit trail integrity"
$verify = Get-Api "/executions/$($exec.id)/audit/verify"
Write-Host "   hash chain valid:" $verify.chain.valid " complete:" $verify.completeness.complete " events:" $verify.chain.event_count

Write-Host "7. Replay under the strict policy and find the first divergence"
$replay = Post "/replays" @{ execution_id = $exec.id; mode = "simulate"; policy_id = "strict-lockdown" }
Write-Host "  " $replay.result.divergence.explanation

Write-Host "8. Export a Markdown report"
$report = Post "/reports" @{ kind = "execution"; subject_id = $exec.id }
Write-Host "   $base/reports/$($report.id)?format=markdown"
Write-Host "Open the UI to explore execution $($exec.id)."
