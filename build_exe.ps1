Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distDir = Join-Path $projectRoot "dist"
$bundleDir = Join-Path $distDir "TwitchDropFarmer"
$archivePath = Join-Path $distDir "TwitchDropFarmer-win64.zip"
$iconPath = Join-Path $projectRoot "src\twitch_drop_farmer\assets\icon.ico"
$assetsSource = Join-Path $projectRoot "src\twitch_drop_farmer\assets"
$assetsTarget = "twitch_drop_farmer\assets"
$specPath = Join-Path $projectRoot "TwitchDropFarmer.spec"

if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Using Python: $python"

& $python -m pip install --upgrade pip pyinstaller

if (Test-Path $archivePath) {
    Remove-Item $archivePath -Force
}

$legacyExePath = Join-Path $distDir "TwitchDropFarmer.exe"
if (Test-Path $legacyExePath) {
    Remove-Item $legacyExePath -Force
}

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", "TwitchDropFarmer",
    "--add-data", "$assetsSource;$assetsTarget",
    "--exclude-module", "tkinter",
    "--paths", (Join-Path $projectRoot "src")
)
if (Test-Path $iconPath) {
    $pyInstallerArgs += @("--icon", $iconPath)
}

$pyInstallerArgs += (Join-Path $projectRoot "TwitchDropFarmer.pyw")

& $python @pyInstallerArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path $bundleDir)) {
    throw "Expected build output folder was not created: $bundleDir"
}

& tar.exe -a -c -f $archivePath -C $distDir "TwitchDropFarmer"

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $archivePath)) {
    throw "ZIP archive creation failed: $archivePath"
}

if (Test-Path $specPath) {
    Remove-Item $specPath -Force
}

Write-Host ""
Write-Host "Build concluido. EXE em: $bundleDir\TwitchDropFarmer.exe"
Write-Host "Pacote ZIP em: $archivePath"
