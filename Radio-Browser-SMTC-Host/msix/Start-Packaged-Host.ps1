param(
    [string]$PackageNamePattern = "*RadioBrowser*SMTCHost*",
    [string]$HealthUrl = "http://127.0.0.1:8765/health",
    [int]$WaitSeconds = 6
)

$ErrorActionPreference = "Stop"

$pkg = Get-AppxPackage | Where-Object { $_.Name -like $PackageNamePattern } | Select-Object -First 1
if (-not $pkg) {
    throw "MSIX package not found by pattern '$PackageNamePattern'. Install package first."
}

# Avoid parser and shell escaping issues around literal '!' in AppUserModelId.
$appId = $pkg.PackageFamilyName + [char]33 + "App"
$target = "shell:AppsFolder\" + $appId

Write-Host "Starting packaged host: $($pkg.Name) ($appId)"
& explorer.exe $target | Out-Null

$deadline = (Get-Date).AddSeconds([Math]::Max(1, $WaitSeconds))
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
        if ($health.success -eq $true) {
            Write-Host "Host is healthy at $HealthUrl"
            exit 0
        }
    }
    catch {
        Start-Sleep -Milliseconds 400
    }
}

throw "Host did not become healthy within $WaitSeconds seconds. Check app window and logs."
