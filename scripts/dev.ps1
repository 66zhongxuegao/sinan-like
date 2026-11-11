# TripCraft 后端启动脚本（M0）
# 用法：在 _lvyuan 目录下执行  .\scripts\dev.ps1
$ErrorActionPreference = "Stop"
$projRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projRoot
Write-Host "TripCraft 后端启动中 ... http://127.0.0.1:18020/  (文档 /docs)"
python -m uvicorn tripcraft.api.app:create_app --factory --host 127.0.0.1 --port 18020 --reload