# TripCraft / Lvyuan 桌面启动（**单一实现**，普通与演示共用）
#
#   -Mode Normal  （默认；双击 司南礼客桌面版.bat 走这里）
#        正常训练实例：随机游客 + 真实模型链路。后端 18020 / 前端 5190，
#        库 .dsh-run\normal\preview.sqlite，独立桌面会话。
#   -Mode Demo    （工作人员内部演示；由 启动标准演示.ps1 调用）
#        内部演示实例：后端 18930 / 前端 15191，库 .dsh-run\codex-review\preview.sqlite，
#        启动期声明 TRIPCRAFT_SCENARIO_MODE=offline + TRIPCRAFT_DEMO_TOURIST=on，
#        服务端把随机游客替换成固定标准案例（黄先生 + 完整资源约束）；独立桌面会话。
#   -WebOnly      只起服务不打开桌面窗口（排障用）。
#   -SelfCheck    打开**独立 profile** 的自检窗口（不聚焦/覆盖/关闭正在使用的窗口）。
#   -RestartBackend  用户显式应用更新时，核对实例身份后沿用同一库重启本项目后端。
#
# 复用规则（不可绕过）：只在**同一个库、同一个进程、同一种模式**的前提下复用后端；
#   复用前必须用运行目录里的 instance.json 与真实进程身份核对（mode/port/pid/启动时间/db/
#   演示开关）。核对不过就报错，由监督者按同一个库精准重启本项目该后端——本脚本不结束任何
#   未知进程，也不提供「未验证也继续」的开关。instance.json 只在**本次新启动**后端时写入。
#
# 安全边界：端口被别人占用就报错退出；不重置数据；只在 -RestartBackend 下重启核实过的后端。
# 注意：本文件必须保存为 **UTF-8 with BOM**（Windows PowerShell 5.1 中文解码）。
param(
    [ValidateSet('Normal', 'Demo')][string]$Mode = 'Normal',
    [switch]$WebOnly,
    [switch]$SelfCheck,
    [switch]$RestartBackend
)
$ErrorActionPreference = 'Stop'

$launchRoot = $PSScriptRoot | Split-Path -Parent        # 仓库根（scripts 的上一级）
$frontendDir = Join-Path $launchRoot 'frontend'

if ($Mode -eq 'Demo') {
    $backendPort = 18930
    $frontendPort = 15191
    $runtimeDir = Join-Path $launchRoot '.dsh-run\codex-review'
    $dbPath = Join-Path $runtimeDir 'preview.sqlite'
    $userDataDir = Join-Path $runtimeDir 'electron-userdata'
    $instanceLabel = '内部演示实例'
} else {
    $backendPort = 18020
    $frontendPort = 5190
    $runtimeDir = Join-Path $launchRoot '.dsh-run\normal'
    $dbPath = Join-Path $runtimeDir 'preview.sqlite'
    $userDataDir = Join-Path $runtimeDir 'electron-userdata'
    $instanceLabel = '正常训练实例'
}

$pythonExe = 'D:\python\python.exe'
$nodeExe = 'D:\nodejs\node.exe'
$viteJs = Join-Path $frontendDir 'node_modules\vite\bin\vite.js'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$instanceMarker = Join-Path $runtimeDir 'instance.json'

function Get-PortTable {
    # 读**完整**监听表；读失败必须报错 —— 绝不把「查询失败」当成「没有监听」，
    # 否则会去启动一个同端口的新服务并写出伪标记（Codex 已实测到这个假阳性）。
    try {
        $table = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
    } catch {
        $why = $_.Exception.Message
        throw ("无法读取本机端口监听表（Get-NetTCPConnection 失败）：{0}。为避免把「查询失败」误判成「端口空闲」而重复启动服务，本脚本在此停止；请在具备端口查询权限的会话里运行，或由监督者启动。" -f $why)
    }
    return $table
}
function Get-PortListener([int]$Port) {
    $table = Get-PortTable
    return $table | Where-Object { [int]$_.LocalPort -eq $Port } | Select-Object -First 1
}
function Get-ProcInfoOrThrow([int]$ProcessId, [string]$What) {
    # 进程信息读不到同样要报错：身份校验不允许「读不到就算通过」
    try {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    } catch {
        $why = $_.Exception.Message
        throw ("无法读取进程 {0}（{1}）信息：{2}。身份无法核对时本脚本停止，不写标记、不宣称成功。" -f $ProcessId, $What, $why)
    }
    if (!$info) { throw "进程 $ProcessId（$What）不存在或已退出：无法核对身份。" }
    return $info
}
function Wait-Ready([string]$Url) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { $result = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2; if ($result.StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Milliseconds 500
    }
    throw "服务未就绪：$Url，请查看 $runtimeDir 下最新日志。"
}
function Get-ProcStartUtc([int]$ProcessId) {
    # 必须带时区（UTC 'o' 以 Z 结尾）：无时区的 's' 再 Parse.ToUniversalTime 会被重复减 8 小时，
    # 导致后续复用校验（创建时间对比）必然失败。
    $info = Get-ProcInfoOrThrow $ProcessId '创建时间'
    if (!$info.CreationDate) { throw "进程 $ProcessId 没有创建时间：身份无法核对，停止。" }
    return ([datetime]$info.CreationDate).ToUniversalTime().ToString('o')
}

# ---------------- 后端 ----------------
$backendListener = Get-PortListener $backendPort
if ($backendListener) {
    $backendProcess = Get-ProcInfoOrThrow ([int]$backendListener.OwningProcess) '后端端口占用者'
    if ($backendProcess.CommandLine -notlike '*tripcraft.api.app:create_app*') {
        throw "$backendPort 已被其他程序占用（不是本项目后端），未停止该程序。"
    }
    $currentPid = [int]$backendListener.OwningProcess
    Write-Output "复用已在运行的后端：$backendPort（PID $currentPid）"
    $verified = $false
    $why = ""
    if (!(Test-Path -LiteralPath $instanceMarker)) {
        $why = "实例标记不存在：$instanceMarker"
    } else {
        try {
            $marker = Get-Content -LiteralPath $instanceMarker -Raw -Encoding UTF8 | ConvertFrom-Json
            $procStart = Get-ProcStartUtc $currentPid                    # 失败即抛错
            $markerStart = ''
            if ($marker.started_at) {
                try {
                    # PowerShell 7 的 ConvertFrom-Json 会把 ISO 时间转成 DateTime；
                    # 直接转 string 会丢失 Kind/时区，随后再次减本地偏移。保留类型后只换算一次。
                    if ($marker.started_at -is [datetime]) {
                        $markerStart = $marker.started_at.ToUniversalTime().ToString('o')
                    } elseif ($marker.started_at -is [DateTimeOffset]) {
                        $markerStart = $marker.started_at.UtcDateTime.ToString('o')
                    } else {
                        # Windows PowerShell 5.1 保留原始 ISO 字符串，用 RoundtripKind 保留 Z/偏移。
                        $markerDate = [datetime]::Parse([string]$marker.started_at,
                            [Globalization.CultureInfo]::InvariantCulture,
                            [Globalization.DateTimeStyles]::RoundtripKind)
                        $markerStart = $markerDate.ToUniversalTime().ToString('o')
                    }
                } catch { $markerStart = '' }
            }
            $startOk = $false
            if ($procStart -ne '' -and $markerStart -ne '') {
                $delta = ([datetime]::Parse($procStart) - [datetime]::Parse($markerStart)).Duration().TotalSeconds
                $startOk = ($delta -lt 5)
            }
            $verified = ($marker.mode -eq $Mode) -and ([int]$marker.backend_port -eq $backendPort) `
                -and ([int]$marker.pid -eq $currentPid) -and ([string]$marker.db -eq $dbPath) `
                -and $startOk -and (($Mode -ne 'Demo') -or ($marker.demo_tourist -eq $true))
            if (!$verified) {
                $why = "标记与当前进程不一致：marker(mode=$($marker.mode), pid=$($marker.pid), port=$($marker.backend_port), db=$($marker.db), start=$markerStart) vs 实际(mode=$Mode, pid=$currentPid, port=$backendPort, db=$dbPath, start=$procStart)"
            }
        } catch {
            $verified = $false
            $why = "校验实例标记时出错：$($_.Exception.Message)"
        }
    }
    if (!$verified) {
        throw ("无法确认 $backendPort 上这个后端是「$Mode」实例：$why。请让监督者**按同一个库**重启本项目该后端（本脚本不会结束未知进程）；重启后再运行本入口即可通过校验。")
    }
    Write-Output "已确认复用后端：mode=$Mode · pid=$currentPid · port=$backendPort · db=$dbPath（marker 校验通过）"
    if ($RestartBackend) {
        Write-Output "应用更新：重启已核实身份的本项目后端（PID $currentPid），沿用同一数据库。"
        Stop-Process -Id $currentPid -ErrorAction Stop
        $backendStopped = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (!(Get-PortListener $backendPort)) { $backendStopped = $true; break }
            Start-Sleep -Milliseconds 250
        }
        if (!$backendStopped) { throw "后端端口 $backendPort 尚未释放，停止重启；数据库与实例标记保留。" }
        $backendListener = $null
    }
}
if (!$backendListener) {
    if (!(Test-Path -LiteralPath $pythonExe)) { throw "未找到项目 Python：$pythonExe" }
    $env:TRIPCRAFT_DB = $dbPath
    $env:TRIPCRAFT_VISIT_LOG_DIR = $runtimeDir
    $env:PYTHONIOENCODING = 'utf-8'
    if ($Mode -eq 'Demo') {
        # 演示实例的两个启动期开关：确定性响应 + 固定案例替换随机游客
        $env:TRIPCRAFT_SCENARIO_MODE = 'offline'
        $env:TRIPCRAFT_DEMO_TOURIST = 'on'
        $env:TRIPCRAFT_BOOTSTRAP_ORDERS = '1'      # 注册即得固定案例单（替换随机初始单）
    } else {
        # 普通实例：显式清掉演示开关，宁可多此一举也不要被环境残留带回演示
        Remove-Item Env:TRIPCRAFT_SCENARIO_MODE -ErrorAction SilentlyContinue
        Remove-Item Env:TRIPCRAFT_DEMO_TOURIST -ErrorAction SilentlyContinue
        Remove-Item Env:TRIPCRAFT_DEMO_CASE -ErrorAction SilentlyContinue
        Remove-Item Env:TRIPCRAFT_BOOTSTRAP_ORDERS -ErrorAction SilentlyContinue
    }
    $tag = Get-Date -Format 'yyyyMMdd-HHmmss'
    $startedProc = Start-Process -FilePath $pythonExe -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'tripcraft.api.app:create_app',
        '--factory', '--host', '127.0.0.1', '--port', "$backendPort") -WorkingDirectory $launchRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeDir "backend-$tag.out.log") `
        -RedirectStandardError (Join-Path $runtimeDir "backend-$tag.err.log") -PassThru
    Wait-Ready "http://127.0.0.1:$backendPort/"
    # 只有**本次新启动**的后端才写实例标记：PID 必须来自 Start-Process（-PassThru）并核对确实在监听该端口；
    # 拿不到真实 PID / 创建时间就**不写标记、不宣称成功**（否则会留下无法核对的伪标记）。
    $startedPid = 0
    if ($startedProc -and $startedProc.Id) { $startedPid = [int]$startedProc.Id }
    if ($startedPid -le 0) { throw "未能拿到本次后端进程 PID（Start-Process 未返回），不写实例标记。" }
    $listenerNow = Get-PortListener $backendPort
    # Windows venv 的 python.exe 会通过 redirector 启动基础 Python 子进程。
    # 仅接纳本次启动进程的直接子进程，并核对解释器路径、命令行及创建时间。
    if ($listenerNow -and [int]$listenerNow.OwningProcess -ne $startedPid) {
        $venvConfig = Join-Path (Split-Path (Split-Path $pythonExe -Parent) -Parent) 'pyvenv.cfg'
        if (Test-Path -LiteralPath $venvConfig) {
            $baseMatch = [regex]::Match((Get-Content -LiteralPath $venvConfig -Raw), '(?m)^executable\s*=\s*(.+?)\r?$')
            if ($baseMatch.Success) {
                $basePython = $baseMatch.Groups[1].Value.Trim()
                $childInfo = Get-ProcInfoOrThrow ([int]$listenerNow.OwningProcess) '虚拟环境后端子进程'
                $parentInfo = Get-ProcInfoOrThrow $startedPid '虚拟环境启动进程'
                $childCreated = ([datetime]$childInfo.CreationDate).ToUniversalTime()
                $parentCreated = ([datetime]$parentInfo.CreationDate).ToUniversalTime()
                $launchCreated = $startedProc.StartTime.ToUniversalTime()
                $portPattern = '(?:^|\s)--port\s+"?' + [regex]::Escape([string]$backendPort) + '"?(?:\s|$)'
                $childVerified = ([int]$childInfo.ParentProcessId -eq $startedPid) `
                    -and ([string]$parentInfo.ExecutablePath -eq $pythonExe) `
                    -and (($parentCreated - $launchCreated).Duration().TotalSeconds -lt 5) `
                    -and ([string]$childInfo.ExecutablePath -eq $basePython) `
                    -and ($childCreated -ge $parentCreated) `
                    -and (($childCreated - $parentCreated).TotalSeconds -lt 30) `
                    -and ($childInfo.CommandLine -like '*tripcraft.api.app:create_app*') `
                    -and ($childInfo.CommandLine -match $portPattern)
                if ($childVerified) { $startedPid = [int]$listenerNow.OwningProcess }
            }
        }
    }
    if (!$listenerNow -or [int]$listenerNow.OwningProcess -ne $startedPid) {
        $owner = if ($listenerNow) { [int]$listenerNow.OwningProcess } else { '（成功读取监听表后为无）' }
        throw ("本次启动的进程 PID={0} 并不在监听 {1}（当前监听者：{2}）。可能是端口被别的进程接手或启动失败：不写实例标记、不宣称成功。" -f $startedPid, $backendPort, $owner)
    }
    $startedAt = Get-ProcStartUtc $startedPid                  # 失败即抛错；不再用本地时间兜底
    $scenarioModeNow = if ($Mode -eq 'Demo') { 'offline' } else { 'live' }
    $markerObj = [ordered]@{
        mode = $Mode
        backend_port = $backendPort
        frontend_port = $frontendPort
        db = $dbPath
        pid = $startedPid
        demo_tourist = ($Mode -eq 'Demo')
        scenario_mode = $scenarioModeNow
        started_at = $startedAt
    }
    try { $markerObj | ConvertTo-Json | Set-Content -LiteralPath $instanceMarker -Encoding UTF8 } catch { }
}

# ---------------- 前端 ----------------
$frontendListener = Get-PortListener $frontendPort
if ($frontendListener) {
    $frontendProcess = Get-ProcInfoOrThrow ([int]$frontendListener.OwningProcess) '前端端口占用者'
    if ($frontendProcess.CommandLine -notlike '*vite*') {
        throw "$frontendPort 已被其他程序占用（不是本项目前端），未停止该程序。"
    }
    Write-Output "复用已在运行的前端：$frontendPort（PID $($frontendListener.OwningProcess)）"
} else {
    if (!(Test-Path -LiteralPath $viteJs)) { throw "前端依赖未安装：$viteJs" }
    $env:VITE_PORT = "$frontendPort"
    $env:VITE_API_PORT = "$backendPort"
    $tag = Get-Date -Format 'yyyyMMdd-HHmmss'
    Start-Process -FilePath $nodeExe -ArgumentList @(('"' + $viteJs + '"'), '--host', '127.0.0.1', '--port', "$frontendPort") `
        -WorkingDirectory $frontendDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeDir "frontend-$tag.out.log") `
        -RedirectStandardError (Join-Path $runtimeDir "frontend-$tag.err.log") | Out-Null
}
Wait-Ready "http://127.0.0.1:$frontendPort/"

Write-Output "[$instanceLabel] 服务已就绪：http://127.0.0.1:$frontendPort/#/login"

# ---------------- 桌面窗口（真实 Electron 本地应用） ----------------
if ($WebOnly) {
    Write-Output '  -WebOnly：只起服务，未打开桌面窗口（排障用）。'
} else {
    # 中文项目路径下 electron.exe 会 0x80000003 起不来：同一份 dist 缓存到纯 ASCII 路径再启动。
    $distDir = Join-Path $frontendDir 'node_modules\electron\dist'
    $distExe = Join-Path $distDir 'electron.exe'
    if (!(Test-Path -LiteralPath $distExe)) {
        throw "未找到 Electron 运行时：$distExe（可在 frontend 目录执行 node node_modules/electron/install.js，或加 -WebOnly）。"
    }
    $runtimeVersion = (Get-Content -LiteralPath (Join-Path $distDir 'version') -Raw).Trim()
    $cacheDir = Join-Path $env:LOCALAPPDATA "TripCraft\desktop-runtime\$runtimeVersion"
    $cachedExe = Join-Path $cacheDir 'electron.exe'
    $cachedVersion = Join-Path $cacheDir 'version'
    $cacheOk = (Test-Path -LiteralPath $cachedExe) -and (Test-Path -LiteralPath $cachedVersion) `
        -and (((Get-Content -LiteralPath $cachedVersion -Raw).Trim()) -eq $runtimeVersion)
    if (!$cacheOk) {
        Write-Output "建立桌面运行文件缓存：$cacheDir（$runtimeVersion，仅缺失/版本不符时复制一次）"
        if (Test-Path -LiteralPath $cacheDir) { Remove-Item -LiteralPath $cacheDir -Recurse -Force }
        New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
        Copy-Item -Path (Join-Path $distDir '*') -Destination $cacheDir -Recurse -Force
    }
    $env:TRIPCRAFT_REUSE = '1'
    $env:TRIPCRAFT_FRONTEND_URL = "http://127.0.0.1:$frontendPort"
    $env:TRIPCRAFT_BACKEND_URL = "http://127.0.0.1:$backendPort"
    $env:TRIPCRAFT_DESKTOP_LOG_DIR = $runtimeDir
    if ($SelfCheck) {
        # 自检用**独立桌面 profile**：新开一个自检窗口，不聚焦/覆盖/关闭正在使用的窗口
        $env:TRIPCRAFT_DESKTOP_SELFCHECK = '1'
        $env:TRIPCRAFT_SELFCHECK_MODE = $Mode.ToLower()
        $env:TRIPCRAFT_DESKTOP_SELFCHECK_OUT = (Join-Path $runtimeDir ("selfcheck-" + $Mode.ToLower()))
        $env:TRIPCRAFT_USER_DATA = (Join-Path $runtimeDir 'selfcheck-userdata')
    } else {
        # 普通与演示各用一份桌面会话数据：单实例锁互不干扰（不会把普通启动带回演示窗口）
        $env:TRIPCRAFT_USER_DATA = $userDataDir
    }
    # DSH 环境可能带 ELECTRON_RUN_AS_NODE：留着会让 electron 被当纯 Node 跑，开不出窗口
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Start-Process -FilePath $cachedExe -ArgumentList @(('"' + $frontendDir + '"')) -WorkingDirectory $frontendDir `
        -RedirectStandardOutput (Join-Path $runtimeDir 'electron-desktop.out.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'electron-desktop.err.log') | Out-Null
    Write-Output "  桌面窗口已打开（$instanceLabel）：后端 $backendPort / 前端 $frontendPort / 库 $dbPath"
    if ($SelfCheck) {
        Write-Output "  自检模式：$($Mode.ToLower())（独立 profile；不覆盖正在使用的窗口）"
        Write-Output "  自检结论：$(Join-Path $runtimeDir ('selfcheck-' + $Mode.ToLower()))\desktop-selfcheck.json"
    } else {
        Write-Output "  桌面会话数据：$userDataDir（与另一种模式相互独立）"
    }
}

if ($Mode -eq 'Demo') {
    Write-Output '  演示口径：服务端已把随机游客替换为固定案例（黄先生 · 云南 5 日），现场走普通注册/接单流程。'
    Write-Output '  逐步填值：output\demo-rehearsal-20261017\完整演示脚本.txt'
} else {
    Write-Output '  正常口径：随机游客 + 真实模型链路；固定案例不会出现在本实例。'
}
Write-Output "  日志与库：$runtimeDir（本脚本不清库、不重启 DSH、不操作桌面）"
