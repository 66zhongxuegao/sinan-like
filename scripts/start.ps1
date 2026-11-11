<#
  司南礼客 TripCraft · 一键启动（安全版 v2）
  ---------------------------------------------------------------------------
  与旧版的区别（监督者审核要求）：
    · 不再按命令行模式（python*+tripcraft.api.app / node*+vite）全机杀进程；
    · 不再按端口占用者盲杀：端口被非本项目进程占用时，要么报错（-StrictPort），
      要么改用可配置的独立端口（-BackendPort/-FrontendPort 或 TRIPCRAFT_*_PORT 环境变量）；
    · 把本次启动的 PID + 启动时间 + 可执行文件路径写入 <仓库根>\.runtime\pids.json，
      scripts\stop.ps1 只依据这份记录停止；
    · 启动 uvicorn --reload 时会尽力登记 fork 出的子进程（能力受限时如实记录方式）；
    · 不碰 DSH 与用户其它项目的任何进程。
    · 能力降级（如实说明）：受限环境里 CIM/WMI/Get-NetTCPConnection 可能被拒。此时
      「端口占用者」查不到，start 会明确报错（-StrictPort）或改用备用端口并打印提示，
      不会静默继续、也不会杀未知占用者。

  端口优先级：参数 -BackendPort/-FrontendPort > 环境变量 TRIPCRAFT_BACKEND_PORT /
  TRIPCRAFT_FRONTEND_PORT > 默认 18020 / 5190。

  用法：
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1
    ... -NoReload -NoBrowser -StrictPort -BackendPort 18910 -FrontendPort 15180
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Keep -NoPause
#>
param(
    [switch]$Keep,
    [switch]$NoBrowser,
    [switch]$NoReload,
    [switch]$StrictPort,
    [switch]$NoPause,
    [switch]$SkipFrontend,
    [int]$BackendPort = 0,
    [int]$FrontendPort = 0
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$ledgerDir = Join-Path $root ".runtime"
$ledgerPath = Join-Path $ledgerDir "pids.json"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $ledgerDir | Out-Null

function Line($t) { Write-Host $t }
function Blank() { Write-Host "" }

function Normalize-Path([string]$p) {
    if ([string]::IsNullOrWhiteSpace($p)) { return "" }
    try { return ([System.IO.Path]::GetFullPath($p)).TrimEnd('\').ToLowerInvariant() } catch { return "" }
}


function Convert-ToUtc([object]$value) {
    # 兼容两种形态：ConvertFrom-Json 会把 ISO 串自动转成 [datetime]（Kind=Utc），
    # 也可能拿到原始字符串。字符串必须按 RoundtripKind 解析，否则会按本地时区解释。
    if ($null -eq $value) { return $null }
    if ($value -is [datetime]) { return ([datetime]$value).ToUniversalTime() }
    $s = ([string]$value).Trim()
    if (-not $s) { return $null }
    $dt = [datetime]::MinValue
    $okParse = [datetime]::TryParse($s, [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind, [ref]$dt)
    if (-not $okParse) { return $null }
    return $dt.ToUniversalTime()
}


function Get-Identity([int]$procId) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) { return $null }
    $exe = ""
    try { $exe = [string]$p.Path } catch { $exe = "" }
    $st = ""
    try { $st = $p.StartTime.ToUniversalTime().ToString("o") } catch { $st = "" }
    return [pscustomobject]@{ pid = $procId; name = [string]$p.ProcessName; exe = $exe; start_time = $st }
}

function Get-CmdLine([int]$procId) {
    try {
        $c = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction Stop
        return [string]$c.CommandLine
    } catch { return "" }
}

function Test-RecordIdentity($rec) {
    if (-not $rec -or -not $rec.pid) { return @{ ok = $false; reason = "记录缺少 pid" } }
    $cur = Get-Identity ([int]$rec.pid)
    if (-not $cur) { return @{ ok = $false; reason = "PID $($rec.pid) 已不存在" } }
    if (-not $rec.start_time -or -not $cur.start_time) {
        return @{ ok = $false; reason = "缺少启动时间，无法确认身份" }
    }
    try {
        $a = Convert-ToUtc $rec.start_time
        $b = Convert-ToUtc $cur.start_time
        if (-not $a -or -not $b) {
            return @{ ok = $false; reason = "启动时间无法解析，拒绝盲停" }
        }
        if ([math]::Abs(($a - $b).TotalSeconds) -gt 3) {
            return @{ ok = $false; reason = "启动时间不符（PID 可能已被复用）" }
        }
    } catch { return @{ ok = $false; reason = "启动时间无法解析" } }
    if ($rec.exe -and $cur.exe -and ((Normalize-Path $rec.exe) -ne (Normalize-Path $cur.exe))) {
        return @{ ok = $false; reason = "可执行文件路径不符" }
    }
    $cmd = Get-CmdLine ([int]$rec.pid)
    if ($cmd) {
        $hitRoot = $cmd.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $hitMark = $false
        if ($rec.cmd_marker) { $hitMark = $cmd.IndexOf([string]$rec.cmd_marker, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 }
        if (-not ($hitRoot -or $hitMark)) { return @{ ok = $false; reason = "命令行不含本仓库路径" } }
    }
    return @{ ok = $true; reason = "" }
}

function Get-PortOwnerPid([int]$port) {
    try {
        $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop | Select-Object -First 1
        if ($c) { return [int]$c.OwningProcess }
    } catch { }
    # 兜底：netstat -ano（不需要 WMI 权限），用于"报告/识别"端口占用者；绝不据此杀进程
    try {
        $rows = netstat -ano 2>$null | Select-String -Pattern ("[:.]" + $port + "\s")
        foreach ($row in @($rows)) {
            $t = $row.ToString()
            if ($t -notmatch "LISTENING") { continue }
            $parts = ($t.Trim() -split "\s+")
            $last = $parts[$parts.Count - 1]
            if ($last -match '^\d+$') { return [int]$last }
        }
    } catch { }
    return 0
}

function Test-PortBusy([int]$port) {
    if ((Get-PortOwnerPid $port) -gt 0) { return $true }
    # 兜底：受限环境下查不到占用者，就用一次 TCP 连接探测"有没有人在听"
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $port)
        $c.Close()
        return $true
    } catch { return $false }
}

function Find-FreePort([int]$port, [int]$tries = 10) {
    for ($i = 1; $i -le $tries; $i++) {
        if (-not (Test-PortBusy ($port + $i))) { return $port + $i }
    }
    return 0
}

function Wait-Http($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
        Write-Host "." -NoNewline
    }
    return $false
}

function Discover-Children([int]$procId, [int]$port) {
    # 尽力登记 fork 出的子进程：CIM → WMI → 端口占用者；都不可用就如实返回空
    $kids = @()
    $method = "unavailable"
    try {
        $rows = Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction Stop
        foreach ($r in @($rows)) {
            $id = Get-Identity ([int]$r.ProcessId)
            if ($id) { $kids += $id }
        }
        $method = "cim-parent"
    } catch {
        try {
            $rows = Get-WmiObject Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction Stop
            foreach ($r in @($rows)) {
                $id = Get-Identity ([int]$r.ProcessId)
                if ($id) { $kids += $id }
            }
            $method = "wmi-parent"
        } catch { }
    }
    if ($kids.Count -eq 0 -and $port -gt 0) {
        $owner = Get-PortOwnerPid $port
        if ($owner -gt 0 -and $owner -ne $procId) {
            $id = Get-Identity $owner
            if ($id) { $kids += $id; $method = "port-owner" }
        }
    }
    return [pscustomobject]@{ children = $kids; method = $method }
}

function Read-Ledger() {
    if (-not (Test-Path $ledgerPath)) { return $null }
    try { return (Get-Content $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Save-Ledger($services) {
    $out = [pscustomobject]@{
        schema     = "tripcraft.runtime.pids/v2"
        root       = $root
        updated_at = (Get-Date).ToString("o")
        services   = $services
    }
    $out | ConvertTo-Json -Depth 8 | Set-Content -Path $ledgerPath -Encoding UTF8
}

# ---------------------------------------------------------------- 端口与账本

$backendPort = if ($BackendPort -gt 0) { $BackendPort }
    elseif ($env:TRIPCRAFT_BACKEND_PORT) { [int]$env:TRIPCRAFT_BACKEND_PORT } else { 18020 }
$frontendPort = if ($FrontendPort -gt 0) { $FrontendPort }
    elseif ($env:TRIPCRAFT_FRONTEND_PORT) { [int]$env:TRIPCRAFT_FRONTEND_PORT } else { 5190 }

Blank
Line "============================================================"
Line "   司南礼客 TripCraft · 定制师全流程模拟实战系统（安全启动 v2）"
Line "   项目目录  $root"
Line "   端口      后端 $backendPort / 前端 $frontendPort"
Line "============================================================"
Blank

Line "【1/5】检查运行环境"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Line "  [x] 找不到 python，请先安装 Python 3.11+ 并加入 PATH"; if (-not $NoPause) { Read-Host "按回车退出" }; exit 1 }
Line ("  [ok] Python  " + ((& python --version 2>&1) -join " "))
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Line "  [x] 找不到 node，请先安装 Node.js 20+ 并加入 PATH"; if (-not $NoPause) { Read-Host "按回车退出" }; exit 1 }
Line ("  [ok] Node    " + ((& node --version 2>&1) -join " "))
if (Test-Path (Join-Path $root "local.env")) { Line "  [ok] local.env 已配置" }
else { Line "  [!] 缺少 local.env（大模型/语音/地图密钥）：确定性演示可用，实时模型会不可用" }
Line ("  [i] 运行态记录：" + $ledgerPath)
Line ("  [i] 能力探测：CIM/WMI/端口枚举在受限环境下可能被拒；查不到占用者时本脚本只报告、不杀进程")

# ---------------------------------------------------------------- 清理：只停本项目记录过的

Blank
Line "【2/5】核对上一次启动记录（只动本项目记录过的进程）"
$ledger = Read-Ledger
$services = @{}
$stoppedAny = 0
if ($Keep) {
    Line "  · 保留已在运行的服务（-Keep）"
} elseif ($ledger -and $ledger.services) {
    if ($ledger.root -and ((Normalize-Path ([string]$ledger.root)) -ne (Normalize-Path $root))) {
        Line ("  ! 记录属于另一个目录（{0}），忽略该记录。" -f $ledger.root)
    } else {
        foreach ($name in @("backend", "frontend")) {
            $rec = $ledger.services.$name
            if (-not $rec) { continue }
            $v = Test-RecordIdentity $rec
            if (-not $v.ok) { Line ("  ! 跳过 {0}（PID {1}）：{2}" -f $name, $rec.pid, $v.reason); continue }
            foreach ($child in @($rec.children)) {
                if (-not $child -or -not $child.pid) { continue }
                $cv = Test-RecordIdentity $child
                if ($cv.ok) { Stop-Process -Id ([int]$child.pid) -Force -ErrorAction SilentlyContinue; $stoppedAny++ }
                else { Line ("  ! 跳过 {0} 子进程 PID {1}：{2}" -f $name, $child.pid, $cv.reason) }
            }
            Stop-Process -Id ([int]$rec.pid) -Force -ErrorAction SilentlyContinue
            Line ("  · 已停止上一次的 {0} PID {1}" -f $name, $rec.pid)
            $stoppedAny++
        }
        Start-Sleep -Milliseconds 800
    }
} else {
    Line "  · 没有运行态记录：不会按命令行/端口猜测并杀进程"
}
if ($stoppedAny -eq 0 -and -not $Keep) { Line "  · 没有需要停止的本项目进程" }

# ---------------------------------------------------------------- 启动

Blank
Line "【3/5】启动服务"
$newServices = @{}

function Resolve-Port([string]$label, [int]$want) {
    if (-not (Test-PortBusy $want)) { return $want }
    $owner = Get-PortOwnerPid $want
    if ($owner -gt 0) {
        $p = Get-Process -Id $owner -ErrorAction SilentlyContinue
        $nm = ""
        if ($p) { $nm = $p.ProcessName }
        if ($StrictPort) {
            Line ("  [x] {0} 端口 {1} 被 PID {2}（{3}）占用；-StrictPort 下不换端口也不杀进程，退出。" -f $label, $want, $owner, $nm)
            if (-not $NoPause) { Read-Host "按回车退出" }
            exit 2
        }
        $alt = Find-FreePort $want
        if ($alt -le 0) {
            Line ("  [x] {0} 端口 {1} 被 PID {2}（{3}）占用且找不到空闲备用端口，退出。" -f $label, $want, $owner, $nm)
            if (-not $NoPause) { Read-Host "按回车退出" }
            exit 2
        }
        Line ("  ! {0} 端口 {1} 被 PID {2}（{3}）占用：不是本项目记录，**不会杀它**，改用 {4}" -f $label, $want, $owner, $nm, $alt)
        return $alt
    }
    # 占用者查不到（受限环境）
    if ($StrictPort) {
        Line ("  [x] {0} 端口 {1} 已被占用且无法确认占用者；-StrictPort 下退出。" -f $label, $want)
        if (-not $NoPause) { Read-Host "按回车退出" }
        exit 2
    }
    $alt = Find-FreePort $want
    if ($alt -le 0) {
        Line ("  [x] {0} 端口 {1} 被占用且找不到空闲备用端口，退出。" -f $label, $want)
        if (-not $NoPause) { Read-Host "按回车退出" }
        exit 2
    }
    Line ("  ! {0} 端口 {1} 已被占用（无法确认占用者）：不杀未知进程，改用 {2}" -f $label, $want, $alt)
    return $alt
}

# —— 后端 ——
$backendPort = Resolve-Port "后端" $backendPort
$uvArgs = @("-X", "utf8", "-m", "uvicorn", "tripcraft.api.app:create_app",
            "--factory", "--host", "127.0.0.1", "--port", "$backendPort")
if (-not $NoReload) { $uvArgs += "--reload" }
$pyExe = $python.Source
$beOut = Join-Path $logDir "backend.log"
$beErr = Join-Path $logDir "backend.err.log"
try {
    $be = Start-Process -FilePath $pyExe -ArgumentList $uvArgs -WorkingDirectory $root `
        -RedirectStandardOutput $beOut -RedirectStandardError $beErr -PassThru -WindowStyle Hidden
    Line ("  · 后端启动中 PID {0}（端口 {1}，日志 logs\backend.log / logs\backend.err.log）" -f $be.Id, $backendPort)
} catch {
    Line ("  [x] 后端起不来：" + $_.Exception.Message)
    if (-not $NoPause) { Read-Host "按回车退出" }
    exit 1
}

# —— 前端 ——
if ($SkipFrontend) {
    Line "  · 按参数跳过前端（-SkipFrontend）"
} else {
    $frontendPort = Resolve-Port "前端" $frontendPort
    $env:VITE_PORT = "$frontendPort"
    $env:VITE_API_PORT = "$backendPort"
    $feOut = Join-Path $logDir "frontend.log"
    $feErr = Join-Path $logDir "frontend.err.log"
    try {
        $npm = (Get-Command npm -ErrorAction SilentlyContinue)
        $npmCmd = if ($npm) { $npm.Source } else { "npm" }
        $fe = Start-Process -FilePath $npmCmd -ArgumentList @("run", "dev") -WorkingDirectory (Join-Path $root "frontend") `
            -RedirectStandardOutput $feOut -RedirectStandardError $feErr -PassThru -WindowStyle Hidden
        Line ("  · 前端启动中 PID {0}（端口 {1}，日志 logs\frontend.log / logs\frontend.err.log）" -f $fe.Id, $frontendPort)
    } catch {
        Line ("  [x] 前端起不来：" + $_.Exception.Message)
        $fe = $null
    }
    Remove-Item Env:\VITE_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:\VITE_API_PORT -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- 就绪检查 + 登记

Blank
Line "【4/5】等待服务就绪并登记 PID"
Write-Host "  后端 " -NoNewline
$backOk = Wait-Http "http://127.0.0.1:$backendPort/" 60
Write-Host ""
if ($backOk) {
    Line "  [ok] 后端就绪  http://127.0.0.1:$backendPort/"
} else {
    Line "  [x] 后端 60 秒内没有就绪，最后 15 行日志："
    if (Test-Path $beOut) { Get-Content $beOut -Tail 15 | ForEach-Object { Line ("      " + $_) } }
    if (Test-Path $beErr) { Get-Content $beErr -Tail 15 | ForEach-Object { Line ("      " + $_) } }
}

$beId = Get-Identity $be.Id
if ($beId) {
    $d = Discover-Children $be.Id $backendPort
    $newServices["backend"] = [pscustomobject]@{
        pid = $beId.pid; start_time = $beId.start_time; exe = $beId.exe; name = $beId.name
        port = $backendPort; log = $beOut; log_err = $beErr
        cmd_marker = "uvicorn"; children = $d.children; children_method = $d.method
        root = $root
    }
    Line ("  · 已登记后端 PID {0}（子进程登记方式：{1}，子进程 {2} 个）" -f $beId.pid, $d.method, @($d.children).Count)
}

if (-not $SkipFrontend -and $fe) {
    Write-Host "  前端 " -NoNewline
    $frontOk = Wait-Http "http://127.0.0.1:$frontendPort/" 90
    Write-Host ""
    if ($frontOk) { Line "  [ok] 前端就绪  http://127.0.0.1:$frontendPort/" }
    else {
        Line "  [x] 前端 90 秒内没有就绪，最后日志："
        if (Test-Path (Join-Path $logDir "frontend.log")) { Get-Content (Join-Path $logDir "frontend.log") -Tail 15 | ForEach-Object { Line ("      " + $_) } }
        if (Test-Path (Join-Path $logDir "frontend.err.log")) { Get-Content (Join-Path $logDir "frontend.err.log") -Tail 15 | ForEach-Object { Line ("      " + $_) } }
    }
    $feId = Get-Identity $fe.Id
    if ($feId) {
        $d2 = Discover-Children $fe.Id $frontendPort
        $newServices["frontend"] = [pscustomobject]@{
            pid = $feId.pid; start_time = $feId.start_time; exe = $feId.exe; name = $feId.name
            port = $frontendPort; log = $feOut; log_err = $feErr
            cmd_marker = "vite"; children = $d2.children; children_method = $d2.method
            root = $root
        }
        Line ("  · 已登记前端 PID {0}（子进程登记方式：{1}，子进程 {2} 个）" -f $feId.pid, $d2.method, @($d2.children).Count)
    }
}

# 合并：仍在运行的旧记录 + 本次新记录
if ($ledger -and $ledger.services) {
    foreach ($name in @("backend", "frontend")) {
        $rec = $ledger.services.$name
        if ($rec -and -not $newServices.ContainsKey($name)) {
            $v = Test-RecordIdentity $rec
            if ($v.ok) { $newServices[$name] = $rec }
        }
    }
}
Save-Ledger $newServices
Line ("  · 运行态记录已写入：{0}" -f $ledgerPath)
Line "  · 停止服务只依据这份记录：双击 停止服务.bat（scripts\stop.ps1）"

# ---------------------------------------------------------------- 收尾

Blank
Line "【5/5】完成"
$url = "http://127.0.0.1:$frontendPort/"
if ($backOk -and (-not $SkipFrontend -and $fe)) {
    Line "============================================================"
    Line "   可以直接用了：$url"
    Line "   接口文档：http://127.0.0.1:$backendPort/docs"
    Line "   确定性演示（标准案例）实例启动方式："
    Line "       `$env:TRIPCRAFT_SCENARIO_MODE='offline'; powershell -File scripts\start.ps1"
    Line "       （独立实例；普通实例始终走真实模型）"
    Line "   停止：双击 停止服务.bat（只停上面登记的 PID）"
    Line "============================================================"
    if (-not $NoBrowser) { Start-Process $url }
} elseif ($backOk) {
    Line "   后端已就绪：http://127.0.0.1:$backendPort/（前端未启动或未就绪）"
} else {
    Line "   服务没有完全起来，请把上面的日志发给开发同学。"
}

Blank
Line "这个窗口可以关掉，服务在后台继续跑。"
if (-not $NoPause -and [Environment]::UserInteractive) { Read-Host "按回车退出" }
