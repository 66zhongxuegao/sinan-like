<#
  司南礼客 TripCraft · 启动/停止安全性验证（launch-safety 的交付验收脚本）

  验证「启动 → 运行 → 停止只影响自身」，重点是**占位进程不被误杀**。

  用法：
    powershell -ExecutionPolicy Bypass -File scripts\acceptance_launch_safety.ps1
    （默认后端测试端口 18910、占位进程端口 19112，避开产品默认 18020/5190）

  断言：
    A. 记录台账由 start.ps1 写入，含 pid + start_time + exe；
    B. 启动后服务真的可访问（HTTP 200），停止后进程消失、台账清空；
    C. 台账里「PID 仍在但启动时间不符」→ stop 跳过并打印原因，不杀；
    D. 台账里「PID 仍在、时间对、但可执行路径不符」→ stop 跳过并打印原因，不杀；
    E. 端口被**非本项目**占位进程占用时，-StrictPort 明确报错退出（非 0）且占位进程存活；
    F. 整个过程中占位进程始终存活（不被误杀）；
    G. 脚本里不存在按命令行模式/端口盲杀的写法，也不含任何针对 DSH 的进程操作。

  证据落 output/acceptance/evidence/launch-safety/，日志落 output/acceptance/logs/。
  任何断言失败 → 非零退出并打印失败项（按纪律不跳过）。
#>
param(
    [int]$TestBackendPort = 18910,
    [int]$PlaceholderPort = 19112
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$ledgerDir = Join-Path $root ".runtime"
$ledgerPath = Join-Path $ledgerDir "pids.json"
$evidDir = Join-Path $root "output\acceptance\evidence\launch-safety"
$logDir = Join-Path $root "output\acceptance\logs"
New-Item -ItemType Directory -Force -Path $evidDir, $logDir | Out-Null

$steps = New-Object System.Collections.ArrayList
$logLines = New-Object System.Collections.ArrayList
function Log($t) { Write-Host $t; [void]$logLines.Add($t) }
function Check([string]$name, [bool]$ok, $detail) {
    [void]$steps.Add([pscustomobject]@{ step = $name; ok = $ok; detail = $detail })
    Log ("  [{0}] {1} → {2}" -f $(if ($ok) { "OK " } else { "NG " }), $name, (($detail | Out-String).Trim() -replace "\r?\n", " "))
}
function Run-Ps([string]$file, [string[]]$extra) {
    # 不能用管道捕获：start.ps1 会派生长期运行的 uvicorn，它继承 stdout，
    # 管道要等所有句柄关闭才 EOF，会死等。改用文件重定向 + WaitForExit（只等父进程）。
    $tag = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $outFile = Join-Path $env:TEMP "runps_$tag.out"
    $errFile = Join-Path $env:TEMP "runps_$tag.err"
    $inner = "& '" + $file + "'"
    foreach ($a in $extra) { $inner += " '" + $a + "'" }
    $inner += " *>&1 | Out-File -FilePath '" + $outFile + "' -Encoding utf8"
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $inner)
    $p = Start-Process -FilePath "pwsh" -ArgumentList $args -PassThru -WindowStyle Hidden `
        -RedirectStandardError $errFile
    # 注意：Start-Process -Wait 在 Windows 上会连子孙进程一起等（uvicorn 不停就一直等），
    # 所以这里只等这一个进程本身。超时必须显式失败，不能拿 null exit code 当通过。
    [void]$p.WaitForExit(300000)
    $timedOut = (-not $p.HasExited)
    if ($timedOut) {
        try { $p.Kill() } catch { }
        $code = 124
        Log ('  [NG ] 嵌套脚本 300 秒未退出（超时）→ 记为失败，退出码 124：' + $file)
    } else {
        $code = $p.ExitCode
    }
    $out = ""
    if (Test-Path $outFile) { $out += (Get-Content $outFile -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $errFile) { $out += "`n" + (Get-Content $errFile -Raw -ErrorAction SilentlyContinue) }
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ output = $out; code = $code; timed_out = $timedOut }
}
function Get-IdentityLite([int]$procId) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) { return $null }
    $exe = ""; try { $exe = [string]$p.Path } catch { }
    $st = ""; try { $st = $p.StartTime.ToUniversalTime().ToString("o") } catch { }
    return [pscustomobject]@{ pid = $procId; exe = $exe; start_time = $st }
}

Log "============================================================"
Log "启动/停止安全性验证（占位进程不被误杀）"
Log "============================================================"

# ---- 台账保护：验证过程会写入测试记录，必须先备份、结束再恢复 ----
$ledgerBackup = $null
if (Test-Path $ledgerPath) {
    $ledgerBackup = Get-Content $ledgerPath -Raw -Encoding UTF8
    Log ("[台账保护] 已备份现有运行态记录（{0} 字节）；验证结束会原样恢复。" -f $ledgerBackup.Length)
} else {
    Log "[台账保护] 当前没有运行态记录；验证结束会删除测试记录。"
}

# ---------------------------------------------------------------- C0 占位进程
Log ""
Log "[C0] 起一个『非本项目』占位进程占住端口 $PlaceholderPort"
$phScript = Join-Path $env:TEMP "tripcraft_placeholder.py"
$phErr = Join-Path $env:TEMP "tripcraft_placeholder.err"
@"
import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", $PlaceholderPort))
s.listen(1)
time.sleep(600)
"@ | Set-Content -Path $phScript -Encoding UTF8
$py = (Get-Command python).Source
$ph = Start-Process -FilePath $py -ArgumentList @($phScript) -PassThru -WindowStyle Hidden -RedirectStandardError $phErr
# 记下占位进程 PID：万一脚本被中途杀掉，也能凭这个文件精确清理（不用猜）
Set-Content -Path (Join-Path $env:TEMP "tripcraft_placeholder.pid") -Value "$($ph.Id)" -Encoding ASCII
Start-Sleep -Seconds 3
$phId = Get-IdentityLite $ph.Id
# 用 TCP 连接确认它真在监听（沙箱里查不到占用者也用这个）
$phListening = $false
try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $PlaceholderPort); $c.Close(); $phListening = $true } catch { }
Check "占位进程已启动并监听 $PlaceholderPort" ($phListening -and $null -ne $phId) @{ pid = $ph.Id; exe = $phId.exe; stderr = (Get-Content $phErr -Raw -ErrorAction SilentlyContinue) }
if (-not $phListening) { Log "  占位进程没起来，后续断言无意义 → 停止"; exit 1 }

$phAlive = { $null -ne (Get-Process -Id $ph.Id -ErrorAction SilentlyContinue) }

try {
    # ------------------------------------------------------------ C1 台账身份核对：时间不符
    Log ""
    Log "[C1] 台账记录『PID 存在但启动时间不符』（模拟 PID 被复用的过期记录）"
    New-Item -ItemType Directory -Force -Path $ledgerDir | Out-Null
    $fake = [pscustomobject]@{
        schema = "tripcraft.runtime.pids/v2"; root = $root
        updated_at = (Get-Date).ToString("o")
        services = [pscustomobject]@{
            backend = [pscustomobject]@{
                pid = $ph.Id; start_time = "2001-01-01T00:00:00.0000000Z"; exe = $phId.exe
                name = "python"; port = $PlaceholderPort; cmd_marker = "uvicorn"; children = @()
            }
        }
    }
    $fake | ConvertTo-Json -Depth 8 | Set-Content -Path $ledgerPath -Encoding UTF8
    $r1 = Run-Ps (Join-Path $root "scripts\stop.ps1") @("-NoPause")
    Check "stop 因启动时间不符而跳过（不杀）" ($r1.output -match "启动时间不符") @{ code = $r1.code }
    Check "占位进程在 C1 后仍存活" (& $phAlive) @{ pid = $ph.Id }
    $ledAfterC1 = $null
    try { $ledAfterC1 = Get-Content $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    $keptC1 = $false
    if ($ledAfterC1 -and $ledAfterC1.services -and $ledAfterC1.services.backend) { $keptC1 = $true }
    Check "身份不符的记录被原样保留（不被脚本抹掉）" $keptC1 @{ kept = $keptC1 }

    # ------------------------------------------------------------ C2 台账身份核对：路径不符
    Log ""
    Log "[C2] 台账记录『PID 存在、时间对、可执行路径不符』"
    $fake2 = [pscustomobject]@{
        schema = "tripcraft.runtime.pids/v2"; root = $root
        updated_at = (Get-Date).ToString("o")
        services = [pscustomobject]@{
            frontend = [pscustomobject]@{
                pid = $ph.Id; start_time = $phId.start_time; exe = "C:\definitely\not\this\repo\other.exe"
                name = "python"; port = $PlaceholderPort; cmd_marker = "vite"; children = @()
            }
        }
    }
    $fake2 | ConvertTo-Json -Depth 8 | Set-Content -Path $ledgerPath -Encoding UTF8
    $r2 = Run-Ps (Join-Path $root "scripts\stop.ps1") @("-NoPause")
    Check "stop 因可执行路径不符而跳过（不杀）" ($r2.output -match "可执行文件路径不符") @{ code = $r2.code }
    Check "占位进程在 C2 后仍存活" (& $phAlive) @{ pid = $ph.Id }

    # ------------------------------------------------------------ C3 端口冲突：-StrictPort 明确报错
    Log ""
    Log "[C3] 端口被非本项目占位进程占用时，start -StrictPort 必须明确报错退出"
    Remove-Item -LiteralPath $ledgerPath -Force -ErrorAction SilentlyContinue
    $r3 = Run-Ps (Join-Path $root "scripts\start.ps1") @(
        "-NoPause", "-NoBrowser", "-SkipFrontend", "-NoReload", "-StrictPort", "-BackendPort", "$PlaceholderPort")
    Check "start -StrictPort 非零退出（明确报错，不静默继续，且不是超时）" (($r3.code -ne 0) -and (-not $r3.timed_out)) @{ code = $r3.code; timed_out = $r3.timed_out }
    Check "start 明确说明端口被占用" ($r3.output -match "占用") @{ snippet = ($r3.output -split "`n" | Where-Object { $_ -match "占用" } | Select-Object -First 1) }
    Check "占位进程在 C3 后仍存活（未被误杀）" (& $phAlive) @{ pid = $ph.Id }

    # ------------------------------------------------------------ C4 正常启动 → 停止只停自己
    Log ""
    Log "[C4] 正常启动（独立端口 $TestBackendPort，-NoReload）→ 停止只停自己记录的进程"
    $env:TRIPCRAFT_DB = Join-Path $env:TEMP "tripcraft_launch_safety.sqlite"
    $r4 = Run-Ps (Join-Path $root "scripts\start.ps1") @(
        "-NoPause", "-NoBrowser", "-SkipFrontend", "-NoReload", "-StrictPort", "-BackendPort", "$TestBackendPort")
    $health = $false
    try { $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$TestBackendPort/" -TimeoutSec 5 -UseBasicParsing; $health = ($resp.StatusCode -eq 200) } catch { }
    Check "后端在本项目端口上真实可用（HTTP 200）" $health @{ port = $TestBackendPort; code = $r4.code }

    $led = $null
    try { $led = Get-Content $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    $rec = $null; if ($led -and $led.services) { $rec = $led.services.backend }
    Check "台账写入 backend 记录（pid + start_time + exe）" ($null -ne $rec -and $rec.pid -gt 0 -and $rec.start_time -and $rec.exe) @{ rec = $rec }
    $ownPid = 0; if ($rec) { $ownPid = [int]$rec.pid }
    Check "台账记录的就是我们刚启动的进程" ($ownPid -gt 0 -and $null -ne (Get-Process -Id $ownPid -ErrorAction SilentlyContinue)) @{ pid = $ownPid }

    $r5 = Run-Ps (Join-Path $root "scripts\stop.ps1") @("-NoPause")
    Start-Sleep -Seconds 1
    $gone = ($null -eq (Get-Process -Id $ownPid -ErrorAction SilentlyContinue))
    Check "stop 停掉了自己记录的进程" $gone @{ pid = $ownPid; code = $r5.code }
    $led2 = $null
    try { $led2 = Get-Content $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    $leftCount = 0
    if ($led2 -and $led2.services) { $leftCount = @($led2.services.PSObject.Properties).Count }
    Check "台账已清空（没有留下猜测性记录）" ($leftCount -eq 0) @{ left = $leftCount }
    Check "占位进程在 C4 后仍存活（stop 只停自己）" (& $phAlive) @{ pid = $ph.Id }

    # ------------------------------------------------------------ C5 静态检查
    Log ""
    Log "[C5] 静态检查：不得按命令行模式/端口盲杀，不得操作 DSH"
    $startTxt = Get-Content (Join-Path $root "scripts\start.ps1") -Raw -Encoding UTF8
    $stopTxt = Get-Content (Join-Path $root "scripts\stop.ps1") -Raw -Encoding UTF8
    $badPatterns = @('CommandLine -like "\*vite\*"', 'CommandLine -like "\*tripcraft.api.app\*"',
                     'Where-Object { $_.Name -like "node\*"')
    $hits = @()
    foreach ($p in $badPatterns) { if ($startTxt -match $p -or $stopTxt -match $p) { $hits += $p } }
    Check "没有『按命令行模式全机杀』的写法" ($hits.Count -eq 0) @{ hits = $hits }
    $dshHits = @()
    foreach ($t in @($startTxt, $stopTxt)) {
        if ($t -match "dsh-run" -or $t -match "DeepSeek Harness" -or $t -match "app.asar") { $dshHits += "found" }
    }
    Check "脚本不含任何针对 DSH 的进程操作" ($dshHits.Count -eq 0) @{ hits = $dshHits }
    Check "stop 引用运行态台账（只按记录停）" ($stopTxt -match "pids.json") @{ ledger = $ledgerPath }
    Check "start 写入运行态台账" ($startTxt -match "pids.json" -and $startTxt -match "Save-Ledger") @{}
} finally {
    if (Get-Process -Id $ph.Id -ErrorAction SilentlyContinue) {
        Log ""
        Log ("[清理] 停止占位进程 PID {0}（它是本脚本自己起的，不是项目服务）" -f $ph.Id)
        Stop-Process -Id $ph.Id -Force -ErrorAction SilentlyContinue
    }
    $pidFile = Join-Path $env:TEMP "tripcraft_placeholder.pid"
    if (Test-Path $pidFile) {
        $oldPid = 0
        [void][int]::TryParse((Get-Content $pidFile -Raw -ErrorAction SilentlyContinue), [ref]$oldPid)
        if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Log ("[清理] 停止遗留占位进程 PID {0}（来自 pid 文件）" -f $oldPid)
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $env:TEMP "tripcraft_launch_safety.sqlite") -Force -ErrorAction SilentlyContinue
}

# ---- 恢复台账：把验证期间写的测试记录还原成用户原来那份 ----
if ($null -ne $ledgerBackup) {
    New-Item -ItemType Directory -Force -Path $ledgerDir | Out-Null
    [System.IO.File]::WriteAllText($ledgerPath, $ledgerBackup, (New-Object System.Text.UTF8Encoding($false)))
    Log "[台账保护] 已恢复验证前的运行态记录。"
} else {
    Remove-Item -LiteralPath $ledgerPath -Force -ErrorAction SilentlyContinue
    Log "[台账保护] 已删除验证期间的测试记录（原本来就没有）。"
}

$ok = $true
foreach ($s in $steps) { if (-not $s.ok) { $ok = $false } }
$failed = @($steps | Where-Object { -not $_.ok } | ForEach-Object { $_.step })
$summary = [pscustomobject]@{
    script = "acceptance_launch_safety.ps1"
    ok = $ok
    failed = $failed
    test_backend_port = $TestBackendPort
    placeholder_port = $PlaceholderPort
    capability_note = "沙箱内 CIM/WMI/Get-NetTCPConnection 被拒；本脚本用 Get-Process 身份核对 + TCP 连接探测做断言。端口占用者识别与 uvicorn --reload 子进程登记需要在正常环境侧复核（见交付说明）。"
    steps = $steps
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $evidDir "launch-safety.json") -Encoding UTF8
[void]$logLines.Add(("证据：{0}" -f (Join-Path $evidDir "launch-safety.json")))
$logLines -join "`r`n" | Set-Content -Path (Join-Path $logDir "launch-safety.log") -Encoding UTF8

Log ""
Log ("结果：{0}" -f $(if ($ok) { "全部通过" } else { "失败项：" + ($failed -join " / ") }))
Log ("证据：{0}" -f (Join-Path $evidDir "launch-safety.json"))
if (-not $ok) { exit 1 }
exit 0
