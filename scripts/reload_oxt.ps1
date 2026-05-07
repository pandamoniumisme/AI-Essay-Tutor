#requires -Version 5.1
<#
.SYNOPSIS
  Hot-reload the extension during dev: build OXT, remove from LO, re-add.

.DESCRIPTION
  You still need to restart LibreOffice for sidebar/toolbar Python changes
  to take effect - UNO components are loaded once per LO process.
#>
[CmdletBinding()]
param(
    [string]$LibreOffice = "C:\Program Files\LibreOffice",
    [string]$IdentifierPrefix = "org.aitutor"
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$unopkg = Join-Path $LibreOffice "program\unopkg.com"

if (-not (Test-Path $unopkg)) {
    Write-Error "unopkg.com not found at $unopkg. Pass -LibreOffice <install_dir> to override."
    exit 1
}

Write-Host "Removing existing extension(s) matching $IdentifierPrefix ..." -ForegroundColor Cyan
$existing = & $unopkg list 2>&1 | Where-Object { $_ -match "Identifier:.*$IdentifierPrefix" }
foreach ($line in $existing) {
    if ($line -match "Identifier:\s*(\S+)") {
        $id = $Matches[1]
        Write-Host "  unopkg remove $id"
        & $unopkg remove $id
    }
}

Write-Host "`nBuilding + installing new OXT..."
& (Join-Path $PSScriptRoot "build_oxt.ps1")
& (Join-Path $PSScriptRoot "install_oxt.ps1") -LibreOffice $LibreOffice

Write-Host "`nRestart LibreOffice to pick up the changes." -ForegroundColor Yellow
