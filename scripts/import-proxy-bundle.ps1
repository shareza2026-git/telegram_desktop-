[CmdletBinding()]
param(
    [string]$FilePath,
    [int]$Port = 8110
)

$ErrorActionPreference = "Stop"
$Base = "http://127.0.0.1:$Port"

if ($FilePath) {
    $Text = Get-Content (Resolve-Path $FilePath) -Raw -Encoding UTF8
} else {
    $Text = Get-Clipboard -Raw
}

if ([string]::IsNullOrWhiteSpace($Text)) {
    throw "No proxy bundle was found. Copy the proxy/VLESS list to the clipboard or pass -FilePath."
}

try {
    $Health = Invoke-RestMethod -Uri "$Base/health" -TimeoutSec 3
} catch {
    throw "Telegram Desktop backend is not running on $Base."
}
if ($Health.status -ne "ok") {
    throw "Telegram Desktop backend health check failed."
}

$Body = @{ text = $Text } | ConvertTo-Json -Compress
$Result = Invoke-RestMethod -Method Post -Uri "$Base/api/telegram/transport/add-bundle" -ContentType "application/json" -Body $Body -TimeoutSec 20

# Do not print the clipboard contents, proxy hosts, UUIDs, keys or complete URIs.
$Added = @($Result.added)
Write-Host "Proxy bundle imported." -ForegroundColor Green
Write-Host "Added/updated routes: $($Added.Count)"
Write-Host "Rejected/unsupported lines: $($Result.failed)"

$Transport = Invoke-RestMethod -Uri "$Base/api/telegram/transport" -TimeoutSec 5
Write-Host "Stored routes now: $(@($Transport.routes).Count)"
Write-Host "Direct connectivity allowed: $($Transport.allow_direct)"

Write-Host ""
Write-Host "Probing all stored routes..." -ForegroundColor Cyan
$Probe = @(Invoke-RestMethod -Uri "$Base/api/telegram/transport/probe" -TimeoutSec 60)
$Rows = foreach ($Item in $Probe) {
    [pscustomobject]@{
        Index = $Item.index
        Available = [bool]$Item.available
        LatencyMs = $Item.latency_ms
        Detail = $Item.detail
    }
}
$Rows | Format-Table -AutoSize
