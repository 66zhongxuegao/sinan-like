"""主动学情诊断：用贝叶斯知识追踪和知识图约束做下一步动作选择。

这不是把画像标签换成更漂亮的雷达图，而是显式维护：
- 技能掌握概率 p(mastery)；
- 一次观察后的信念更新；
- 候选诊断动作的期望信息增益；
- 技能图前置约束下的可执行学习顺序。
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from ..contracts.skill_graph import SkillGraph
from ..contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def entropy(p: float) -> float:
    p = clamp(p)
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def bkt_update(prior: float, correct: bool, *, slip: float = 0.1,
               guess: float = 0.2, learn: float = 0.15) -> float:
    """标准 BKT 后验 + 学习转移；把答对/答错都当作软证据而非 0/1 结论。"""
    p = clamp(prior)
    if correct:
        denom = p * (1.0 - slip) + (1.0 - p) * guess
        posterior = p * (1.0 - slip) / max(denom, 1e-9)
    else:
        denom = p * slip + (1.0 - p) * (1.0 - guess)
        posterior = p * slip / max(denom, 1e-9)
    return clamp(posterior + (1.0 - posterior) * learn)


def expected_information_gain(prior: float, p_correct: float) -> float:
    """用一次观测前后的熵差近似候选诊断动作的价值。"""
    p = clamp(prior)
    q = clamp(p_correct)
    before = entropy(p)
    after_correct = bkt_update(p, True)
    after_wrong = bkt_update(p, False)
    expected_after = q * entropy(after_correct) + (1.0 - q) * entropy(after_wrong)
    return max(0.0, before - expected_after)


def candidate_probes(abilities: dict[str, dict], *, limit: int = 12) -> list[dict[str, Any]]:
    """从当前能力表生成候选诊断点；不调用 LLM，便于重复实验和审计。"""
    rows: list[dict[str, Any]] = []
    for sp in SKILL_POINTS:
        row = abilities.get(sp.id) or {}
        # 没做过诊断不等于掌握度为 0；未观测节点使用 0.5 的均匀先验，
        # 否则系统会把“未知”误判成“薄弱”，并优先刷完整条 C1 链。
        observed = bool(row)
        teach = float(row.get("teach") or 0.0) / 100.0 if observed else 0.5
        # 越接近 0.5 的掌握概率，越值得通过一次高质量观察来消除不确定性。
        uncertainty = 1.0 - abs(teach - 0.5) * 2.0
        p_correct = clamp(0.25 + 0.6 * teach)
        eig = expected_information_gain(teach, p_correct)
        rows.append({"skill_point_id": sp.id, "name": sp.name, "observed": observed,
                     "mastery": round(teach, 3), "uncertainty": round(uncertainty, 3),
                     "expected_information_gain": round(eig, 4),
                     "score": round(eig * 0.7 + uncertainty * 0.3, 4)})
    rows.sort(key=lambda x: (-x["score"], x["skill_point_id"]))
    return rows[:max(1, limit)]


def prerequisite_ready(skill_point_id: str, abilities: dict[str, dict],
                       graph: SkillGraph, *, threshold: float = 0.45) -> bool:
    node = graph.node(skill_point_id)
    if node is None:
        return False
    for prior in node.prerequisites:
        prior_row = abilities.get(prior) or {}
        if float(prior_row.get("teach") or 0.0) / 100.0 < threshold:
            return False
    return True


def constrained_route(abilities: dict[str, dict], graph: SkillGraph,
                      *, size: int = 16, demand_dims: Iterable[str] = ()) -> list[dict[str, Any]]:
    """在技能图前置约束下选出可执行路线；前置不足时先补前置。"""
    demand = set(demand_dims)
    remaining = set(SKILL_POINTS_BY_ID)
    chosen: list[dict[str, Any]] = []
    while remaining and len(chosen) < size:
        ready = [sid for sid in remaining if prerequisite_ready(sid, abilities, graph)]
        if not ready:
            break
        def rank(sid: str) -> tuple[float, str]:
            sp = SKILL_POINTS_BY_ID[sid]
            row = abilities.get(sid) or {}
            mastery = float(row.get("teach") or 0.0) / 100.0
            risk_boost = 0.15 if graph.node(sid) and graph.node(sid).risk_level == "high" else 0.0
            # 需求命中的维度要能在基础掌握度较高时仍然排到前面，否则
            # “高掌握 + 高需求”会被其它低掌握维度永久压住。
            demand_boost = 0.8 if sp.dimension.value in demand else 0.0
            # 低掌握、风险高、与需求相关优先；同分按稳定 id 排序。
            return (-(1.0 - mastery + risk_boost + demand_boost), sid)
        sid = sorted(ready, key=rank)[0]
        sp = SKILL_POINTS_BY_ID[sid]
        row = abilities.get(sid) or {}
        mastery = float(row.get("teach") or 0.0) / 100.0
        chosen.append({"skill_point_id": sid, "name": sp.name,
                       "dimension": sp.dimension.value, "mastery": round(mastery, 3),
                       "risk_level": graph.node(sid).risk_level if graph.node(sid) else "unknown",
                       "reason": "前置已满足，且当前掌握度/风险/需求综合优先"})
        remaining.remove(sid)
    return chosen


def observation_update(prior_score: float, correct: bool, *, attempts_after: int = 1) -> dict[str, Any]:
    prior = clamp(float(prior_score or 0.0) / 100.0)
    posterior = bkt_update(prior, correct)
    return {"prior": round(prior, 3), "posterior": round(posterior, 3),
            "posterior_score": round(posterior * 100.0, 1),
            "observation": "correct" if correct else "incorrect",
            "attempts_after": max(1, int(attempts_after)),
            "method": "BKT(slip=.10,guess=.20,learn=.15)"}
