"""学情画像与能力参数 —— 技能点级数值 + 维度聚合。

口径来源：PRD 第 17.1/17.4/17.5/17.6 节。
- 能力参数：每个技能点一个 0-100 的值（掌握度）。
- 维度值：该维度各技能点按权重聚合。
- 画像：学员级汇总（薄弱/强项标签、难度快照）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import (
    DIMENSION_WEIGHTS,
    Dimension,
    DifficultyLevel,
    MasteryLevel,
    mastery_of,
)
from .skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID, by_dimension

DEFAULT_INBOUND_DIMENSIONS: frozenset[Dimension] = frozenset({Dimension.C8_CROSS_CULTURE})


@dataclass
class AbilityParam:
    """单个技能点的能力参数。"""

    skill_point_id: str
    value: float = 0.0          # 0-100
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.skill_point_id not in SKILL_POINTS_BY_ID:
            raise KeyError(f"未知技能点: {self.skill_point_id}")
        self.value = max(0.0, min(100.0, float(self.value)))

    @property
    def mastery(self) -> MasteryLevel:
        return mastery_of(self.value)


def dimension_value(params: dict[str, float], dimension: Dimension) -> float:
    """维度值 = 该维度各技能点能力值的均值（技能点权重相同；后续可细分权重）。"""
    points = [sp for sp in by_dimension(dimension)]
    if not points:
        return 0.0
    vals = [params.get(sp.id, 0.0) for sp in points]
    return round(sum(vals) / len(vals), 2)


def overall_value(params: dict[str, float], dimensions: frozenset[Dimension] | None = None) -> float:
    """按维度权重聚合总分；可指定启用的维度集合（国内单不含 C8）。"""
    active = dimensions if dimensions is not None else frozenset(Dimension)
    weights = {d: DIMENSION_WEIGHTS[d] for d in active}
    total_w = sum(weights.values())
    if total_w <= 0:
        return 0.0
    acc = 0.0
    for d, w in weights.items():
        acc += dimension_value(params, d) * (w / total_w)
    return round(acc, 2)


@dataclass
class LearnerProfile:
    """学员画像（对应 PRD 第 5.2.1 节 learner_profile）。"""

    user_id: str
    level: str = "L1"
    weak_tags: list[str] = field(default_factory=list)   # 技能点 ID
    strong_tags: list[str] = field(default_factory=list)
    total_deals: int = 0
    total_lost: int = 0
    total_complaints: int = 0
    last_difficulty: dict[str, str] = field(default_factory=dict)
    abilities: dict[str, AbilityParam] = field(default_factory=dict)

    def set_ability(self, skill_point_id: str, value: float, now: str = "") -> AbilityParam:
        param = AbilityParam(skill_point_id, value, now)
        self.abilities[skill_point_id] = param
        return param

    def values(self) -> dict[str, float]:
        return {sp.id: self.abilities[sp.id].value if sp.id in self.abilities else 0.0 for sp in SKILL_POINTS}

    def weak_points(self, threshold: float = 70.0) -> list[str]:
        """薄弱点 = M1(未掌握)+M2(初步)，即能力值 < 70（PRD 第 17.4 节）。"""
        vals = self.values()
        return [sp.id for sp in SKILL_POINTS if vals[sp.id] < threshold]