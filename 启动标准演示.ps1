# 司南礼客桌面版 · 内部演示启动入口（工作人员用）
#
# 与普通入口（双击 司南礼客桌面版.bat）共用同一份启动实现 scripts\desktop_launch.ps1，
# 只是切到 -Mode Demo：端口 18930/15191、演示库 .dsh-run\codex-review\preview.sqlite、
# 启动期声明确定性离线 + 固定案例替换随机游客、独立桌面会话。
#
#   -WebOnly     只起服务、不开桌面窗口（排障用）
#   -SelfCheck   用独立桌面 profile 打开自检窗口（不覆盖正在使用的窗口）
# 注意：本文件必须保存为 **UTF-8 with BOM**（Windows PowerShell 5.1 中文解码）。
param([switch]$WebOnly, [switch]$SelfCheck)
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'scripts\desktop_launch.ps1'
if (!(Test-Path -LiteralPath $launcher)) {
    throw "未找到启动实现：$launcher（仓库结构不完整）。"
}
# 命名参数直接转发（不用数组展开：数组会被当作位置参数，-Mode 可能绑不上 ValidateSet）
& $launcher -Mode Demo -WebOnly:$WebOnly -SelfCheck:$SelfCheck
