Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [switch]$Force
)

function Write-Info([string]$Message) {
    Write-Host "[icon-cache] $Message"
}

if ($env:OS -ne "Windows_NT") {
    throw "This script is intended for Windows only."
}

if (-not $Force) {
    $answer = Read-Host "This will restart Explorer and clear icon cache files. Continue? (y/N)"
    if ($answer -notin @("y", "Y", "yes", "YES")) {
        Write-Info "Cancelled by user."
        exit 0
    }
}

$explorerCacheDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Explorer"
$legacyIconCache = Join-Path $env:LOCALAPPDATA "IconCache.db"

Write-Info "Stopping explorer.exe"
Get-Process explorer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Info "Removing icon cache files"
if (Test-Path $explorerCacheDir) {
    Get-ChildItem -Path $explorerCacheDir -Filter "iconcache*" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

if (Test-Path $legacyIconCache) {
    Remove-Item $legacyIconCache -Force -ErrorAction SilentlyContinue
}

Write-Info "Starting explorer.exe"
Start-Process explorer.exe

Write-Info "Done. If taskbar icons still look stale, sign out and sign in once."
