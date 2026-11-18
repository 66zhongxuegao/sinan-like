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

## Recommended: serve the production build (faster on phones)

Pointing the tunnel at the Vite dev server (25190) ships unbundled, uncompressed modules through the tunnel on every visit. Measured with an emulated 250 ms RTT / 5 Mbps link: first usable screen 4.8 s on the dev server vs 2.2 s (1.2 s on repeat visits) on the production build.

```powershell
cd D:\司南礼客项目
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\serve_public.ps1   # build + vite preview on 25180
```

Then change both `service:` lines in `C:\Users\21559\.cloudflared\sinan-like.yml` from `http://127.0.0.1:25190` to `http://127.0.0.1:25180` and restart `cloudflared`. Re-run the script after each frontend change. Local development keeps using 25190 with hot reload.
