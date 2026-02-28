param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$Version = "1.0.0.0",
    [string]$PackageName = "RadioBrowser.SMTCHost",
    [string]$DisplayName = "Radio Browser",
    [string]$Publisher = "CN=RadioBrowserSMTCHostDev",
    [string]$PublisherDisplayName = "Local Developer",
    [string]$CertificatePassword = "radio-browser-dev",
    [switch]$SelfContained
)

$ErrorActionPreference = "Stop"

function Require-Tool([string]$name) {
    $tool = Get-Command $name -ErrorAction SilentlyContinue
    if ($tool) {
        return $tool.Source
    }

    $kitsRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $candidates = Get-ChildItem -Path $kitsRoot -Recurse -Filter $name -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        if ($candidates -and $candidates.Count -gt 0) {
            return $candidates[0].FullName
        }
    }

    throw "Required tool not found: $name. Install Windows 10/11 SDK (App Certification Kit)."
}

function Ensure-Directory([string]$path) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

function New-AppIcon([string]$path, [int]$size) {
    Add-Type -AssemblyName System.Drawing
    $bitmap = New-Object System.Drawing.Bitmap $size, $size
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([System.Drawing.Color]::FromArgb(255, 15, 84, 136))
    $fontSize = [Math]::Max(12, [int]($size * 0.34))
    $font = New-Object System.Drawing.Font("Segoe UI", $fontSize, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $rect = New-Object System.Drawing.RectangleF(0, 0, $size, $size)
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.DrawString("RB", $font, $brush, $rect, $format)
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $font.Dispose()
    $brush.Dispose()
    $format.Dispose()
    $bitmap.Dispose()
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$projectFile = Join-Path $projectRoot "RadioBrowserSmtcHost.csproj"
$outRoot = Join-Path $scriptRoot "out"
$publishDir = Join-Path $outRoot "publish"
$packageDir = Join-Path $outRoot "package"
$assetsDir = Join-Path $packageDir "Assets"
$manifestPath = Join-Path $packageDir "AppxManifest.xml"
$msixPath = Join-Path $outRoot ("{0}_{1}_{2}.msix" -f $PackageName, $Version, $Runtime)
$pfxPath = Join-Path $outRoot ("{0}.pfx" -f $PackageName)
$cerPath = Join-Path $outRoot ("{0}.cer" -f $PackageName)

Ensure-Directory $outRoot

if (Test-Path $publishDir) {
    Remove-Item -Path $publishDir -Recurse -Force
}
if (Test-Path $packageDir) {
    Remove-Item -Path $packageDir -Recurse -Force
}
if (Test-Path $msixPath) {
    Remove-Item -Path $msixPath -Force
}

Ensure-Directory $publishDir
Ensure-Directory $packageDir
Ensure-Directory $assetsDir

Write-Host "Publishing host app..."
$selfContainedArg = if ($SelfContained) { "true" } else { "false" }
dotnet publish $projectFile `
    -c $Configuration `
    -r $Runtime `
    --self-contained $selfContainedArg `
    /p:PublishSingleFile=false `
    /p:DebugType=None `
    -o $publishDir

Write-Host "Preparing package layout..."
Copy-Item -Path (Join-Path $publishDir "*") -Destination $packageDir -Recurse -Force

$logo150 = Join-Path $assetsDir "Logo150x150.png"
$logo44 = Join-Path $assetsDir "Logo44x44.png"
New-AppIcon -path $logo150 -size 150
New-AppIcon -path $logo44 -size 44

$manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap desktop rescap">
  <Identity
    Name="$PackageName"
    Publisher="$Publisher"
    Version="$Version" />
  <Properties>
    <DisplayName>$DisplayName</DisplayName>
    <PublisherDisplayName>$PublisherDisplayName</PublisherDisplayName>
    <Logo>Assets\Logo150x150.png</Logo>
  </Properties>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Applications>
    <Application Id="App" Executable="RadioBrowserSmtcHost.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="$DisplayName"
        Description="$DisplayName"
        BackgroundColor="transparent"
        Square150x150Logo="Assets\Logo150x150.png"
        Square44x44Logo="Assets\Logo44x44.png">
        <uap:DefaultTile Wide310x150Logo="Assets\Logo150x150.png" Square71x71Logo="Assets\Logo44x44.png" />
      </uap:VisualElements>
      <Extensions>
        <desktop:Extension Category="windows.fullTrustProcess" Executable="RadioBrowserSmtcHost.exe" />
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"@

Set-Content -Path $manifestPath -Value $manifest -Encoding utf8

$makeAppx = Require-Tool "makeappx.exe"
$signTool = Require-Tool "signtool.exe"

Write-Host "Packing MSIX..."
& $makeAppx pack /d $packageDir /p $msixPath /o | Out-Null

Write-Host "Creating self-signed certificate..."
$existingCert = Get-ChildItem "Cert:\CurrentUser\My" -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -eq $Publisher -and $_.NotAfter -gt (Get-Date).AddDays(7) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if ($existingCert) {
    $cert = $existingCert
    Write-Host "Reusing existing certificate: $($cert.Thumbprint)"
}
else {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Publisher `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(2)
    Write-Host "Created new certificate: $($cert.Thumbprint)"
}

$securePassword = ConvertTo-SecureString -String $CertificatePassword -AsPlainText -Force
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $securePassword | Out-Null
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null

Write-Host "Signing MSIX..."
& $signTool sign /fd SHA256 /f $pfxPath /p $CertificatePassword $msixPath | Out-Null

Write-Host ""
Write-Host "Done."
Write-Host "MSIX: $msixPath"
Write-Host "CER : $cerPath"
Write-Host ""
Write-Host "Next:"
Write-Host "1) Trust certificate: .\\Install-DevCert.ps1"
Write-Host "2) Install package: Add-AppxPackage -Path `"$msixPath`""
