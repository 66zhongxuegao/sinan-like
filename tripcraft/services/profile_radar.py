"""画像雷达：训练更新已涉及维度，其余维度沿用本人初始测评。"""

import json
import math

from tripcraft.contracts.enums import DIMENSION_NAMES, Dimension
from tripcraft.contracts.skill_points import SKILL_POINTS


def radar_abilities(abilities: dict, order_scores: list[dict]) -> dict:
    """展示可读取已入库的有证据评分；不会回写能力表或采纳待复核分数。"""
    result = {key: dict(row) for key, row in abilities.items()}
    valid_ids = {point.id for point in SKILL_POINTS}
    for score in sorted(order_scores, key=lambda row: str(row.get("created_at") or "")):
        sp = score.get("skill_point_id")
        if sp not in valid_ids or not str(score.get("status") or "").startswith("已入库"):
            continue
        evidence = score.get("evidence")
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except ValueError:
                continue
        if not isinstance(evidence, list) or not evidence:
            continue
        try:
            value = float(score["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(value) or not 0 <= value <= 100:
            continue
        row = result.get(sp) or {}
        at = str(score.get("created_at") or "")
        if row.get("real_source") == "practice" and str(row.get("real_updated_at") or row.get("updated_at") or "") > at:
            continue
        result[sp] = {**row, "real_v": value, "real_source": "practice", "real_updated_at": at,
                      "real_origin": "order_score"}
    return result


def build_radar(user_id: str, abilities: dict, baseline: dict,
                initial_report: dict | None = None, *, practice_completed_at: str = "") -> dict:
    initial_report = initial_report or {}
    initial, learning, practice, current = [], [], [], []
    initial_at, learning_at, practice_at = "", "", ""
    initial_source = "intake" if baseline else "initial" if initial_report else ""
    # 初始测评就是学习能力的起点：没有后续学习记录时，学习层沿用初始画像，
    # 与学习地图读取 teach/baseline 的口径保持一致。
    has_initial = bool(baseline) or bool(initial_report)
    has_learning = has_initial or any(row.get("teach_source") == "learning" for row in abilities.values())
    has_practice = bool(practice_completed_at) or any(row.get("real_source") == "practice" for row in abilities.values())

    def dimension(dim, values, total):
        return {"id": dim.value, "name": DIMENSION_NAMES[dim],
                "value": round(sum(values) / len(values), 1) if values else None,
                "assessed": bool(values), "assessed_points": len(values), "total_points": total}

    def training_dimension(dim, values, total, base_value, active):
        row = dimension(dim, values, total)
        inherited = not values and active and base_value is not None
        if inherited:
            row.update(value=round(float(base_value), 1), assessed=True)
        return {**row, "inherited": inherited, "source": "initial" if inherited else "training" if values else ""}

    for dim in Dimension:
        points = [p for p in SKILL_POINTS if p.dimension is dim]
        base = baseline.get(dim.value)
        base_value = base.get("value") if base else (initial_report.get("scores") or {}).get(dim.value)
        initial.append(dimension(dim, [float(base_value)] if base_value is not None else [], len(points)))
        if base:
            initial_at = max(initial_at, str(base.get("created_at") or ""))
        learn_values, real_values, current_values = [], [], []
        for point in points:
            row = abilities.get(point.id)
            if not row:
                continue
            teach, real = float(row.get("teach") or 0), float(row.get("real_v") or 0)
            if row.get("teach_source") in ("initial", "learning"):
                # 初始测评就是学习能力的起点；后续答题会以 learning 来源继续更新。
                learn_values.append(teach)
                learning_at = max(learning_at, str(row.get("teach_updated_at") or row.get("updated_at") or ""))
            if row.get("real_source") == "practice":
                real_values.append(real)
                practice_at = max(practice_at, str(row.get("real_updated_at") or row.get("updated_at") or ""))
            # 兼容测评结果页的旧 current/delta 契约；新页面只使用三类独立图层。
            current_values.append(real if row.get("real_source") == "practice" else teach)
        learning.append(training_dimension(dim, learn_values, len(points), base_value, has_learning))
        practice.append(training_dimension(dim, real_values, len(points), base_value, has_practice))
        current.append(training_dimension(dim, current_values, len(points), base_value, True))

    initial_at = initial_at or str(initial_report.get("created_at") or "")
    if has_initial and not learning_at:
        learning_at = initial_at
    practice_at = max(practice_at, practice_completed_at)
    delta = [{"id": i["id"], "name": i["name"],
              "value": round(c["value"] - i["value"], 1) if i["assessed"] and c["assessed"] else None,
              "assessed": i["assessed"] and c["assessed"]} for i, c in zip(initial, current)]
    assessed = any(d["assessed"] for layer in (initial, learning, practice) for d in layer)
    return {"user_id": user_id, "scale": {"min": 0, "max": 100, "unit": "维度值"},
            "assessed": assessed,
            "initial": {"label": "初始能力", "at": initial_at, "source": initial_source, "dimensions": initial},
            "learning": {"label": "学习能力", "at": learning_at, "source": "learning_map", "dimensions": learning},
            "practice": {"label": "实战能力", "at": practice_at, "source": "practice", "dimensions": practice},
            "current": {"label": "当前能力", "at": max(learning_at, practice_at, initial_at),
                        "source": "ability", "dimensions": current},
            "delta": delta, "note": "" if assessed else "尚无能力评估记录，请先完成初始测评或训练。"}


def initial_only(radar: dict) -> dict:
    """旧初始报告只有当时的测评分数，不把今天的训练值填进过去。"""
    out = {**radar, "at": radar["initial"]["at"], "snapshot_id": "initial"}
    for key in ("learning", "practice", "current"):
        out[key] = {**radar[key], "at": "", "dimensions": [
            {**d, "value": None, "assessed": False, "assessed_points": 0, "inherited": False, "source": ""}
            for d in radar[key]["dimensions"]]}
    out["delta"] = [{**d, "value": None, "assessed": False} for d in radar["delta"]]
    out["assessed"] = any(d["assessed"] for d in radar["initial"]["dimensions"])
    return out
