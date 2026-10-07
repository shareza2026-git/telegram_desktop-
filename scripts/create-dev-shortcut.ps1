[CmdletBinding()]
param(
    [string]$ShortcutName = "Telegram Desktop DEV"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$RunScript = Join-Path $RepoRoot "scripts\run-dev.ps1"
$IconPath = Join-Path $RepoRoot "frontend\src-tauri\icons\icon.ico"

if (-not (Test-Path $RunScript)) {
    throw "Development launcher was not found: $RunScript"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
if (-not $Desktop) {
    throw "Windows Desktop folder could not be resolved."
}

$ShortcutPath = Join-Path $Desktop "$ShortcutName.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`""
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.Description = "Telegram Desktop development launcher"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.Save()

Write-Host "Development shortcut created:" -ForegroundColor Green
Write-Host $ShortcutPath -ForegroundColor Green
