param(
    [string]$CertificatePath = "",
    [switch]$LocalMachine
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($CertificatePath)) {
    $autoCert = Get-ChildItem -Path (Join-Path $scriptRoot "out") -Filter *.cer -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($autoCert) {
        $CertificatePath = $autoCert.FullName
    }
}

if (-not (Test-Path $CertificatePath)) {
    throw "Certificate not found. Pass -CertificatePath or run Build-MSIX.ps1 first."
}

$scope = if ($LocalMachine) { "LocalMachine" } else { "CurrentUser" }
$stores = @("TrustedPeople", "Root")

foreach ($store in $stores) {
    $storePath = "Cert:\$scope\$store"
    Import-Certificate -FilePath $CertificatePath -CertStoreLocation $storePath | Out-Null
    Write-Host "Certificate installed to $storePath"
}
