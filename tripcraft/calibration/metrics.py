"""校准指标与阈值标定（PRD 25.4 / 25.6）。"""

from __future__ import annotations

from collections import Counter, defaultdict

from .dataset import normalize_text

TARGET_AGREEMENT = 0.85       # M 档一致率门槛（PRD 25.4）
TARGET_EVIDENCE = 0.90        # 证据准确率门槛
BOUNDARIES = (60, 70, 80, 90)  # M 档边界（分数）
CONF_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
DELTA_GRID = (0, 3, 5)

# 标定目标：在一致率达标的前提下取**最保守**的阈值（尽量拦截低置信判定），
# 但保留率不得低于该下限——否则等于把几乎所有判定都推给人工，主链失去意义。
MIN_KEPT_RATIO = 0.6


def _quote_in_source(quote: str, source: str) -> bool:
    q = normalize_text(quote)
    if len(q) < 4:
        return False
    return q in normalize_text(source)


def evaluate(predictions: list[dict], samples: list[dict]) -> dict:
    """M 档一致率 / 证据准确率 / 稳定性 / 错误分布。"""
    by_id = {s["id"]: s for s in samples}
    n = len(predictions)
    if not n:
        return {"predictions": 0, "agreement": 0.0, "evidence_accuracy": 0.0,
                "stability": 0.0, "errors": [], "by_skill_point": {}, "confusion": {}}

    hits = sum(1 for p in predictions if p["level"] == p["human_level"])
    good_evidence = 0
    for p in predictions:
        s = by_id.get(p["sample_id"], {})
        source = (s.get("transcript") or "") + "\n" + "\n".join((s.get("deliverables") or {}).values())
        if _quote_in_source(p.get("evidence_quote", ""), source):
            good_evidence += 1

    # 稳定性：同一 (样本, 技能点) 在多次重复中是否始终判同一档
    groups: dict[tuple, list[str]] = defaultdict(list)
    for p in predictions:
        groups[(p["sample_id"], p["skill_point_id"])].append(p["level"])
    stable = sum(1 for v in groups.values() if len(set(v)) == 1)

    errors = [{"sample_id": p["sample_id"], "skill_point_id": p["skill_point_id"],
               "human": p["human_level"], "predicted": p["level"],
               "confidence": p.get("confidence"), "score": p.get("score"),
               "human_quote": p.get("human_quote", ""), "predicted_quote": p.get("evidence_quote", "")}
              for p in predictions if p["level"] != p["human_level"]]

    per_sp: dict[str, dict] = {}
    for p in predictions:
        b = per_sp.setdefault(p["skill_point_id"], {"total": 0, "hit": 0})
        b["total"] += 1
        b["hit"] += 1 if p["level"] == p["human_level"] else 0
    for sp, b in per_sp.items():
        b["agreement"] = round(b["hit"] / b["total"], 4)

    confusion = Counter((p["human_level"], p["level"]) for p in predictions)

    return {
        "predictions": n,
        "agreement": round(hits / n, 4),
        "evidence_accuracy": round(good_evidence / n, 4),
        "stability": round(stable / len(groups), 4) if groups else 0.0,
        "errors": errors,
        "by_skill_point": per_sp,
        "confusion": {f"{h}->{p}": c for (h, p), c in confusion.most_common()},
    }


def _distance_to_boundary(score: float) -> int:
    return min(abs(score - b) for b in BOUNDARIES)


def sweep_thresholds(predictions: list[dict], target: float = TARGET_AGREEMENT) -> dict:
    """用校准集标定「低置信度升级」的两个阈值（PRD 25.6）。

    目标：在**保留尽量多判定**的前提下，让保留下来的判定一致率达到 target。
    """
    n = len(predictions)
    if not n:
        return {"confidence": 0.7, "boundary_delta": 3, "target": target,
                "passed": False, "table": [], "note": "无预测数据"}

    table = []
    for conf in CONF_GRID:
        for delta in DELTA_GRID:
            kept = [p for p in predictions
                    if float(p.get("confidence") or 0) >= conf
                    and _distance_to_boundary(float(p.get("score") or 0)) > delta]
            if not kept:
                table.append({"confidence": conf, "boundary_delta": delta,
                              "kept": 0, "kept_ratio": 0.0, "accuracy": None})
                continue
            acc = sum(1 for p in kept if p["level"] == p["human_level"]) / len(kept)
            table.append({"confidence": conf, "boundary_delta": delta, "kept": len(kept),
                          "kept_ratio": round(len(kept) / n, 4), "accuracy": round(acc, 4)})

    feasible = [r for r in table if r["accuracy"] is not None
                and r["accuracy"] >= target and r["kept_ratio"] >= MIN_KEPT_RATIO]
    relaxed = False
    if not feasible:
        # 达标且保留率下限都满足不了：退回「只要达标且保留最多」
        feasible = [r for r in table if r["accuracy"] is not None and r["accuracy"] >= target]
        relaxed = True
    if feasible:
        # 最保守 = 置信度门槛最高、边界带最宽（拦截最多）的可行组合
        best = max(feasible, key=lambda r: (r["confidence"], r["boundary_delta"], r["kept"]))
        passed = True
    else:
        cand = [r for r in table if r["accuracy"] is not None]
        best = max(cand, key=lambda r: (r["accuracy"], r["kept"])) if cand else table[-1]
        passed = False

    return {"confidence": best["confidence"], "boundary_delta": best["boundary_delta"],
            "accuracy_at": best["accuracy"], "kept": best["kept"], "kept_ratio": best["kept_ratio"],
            "target": target, "min_kept_ratio": MIN_KEPT_RATIO, "relaxed": relaxed,
            "passed": passed, "table": table,
            "note": ("一致率达标前提下取最保守阈值（保留率不低于 {:.0%}）".format(MIN_KEPT_RATIO)
                     if passed and not relaxed else
                     "一致率达标但保留率下限不可满足，已放宽保留率约束" if passed
                     else "校准集上没有任何阈值组合能达标，需要修 Rubric 或改 Prompt")}