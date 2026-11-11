<#
  司南礼客 TripCraft · 停止服务（安全版 v2）
  ---------------------------------------------------------------------------
  这个脚本**只停本项目自己记录过的进程**：
    · 记录文件：<仓库根>\.runtime\pids.json（由 scripts\start.ps1 写入）
    · 停止前逐个核对身份：PID 仍在 + 启动时间一致 + 可执行文件路径一致
      （能用命令行时还要含本仓库路径）；任何一条不符就**跳过并打印原因**。
    · 不再按命令行模式（python*/node*+vite）或端口占用者盲杀任何进程。
    · 不碰 DSH、不碰用户其它项目；端口只是"报告"用，不据端口杀进程。
    · 能力降级（如实说明）：受限环境里 Get-CimInstance(WMI) / Get-NetTCPConnection
      可能被拒。此时身份核对退回 Get-Process 的 Path + StartTime（宁可漏杀不可误杀），
      **端口占用检测不可用时本脚本只报告、不处理**，不会假装查到了占用者。

  用法：
    powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
    powershell -ExecutionPolicy Bypass -File scripts\stop.ps1 -NoPause -DryRun
#>
param(
    [switch]$NoPause,
    [switch]$DryRun
)

$root = Split-Path -Parent $PSScriptRoot
$ledgerDir = Join-Path $root ".runtime"
$ledgerPath = Join-Path $ledgerDir "pids.json"

function Line($t) { Write-Host $t }

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


# 只用 Get-Process：沙箱/受限环境下 CIM/WMI 可能被拒，不能让身份核对依赖它
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

function Test-RecordIdentity($rec, [string]$rootNorm) {
    if (-not $rec -or -not $rec.pid) { return @{ ok = $false; reason = "记录缺少 pid" } }
    $cur = Get-Identity ([int]$rec.pid)
    if (-not $cur) { return @{ ok = $false; reason = "PID $($rec.pid) 已不存在（可能自己退出了）" } }
    if (-not $rec.start_time -or -not $cur.start_time) {
        return @{ ok = $false; reason = "缺少启动时间，无法确认是本项目进程" }
    }
    try {
        $a = Convert-ToUtc $rec.start_time
        $b = Convert-ToUtc $cur.start_time
        if (-not $a -or -not $b) {
            return @{ ok = $false; reason = "启动时间无法解析，拒绝盲停" }
        }
        if ([math]::Abs(($a - $b).TotalSeconds) -gt 3) {
            return @{ ok = $false; reason = "启动时间不符（记录 $($rec.start_time) / 实际 $($cur.start_time)）：PID 可能已被系统复用" }
        }
    } catch {
        return @{ ok = $false; reason = "启动时间无法解析，拒绝盲停" }
    }
    if ($rec.exe -and $cur.exe) {
        if ((Normalize-Path $rec.exe) -ne (Normalize-Path $cur.exe)) {
            return @{ ok = $false; reason = "可执行文件路径不符（记录 $($rec.exe) / 实际 $($cur.exe)）" }
        }
    }
    $cmd = Get-CmdLine ([int]$rec.pid)
    if ($cmd) {
        $hitRoot = $cmd.IndexOf($rootNorm, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $hitMark = $false
        if ($rec.cmd_marker) { $hitMark = $cmd.IndexOf([string]$rec.cmd_marker, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 }
        if (-not ($hitRoot -or $hitMark)) {
            return @{ ok = $false; reason = "命令行不含本仓库路径，拒绝停止" }
        }
    }
    return @{ ok = $true; reason = "" }
}

function Get-PortOwnerPid([int]$port) {
    # 受限环境下可能无权限；返回 0 表示"查不到"，查不到就绝不杀
    try {
        $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop | Select-Object -First 1
        if ($c) { return [int]$c.OwningProcess }
    } catch { }
    # 兜底：netstat -ano（不需要 WMI 权限）。仅用于"报告谁占着端口"，绝不据此杀进程。
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

Line ""
Line "正在停止司南礼客服务（只停本项目记录过的进程）..."

if (-not (Test-Path $ledgerPath)) {
    Line "  · 没有运行态记录文件：$ledgerPath"
    Line "  · 按安全规则，本脚本不会按命令行或端口盲杀任何进程。"
    Line "  · 如果你确认有司南礼客服务在跑，请先用 scripts\start.ps1 重新启动（会写入记录），再停止。"
    if (-not $NoPause -and [Environment]::UserInteractive) { Read-Host "按回车退出" }
    exit 0
}

$ledger = $null
try { $ledger = Get-Content $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {
    Line "  · 运行态记录无法解析：$($_.Exception.Message)"
    Line "  · 为安全起见不做任何停止操作。"
    if (-not $NoPause -and [Environment]::UserInteractive) { Read-Host "按回车退出" }
    exit 0
}

$rootNorm = $root
$recRootNorm = ""
if ($ledger.root) { $recRootNorm = [string]$ledger.root }
if ($recRootNorm -and ((Normalize-Path $recRootNorm) -ne (Normalize-Path $root))) {
    Line "  · 记录文件属于另一个目录（记录 $recRootNorm / 当前 $root）：拒绝操作。"
    if (-not $NoPause -and [Environment]::UserInteractive) { Read-Host "按回车退出" }
    exit 0
}

$stopped = 0
$skipped = 0
$stoppedIds = @()
$remaining = @{}
$ports = @()
# 身份不符的记录必须**保留**在台账里：那是用户正在运行的服务记录，
# 不能因为"这次没能安全停掉"就被脚本抹掉（监督者明确要求）。
$preserved = @{}

foreach ($name in @("backend", "frontend")) {
    if (-not $ledger.services) { break }
    $rec = $ledger.services.$name
    if (-not $rec) { continue }
    $verdict = Test-RecordIdentity $rec $rootNorm
    if (-not $verdict.ok) {
        Line ("  ! 跳过 {0}：{1}" -f $name, $verdict.reason)
        $skipped++
        $preserved[$name] = $rec
        $preserved[$name] | Add-Member -NotePropertyName last_skip_reason -NotePropertyValue $verdict.reason -Force
        $preserved[$name] | Add-Member -NotePropertyName last_skip_at -NotePropertyValue ((Get-Date).ToString("o")) -Force
        continue
    }
    # 先子后父
    foreach ($child in @($rec.children)) {
        if (-not $child -or -not $child.pid) { continue }
        $cv = Test-RecordIdentity $child $rootNorm
        if ($cv.ok) {
            if ($DryRun) { Line ("  · [DryRun] 将停止 {0} 子进程 PID {1}" -f $name, $child.pid) }
            else {
                Stop-Process -Id ([int]$child.pid) -Force -ErrorAction SilentlyContinue
                Line ("  · 已停止 {0} 子进程 PID {1}" -f $name, $child.pid)
            }
            $stoppedIds += [int]$child.pid
            $stopped++
        } else {
            Line ("  ! 跳过 {0} 子进程 PID {1}：{2}" -f $name, $child.pid, $cv.reason)
            $skipped++
        }
    }
    if ($DryRun) { Line ("  · [DryRun] 将停止 {0} PID {1}" -f $name, $rec.pid) }
    else {
        Stop-Process -Id ([int]$rec.pid) -Force -ErrorAction SilentlyContinue
        Line ("  · 已停止 {0} PID {1}（{2}）" -f $name, $rec.pid, $rec.exe)
    }
    $stoppedIds += [int]$rec.pid
    $stopped++
    if ($rec.port) { $ports += [int]$rec.port }
}

# 端口只做「报告」：不认识的占用者一律不动
Start-Sleep -Milliseconds 500
foreach ($port in $ports) {
    $owner = Get-PortOwnerPid $port
    if ($owner -le 0) { continue }
    if ($stoppedIds -contains $owner) { continue }
    $p = Get-Process -Id $owner -ErrorAction SilentlyContinue
    $nm = ""
    if ($p) { $nm = $p.ProcessName }
    Line ("  ! 端口 {0} 仍被 PID {1}（{2}）占用：不在本项目记录里，本脚本不会动它。" -f $port, $owner, $nm)
}

if (-not $DryRun) {
    # 记录被清空：下次停止不会有任何"猜测"
    $left = @{}
    if ($ledger.services) {
        foreach ($name in @("backend", "frontend")) {
            $rec = $ledger.services.$name
            if (-not $rec) { continue }
            if ($preserved.ContainsKey($name)) {
                $left[$name] = $preserved[$name]      # 没安全停掉的：原样保留
                continue
            }
            $v = Test-RecordIdentity $rec $rootNorm
            if ($v.ok) { $left[$name] = $rec }         # 仍然活着的：保留
        }
    }
    $out = [pscustomobject]@{
        schema     = "tripcraft.runtime.pids/v2"
        root       = $root
        updated_at = (Get-Date).ToString("o")
        services   = $left
    }
    New-Item -ItemType Directory -Force -Path $ledgerDir | Out-Null
    $out | ConvertTo-Json -Depth 8 | Set-Content -Path $ledgerPath -Encoding UTF8
}

Line ""
if ($stopped -gt 0) { Line ("已停止 $stopped 个本项目进程。") }
else { Line "没有停止任何进程。" }
if ($skipped -gt 0) {
    Line ("跳过 $skipped 个身份不符的记录（已打印原因），这些记录**原样保留**在台账里，不会被抹掉。")
}
Line ("记录文件：{0}" -f $ledgerPath)
if (-not $NoPause -and [Environment]::UserInteractive) { Read-Host "按回车退出" }
