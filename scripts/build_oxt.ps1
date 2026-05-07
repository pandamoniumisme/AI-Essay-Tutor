#requires -Version 5.1
<#
.SYNOPSIS
  Zip extension/ into dist/AIEssayTutor.oxt.

.DESCRIPTION
  An .oxt is just a ZIP archive with a specific manifest layout. This script
  packs the entire extension/ tree, excluding __pycache__ folders.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repoRoot "extension"
$distDir = Join-Path $repoRoot "dist"
$out = Join-Path $distDir "AIEssayTutor.oxt"

if (-not (Test-Path $src)) {
    Write-Error "extension/ not found at $src"
    exit 1
}
if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
}
if (Test-Path $out) {
    Remove-Item $out -Force
}

Write-Host "Building $out ..." -ForegroundColor Cyan

# Stage to a clean temp dir so we can exclude __pycache__ before zipping.
$staging = Join-Path $env:TEMP "aitutor-oxt-build-$([Guid]::NewGuid().Guid.Substring(0,8))"
New-Item -ItemType Directory -Path $staging -Force | Out-Null
try {
    Get-ChildItem -Path $src -Recurse -Force | Where-Object {
        $_.FullName -notmatch "[\\/]__pycache__([\\/]|$)" -and
        $_.Name -notmatch "\.pyc$"
    } | ForEach-Object {
        $rel = $_.FullName.Substring($src.Length).TrimStart("\")
        $dst = Join-Path $staging $rel
        if ($_.PSIsContainer) {
            if (-not (Test-Path $dst)) {
                New-Item -ItemType Directory -Path $dst -Force | Out-Null
            }
        } else {
            $dstParent = Split-Path -Parent $dst
            if (-not (Test-Path $dstParent)) {
                New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
            }
            Copy-Item -Path $_.FullName -Destination $dst -Force
        }
    }

    # Build the archive entry-by-entry so we can force forward-slash paths.
    # Both Compress-Archive and ZipFile.CreateFromDirectory write backslashes
    # on Windows, which violates the ZIP spec -- unopkg (Java) rejects the
    # archive with "Zip entry has an invalid name".
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $fs = [System.IO.File]::Open($out, [System.IO.FileMode]::Create)
    try {
        $zip = New-Object System.IO.Compression.ZipArchive(
            $fs, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            $stagingFull = (Resolve-Path $staging).Path
            Get-ChildItem -Path $staging -Recurse -File -Force | ForEach-Object {
                $rel = $_.FullName.Substring($stagingFull.Length).TrimStart('\','/')
                $entryName = $rel -replace '\\', '/'
                $entry = $zip.CreateEntry(
                    $entryName, [System.IO.Compression.CompressionLevel]::Optimal)
                $stream = $entry.Open()
                try {
                    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
                    $stream.Write($bytes, 0, $bytes.Length)
                } finally {
                    $stream.Dispose()
                }
            }
        } finally {
            $zip.Dispose()
        }
    } finally {
        $fs.Dispose()
    }
    Write-Host "Built $out ($('{0:N0}' -f (Get-Item $out).Length) bytes)" -ForegroundColor Green
} finally {
    if (Test-Path $staging) {
        Remove-Item $staging -Recurse -Force
    }
}
