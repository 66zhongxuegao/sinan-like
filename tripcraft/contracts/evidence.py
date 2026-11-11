"""证据链 —— 追溯的最小单位（PRD 第 20.6 节）。

评分必须引用证据；能力参数每次变化都留「实例→步骤→证据→锚点」链。
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import EvidenceKind, StepId


@dataclass(frozen=True)
class Evidence:
    id: str                 # 证据 ID（消息 ID / 动作日志 ID / 交付物片段 ID）
    instance_id: str        # 演练实例
    step: StepId            # 发生步骤
    kind: EvidenceKind      # 消息 / 动作 / 交付物
    ref_id: str             # 指向原始对象的 ID
    snippet: str            # 原文/字段片段（用于前端高亮）
    created_at: str = ""


@dataclass(frozen=True)
class ScoreTrace:
    """一次评分（对某技能点）—— 含锚点命中与证据引用。"""

    skill_point_id: str
    level: str              # M1-M5
    score: float            # 0-100
    evidence_ids: tuple[str, ...]
    hit_negative: bool      # 是否命中反例
    comment: str = ""

    def validate(self) -> None:
        assert self.evidence_ids, f"{self.skill_point_id} 评分缺证据（PRD 第 21.2 节：每分必有证据）"