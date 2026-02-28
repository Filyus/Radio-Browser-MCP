# Windows SMTC + MSIX Guide

This guide gives copy-paste command sequences for:

- stable media flyout metadata (`Win+A`)
- proper app identity (no `Unknown app`)
- live radio track updates from stream metadata

## 1) What you need

- MCP server: `server.py`
- Desktop host: `Radio-Browser-SMTC-Host` (WPF, local HTTP bridge on `127.0.0.1:8765`)
- Windows SDK tools (`makeappx.exe`, `signtool.exe`) installed
  - `Build-MSIX.ps1` auto-detects them from `PATH` or `Windows Kits`

## 2) First-time install (recommended)

Run these in a normal PowerShell:

```powershell
cd C:\MCP-Servers\Radio-Browser-MCP\Radio-Browser-SMTC-Host\msix
.\Build-MSIX.ps1 -Version 1.0.0.0
```

Then run these in **PowerShell as Administrator**:

```powershell
cd C:\MCP-Servers\Radio-Browser-MCP\Radio-Browser-SMTC-Host\msix
.\Install-DevCert.ps1 -LocalMachine
$msix = Get-ChildItem .\out\*.msix | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Add-AppxPackage -Path $msix.FullName
```

Verify install:

```powershell
Get-AppxPackage | Where-Object { $_.Name -like "*RadioBrowser*SMTCHost*" } | Select Name, Version, PackageFullName, Status
```

## 3) Update existing package

```powershell
cd C:\MCP-Servers\Radio-Browser-MCP\Radio-Browser-SMTC-Host\msix
.\Build-MSIX.ps1 -Version 1.0.0.1
$msix = Get-ChildItem .\out\*.msix | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Add-AppxPackage -Path $msix.FullName
```

Only `-Version` must change on each update.

## 4) Start packaged host

```powershell
cd C:\MCP-Servers\Radio-Browser-MCP\Radio-Browser-SMTC-Host\msix
.\Start-Packaged-Host.ps1
```

Fallback (manual one-liner):

```powershell
$pkg = Get-AppxPackage | Where-Object { $_.Name -like "*RadioBrowser*SMTCHost*" } | Select-Object -First 1
explorer.exe ("shell:AppsFolder\" + $pkg.PackageFamilyName + [char]33 + "App")
```

Host health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health
```

## 5) Runtime backend check

The MCP server supports:

- `host_player` (preferred): playback via C# host (`/player/*`)
- `vlc` (fallback): VLC if host is unavailable

Check with MCP tool `get_windows_media_bridge_status()`:

- field `playback_backend` should be `host_player`

## 6) Expected Win+A behavior

- App title: `Radio Browser` (not `Unknown app`)
- Title: `Artist - Track`
- Artist: station name
- Live updates when stream provides ICY/timed metadata

## 7) Common issues

1. `playback_backend` is `vlc`:
   - Host is down or unreachable.
   - Check `http://127.0.0.1:8765/health`.

2. `Add-AppxPackage` fails with `0x800B0109`:
   - Certificate is not trusted in root store.
   - Run `.\Install-DevCert.ps1 -LocalMachine` from elevated shell.

3. Build fails with file lock (`MSB3021/MSB3027`):
   - `RadioBrowserSmtcHost.exe` is running.
   - Stop process, then rebuild.

4. Flyout shows station but not current track:
   - Stream may not provide ICY metadata.
   - Test with another station.

## 8) Relevant env vars

- `RADIO_ENABLE_WINDOWS_SMTC_HOST` (default `true`)
- `RADIO_ENABLE_WINDOWS_SMTC_HOST_PLAYER` (default `true`)
- `RADIO_WINDOWS_SMTC_HOST_UPDATE_URL` (default `http://127.0.0.1:8765/smtc/update`)
- `RADIO_WINDOWS_SMTC_HOST_TIMEOUT` (default `0.6`)
- `RADIO_DEFAULT_STREAM_ENCODING` (optional; e.g. `gb18030`, `shift_jis`, `windows-1251`)
  - Used as fallback for ICY metadata decoding when station does not send charset.
