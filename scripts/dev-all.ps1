# 兼容入口：一键启动已迁到 scripts\start.ps1
# 保留本文件是为了让老的命令（.\scripts\dev-all.ps1）继续能用。
& (Join-Path $PSScriptRoot "start.ps1") @args
