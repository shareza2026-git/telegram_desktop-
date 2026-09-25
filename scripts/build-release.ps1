[CmdletBinding()]
param(
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $RepoRoot "frontend"
$TauriRoot = Join-Path $FrontendRoot "src-tauri"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PortableConfig = Join-Path $RepoRoot "telegram-portable.json"
$ReleaseRoot = Join-Path $RepoRoot "release"
$SidecarSource = Join-Path $RepoRoot "dist\telegram-desktop-backend.exe"
$SidecarTarget = Join-Path $TauriRoot "binaries\telegram-desktop-backend-x86_64-pc-windows-msvc.exe"

if (-not (Test-Path $Python)) {
    throw "Python virtual environment is missing. Run .\scripts\setup-dev.ps1 first."
}
if (-not (Test-Path $PortableConfig)) {
    throw "telegram-portable.json is missing from the repository root. Export it before building the release."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not installed."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo is not installed."
}

Write-Host "Preparing Telegram Desktop release $Version ..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    & $Python -m pip install -e ".[test,package]"
    if ($LASTEXITCODE -ne 0) { throw "Backend dependencies failed to install." }

    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }

    & $Python -m PyInstaller --noconfirm --clean --onefile --name telegram-desktop-backend --collect-all uvicorn app/desktop.py
    if ($LASTEXITCODE -ne 0) { throw "Backend sidecar build failed." }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force (Split-Path -Parent $SidecarTarget) | Out-Null
Copy-Item $SidecarSource $SidecarTarget -Force

Push-Location $FrontendRoot
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm install failed." }

    & npm test
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }

    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

    & npm run tauri build -- --config src-tauri/tauri.windows.conf.json
    if ($LASTEXITCODE -ne 0) { throw "Tauri installer build failed." }
} finally {
    Pop-Location
}

$InstallerDir = Join-Path $TauriRoot "target\release\bundle\nsis"
$Installer = Get-ChildItem $InstallerDir -Filter "*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $Installer) {
    throw "NSIS installer was not produced."
}

if (Test-Path $ReleaseRoot) {
    Remove-Item $ReleaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Force $ReleaseRoot | Out-Null

$FinalInstaller = Join-Path $ReleaseRoot "Telegram-Desktop-Setup-$Version.exe"
Copy-Item $Installer.FullName $FinalInstaller -Force
Copy-Item $PortableConfig (Join-Path $ReleaseRoot "telegram-portable.json") -Force

$XrayCandidates = @(
    (Join-Path $RepoRoot "xray.exe"),
    (Join-Path $RepoRoot "data\tools\xray\xray.exe")
)
$Xray = $XrayCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Xray) {
    Copy-Item $Xray (Join-Path $ReleaseRoot "xray.exe") -Force
}

$Readme = @"
Telegram Desktop release package

1. Run: Telegram-Desktop-Setup-$Version.exe
2. Keep telegram-portable.json private.
3. After install, copy telegram-portable.json next to the installed Telegram Desktop executable if it is not already present there.
4. If xray.exe is included, keep it next to the executable as well.
5. Updating by installing a newer setup over the old installation preserves AppData sessions/database/account state.
"@
Set-Content -Path (Join-Path $ReleaseRoot "README.txt") -Value $Readme -Encoding UTF8

Write-Host ""
Write-Host "Release package is ready:" -ForegroundColor Green
Write-Host $ReleaseRoot -ForegroundColor Green
Get-ChildItem $ReleaseRoot | Format-Table Name, Length, LastWriteTime
