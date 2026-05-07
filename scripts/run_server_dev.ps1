#requires -Version 5.1
<#
.SYNOPSIS
  Run the AI server in dev mode with auto-reload on a fixed port.

.DESCRIPTION
  Starts uvicorn with --reload at http://127.0.0.1:8765. This is the dev path -
  the production path is auto-spawn from the LO extension on an ephemeral port.

  Sidebar "Advanced" pane in the extension lets you point at this fixed dev port.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$SkipModelFetch
)

$ErrorActionPreference = "Stop"
$venvPython = Join-Path $env:LOCALAPPDATA "AIEssayTutor\venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "venv not found at $venvPython. Run .\scripts\bootstrap_server.ps1 first."
    exit 1
}

if ($SkipModelFetch) {
    $env:AITUTOR_SKIP_MODEL_FETCH = "1"
}

# Wipe stale .pyc bytecode -- watchfiles can reload the .py but Python still
# uses the cached bytecode from the previous boot, leading to "I edited the
# fix but the server still has the old behaviour" mysteries.
$repoRoot = Split-Path -Parent $PSScriptRoot
Get-ChildItem -Path (Join-Path $repoRoot "server") -Directory -Recurse `
              -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force }

Write-Host "AI Essay Tutor server (dev) - http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "  log:  $env:APPDATA\AIEssayTutor\server.log"
Write-Host "  Ctrl-C to stop`n"

& $venvPython -m aitutor_server.main --port $Port --reload
