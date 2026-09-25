[CmdletBinding()]
param(
    [string]$Version = "0.1.7"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $RepoRoot "frontend"
$TauriRoot = Join-Path $FrontendRoot "src-tauri"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SessionSeed = Join-Path $RepoRoot "data\telegram_desktop\accounts\default\client.session"
$LegacyPortableConfig = Join-Path $RepoRoot "telegram-portable.json"
$ReleaseRoot = Join-Path $RepoRoot "release"
$SidecarSource = Join-Path $RepoRoot "dist\telegram-desktop-backend.exe"
$SidecarTarget = Join-Path $TauriRoot "binaries\telegram-desktop-backend-x86_64-pc-windows-msvc.exe"
$BuildTemp = Join-Path $RepoRoot ".build-temp"
$PytestTemp = Join-Path $RepoRoot ".pytest-release"

if (-not (Test-Path $Python)) {
    throw "Python virtual environment is missing. Run .\scripts\setup-dev.ps1 first."
}
if (-not (Test-Path $SessionSeed)) {
    throw "Authorized Telegram session is missing at data\telegram_desktop\accounts\default\client.session."
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
Copy-Item $SessionSeed (Join-Path $ReleaseRoot "telegram-session.session") -Force

# Carry currently working proxy routes without committing them to Git.
# If the old local portable bundle exists, extract only its proxy list for this release.
if (Test-Path $LegacyPortableConfig) {
    try {
        $Portable = Get-Content $LegacyPortableConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($Portable.proxies -and $Portable.proxies.Count -gt 0) {
            $ProxySeed = [ordered]@{ proxies = @($Portable.proxies) }
            $ProxyJson = $ProxySeed | ConvertTo-Json -Depth 10
            $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText(
                (Join-Path $ReleaseRoot "telegram-proxies.json"),
                $ProxyJson,
                $Utf8NoBom
            )
        }
    } catch {
        Write-Warning "Could not extract proxy routes from telegram-portable.json: $($_.Exception.Message)"
    }
}

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

1. Keep telegram-session.session beside Telegram-Desktop-Setup-$Version.exe.
2. Run Telegram-Desktop-Setup-$Version.exe directly.
3. The installer seeds the existing Telegram session into AppData before first launch.
4. On first launch enter API ID and API Hash in the application form.
5. xray.exe is copied automatically when present beside the installer.

Security:
- telegram-session.session authorizes the Telegram account. Keep it private.
- The session is not committed to Git and is copied from the current local client only when building this release.
"@
Set-Content -Path (Join-Path $ReleaseRoot "README.txt") -Value $Readme -Encoding UTF8

Write-Host ""
Write-Host "Release package is ready:" -ForegroundColor Green
Write-Host $ReleaseRoot -ForegroundColor Green
Get-ChildItem $ReleaseRoot | Format-Table Name, Length, LastWriteTime
