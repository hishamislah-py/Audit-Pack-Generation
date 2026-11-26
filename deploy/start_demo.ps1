<#
.SYNOPSIS
  Starts the UC-042 analyst application (Smart Parser + analyst web app + UC-042 engine) from this repository.
  Every path defaults to the repository or its ignored .runtime\ folder; nothing outside the clone is needed.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\start_demo.ps1
  powershell -ExecutionPolicy Bypass -File deploy\start_demo.ps1 -Port 8960 -Workspace D:\uc042\ws -Theme dark
#>
param(
    [int]$Port = 8780,
    [string]$Workspace = "",               # default .runtime\ws (created if missing)
    [string]$AuthFile = "",                # default .runtime\auth.json (create with deploy\create_user.ps1)
    [string]$EnvFile = "",                 # default .runtime\.env; only OPENAI_API_KEY and UC042_LLM_* are read from it
    [string]$ReviewerId = "analyst@ringfence.demo",
    [int]$AiMaxRequests = 5,               # hard cap of OpenAI requests per AI operation
    [ValidateSet("light", "dark")][string]$Theme = "light",
    [switch]$NoRelationshipDiscovery       # the demo runs the engine's relationship discovery (default on)
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "No .venv found. Run deploy\setup.ps1 first." }

$Runtime = Join-Path $Repo ".runtime"
if (-not $Workspace) { $Workspace = Join-Path $Runtime "ws" }
if (-not $AuthFile) { $AuthFile = Join-Path $Runtime "auth.json" }
if (-not $EnvFile) { $EnvFile = Join-Path $Runtime ".env" }
if (-not (Test-Path $AuthFile)) { throw "No auth file at $AuthFile. Run deploy\create_user.ps1 <email> first." }

$ServerArgs = @(
    "-B", "-m", "smartparser.webapp.server",
    "--root", $Workspace,
    # Demo-only authority policy (TEST_ONLY, provisional roles). A production deployment needs an approved policy.
    "--authority", (Join-Path $Repo "app\tests\fixtures\review\test_authority_policy.json"),
    "--uc042-root", (Join-Path $Repo "uc042"),
    "--reviewer-id", $ReviewerId, "--reviewer-role", "analyst", "--reviewer-kind", "TEST",
    "--auth-file", $AuthFile,
    "--port", "$Port",
    "--demo-scenarios", (Join-Path $Repo "demo_datasets\ringfence_demo_scenarios"),
    "--closure-python", $Py,
    "--ai-max-requests-per-operation", "$AiMaxRequests",
    "--mapping-ai", "off",
    "--default-theme", $Theme
)
$HasKey = (Test-Path $EnvFile) -and (Select-String -Path $EnvFile -Pattern '^\s*OPENAI_API_KEY\s*=\s*\S' -Quiet)
if ($HasKey) {
    $ServerArgs += @("--ai-env-file", $EnvFile)
    Write-Host "AI investigations: ON (key read from $EnvFile; evidence for each exception is sent to OpenAI with store:false)"
} elseif (Test-Path $EnvFile) {
    Write-Host "AI investigations: OFF ($EnvFile has no OPENAI_API_KEY value). Reconciliation, review and audit packs work without AI."
} else {
    Write-Host "AI investigations: OFF (no $EnvFile). Reconciliation, review and audit packs work without AI."
}
if (-not $NoRelationshipDiscovery) { $env:RINGFENCE_ENGINE_RELATIONSHIP_DISCOVERY = "on" }

Write-Host "Starting on http://127.0.0.1:$Port/analyst/  (workspace: $Workspace)"
Push-Location (Join-Path $Repo "app")
try {
    & $Py @ServerArgs
} finally { Pop-Location }
