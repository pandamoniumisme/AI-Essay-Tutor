#requires -Version 5.1
<#
.SYNOPSIS
  One-time setup: create the server venv and install dependencies.

.DESCRIPTION
  Creates a Python venv at %LOCALAPPDATA%\AIEssayTutor\venv and installs the
  server package (editable, so the developer can edit the server\ tree in
  place). Online inference goes to Hugging Face (Qwen3.5-9B), so there is NO
  multi-GB model download -- just set an HF_TOKEN (see the end of this script)
  and run the dev server.

.EXAMPLE
  .\scripts\bootstrap_server.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $env:LOCALAPPDATA "AIEssayTutor\venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

Write-Host "AI Essay Tutor - server bootstrap" -ForegroundColor Cyan
Write-Host "  repo:       $repoRoot"
Write-Host "  venv:       $venvDir"

# --- 1. Locate a system Python 3.11 or 3.12 -----------------------------
# Uses py (Python launcher) where available, then falls back to python3.x / python on PATH.
# Checks Get-Command first to avoid CommandNotFoundException under
# $ErrorActionPreference = 'Stop'. Also filters out the Microsoft Store stub
# python.exe in WindowsApps, which doesn't actually run Python and is on PATH
# by default on Windows 11.
function Test-PythonExe {
    param([string]$Path)
    # Stub at Microsoft\WindowsApps\python.exe is a 0-byte alias that opens the Store.
    if ($Path -match '\\WindowsApps\\python(\d.*)?\.exe$') {
        try {
            $size = (Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue).Length
            if ($size -lt 1024) { return $false }
        } catch {}
    }
    return $true
}

function Test-PythonVersion {
    param([string]$Exe, [string[]]$Prefix)
    try {
        $cmd = $Prefix + @('-c', 'import sys;print(sys.version_info.major,sys.version_info.minor)')
        $out = & $Exe @cmd 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $parts = ($out | Out-String).Trim().Split()
        if ($parts.Length -ge 2 -and $parts[0] -eq '3' -and ($parts[1] -in '11','12')) {
            return $parts[1]
        }
    } catch {}
    return $null
}

function Find-SystemPython {
    # Try the Python launcher first
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        foreach ($flag in @('-3.12', '-3.11')) {
            $minor = Test-PythonVersion -Exe 'py' -Prefix @($flag)
            if ($minor) { return @{ Exe = 'py'; Flag = $flag; Minor = $minor } }
        }
    }
    # Fallback: probe direct executables
    foreach ($exe in @('python3.12','python3.11','python')) {
        $found = Get-Command $exe -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        if (-not (Test-PythonExe -Path $found.Source)) { continue }
        $minor = Test-PythonVersion -Exe $exe -Prefix @()
        if ($minor) { return @{ Exe = $exe; Flag = ''; Minor = $minor } }
    }
    return $null
}

function Invoke-SystemPython {
    param([hashtable]$Py, [string[]]$Arguments)
    if ($Py.Flag) {
        & $Py.Exe $Py.Flag @Arguments
    } else {
        & $Py.Exe @Arguments
    }
}

if (-not (Test-Path $venvPython)) {
    $sysPy = Find-SystemPython
    if (-not $sysPy) {
        Write-Error @"
No Python 3.11 or 3.12 found on PATH.
Install Python 3.12 from https://www.python.org/downloads/ (check 'Add to PATH').
After install, re-run this script.
"@
        exit 1
    }
    $sysDesc = if ($sysPy.Flag) { "$($sysPy.Exe) $($sysPy.Flag)" } else { $sysPy.Exe }
    Write-Host "  using:      $sysDesc (Python 3.$($sysPy.Minor))" -ForegroundColor Green

    Write-Host "`nCreating venv..."
    $venvParent = Split-Path -Parent $venvDir
    if (-not (Test-Path $venvParent)) {
        New-Item -ItemType Directory -Path $venvParent -Force | Out-Null
    }
    Invoke-SystemPython -Py $sysPy -Arguments @('-m', 'venv', $venvDir)
    if ($LASTEXITCODE -ne 0) { Write-Error "venv creation failed"; exit 1 }
} else {
    Write-Host "  venv exists, reusing"
}

# --- 2. Install / upgrade the server package ----------------------------
Write-Host "`nUpgrading pip + wheel + setuptools..."
& $venvPython -m pip install --upgrade --quiet pip wheel setuptools
if ($LASTEXITCODE -ne 0) { Write-Error "pip upgrade failed"; exit 1 }

Write-Host "`nInstalling server package (editable)..."
& $venvPython -m pip install --editable (Join-Path $repoRoot "server")
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

# --- 3. Hugging Face token reminder -------------------------------------
$configFile = Join-Path $env:APPDATA "AIEssayTutor\config.json"
if (-not ($env:HF_TOKEN) -and -not (Test-Path $configFile)) {
    Write-Host "`nNo Hugging Face token found." -ForegroundColor Yellow
    Write-Host "Set one before running the server, e.g.:"
    Write-Host '    $env:HF_TOKEN = "hf_your-token-here"' -ForegroundColor Gray
    Write-Host "  or create $configFile with:"
    Write-Host '    { "hf_token": "hf_your-token-here" }' -ForegroundColor Gray
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "Run dev server: .\scripts\run_server_dev.ps1   (opens http://127.0.0.1:8765)"
