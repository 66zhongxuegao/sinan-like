"""交付物 —— 学员动作产生的可评分工作物（PRD 第 11 章 6 类）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import DeliverableKind, StepId, VersionStatus

# 每类交付物归属的步骤（用于门控：走到该步必须产出）
DELIVERABLE_STEP: dict[DeliverableKind, StepId] = {
    DeliverableKind.REQUIREMENT_SHEET: StepId.S3_REQUIREMENT,
    DeliverableKind.RESOURCE_TABLE: StepId.S4_RESOURCE,
    DeliverableKind.ITINERARY_PLAN: StepId.S5_ITINERARY,
    DeliverableKind.QUOTATION: StepId.S6_QUOTATION,
    DeliverableKind.INCIDENT_LOG: StepId.S10_ON_TRIP,
    DeliverableKind.SETTLEMENT: StepId.S11_SETTLEMENT,
}


@dataclass
class Deliverable:
    id: str
    instance_id: str
    kind: DeliverableKind
    step: StepId
    version: int = 1
    status: VersionStatus = VersionStatus.DRAFT
    payload: dict[str, Any] = field(default_factory=dict)

    def new_version(self) -> "Deliverable":
        """生成新版本（不覆盖旧版本，保证可追溯 —— PRD 第 3.4 节）。"""
        return Deliverable(
            id=self.id,
            instance_id=self.instance_id,
            kind=self.kind,
            step=self.step,
            version=self.version + 1,
            status=VersionStatus.DRAFT,
            payload=dict(self.payload),
        )