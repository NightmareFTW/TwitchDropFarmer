Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Using Python: $python"

& $python -m pip install --upgrade pip pyinstaller

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name TwitchDropFarmer `
    --paths (Join-Path $projectRoot "src") `
    (Join-Path $projectRoot "TwitchDropFarmer.pyw")

Write-Host ""
Write-Host "Build concluido. EXE em: $projectRoot\dist\TwitchDropFarmer.exe"
