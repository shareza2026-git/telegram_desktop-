[CmdletBinding()]
param(
    [string]$ProxyCatalogPath,
    [switch]$SkipTests,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $RepoRoot
$DesktopRoot = Join-Path ([Environment]::GetFolderPath("Desktop")) "Desktop Telegram"
$ExpectedDev = Join-Path $DesktopRoot "dev"
$EnvFile = Join-Path $RepoRoot ".env"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Normalize-PathString {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Read-EnvValue {
    param([string]$Name)
    if (-not (Test-Path $EnvFile)) { return "" }
    foreach ($Line in [System.IO.File]::ReadAllLines($EnvFile)) {
        if ($Line.StartsWith("$Name=")) {
            return $Line.Substring($Name.Length + 1)
        }
    }
    return ""
}

function Set-EnvValue {
    param(
        [string]$Name,
        [string]$Value
    )
    $Lines = @()
    if (Test-Path $EnvFile) {
        $Lines = @([System.IO.File]::ReadAllLines($EnvFile))
    }
    $Found = $false
    $Updated = foreach ($Line in $Lines) {
        if ($Line.StartsWith("$Name=")) {
            $Found = $true
            "$Name=$Value"
        } else {
            $Line
        }
    }
    if (-not $Found) {
        $Updated += "$Name=$Value"
    }
    [System.IO.File]::WriteAllLines(
        $EnvFile,
        [string[]]$Updated,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function SecureString-ToPlainText {
    param([Security.SecureString]$Value)
    $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }
}

$ActualDev = Normalize-PathString $RepoRoot
$ExpectedDevNormalized = Normalize-PathString $ExpectedDev
if ($ActualDev -ne $ExpectedDevNormalized) {
    throw "This fresh-machine bootstrap must run from '$ExpectedDevNormalized'. Current repo: '$ActualDev'."
}

Push-Location $RepoRoot
try {
    $Branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not determine Git branch." }
    if ($Branch -notin @("feature/telegram-desktop-foundation", "work/fresh-machine-bootstrap")) {
        throw "Unexpected branch '$Branch'. Use the Telegram Desktop development branch/work branch, not main."
    }

    $Status = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw "git status failed." }
    if ($Status.Count -gt 0) {
        throw "Development working tree is not clean. Preserve and review existing changes before bootstrap."
    }

    $SessionCandidates = @(
        (Join-Path $RepoRoot "data\telegram_desktop\accounts\default\client"),
        (Join-Path $RepoRoot "data\telegram_desktop\accounts\default\client.session"),
        (Join-Path $RepoRoot "telegram-portable.json"),
        (Join-Path $RepoRoot "telegram-session.session"),
        (Join-Path $RepoRoot "telegram-api.env")
    )
    $ExistingSensitive = @($SessionCandidates | Where-Object { Test-Path $_ })
    if ($ExistingSensitive.Count -gt 0) {
        throw "Fresh-machine bootstrap stopped because prior session/portable credential state exists locally. Do not overwrite or import it automatically."
    }

    if ($SkipTests) {
        & (Join-Path $RepoRoot "scripts\setup-dev.ps1") -SkipTests
    } else {
        & (Join-Path $RepoRoot "scripts\setup-dev.ps1")
    }
    if ($LASTEXITCODE -ne 0) { throw "Development setup failed." }

    $ApiId = Read-EnvValue "TELEGRAM_API_ID"
    if (-not $ApiId) {
        $ApiId = (Read-Host "Telegram API_ID from the approved my.telegram.org application").Trim()
    }
    if ($ApiId -notmatch '^[1-9][0-9]*$') {
        throw "Telegram API_ID must be a positive integer."
    }

    $ApiHash = Read-EnvValue "TELEGRAM_API_HASH"
    if (-not $ApiHash) {
        $SecureApiHash = Read-Host "Telegram API_HASH (input hidden)" -AsSecureString
        $ApiHash = SecureString-ToPlainText $SecureApiHash
    }
    if ([string]::IsNullOrWhiteSpace($ApiHash) -or $ApiHash.Length -lt 16) {
        throw "Telegram API_HASH is missing or invalid."
    }

    Set-EnvValue "TELEGRAM_API_ID" $ApiId
    Set-EnvValue "TELEGRAM_API_HASH" $ApiHash
    Set-EnvValue "TELEGRAM_SESSION_PATH" "data/telegram_desktop/accounts/default/client"
    Set-EnvValue "TELEGRAM_DATABASE_PATH" "data/telegram_desktop/accounts/default/client.db"
    Set-EnvValue "TELEGRAM_SOURCE_SESSION_PATH" ""
    Set-EnvValue "TELEGRAM_AUTO_IMPORT_SOURCE" "false"
    Set-EnvValue "TELEGRAM_ALLOW_DIRECT" "false"
    Set-EnvValue "TELEGRAM_BACKEND_HOST" "127.0.0.1"
    Set-EnvValue "TELEGRAM_BACKEND_PORT" "8110"
    Set-EnvValue "TELEGRAM_PORTABLE_CONFIG" ""
    Set-EnvValue "TELEGRAM_PORTABLE_MIRROR_CONFIG" ""

    if ($ProxyCatalogPath) {
        $ResolvedCatalog = (Resolve-Path $ProxyCatalogPath).Path
        Set-EnvValue "TELEGRAM_PROXY_CONFIG" $ResolvedCatalog
        Write-Host "Using the selected read-only proxy catalog. It will not be copied into Git." -ForegroundColor Green
    } else {
        $Answer = (Read-Host "Configure a private VLESS/REALITY tunnel now? [Y/n]").Trim()
        if (-not $Answer -or $Answer -match '^(?i:y|yes)$') {
            $ToolsRoot = Join-Path $ProjectRoot "tools\xray"
            $Xray = Join-Path $ToolsRoot "xray.exe"
            if (-not (Test-Path $Xray)) {
                New-Item -ItemType Directory -Force $ToolsRoot | Out-Null
                $Zip = Join-Path $env:TEMP "Xray-windows-64-v26.9.9.zip"
                $Extract = Join-Path $env:TEMP "telegram-desktop-xray-v26.9.9"
                Remove-Item $Extract -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "Downloading the pinned Xray core used by the release workflow..." -ForegroundColor Cyan
                Invoke-WebRequest `
                    -Uri "https://github.com/XTLS/Xray-core/releases/download/v26.9.9/Xray-windows-64.zip" `
                    -OutFile $Zip
                Expand-Archive -Path $Zip -DestinationPath $Extract -Force
                Copy-Item (Join-Path $Extract "xray.exe") $Xray -Force
            }
            & $Xray version | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "xray.exe failed its version check." }

            $LocalCatalog = Join-Path $RepoRoot "data\telegram_desktop\proxies.json"
            Set-EnvValue "TELEGRAM_PROXY_CONFIG" "data/telegram_desktop/proxies.json"
            Set-EnvValue "TELEGRAM_XRAY_CORE" $Xray

            $SecureVless = Read-Host "Paste the VLESS/REALITY link (input hidden; never printed)" -AsSecureString
            $Vless = SecureString-ToPlainText $SecureVless
            if ([string]::IsNullOrWhiteSpace($Vless)) {
                throw "No tunnel link was provided."
            }
            $Vless | & $Python (Join-Path $RepoRoot "scripts\configure-private-proxy.py") `
                --catalog $LocalCatalog `
                --xray-core $Xray | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "Private tunnel configuration failed."
            }
            $Vless = $null
            $SecureVless = $null
        } else {
            throw "No Telegram route was configured. Direct connectivity remains disabled by policy."
        }
    }

    & (Join-Path $RepoRoot "scripts\create-dev-shortcut.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Desktop shortcut creation failed." }

    Write-Host ""
    Write-Host "Fresh-machine development configuration is ready." -ForegroundColor Green
    Write-Host "The app will use a new independent session under data\telegram_desktop\accounts\default." -ForegroundColor Green
    Write-Host "Complete phone/code/2FA only inside the app when prompted; do not paste those secrets into chat or Git." -ForegroundColor Yellow

    if (-not $NoStart) {
        & (Join-Path $RepoRoot "scripts\run-dev.ps1")
    }

    Write-Host ""
    Write-Host "After Telegram login is complete and the app is running, verify with:" -ForegroundColor Cyan
    Write-Host ".\scripts\verify-local-session.ps1" -ForegroundColor Cyan
} finally {
    Pop-Location
}
