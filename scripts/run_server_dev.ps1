#requires -Version 5.1
<#
.SYNOPSIS
  Run the AI server in dev mode with auto-reload on a fixed port.

.DESCRIPTION
  Starts uvicorn with --reload at http://127.0.0.1:8765 and opens it in the
  browser. This serves both the SPA and the JSON API.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$venvPython = Join-Path $env:LOCALAPPDATA "AIEssayTutor\venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "venv not found at $venvPython. Run .\scripts\bootstrap_server.ps1 first."
    exit 1
}

if (-not ($env:GEMINI_API_KEY)) {
    $configFile = Join-Path $env:APPDATA "AIEssayTutor\config.json"
    if (-not (Test-Path $configFile)) {
        Write-Warning "No GEMINI_API_KEY set and no config.json; /api calls will 503 until you add a key."
    }
}

# Wipe stale .pyc bytecode -- watchfiles can reload the .py but Python still
# uses the cached bytecode from the previous boot, leading to "I edited the
# fix but the server still has the old behaviour" mysteries.
$repoRoot = Split-Path -Parent $PSScriptRoot
Get-ChildItem -Path (Join-Path $repoRoot "server") -Directory -Recurse `
              -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force }

Write-Host "AI Essay Tutor (dev) - http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "  log:  $env:APPDATA\AIEssayTutor\server.log"
Write-Host "  Ctrl-C to stop`n"

$openFlag = if ($NoOpen) { @() } else { @('--open') }
& $venvPython -m aitutor_server.main --port $Port --reload @openFlag
