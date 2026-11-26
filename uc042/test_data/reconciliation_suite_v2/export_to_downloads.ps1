<#
.SYNOPSIS
  Copy the UC-042 Reconciliation Test Suite V2 into a new folder under the user's Downloads directory.

.DESCRIPTION
  Never overwrites: if the target folder already exists, the script stops without copying anything.
  After copying, every file's SHA-256 is compared between source and target.
  Windows PowerShell 5.1 compatible.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\export_to_downloads.ps1
  powershell -ExecutionPolicy Bypass -File .\export_to_downloads.ps1 -TargetName UC042_RECONCILIATION_TEST_SUITE_V2_copy2
#>
param(
    [string]$Source = $PSScriptRoot,
    [string]$TargetName = "UC042_RECONCILIATION_TEST_SUITE_V2"
)

$ErrorActionPreference = "Stop"
$downloads = Join-Path $env:USERPROFILE "Downloads"
$target = Join-Path $downloads $TargetName

if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    Write-Error "Source folder not found: $Source"
    exit 1
}
if (Test-Path -LiteralPath $target) {
    Write-Error "Target already exists and will NOT be overwritten: $target. Choose another -TargetName."
    exit 1
}

Copy-Item -LiteralPath $Source -Destination $target -Recurse

$srcFiles = Get-ChildItem -LiteralPath $Source -Recurse -File
$bad = 0
foreach ($f in $srcFiles) {
    $rel = $f.FullName.Substring($Source.TrimEnd('\').Length + 1)
    $t = Join-Path $target $rel
    if (-not (Test-Path -LiteralPath $t)) { Write-Warning "missing: $rel"; $bad++; continue }
    if ((Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $t -Algorithm SHA256).Hash) {
        Write-Warning "hash differs: $rel"; $bad++
    }
}
if ($bad -gt 0) {
    Write-Error "$bad file(s) failed verification in $target"
    exit 1
}
Write-Output "Copied and verified $($srcFiles.Count) files to $target"
