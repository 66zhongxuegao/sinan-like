# Cloudflare Deployment

## Public URLs

- https://sinanlike.com
- https://www.sinanlike.com

## Current topology

```text
Cloudflare edge
  -> named tunnel: sinan-like
  -> local Vite entry: http://127.0.0.1:25190
  -> local FastAPI backend: http://127.0.0.1:28020
```

Vite proxies `/api` to FastAPI so the browser uses one public origin.

## Tunnel metadata

- Tunnel name: `sinan-like`
- Tunnel ID: `ae332bff-d40f-4d60-a3b5-bc935548fedd`
- Config: `C:\Users\21559\.cloudflared\sinan-like.yml`
- Credentials: `C:\Users\21559\.cloudflared\ae332bff-d40f-4d60-a3b5-bc935548fedd.json`

Tunnel credentials are not committed to Git.

## Restart order

```powershell
cd D:\司南礼客项目
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desktop_launch.ps1 -Mode Normal -WebOnly
& 'C:\Program Files (x86)\cloudflared\cloudflared.exe' tunnel --config "$HOME\.cloudflared\sinan-like.yml" run sinan-like
```

## Health checks

```powershell
Invoke-WebRequest https://sinanlike.com/ -TimeoutSec 30
Invoke-WebRequest https://sinanlike.com/api/docs -TimeoutSec 30
```

## Operational note

The current deployment uses this computer as the origin. The site remains online while this computer is powered on and both the local Web services and `cloudflared` are running.
