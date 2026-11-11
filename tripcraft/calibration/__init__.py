"""人工校准集：数据集 / 指标 / 跑器（PRD 第 25 章）。

用途：用一组**人工打过 M 档并标注了证据坐标**的样本，定期测验评分 Agent。
解决的问题不是「有没有标准」（Rubric 已经解决），而是「判得准不准」。

交付物：
  - data/calibration/samples.jsonl   人工标注样本
  - data/calibration/report.json     最近一次评测报告（同时落库 calibration_run）
"""

from .audit import MIN_PER_SKILL_POINT, audit_dataset
from .dataset import DEFAULT_SAMPLES, load_samples, normalize_text, save_samples
from .metrics import evaluate, sweep_thresholds, TARGET_AGREEMENT, TARGET_EVIDENCE
from .runner import run_calibration

__all__ = ["DEFAULT_SAMPLES", "load_samples", "save_samples", "normalize_text",
           "audit_dataset", "MIN_PER_SKILL_POINT",
           "evaluate", "sweep_thresholds", "run_calibration",
           "TARGET_AGREEMENT", "TARGET_EVIDENCE"]