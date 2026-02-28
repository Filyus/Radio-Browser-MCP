# RadioBrowser SMTC Host

WPF host for publishing metadata to Windows System Media Transport Controls (SMTC).

## Endpoints

- `GET /health`
- `GET /debug/state`
- `POST /smtc/update`
  - JSON body: `{"title":"...", "artist":"...", "status":"Playing|Paused|Stopped"}`
- `POST /player/play`
  - JSON body: `{"url":"https://...", "name":"Station Name"}`
- `POST /player/stop`
- `POST /player/volume`
  - JSON body: `{"volume": 0..100}`
- `GET /player/status`

Default listener prefix: `http://127.0.0.1:8765/`

You can override it with env var:

- `RADIO_SMTC_HOST_PREFIX` (must include trailing slash)

## Build

```powershell
dotnet build .\RadioBrowserSmtcHost.csproj -c Release
```

## Run

```powershell
dotnet run --project .\RadioBrowserSmtcHost.csproj
```

## Mini MSIX (Win+A app identity)

Use the single source of truth:

- [`./Windows-SMTC-MSIX.md`](./Windows-SMTC-MSIX.md)

It contains:

- first install commands
- update commands
- admin/non-admin shell split
- troubleshooting and verification steps
