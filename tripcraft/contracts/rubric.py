"""对齐 Rubric（BARS 行为锚定）—— 每个技能点一张。

口径来源：PRD 第 18 章。Rubric = 考核定位（步骤/考核对象/触发条件）+ 判定标准
（M1-M5 锚点 / 正例 / 反例 / 证据要求 / 关联知识点）。

「实战评分点」已并入本模型的「考核定位」（DECISIONS D-003）。
数据来源：
- 手工金标准（本文件内 RUBRICS_SEED，目前为 C2.2）；
- 大模型生成并校验入库的数据（contracts/data/rubrics.json，见 scripts/import_rubrics.py）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .enums import CheckpointType, MasteryLevel, StepId
from .skill_points import SKILL_POINTS_BY_ID

_DATA_PATH = Path(__file__).resolve().parent / "data" / "rubrics.json"


@dataclass(frozen=True)
class RubricAnchor:
    """某一掌握度等级的可观测行为锚点。"""

    level: MasteryLevel
    behavior: str


@dataclass(frozen=True)
class Rubric:
    skill_point_id: str
    steps: tuple[StepId, ...]
    target: str
    trigger: str | None
    anchors: tuple[RubricAnchor, ...]
    positive: str
    negative: str
    evidence_required: str
    knowledge: str

    @property
    def checkpoint(self) -> CheckpointType:
        return SKILL_POINTS_BY_ID[self.skill_point_id].checkpoint

    def anchor(self, level: MasteryLevel) -> str | None:
        for a in self.anchors:
            if a.level == level:
                return a.behavior
        return None

    def validate(self) -> None:
        """B 型必须有触发条件；锚点必须覆盖 M1-M5。"""
        if self.checkpoint is CheckpointType.B_EVENT:
            assert self.trigger, f"{self.skill_point_id} 为 B 型考点，必须给触发条件"
        levels = {a.level for a in self.anchors}
        missing = [m for m in MasteryLevel if m not in levels]
        assert not missing, f"{self.skill_point_id} 缺锚点: {missing}"


# ---- 手工金标准（C2.2，PRD 第 18.3 节；作为生成质量的对照基准）----

RUBRICS_SEED: dict[str, Rubric] = {
    "C2.2": Rubric(
        skill_point_id="C2.2",
        steps=(StepId.S2_FIRST_CALL, StepId.S6_QUOTATION),
        target="是否把「性价比高」当预算已明确",
        trigger="客户说「性价比高」",
        anchors=(
            RubricAnchor(MasteryLevel.M1, "全程未追问预算，直接按「性价比高」做方案/报价"),
            RubricAnchor(MasteryLevel.M2, "只问「预算多少」，客户答「性价比高」就停止"),
            RubricAnchor(MasteryLevel.M3, "追问「人均还是总价」，但没确认区间、是否含大交通"),
            RubricAnchor(MasteryLevel.M4, "问到人均/总价+区间，但未二次复述确认"),
            RubricAnchor(MasteryLevel.M5, "追问并量化确认（人均/总价+区间+是否含大交通），复述得到确认"),
        ),
        positive="「您的预算是人均还是整团总价？大概区间？含不含机票高铁？」并复述确认",
        negative="客户说「性价比高」就当成预算已明确，报价被否定",
        evidence_required="引用 S2 通话转写中关于预算的问答原文",
        knowledge="需求管理·期望管理——「性价比高 ≠ 预算明确」；KANO（预算属硬约束）",
    ),
}


def _load_generated() -> dict[str, Rubric]:
    """加载大模型生成并校验入库的数据。"""
    if not _DATA_PATH.exists():
        return {}
    out: dict[str, Rubric] = {}
    try:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    for obj in raw:
        try:
            anchors = tuple(
                RubricAnchor(MasteryLevel(level), obj["anchors"][level])
                for level in ("M1", "M2", "M3", "M4", "M5")
            )
            r = Rubric(
                skill_point_id=obj["skill_point_id"],
                steps=tuple(StepId(s) for s in obj["steps"]),
                target=obj["target"],
                trigger=obj.get("trigger"),
                anchors=anchors,
                positive=obj["positive"],
                negative=obj["negative"],
                evidence_required=obj["evidence_required"],
                knowledge=obj["knowledge"],
            )
            r.validate()
            out[r.skill_point_id] = r
        except Exception:
            continue
    return out


# 入库数据优先，手工金标准兜底
RUBRICS: dict[str, Rubric] = {**RUBRICS_SEED, **_load_generated()}


def get_rubric(skill_point_id: str) -> Rubric | None:
    return RUBRICS.get(skill_point_id)