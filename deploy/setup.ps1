<#
.SYNOPSIS
  One-time setup of the UC-042 demo from a fresh clone: Python 3.11 virtual environment (.venv at the repository root),
  engine + application dependencies, and (optionally) a rebuild of the analyst UI.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\setup.ps1
  powershell -ExecutionPolicy Bypass -File deploy\setup.ps1 -Python "C:\Python311\python.exe" -BuildUi
#>
param(
    [string]$Python = "",      # a Python 3.11 interpreter; default: the py launcher (py -3.11)
    [switch]$BuildUi           # rebuild app/smartparser/webapp/analyst from app/ringfence-analyst-app (needs Node 20.19+)
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "failed (exit $LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

# 1. Python 3.11
if (-not $Python) {
    try { $Python = (& py -3.11 -c "import sys; print(sys.executable)").Trim() } catch { $Python = "" }
}
if (-not $Python) { throw "Python 3.11 not found. Install it, or pass -Python <path to python.exe>." }
Invoke-Checked $Python @("-c", "import sys; assert sys.version_info[:2] == (3, 11), 'Python 3.11 required, found ' + sys.version")

# 2. Virtual environment
$Venv = Join-Path $Repo ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) { Invoke-Checked $Python @("-m", "venv", $Venv) }
Invoke-Checked $Py @("-m", "pip", "install", "--upgrade", "pip")

# 3. Engine dependencies (pinned) + application (Smart Parser and analyst web app, with its API and test extras)
Invoke-Checked $Py @("-m", "pip", "install", "-r", (Join-Path $Repo "uc042\requirements-dev.txt"))
Invoke-Checked $Py @("-m", "pip", "install", "-e", ((Join-Path $Repo "app") + "[api,dev]"))

# 4. SQLAlchemy on machines whose Application Control blocks unsigned DLLs: use the pure-Python wheel
#    (same version; see uc042/requirements-api.txt and uc042/docs/audit_pack/11_PHASE4_MONTHLY_DOCUMENTS.md).
$Previous = $ErrorActionPreference; $ErrorActionPreference = "Continue"   # Windows PowerShell 5.1: native stderr is not fatal
& $Py -c "import sqlalchemy" 2>$null
$SqlAlchemyOk = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $Previous
if (-not $SqlAlchemyOk) {
    Write-Host "SQLAlchemy compiled extension blocked; installing the pure-Python wheel"
    $Wheels = Join-Path $Repo ".runtime\wheels"
    Invoke-Checked $Py @("-m", "pip", "download", "sqlalchemy==2.1.6", "--only-binary=:all:", "--platform", "any",
                         "--python-version", "3.11", "--implementation", "py", "--no-deps", "-d", $Wheels)
    Invoke-Checked $Py @("-m", "pip", "install", "--force-reinstall", "--no-deps",
                         (Join-Path $Wheels "sqlalchemy-2.1.6-py3-none-any.whl"))
}
Invoke-Checked $Py @("-c", "import sqlalchemy, fastapi, openai, langgraph, pypdf, reportlab, smartparser; print('Python dependencies OK')")

# 5. Optional: rebuild the analyst UI (the built bundle is already committed under app/smartparser/webapp/analyst)
if ($BuildUi) {
    Push-Location (Join-Path $Repo "app\ringfence-analyst-app")
    try {
        Invoke-Checked "npm.cmd" @("ci")
        Invoke-Checked "npm.cmd" @("run", "build:backend")
    } finally { Pop-Location }
}

# 6. Local runtime folder (ignored by git): workspace, auth file, optional AI env file
New-Item -ItemType Directory -Force (Join-Path $Repo ".runtime") | Out-Null
Write-Host ""
Write-Host "Setup complete. Next:"
Write-Host "  1. deploy\create_user.cmd analyst@ringfence.demo      (creates .runtime\auth.json)"
Write-Host "  2. optional, for AI investigations: copy deploy\demo.env.example to .runtime\.env and set OPENAI_API_KEY"
Write-Host "  3. deploy\start_demo.cmd                               (then open http://127.0.0.1:8780/analyst/)"
