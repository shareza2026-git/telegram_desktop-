[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $RepoRoot "frontend"
$VenvRoot = Join-Path $RepoRoot ".venv"
$Python = Join-Path $VenvRoot "Scripts\python.exe"
$EnvFile = Join-Path $RepoRoot ".env"

function Require-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not installed. $InstallHint"
    }
}

Require-Command -Name "py" -InstallHint "Install Python 3.12 and enable the Python launcher."
Require-Command -Name "node" -InstallHint "Install Node.js 22 LTS."
Require-Command -Name "npm" -InstallHint "Install Node.js 22 LTS."
Require-Command -Name "cargo" -InstallHint "Install Rust with rustup for the Tauri desktop build."

& py -3.12 --version | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 is required. Install it, then run this script again."
}

if (-not (Test-Path $Python)) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
    & py -3.12 -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Python virtual environment."
    }
}

Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
& $Python -m pip install --upgrade pip
& $Python -m pip install -e "${RepoRoot}[test]"
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency installation failed."
}

Write-Host "Installing locked frontend dependencies..." -ForegroundColor Cyan
Push-Location $FrontendRoot
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend dependency installation failed."
    }
} finally {
    Pop-Location
}

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $RepoRoot ".env.example") $EnvFile
    Write-Host "Created .env from .env.example." -ForegroundColor Yellow
}

if (-not $SkipTests) {
    Write-Host "Running backend tests..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        & $Python -m pytest -q
        if ($LASTEXITCODE -ne 0) {
            throw "Backend tests failed."
        }
    } finally {
        Pop-Location
    }

    Write-Host "Running frontend tests and build check..." -ForegroundColor Cyan
    Push-Location $FrontendRoot
    try {
        & npm test
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend tests failed."
        }
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build check failed."
        }
    } finally {
        Pop-Location
    }
}

Write-Host "Development setup is ready." -ForegroundColor Green
Write-Host "Before the first run, open .env and fill TELEGRAM_API_ID, TELEGRAM_API_HASH and the read-only proxy/source paths." -ForegroundColor Yellow
Write-Host "Then run: .\scripts\run-dev.ps1" -ForegroundColor Green
