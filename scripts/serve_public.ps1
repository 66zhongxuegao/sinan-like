# 公网前端（生产构建）启动脚本
#
# 为什么需要它：sinanlike.com 原先经 Cloudflare 隧道直连 Vite 开发服务（25190）。
# 开发服务按源码逐个下发未压缩的模块（首屏约 4MB+、几十个请求），每个请求都要穿过隧道回到本机，
# 手机上表现为「首屏很慢、点一个页面要等半天」。这里改为：
#   npm run build → vite preview 托管 dist（压缩、带内容哈希、/assets/ 长期缓存，可被 Cloudflare 边缘缓存）
# /api 代理与 WebSocket 配置与开发服务相同（见 frontend/vite.config.ts），后端仍是 28020。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\serve_public.ps1            # 构建并启动
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\serve_public.ps1 -SkipBuild # 只重启服务
# 前端代码改动后需重新运行本脚本（或单独 npm run build），公网才会看到新版本。
# 本地开发仍用 25190（热更新），两者互不影响。

param(
    [int]$Port = 25180,
    [int]$ApiPort = 28020,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'
$node = if (Test-Path 'D:\nodejs\node.exe') { 'D:\nodejs\node.exe' } else { (Get-Command node).Source }
$npm = Join-Path (Split-Path $node) 'npm.cmd'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

if (-not $SkipBuild) {
    Write-Output "[serve_public] building frontend ..."
    Push-Location $frontend
    try {
        & $npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed ($LASTEXITCODE)" }
    } finally { Pop-Location }
}

# 停掉占用该端口的旧 preview 进程
$old = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $old) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like '*vite*preview*') {
        Stop-Process -Id $c.OwningProcess -Force
        Write-Output "[serve_public] stopped old preview pid=$($c.OwningProcess)"
    } elseif ($proc) {
        throw "port $Port is used by another program: $($proc.CommandLine)"
    }
}

$env:VITE_API_PORT = "$ApiPort"
$p = Start-Process -FilePath $node `
    -ArgumentList @('node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', "$Port", '--strictPort') `
    -WorkingDirectory $frontend -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'public-preview.out.log') `
    -RedirectStandardError (Join-Path $logDir 'public-preview.err.log') -PassThru

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try { if ((Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $ok = $true; break } } catch {}
}
if (-not $ok) { throw "preview did not start on port $Port (see logs\public-preview.err.log)" }
Write-Output "[serve_public] production frontend on http://127.0.0.1:$Port (pid=$($p.Id)), /api -> 127.0.0.1:$ApiPort"
