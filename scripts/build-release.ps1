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
$BuildTemp = Join-Path $RepoRoot ".build-temp"
$PytestTemp = Join-Path $RepoRoot ".pytest-release"

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

# Avoid Windows user Temp ACL issues (for example pytest-of-IT access denied).
# Keep all release temporary files inside the repository instead.
foreach ($Path in @($BuildTemp, $PytestTemp)) {
    if (Test-Path $Path) {
        Remove-Item $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force $Path | Out-Null
}
$PreviousTemp = $env:TEMP
$PreviousTmp = $env:TMP
$env:TEMP = $BuildTemp
$env:TMP = $BuildTemp

Push-Location $RepoRoot
try {
    & $Python -m pip install -e ".[test,package]"
    if ($LASTEXITCODE -ne 0) { throw "Backend dependencies failed to install." }

    & $Python -m pytest -q --basetemp $PytestTemp
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }

    & $Python -m PyInstaller --noconfirm --clean --onefile --name telegram-desktop-backend --collect-all uvicorn app/desktop.py
    if ($LASTEXITCODE -ne 0) { throw "Backend sidecar build failed." }
} finally {
    Pop-Location
    $env:TEMP = $PreviousTemp
    $env:TMP = $PreviousTmp
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

$InstallHelper = @'
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Setup = Get-ChildItem $Here -Filter "Telegram-Desktop-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Setup) { throw "Telegram Desktop setup was not found." }

Start-Process -FilePath $Setup.FullName -Wait

$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Telegram Desktop\Telegram Desktop.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Telegram Desktop\Telegram Desktop.exe")
)
$InstalledExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $InstalledExe) {
    $InstalledExe = Get-ChildItem $env:LOCALAPPDATA -Filter "Telegram Desktop.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $InstalledExe) {
    throw "Telegram Desktop was installed but its executable could not be located."
}

$InstallDir = Split-Path -Parent $InstalledExe
$PortableSource = Join-Path $Here "telegram-portable.json"

# The NSIS installer may launch the app immediately. Stop that first launch so
# the next startup sees the portable account bundle from the very beginning.
Get-Process -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -and ([System.IO.Path]::GetFullPath($_.Path) -eq [System.IO.Path]::GetFullPath($InstalledExe)) }
    catch { $false }
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# Keep a copy beside the installed executable (portable bootstrap/mirror).
Copy-Item $PortableSource (Join-Path $InstallDir "telegram-portable.json") -Force

# Also seed the persistent Tauri data location before relaunch. Tauri uses the
# stable identifier local.telegram.desktop, so future upgrades reuse this copy.
$PersistentRoots = @(
    (Join-Path $env:APPDATA "local.telegram.desktop"),
    (Join-Path $env:LOCALAPPDATA "local.telegram.desktop")
)
foreach ($Root in $PersistentRoots) {
    if (-not $Root) { continue }
    $PortableDir = Join-Path $Root "portable"
    New-Item -ItemType Directory -Force $PortableDir | Out-Null
    Copy-Item $PortableSource (Join-Path $PortableDir "telegram-portable.json") -Force
}

$Xray = Join-Path $Here "xray.exe"
if (Test-Path $Xray) {
    Copy-Item $Xray (Join-Path $InstallDir "xray.exe") -Force
}

# Relaunch only after credentials/configuration are in place.
Start-Process -FilePath $InstalledExe

Write-Host "Telegram Desktop is ready." -ForegroundColor Green
Write-Host "Installed at: $InstallDir"
Write-Host "Portable account configuration seeded before first launch."
'@
Set-Content -Path (Join-Path $ReleaseRoot "Install-Telegram-Desktop.ps1") -Value $InstallHelper -Encoding UTF8

$InstallCmd = '@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Telegram-Desktop.ps1"
pause
'
Set-Content -Path (Join-Path $ReleaseRoot "INSTALL.cmd") -Value $InstallCmd -Encoding ASCII

$Readme = @"
Telegram Desktop release package

Recommended:
1. Double-click INSTALL.cmd.
2. The installer runs normally.
3. telegram-portable.json is copied beside the installed Telegram Desktop executable automatically.
4. xray.exe is also copied automatically when present in this package.
5. Keep telegram-portable.json private; it contains Telegram authorization credentials.

Updates:
- Build a newer release package and run INSTALL.cmd again.
- The new application replaces the old application files.
- Existing AppData session/database/account state is preserved.
- The portable account file remains synchronized by the application.
"@
Set-Content -Path (Join-Path $ReleaseRoot "README.txt") -Value $Readme -Encoding UTF8

Write-Host ""
Write-Host "Release package is ready:" -ForegroundColor Green
Write-Host $ReleaseRoot -ForegroundColor Green
Get-ChildItem $ReleaseRoot | Format-Table Name, Length, LastWriteTime
