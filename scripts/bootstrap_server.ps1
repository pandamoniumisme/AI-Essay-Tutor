#requires -Version 5.1
<#
.SYNOPSIS
  One-time setup: create the AI server venv, install dependencies, fetch models.

.DESCRIPTION
  Creates a Python venv at %LOCALAPPDATA%\AIEssayTutor\venv, installs the
  server package (editable, so the developer can edit C:\AI-Essay-Tutor\server\
  in place), and runs the model manager to download + convert PP-OCRv5,
  Qwen3.5-9B (with Qwen3-8B fallback), and TrOCR (deferred, see manager.py).

  The model fetch step downloads ~7 GB from HuggingFace and runs the
  optimum-cli INT4 export for Qwen3.5-9B, which can take 20-40 minutes.

.PARAMETER SkipModels
  Skip the models.manager fetch step. Use this when re-running bootstrap
  after a code-only change.

.EXAMPLE
  .\scripts\bootstrap_server.ps1
  .\scripts\bootstrap_server.ps1 -SkipModels
#>
[CmdletBinding()]
param(
    [switch]$SkipModels
)

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

# --- 3. Fetch models ----------------------------------------------------
if ($SkipModels) {
    Write-Host "`nSkipping model fetch (-SkipModels)" -ForegroundColor Yellow
} else {
    Write-Host "`nFetching models - this can take 20-40 minutes for the Qwen3.5-9B INT4 conversion."
    & $venvPython -m aitutor_server.models.manager fetch
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "model manager exited with code $LASTEXITCODE; check %APPDATA%\AIEssayTutor\server.log"
    }
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "Run dev server:    .\scripts\run_server_dev.ps1"
Write-Host "Build/install OXT: .\scripts\build_oxt.ps1; .\scripts\install_oxt.ps1"
