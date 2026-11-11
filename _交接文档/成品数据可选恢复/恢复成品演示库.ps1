# TripCraft 司南礼客 · 恢复成品演示库（可选）
#
# 重要口径（先读）：
#   · 本脚本**不会**在线替换任何正在使用的库；请在**首次启动演示模式之前**恢复
#     （此时没有任何进程打开目标库）。已有运行库时请先自行备份/改名，不要带着服务改名。
#   · 标准入口 启动标准演示.ps1**只认固定位置** .dsh-run\codex-review\preview.sqlite。
#     用 -Target 写到别的路径 = 只是**保存一份备份**，标准入口不会自动用它；
#     想在演示里看到成品订单，必须恢复到那个固定位置（且该位置当前不存在）。
#   · 复制用 File.Copy(..., overwrite:false)：目标存在就**抛错**，不存在隐式覆盖。
#
# 用法：
#   1) 恢复到演示库固定位置（推荐顺序：先恢复，再启动演示）
#      powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\成品数据可选恢复\恢复成品演示库.ps1
#   2) 只想另存一份备份（不会被标准入口使用）
#      powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\成品数据可选恢复\恢复成品演示库.ps1 -Target backup\demo-preview-backup.sqlite
#
# 注意：本文件必须保存为 **UTF-8 with BOM**（Windows PowerShell 5.1 中文解码）。
param([string]$Target = '')
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
$pkg = $here | Split-Path -Parent | Split-Path -Parent
$snapshot = Join-Path $here 'preview-verified-snapshot.sqlite'
if (!(Test-Path -LiteralPath $snapshot)) { throw "未找到快照：$snapshot" }

$fixedTarget = Join-Path $pkg '.dsh-run\codex-review\preview.sqlite'
$isBackupOnly = $false
if (!$Target) {
    $Target = $fixedTarget
} elseif (![System.IO.Path]::IsPathRooted($Target)) {
    $Target = Join-Path $pkg $Target
    $isBackupOnly = ($Target -ne $fixedTarget)
} else {
    $isBackupOnly = ($Target -ne $fixedTarget)
}

# 目标存在 → 直接报错（File.Copy 也会再兜底一次）
if (Test-Path -LiteralPath $Target) {
    throw ("目标库已存在，按交接包约定**拒绝覆盖**：$Target`n" +
           "请先备份并改名/移走它（例如 preview.sqlite -> preview-backup-<日期>.sqlite），再运行本脚本；`n" +
           "或用 -Target 指定新的备份路径（注意：-Target 只保存备份，标准入口不会自动使用它）。")
}

$targetDir = $Target | Split-Path -Parent
if ($targetDir -and !(Test-Path -LiteralPath $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }

# 不覆盖复制：目标若在竞态中被创建，这里会抛错
[System.IO.File]::Copy($snapshot, $Target, $false)
Write-Output "已从快照复制到：$Target"
if ($isBackupOnly) {
    Write-Output '  ！注意：这是**备份路径**，不是一个会被标准入口使用的位置。'
    Write-Output ("  标准入口固定使用：" + $fixedTarget)
    Write-Output '  若要在演示里直接看到成品订单，请在首次启动演示前恢复到上面那个固定位置（当前它不存在）。'
} else {
    Write-Output '  这是演示模式的固定库位置：启动标准演示.ps1 后会直接使用它。'
    Write-Output '  顺序要求：先完成本次恢复，再启动演示（不要在服务运行时改名/替换库）。'
}
Write-Output ("快照 SHA256：" + (Get-FileHash -LiteralPath $snapshot -Algorithm SHA256).Hash)
Write-Output ("恢复后 SHA256：" + (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash)

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd -and $pyCmd.Source -notmatch 'WindowsApps') {
    $code = @'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print('users       :', con.execute('select username, kind from users').fetchall())
print('orders      :', con.execute('select order_id, status, stage_index from biz_order').fetchall())
print('sessions    :', con.execute('select count(*) from sessions').fetchone()[0])
print('calibration :', con.execute('select count(*) from calibration_run').fetchone()[0])
print('ability rows:', con.execute('select count(*) from ability').fetchone()[0])
con.close()
'@
    $tmp = Join-Path $pkg ('_chk-' + [guid]::NewGuid().ToString('N') + '.py')
    Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8
    try { & $pyCmd.Source $tmp $Target } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
} else {
    Write-Output '提示：未找到可用 python，跳过核对查询（可用任意 SQLite 工具打开上面的路径查看）。'
}

Write-Output ''
Write-Output '下一步（示例）：'
Write-Output '  powershell -NoProfile -ExecutionPolicy Bypass -File .\启动标准演示.ps1'
Write-Output '  用成品账号登录查看已完成订单：demo-linxiao-verified-20261017 / LvyuanDemo#2026'
Write-Output '  现场从零演示账号 demo-linxiao-replay-20261017 仍未注册，请勿提前创建。'
