# TripCraft 司南礼客 · 交接包 · 首次安装与适配（换机第一步）
#
# 作用（**只改本包内的副本**，不动你机器上的其它工程、不动任何运行中的服务）：
#   1) 定位并**校验** python（>=3.11，拒绝 WindowsApps 假 python）与 node（>=22.12.0，推荐 24.x）、npm；
#   2) 改写包内 scripts\desktop_launch.ps1 里打包机的两个绝对路径，回读确认并做 **Parser 解析校验**；
#   3) 安装依赖：frontend 目录 npm ci；后端 pip install -e .（-WithDev 时装 .[dev]，含 pytest/httpx）；
#      任何一步非零退出 → **直接报错停止**，不会打印"适配成功"；
#   4) 打印下一步的两个入口命令。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\首次安装与适配.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\首次安装与适配.ps1 -SkipInstall
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\首次安装与适配.ps1 -WithDev
#
# 注意：本文件必须保存为 **UTF-8 with BOM**（Windows PowerShell 5.1 中文解码）。
param([switch]$SkipInstall, [switch]$WithDev)
$ErrorActionPreference = 'Stop'

$MIN_PY = [version]'3.11.0'
$MIN_NODE = [version]'22.12.0'

$docDir = $PSScriptRoot
$pkg = $docDir | Split-Path -Parent
$launcher = Join-Path $pkg 'scripts\desktop_launch.ps1'
$frontend = Join-Path $pkg 'frontend'
$lock = Join-Path $frontend 'package-lock.json'

Write-Output "包根目录：$pkg"
if (!(Test-Path -LiteralPath $launcher)) { throw "未找到启动脚本：$launcher（包结构不完整）。" }

# 取版本：第二个参数名**不能**叫 $Args —— 那是 PowerShell 自动变量，会被框架清空，
# 结果 python 收到空参数、直接进入交互解释器（独立解压测试实测到过这个 bug）。
function Get-VersionInfo([string]$Exe, [string]$VersionArg) {
    $info = [ordered]@{ Exe = $Exe; Arg = $VersionArg; Version = $null; ExitCode = $null; Raw = '' }
    if ([string]::IsNullOrWhiteSpace($VersionArg)) {
        $info.Raw = '（内部错误：未传入版本参数，拒绝无参启动解释器）'
        return [pscustomobject]$info
    }
    try {
        $raw = & $Exe $VersionArg 2>&1 | Out-String
        $info.ExitCode = $LASTEXITCODE
    } catch {
        $info.Raw = $_.Exception.Message
        return [pscustomobject]$info
    }
    $info.Raw = $raw.Trim()
    $m = [regex]::Match($raw, '(\d+)\.(\d+)\.(\d+)')
    if ($m.Success) {
        $info.Version = [version]("$($m.Groups[1].Value).$($m.Groups[2].Value).$($m.Groups[3].Value)")
    }
    return [pscustomobject]$info
}

# ---- python：排除 WindowsApps 假 python，校验版本与实际退出码 ----
$py = ''
$candidates = @()
$cmdPy = Get-Command python -ErrorAction SilentlyContinue
if ($cmdPy) { $candidates += $cmdPy.Source }
$cmdPy3 = Get-Command python3 -ErrorAction SilentlyContinue
if ($cmdPy3) { $candidates += $cmdPy3.Source }
foreach ($c in $candidates) {
    if ($c -match 'WindowsApps') {
        Write-Output "跳过 WindowsApps 占位 python（不是真实解释器）：$c"
        continue
    }
    $pInfo = Get-VersionInfo -Exe $c -VersionArg '--version'
    if ($pInfo.ExitCode -ne 0 -or !$pInfo.Version) {
        Write-Output ("无法确认 python 版本（退出码 $($pInfo.ExitCode)）：$c  输出：$($pInfo.Raw)")
        continue
    }
    Write-Output "探测 python：$c -> $($pInfo.Version)（exit=$($pInfo.ExitCode)）"
    if ($pInfo.Version -ge $MIN_PY) { $py = $c; break }
    Write-Output "跳过版本过低的 python（$($pInfo.Version) < $MIN_PY）：$c"
}
if (!$py) {
    throw "未找到可用的 python（要求 >= $MIN_PY，且不能是 WindowsApps 占位）。请安装 Python 3.11+ 并勾选 Add python.exe to PATH。"
}
$pyv = (Get-VersionInfo -Exe $py -VersionArg '--version').Version
Write-Output "python = $py（$pyv）"

# ---- node / npm：校验版本；npm 缺失或 lock 缺失都必须报错 ----
$node = ''
$cmdNode = Get-Command node -ErrorAction SilentlyContinue
if ($cmdNode) { $node = $cmdNode.Source }
if (!$node) { throw "未找到 node（要求 >= $MIN_NODE）。请安装 Node.js 22.12+（推荐 24.x）。" }
$nInfo = Get-VersionInfo -Exe $node -VersionArg '--version'
if ($nInfo.ExitCode -ne 0 -or !$nInfo.Version) {
    throw "无法确认 node 版本（退出码 $($nInfo.ExitCode)）：$($nInfo.Raw)"
}
if ($nInfo.Version -lt $MIN_NODE) {
    throw "node 版本过低（$($nInfo.Version) < $MIN_NODE）。前端依赖 electron 要求 node >= 22.12.0（推荐 24.x）。"
}
Write-Output "node   = $node（$($nInfo.Version)）"
$npm = ''
$cmdNpm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (!$cmdNpm) { $cmdNpm = Get-Command npm -ErrorAction SilentlyContinue }
if ($cmdNpm) { $npm = $cmdNpm.Source }
if (!$npm) { throw "未找到 npm（Node.js 安装不完整）。" }
Write-Output "npm    = $npm"

# ---- 路径替换（只改包内副本）----
# 正则用 \r?$ 兼容 CRLF；替换值把单引号转义成 '' 再写入；替换后回读 + Parser 双重校验。
$text = Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
$pyRx = '(?m)^\$pythonExe = ''[^'']*''\r?$'
$nodeRx = '(?m)^\$nodeExe = ''[^'']*''\r?$'
if (![regex]::IsMatch($text, $pyRx) -or ![regex]::IsMatch($text, $nodeRx)) {
    throw '包内启动脚本里没有找到预期的 $pythonExe / $nodeExe 行，无法安全替换（请核对包完整性）。'
}
$pyEsc = $py -replace "'", "''"
$nodeEsc = $node -replace "'", "''"
$text = [regex]::Replace($text, $pyRx, [System.Text.RegularExpressions.MatchEvaluator]{
    param($m) '$pythonExe = ''' + $pyEsc + ''''
}, 1)
$text = [regex]::Replace($text, $nodeRx, [System.Text.RegularExpressions.MatchEvaluator]{
    param($m) '$nodeExe = ''' + $nodeEsc + ''''
}, 1)
Set-Content -LiteralPath $launcher -Value $text -Encoding UTF8

$verify = Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
if ($verify -notmatch [regex]::Escape("`$pythonExe = '$pyEsc'") -or
    $verify -notmatch [regex]::Escape("`$nodeExe = '$nodeEsc'")) {
    throw "路径替换后回读校验失败：$launcher"
}
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($launcher, [ref]$null, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "替换后启动脚本解析失败：$($parseErrors[0].Message)（$launcher）"
}
Write-Output "已改写 / 回读 / Parser 校验通过：$launcher"

if ($SkipInstall) {
    Write-Output "-SkipInstall：跳过依赖安装（只做了路径适配与版本校验）。"
    exit 0
}

# ---- 依赖安装（非零退出必须报错）----
if (!(Test-Path -LiteralPath $lock)) { throw "缺少 frontend\package-lock.json：无法用 npm ci 复现依赖。" }
Write-Output "安装前端依赖：npm ci（frontend 目录，可能需要几分钟）"
Push-Location $frontend
try {
    & $npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci 失败（退出码 $LASTEXITCODE），已停止，不会继续。" }
} finally { Pop-Location }

$pipTarget = if ($WithDev) { '.[dev]' } else { '.' }
Write-Output "安装后端依赖：python -m pip install -e `"$pipTarget`""
Push-Location $pkg
try {
    & $py -m pip install -e $pipTarget
    if ($LASTEXITCODE -ne 0) { throw "pip install -e $pipTarget 失败（退出码 $LASTEXITCODE），已停止。" }
} finally { Pop-Location }

Write-Output ''
Write-Output '适配完成（已装依赖；未做任何服务启动）。下一步：'
Write-Output '  普通模式（随机游客 + 真实模型）：双击 司南礼客桌面版.bat'
Write-Output '  演示模式（固定黄先生，工作人员）：powershell -NoProfile -ExecutionPolicy Bypass -File .\启动标准演示.ps1'
Write-Output '  逐步演示脚本：_交接文档\演示脚本与说明\完整演示脚本.txt'
Write-Output '  开发/跑测试需要 pytest 与 httpx：用 -WithDev 重跑本脚本（= pip install -e ".[dev]"）。'
