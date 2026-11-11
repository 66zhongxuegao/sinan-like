# TripCraft M0 冒烟自检：跑测试 + 打印契约摘要
$ErrorActionPreference = "Stop"
$projRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projRoot
python -m pytest -q
python -X utf8 -c "from tripcraft.contracts import skill_points as sp; from tripcraft.contracts.enums import Dimension, StepId; print('技能点:', len(sp.SKILL_POINTS)); print('维度:', len(list(Dimension))); print('步骤:', len(list(StepId)))"