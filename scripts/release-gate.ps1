[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $RepoRoot
$ReviewRoot = Join-Path $ProjectRoot "review\LIVE_GATE"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Frontend = Join-Path $RepoRoot "frontend"
$PytestTemp = Join-Path $RepoRoot ".pytest-live-gate"

if (-not (Test-Path $Python)) {
    throw "Python virtual environment is missing. Run scripts\setup-dev.ps1 first."
}

Push-Location $RepoRoot
try {
    $Branch = (& git branch --show-current).Trim()
    $Head = (& git rev-parse HEAD).Trim()
    $StatusBefore = @(& git status --short)
    if ($StatusBefore.Count -gt 0) {
        throw "Release gate requires a clean Git working tree before validation."
    }

    & $Python scripts\sync-version.py --check
    if ($LASTEXITCODE -ne 0) { throw "Version manifest check failed." }

    Remove-Item $PytestTemp -Recurse -Force -ErrorAction SilentlyContinue
    & $Python -m pytest -q --basetemp=$PytestTemp
    if ($LASTEXITCODE -ne 0) { throw "Backend test suite failed." }

    Remove-Item $PytestTemp -Recurse -Force -ErrorAction SilentlyContinue

    Push-Location $Frontend
    try {
        & npm.cmd test
        if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }

        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
    } finally {
        Pop-Location
    }

    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check failed." }

    $StatusAfter = @(& git status --short)
    if ($StatusAfter.Count -gt 0) {
        throw "Release gate requires a clean Git working tree. Review local changes before promotion."
    }

    New-Item -ItemType Directory -Force $ReviewRoot | Out-Null
    $Report = @"
Telegram Desktop local release gate

BRANCH: $Branch
HEAD: $Head
VERSION CHECK: PASS
BACKEND TESTS: PASS
FRONTEND TESTS: PASS
FRONTEND BUILD: PASS
GIT DIFF CHECK: PASS
GIT STATUS: CLEAN

This gate does not modify Desktop Telegram\live, create a tag, or publish a GitHub Release.
Live promotion and release tagging require explicit user approval.
"@
    [System.IO.File]::WriteAllText(
        (Join-Path $ReviewRoot "RELEASE_GATE_RESULTS.txt"),
        $Report,
        (New-Object System.Text.UTF8Encoding($false))
    )

    Write-Host "Release gate passed." -ForegroundColor Green
    Write-Host "Report: $(Join-Path $ReviewRoot 'RELEASE_GATE_RESULTS.txt')" -ForegroundColor Green
    Write-Host "No live files, tags, or releases were changed." -ForegroundColor Yellow
} finally {
    Remove-Item $PytestTemp -Recurse -Force -ErrorAction SilentlyContinue
    Pop-Location
}
