[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ApiFile,
    [Parameter(Mandatory=$true)][string]$ProxyFile,
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$XrayExe
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $repo 'frontend'
$tauri = Join-Path $frontend 'src-tauri'
$configPath = Join-Path $tauri 'tauri.private.conf.json'
$version = (Get-Content (Join-Path $tauri 'tauri.conf.json') -Raw | ConvertFrom-Json).version
foreach ($inputFile in @($ApiFile, $ProxyFile, $PythonExe, $XrayExe)) {
    if (-not (Test-Path -LiteralPath $inputFile -PathType Leaf)) { throw 'Required build input is missing.' }
}
# Explicit allowlist: never package a session, data directory, or arbitrary glob.
$resources = @{}
$resources[(Resolve-Path -LiteralPath $ApiFile).Path] = 'telegram-api.env'
$resources[(Resolve-Path -LiteralPath $ProxyFile).Path] = 'telegram-proxies.json'
# Keep the Python runtime unpacked beside the sidecar. One-file PyInstaller
# extracts all DLLs into Temp on every launch, delaying the local API.
$resources[(Join-Path $repo 'dist/telegram-desktop-backend/backend-runtime/')] = 'backend-runtime/'
$config = @{
    # An absolute Windows path can deserialize as a URL (c:), displaying a
    # directory listing instead of embedding React. Keep this relative.
    build = @{ frontendDist = '../dist'; beforeBuildCommand = 'npm run build' }
    bundle = @{
        active = $true
        targets = @('nsis')
        externalBin = @('binaries/telegram-desktop-backend', 'binaries/xray')
        resources = $resources
        windows = @{ nsis = @{
            installMode = 'currentUser'
            installerHooks = './windows/hooks.nsh'
            template = './windows/installer-multi-instance.nsi'
        }}
    }
}
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding UTF8
Push-Location $repo
try {
    # --paths ensures the sidecar contains this checkout, even if Python was
    # installed in editable mode against an older checkout.
    & $PythonExe -m PyInstaller --noconfirm --clean --onedir --contents-directory backend-runtime --paths $repo --name telegram-desktop-backend --collect-all uvicorn --workpath (Join-Path $repo '.build-temp/pyinstaller') app/desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
    New-Item -ItemType Directory -Path (Join-Path $tauri 'binaries') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo 'dist/telegram-desktop-backend/telegram-desktop-backend.exe') -Destination (Join-Path $tauri 'binaries/telegram-desktop-backend-x86_64-pc-windows-msvc.exe') -Force
    Copy-Item -LiteralPath $XrayExe -Destination (Join-Path $tauri 'binaries/xray-x86_64-pc-windows-msvc.exe') -Force
    Set-Location $frontend
    & npm.cmd test -- --run
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    & npm.cmd run tauri build -- --config src-tauri/tauri.private.conf.json
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    $output = Join-Path $tauri "target/release/bundle/nsis/Telegram Desktop_${version}_x64-setup.exe"
    $privateOutput = Join-Path $tauri "target/release/bundle/nsis/Telegram Desktop_${version}_x64-setup-private.exe"
    Copy-Item -LiteralPath $output -Destination $privateOutput -Force
    # A fresh portable folder lets the user sign in once, then copy that
    # complete folder to another Windows PC without running an installer there.
    # Never include a session in the build output.
    $portableOutput = Join-Path $repo "release/Telegram Desktop $version Portable"
    if (Test-Path -LiteralPath $portableOutput) { throw 'Portable output already exists; do not overwrite a possible signed-in session.' }
    New-Item -ItemType Directory -Path $portableOutput -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $tauri 'target/release/telegram-desktop.exe') -Destination (Join-Path $portableOutput 'telegram-desktop.exe')
    Copy-Item -LiteralPath (Join-Path $tauri 'binaries/telegram-desktop-backend-x86_64-pc-windows-msvc.exe') -Destination (Join-Path $portableOutput 'telegram-desktop-backend.exe')
    Copy-Item -LiteralPath (Join-Path $tauri 'binaries/xray-x86_64-pc-windows-msvc.exe') -Destination (Join-Path $portableOutput 'xray.exe')
    Copy-Item -LiteralPath (Join-Path $repo 'dist/telegram-desktop-backend/backend-runtime') -Destination (Join-Path $portableOutput 'backend-runtime') -Recurse
    Copy-Item -LiteralPath $ApiFile -Destination (Join-Path $portableOutput 'telegram-api.env')
    Copy-Item -LiteralPath $ProxyFile -Destination (Join-Path $portableOutput 'telegram-proxies.json')
    Write-Output "PRIVATE_INSTALLER=$privateOutput"
    Write-Output "PORTABLE_FOLDER=$portableOutput"
} finally {
    Pop-Location
    # This generated config contains local source paths only; keep it ignored.
}
