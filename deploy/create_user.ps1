<#
.SYNOPSIS
  Creates (or changes the password of) a sign-in account for the analyst application. The password is prompted for and
  stored only as a PBKDF2 hash in the auth file (default .runtime\auth.json, ignored by git).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\create_user.ps1 analyst@ringfence.demo
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Username,
    [string]$AuthFile = "",
    [string]$PasswordEnv = ""     # scripted setups: name of an environment variable holding the password (no prompt)
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "No .venv found. Run deploy\setup.ps1 first." }
if (-not $AuthFile) { $AuthFile = Join-Path $Repo ".runtime\auth.json" }
New-Item -ItemType Directory -Force (Split-Path -Parent $AuthFile) | Out-Null

Push-Location (Join-Path $Repo "app")
try {
    $AuthArgs = @("-m", "smartparser.webapp.auth", "set-password", "--file", $AuthFile, "--username", $Username)
    if ($PasswordEnv) { $AuthArgs += @("--password-env", $PasswordEnv) }
    & $Py @AuthArgs
    if ($LASTEXITCODE -ne 0) { throw "set-password failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }
Write-Host "Account $Username saved in $AuthFile"
