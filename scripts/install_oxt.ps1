#requires -Version 5.1
<#
.SYNOPSIS
  Install dist/AIEssayTutor.oxt into LibreOffice via unopkg add --force.
#>
[CmdletBinding()]
param(
    [string]$LibreOffice = "C:\Program Files\LibreOffice"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$oxt = Join-Path $repoRoot "dist\AIEssayTutor.oxt"

if (-not (Test-Path $oxt)) {
    Write-Error "$oxt not found. Run .\scripts\build_oxt.ps1 first."
    exit 1
}

$unopkg = Join-Path $LibreOffice "program\unopkg.com"
if (-not (Test-Path $unopkg)) {
    Write-Error "unopkg.com not found at $unopkg. Pass -LibreOffice <install_dir> to override."
    exit 1
}

Write-Host "Installing $oxt ..." -ForegroundColor Cyan
& $unopkg add --force $oxt
if ($LASTEXITCODE -ne 0) {
    Write-Error "unopkg failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Done. Restart LibreOffice to pick up the extension." -ForegroundColor Green
