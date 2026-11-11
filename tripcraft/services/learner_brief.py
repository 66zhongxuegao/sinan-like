"""学习者简报 —— 把画像换算成「本单针对谁、什么难度、各压力旋钮几档」（PRD 第 20 章）。

这是「画像 ↔ 实战难度」的中间层，也是派单生成器的输入：
    画像（每技能点 teach / real_v）
      → 目标技能点（最薄弱 / 未评估优先）
      → 各压力旋钮档位（0=补救 … 4=加压四级）
      → 交给派单生成器产出游客人设 + 派单残缺度 + 时限与情绪压力

口径（PRD 20.2 / 20.4 / 20.5）：
- **M1 走补救、M2–M5 走递增加压**，不是「掌握度低→难度低」一条直线；
- 难度旋钮按**维度**分别取值（C1 情绪、C2 模糊度与派单完整度、C5 预算紧度…）；
- 一个旋钮可能被多个维度拉动时取**更需要训练的那一档**（弱项优先）。

所有档位都是确定性计算，同画像必然得到同一份简报，可解释、可复盘。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..contracts.enums import MasteryLevel, mastery_of
from ..contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID

# 一个旋钮由哪些维度拉动（PRD 20.4「维度 → 压力参数映射」）
KNOBS: dict[str, tuple[str, ...]] = {
    "source_complexity": ("C8",),                 # 客源国 / 语言文化复杂度
    "demand_vagueness": ("C2", "C5"),             # 需求模糊度
    "dispatch_gap": ("C2",),                      # 派单信息完整度（缺得越多越难）
    "time_pressure": ("C7", "C2"),                # 时限松紧
    "budget_tightness": ("C5", "C3", "C4"),       # 预算紧度
    "resource_conflict": ("C4", "C6"),            # 资源冲突 / 突发事件
    "emotion_intensity": ("C1",),                 # 客户情绪强度
}

KNOB_LABELS = {
    "source_complexity": "客源与语言复杂度",
    "demand_vagueness": "需求模糊度",
    "dispatch_gap": "派单信息残缺度",
    "time_pressure": "时限压力",
    "budget_tightness": "预算紧度",
    "resource_conflict": "资源冲突程度",
    "emotion_intensity": "客户情绪强度",
}

# 档位 → 人话（给学员和评委看）
LEVEL_WORDS = ("补救", "加压一档", "加压二档", "加压三档", "加压四档")

TARGET_LIMIT = 3          # 一单主考的技能点数


@dataclass
class LearnerBrief:
    user_id: str
    level: int                                  # 0..4
    branch: str                                 # 补救 / 加压
    label: str                                  # 「补救 · L0」
    target_skill_points: tuple[str, ...]
    target_names: tuple[str, ...]
    target_dimensions: tuple[str, ...]
    mastery: dict[str, float] = field(default_factory=dict)
    knobs: dict[str, int] = field(default_factory=dict)
    rationale: str = ""
    carried_over: tuple[str, ...] = ()          # 上一单未覆盖、本单继续考的

    def to_dict(self) -> dict:
        d = asdict(self)
        d["knob_labels"] = {k: KNOB_LABELS[k] for k in self.knobs}
        d["knob_words"] = {k: LEVEL_WORDS[v] for k, v in self.knobs.items()}
        return d


def _mastery_of_point(row: dict | None) -> tuple[float, bool]:
    """返回 (掌握度, 是否已评估)。实战分优先——它才是「能不能上手」的证据。"""
    if not row:
        return 0.0, False
    real = float(row.get("real_v") or 0)
    teach = float(row.get("teach") or 0)
    if real > 0:
        return real, True
    if teach > 0:
        return teach, True
    return 0.0, False


def build_brief(abilities: dict[str, dict], carried_over: list[str] | None = None,
                limit: int = TARGET_LIMIT) -> LearnerBrief:
    """由能力表算出本单简报。abilities: {skill_point_id: {teach, real_v}}。"""
    rows = []
    for sp in SKILL_POINTS:
        value, evaluated = _mastery_of_point(abilities.get(sp.id))
        rows.append({"sp": sp, "value": value, "evaluated": evaluated})

    # 目标技能点：未评估优先（还没考过），其次分数最低；同分按 ID 稳定排序
    rows.sort(key=lambda r: (r["evaluated"], r["value"], r["sp"].id))

    picked: list[dict] = []
    carry = list(carried_over or [])
    for cid in carry:
        sp = SKILL_POINTS_BY_ID.get(cid)
        if sp and not any(p["sp"].id == sp.id for p in picked):
            value, evaluated = _mastery_of_point(abilities.get(sp.id))
            picked.append({"sp": sp, "value": value, "evaluated": evaluated})
    for r in rows:
        if len(picked) >= max(limit, len(carry)):
            break
        if any(p["sp"].id == r["sp"].id for p in picked):
            continue
        picked.append(r)

    # 整单难度：以**最弱**的主考技能点定分支（它决定是补救还是加压）
    weakest = min(p["value"] for p in picked) if picked else 0.0
    if not picked or weakest < 60:
        level = 0
    else:
        level = min(4, int((weakest - 60) // 10) + 1)   # 60-69→1 … 90+→4
    branch = "补救" if level == 0 else "加压"

    # 分旋钮取值：按维度分别算，取「最需要训练」的那一档
    # 本单没考到的维度 → **跟随整单档位**，不能偷偷按中性加压
    # （否则会出现「整单标补救、时限却收紧到 45 分钟」这种自相矛盾的派单）
    knobs: dict[str, int] = {}
    for knob, dims in KNOBS.items():
        vals = [p["value"] for p in picked if p["sp"].dimension.value in dims]
        if vals:
            v = min(vals)                              # 弱项优先：宁可练到，不可放过
            knobs[knob] = 0 if v < 60 else min(4, int((v - 60) // 10) + 1)
        else:
            knobs[knob] = level

    dims_out = tuple(dict.fromkeys(p["sp"].dimension.value for p in picked))
    rationale = _rationale(picked, level, branch, carried_over)
    return LearnerBrief(
        user_id="", level=level, branch=branch,
        label=("补救（降难）" if level == 0 else f"加压 · {LEVEL_WORDS[level]}"),
        target_skill_points=tuple(p["sp"].id for p in picked),
        target_names=tuple(p["sp"].name for p in picked),
        target_dimensions=dims_out,
        mastery={p["sp"].id: round(p["value"], 1) for p in picked},
        knobs=knobs, rationale=rationale,
        carried_over=tuple(carried_over or ()),
    )


def _rationale(picked: list[dict], level: int, branch: str,
               carried_over: list[str] | None) -> str:
    if not picked:
        return "画像里还没有可用数据，先按常规难度出一单摸底。"
    parts = []
    for p in picked[:3]:
        sp = p["sp"]
        if not p["evaluated"]:
            parts.append(f"{sp.id} {sp.name}（还没考过）")
        else:
            lv = mastery_of(p["value"]).value      # 已经是 "M1".."M5"
            parts.append(f"{sp.id} {sp.name}（{lv}，{round(p['value'])} 分）")
    head = "、".join(parts)
    if carried_over:
        head += f"；其中 {'、'.join(carried_over)} 是上一单未覆盖、本单接着考"
    if branch == "补救":
        return f"本单针对 {head}。因为存在未掌握项，走**补救**：触发点更显式、时限放宽、派单信息给得更全。"
    return f"本单针对 {head}。已有基础，走**加压（{LEVEL_WORDS[level]}）**：需求更模糊、派单缺得更多、时限更紧。"