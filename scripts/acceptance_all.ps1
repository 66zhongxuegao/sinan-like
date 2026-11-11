<#
集中验收脚本（Lead 提供，可在正常用户环境直接运行）

用途：全部开发成型后一次性跑完交付要求的验收项，原始日志落 output/acceptance/logs/，
      每步退出码汇总到 output/acceptance/logs/steps.json，供 manifest.json 引用。

用法：
    pwsh -NoProfile -File scripts/acceptance_all.ps1
    pwsh -NoProfile -File scripts/acceptance_all.ps1 -SkipFrontendBuild   # 前端已单独构建时

说明：
- 不做「每改几行就跑一次」的碎片测试；这是成型后的集中验收。
- 前端生产构建 = vue-tsc --noEmit && vite build（frontend/package.json 的 build 脚本）。
- 后端测试使用独立临时库（tests/conftest.py 强制 TRIPCRAFT_DB 指向 tempdir）。
- 若某步在受限沙箱下因进程/管道限制失败，脚本会如实记录退出码与日志路径，
  不会伪造通过；请把该步的命令与错误交给可执行环境复跑。
#>

param(
    [switch]$SkipFrontendBuild,
    [switch]$SkipPytest
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "output\acceptance\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$steps = New-Object System.Collections.ArrayList

function Invoke-Step {
    param(
        [string]$Name,
        [string]$WorkDir,
        [scriptblock]$Action
    )
    $log = Join-Path $logDir "$Name.log"
    Write-Host ""
    Write-Host "=============================================================="
    Write-Host " STEP $Name   (cwd: $WorkDir)"
    Write-Host "=============================================================="
    Push-Location $WorkDir
    try {
        & $Action 2>&1 | Tee-Object -FilePath $log
    } finally {
        Pop-Location
    }
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    Write-Host "  -> exit code: $code   (log: $log)"
    [void]$steps.Add([pscustomobject]@{
        step      = $Name
        cwd       = $WorkDir
        exit_code = $code
        log       = $log.Replace("$root\", "")
    })
}

# 1) 后端语法/导入完整性
Invoke-Step -Name "01-compileall" -WorkDir $root -Action {
    python -m compileall -q tripcraft
}

# 2) 应用装配（真实 create_app + OpenAPI 路由表）
Invoke-Step -Name "02-app-assembly" -WorkDir $root -Action {
    $env:TRIPCRAFT_DB = Join-Path $logDir "assembly-smoke.sqlite"
    python -X utf8 -c "import tripcraft.api.app as a; app=a.create_app(); p=app.openapi()['paths']; print('openapi paths:', len(p)); print('has /auth/login:', '/auth/login' in p)"
}

# 3) 前端生产构建（vue-tsc + vite build）
if (-not $SkipFrontendBuild) {
    Invoke-Step -Name "03-frontend-build" -WorkDir (Join-Path $root "frontend") -Action {
        npm run build
    }
}

# 4) 后端全量测试
if (-not $SkipPytest) {
    Invoke-Step -Name "04-backend-pytest" -WorkDir $root -Action {
        # -p no:cacheprovider：受限环境下 pytest 缓存目录会落在仓库根且沙箱无法删除，
        # 打开缓存会持续产生不可清理残留。正常环境也可以安全地关掉。
        python -m pytest -q -p no:cacheprovider
    }
}

# 5) 标准案例全链路（scenario 域交付的验收脚本；存在才跑）
$caseScript = Join-Path $root "scripts\acceptance_standard_case.py"
if (Test-Path $caseScript) {
    Invoke-Step -Name "05-standard-case" -WorkDir $root -Action {
        python -X utf8 scripts\acceptance_standard_case.py
    }
} else {
    Write-Host "[skip] scripts/acceptance_standard_case.py 不存在"
    [void]$steps.Add([pscustomobject]@{ step = "05-standard-case"; cwd = $root; exit_code = $null; log = "NOT PRESENT" })
}

# 6) Lead 跨模块验收：两账号隔离 / 越权 / 隐藏字段 / PDF / WebSocket 门禁
Invoke-Step -Name "06-lead-isolation-leak" -WorkDir $root -Action {
    python -X utf8 scripts\lead_acceptance_checks.py
}

# 7) 真实模型链路（与确定性标准案例**分开**记录）
#    配置存在 ≠ 连通可用；脚本只做适量真实调用，且不打印任何凭据。
Invoke-Step -Name "07-real-model" -WorkDir $root -Action {
    python -X utf8 scripts\acceptance_real_model.py
}

# 汇总
$summaryPath = Join-Path $logDir "steps.json"
$payload = [pscustomobject]@{
    generated_at = (Get-Date).ToString("s")
    baseline     = "b6535fd5dff9a074bd7999596628cdd363e1cc06"
    steps        = $steps
}
$payload | ConvertTo-Json -Depth 5 | Set-Content -Path $summaryPath -Encoding utf8

Write-Host ""
Write-Host "=============================================================="
Write-Host " 汇总（退出码）"
Write-Host "=============================================================="
foreach ($s in $steps) {
    $mark = if ($null -eq $s.exit_code) { "SKIP" } elseif ($s.exit_code -eq 0) { "PASS" } else { "FAIL" }
    Write-Host ("  {0,-22} {1} (exit={2})" -f $s.step, $mark, $s.exit_code)
}
Write-Host ""
Write-Host "步骤汇总: $summaryPath"
Write-Host "注意：任一步 FAIL 都必须在最终报告中如实列出，不得写「全部通过」。"

$failed = @($steps | Where-Object { $null -ne $_.exit_code -and $_.exit_code -ne 0 })
if ($failed.Count -gt 0) { exit 1 } else { exit 0 }
