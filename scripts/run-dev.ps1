[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $RepoRoot "frontend"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $RepoRoot ".env"
$Backend = $null

if (-not (Test-Path $Python)) {
    throw "The virtual environment is missing. Run .\scripts\setup-dev.ps1 first."
}
if (-not (Test-Path $EnvFile)) {
    throw ".env is missing. Run .\scripts\setup-dev.ps1 first, then configure .env."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not installed. Install Node.js 22 LTS."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo is not installed. Install Rust with rustup for Tauri development."
}

Write-Host "Starting the local backend on http://127.0.0.1:8110 ..." -ForegroundColor Cyan
$Backend = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8110") `
    -WorkingDirectory $RepoRoot `
    -PassThru `
    -NoNewWindow

try {
    $Healthy = $false
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if ($Backend.HasExited) {
            throw "The backend stopped before becoming ready. Check the error shown above."
        }
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8110/health" -TimeoutSec 2
            if ($Health.status -eq "ok") {
                $Healthy = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $Healthy) {
        throw "The backend did not become ready within 30 seconds."
    }

    Write-Host "Backend is ready. Starting the Tauri desktop window..." -ForegroundColor Green
    Push-Location $FrontendRoot
    try {
        & npm run tauri dev -- --config src-tauri/tauri.dev.conf.json
        if ($LASTEXITCODE -ne 0) {
            throw "Tauri development mode exited with an error."
        }
    } finally {
        Pop-Location
    }
} finally {
    if ($null -ne $Backend -and -not $Backend.HasExited) {
        Write-Host "Stopping the local backend..." -ForegroundColor Cyan
        Stop-Process -Id $Backend.Id -Force
        $Backend.WaitForExit()
    }
}
