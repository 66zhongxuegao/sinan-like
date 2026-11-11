"""校准跑器：用人工标注样本测验评分 Agent（PRD 25.3–25.5）。"""

from __future__ import annotations

import time
from typing import Callable

from ..agents.scorer import ScoringAgent
from ..contracts.rubric import RUBRICS
from .audit import audit_dataset
from .dataset import load_samples, save_report
from .metrics import (TARGET_AGREEMENT, TARGET_EVIDENCE, evaluate, sweep_thresholds)


def _pick_quote(results, sp_id: str) -> str:
    for r in results:
        if r.skill_point_id == sp_id:
            if r.evidence:
                first = r.evidence[0]
                if isinstance(first, dict):
                    return str(first.get("quote", ""))
                return str(first)
            return ""
    return ""


def run_calibration(llm, samples: list[dict] | None = None, repeats: int = 1,
                    target_agreement: float = TARGET_AGREEMENT,
                    target_evidence: float = TARGET_EVIDENCE,
                    on_progress: Callable[[int, int, str], None] | None = None,
                    persist: bool = True) -> dict:
    """跑一遍校准集，返回报告（同时写 data/calibration/report.json）。"""
    samples = samples if samples is not None else load_samples()
    agent = ScoringAgent(llm)
    predictions: list[dict] = []
    total = len(samples) * max(1, repeats)
    step = 0

    for rep in range(max(1, repeats)):
        for s in samples:
            step += 1
            rubrics = [RUBRICS[sp] for sp in s["skill_point_ids"] if sp in RUBRICS]
            if not rubrics:
                if on_progress:
                    on_progress(step, total, s["id"])
                continue
            try:
                results = agent.score(s["transcript"], rubrics, s.get("deliverables") or {})
            except Exception as exc:                     # 单样本失败不中断整轮
                results = []
                if on_progress:
                    on_progress(step, total, f"{s['id']} (失败: {type(exc).__name__})")
            for label in s["labels"]:
                sp = label["skill_point_id"]
                got = next((r for r in results if r.skill_point_id == sp), None)
                predictions.append({
                    "run": rep, "sample_id": s["id"], "skill_point_id": sp,
                    "level": got.level if got else "未返回",
                    "score": round(got.score) if got else 0,
                    "confidence": round(got.confidence, 3) if got else 0.0,
                    "evidence_quote": _pick_quote(results, sp),
                    "human_level": label["level"], "human_quote": label.get("evidence_quote", ""),
                })
            if on_progress:
                on_progress(step, total, s["id"])

    metrics = evaluate(predictions, samples)
    sweep = sweep_thresholds(predictions, target=target_agreement)
    passed = (metrics["agreement"] >= target_agreement
              and metrics["evidence_accuracy"] >= target_evidence)

    audit = audit_dataset(samples)
    report = {
        "run_id": f"cal-{int(time.time())}",
        "dataset": audit,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "samples": len(samples), "repeats": max(1, repeats),
        "predictions": metrics["predictions"],
        "agreement": metrics["agreement"], "target_agreement": target_agreement,
        "evidence_accuracy": metrics["evidence_accuracy"], "target_evidence": target_evidence,
        "stability": metrics["stability"],
        "threshold": {"confidence": sweep["confidence"], "boundary_delta": sweep["boundary_delta"],
                      "accuracy_at": sweep["accuracy_at"], "kept": sweep["kept"],
                      "kept_ratio": sweep["kept_ratio"], "passed": sweep["passed"],
                      "note": sweep["note"]},
        "threshold_table": sweep["table"],
        "by_skill_point": metrics["by_skill_point"],
        "confusion": metrics["confusion"],
        "errors": metrics["errors"],
        "passed": passed,
    }
    if persist:
        save_report(report)
    return report