[CmdletBinding()]
param(
    [int]$Port = 8110
)

$ErrorActionPreference = "Stop"
$Base = "http://127.0.0.1:$Port"

$Health = Invoke-RestMethod -Uri "$Base/health" -TimeoutSec 3
if ($Health.status -ne "ok") {
    throw "Backend health check failed."
}

$Status = Invoke-RestMethod -Uri "$Base/api/telegram/status" -TimeoutSec 5
if (-not $Status.configured) {
    throw "Telegram API credentials are not configured."
}
if (-not $Status.connected) {
    throw "Telegram is not connected. State: $($Status.state)"
}
if (-not $Status.authorized) {
    throw "Telegram session is not authorized yet. Complete phone/code/2FA login in the app."
}

$Devices = @(Invoke-RestMethod -Uri "$Base/api/telegram/devices" -TimeoutSec 10)
$Current = @($Devices | Where-Object { $_.current }) | Select-Object -First 1
if (-not $Current) {
    throw "Telegram did not report a current device authorization."
}

$ExpectedDevice = [Environment]::MachineName
if ($Current.device_model -ne $ExpectedDevice) {
    throw "Current Telegram device name mismatch. Expected '$ExpectedDevice', got '$($Current.device_model)'."
}

$Dialogs = @(Invoke-RestMethod -Uri "$Base/api/telegram/dialogs" -TimeoutSec 15)

Write-Host "Local Telegram session verification passed." -ForegroundColor Green
Write-Host "health: ok"
Write-Host "configured: true"
Write-Host "connected: true"
Write-Host "authorized: true"
Write-Host "current device: $($Current.device_model)"
Write-Host "dialogs visible: $($Dialogs.Count)"
