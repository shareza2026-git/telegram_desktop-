[CmdletBinding()]
param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Bump = "patch",
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$ExpectedBranch = "feature/telegram-desktop-foundation"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $output
}

$RepoRoot = (Invoke-Git rev-parse --show-toplevel | Select-Object -First 1).Trim()
Push-Location $RepoRoot
try {
    $Branch = (Invoke-Git branch --show-current | Select-Object -First 1).Trim()
    if ($Branch -ne $ExpectedBranch) {
        throw "Release tags must be created from $ExpectedBranch, current branch is $Branch."
    }

    $Status = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed with exit code $LASTEXITCODE"
    }
    if ($Status.Count -gt 0) {
        throw "Working tree is not clean. Commit or intentionally resolve local changes before releasing."
    }

    Invoke-Git fetch origin "+refs/heads/${ExpectedBranch}:refs/remotes/origin/${ExpectedBranch}" --tags | Out-Null

    & git merge-base --is-ancestor "origin/$ExpectedBranch" HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "Local $ExpectedBranch is behind or diverged from origin/$ExpectedBranch. Fetch/reconcile without destructive reset before releasing."
    }

    $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $PythonCommand) {
            throw "Python is required to validate release version manifests."
        }
        $Python = $PythonCommand.Source
    }
    & $Python (Join-Path $RepoRoot "scripts\sync-version.py") --check | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Release version manifests are not synchronized."
    }

    $Candidates = @()
    foreach ($Tag in @(Invoke-Git tag --merged HEAD --list "v*")) {
        if ($Tag -match '^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
            $Candidates += [PSCustomObject]@{
                Tag = $Tag
                Version = [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
            }
        }
    }

    if ($Candidates.Count -gt 0) {
        $BaseVersion = ($Candidates | Sort-Object Version -Descending | Select-Object -First 1).Version
    } else {
        $TauriConfig = Get-Content (Join-Path $RepoRoot "frontend\src-tauri\tauri.conf.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$TauriConfig.version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
            throw "Checked-in Tauri version is not MAJOR.MINOR.PATCH."
        }
        $BaseVersion = [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
    }

    switch ($Bump) {
        "major" { $NextVersion = [version]::new($BaseVersion.Major + 1, 0, 0) }
        "minor" { $NextVersion = [version]::new($BaseVersion.Major, $BaseVersion.Minor + 1, 0) }
        default { $NextVersion = [version]::new($BaseVersion.Major, $BaseVersion.Minor, $BaseVersion.Build + 1) }
    }
    $TagName = "v$($NextVersion.ToString(3))"

    & git rev-parse -q --verify "refs/tags/$TagName" *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "Tag $TagName already exists."
    }

    $Head = (Invoke-Git rev-parse HEAD | Select-Object -First 1).Trim()
    Write-Host "Release source: $ExpectedBranch@$Head" -ForegroundColor Cyan
    Write-Host "Next release tag: $TagName ($Bump)" -ForegroundColor Green

    if ($Preview) {
        Write-Host "Preview only: no tag or remote ref was changed." -ForegroundColor Yellow
        return
    }

    Invoke-Git tag -a $TagName -m "Release $TagName" | Out-Null
    try {
        Invoke-Git push --atomic origin "HEAD:refs/heads/$ExpectedBranch" "refs/tags/$TagName:refs/tags/$TagName" | Out-Null
    } catch {
        & git tag -d $TagName *> $null
        throw
    }

    Write-Host "Published $TagName. GitHub Actions will validate, build and publish that exact version." -ForegroundColor Green
} finally {
    Pop-Location
}
