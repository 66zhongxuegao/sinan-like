"""任务与流程实例 —— 演练的最小载体（PRD 第 5.2.2 节）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import DifficultyLevel, OrderStatus, StepId

# 本单硬规则默认值（PRD 第 13 章硬规则）
DEFAULT_DEADLINES_MINUTES: dict[str, int] = {
    "grab": 5,
    "first_call": 60,      # 1 小时内打电话
    "plan_upload": 240,    # 4 小时内上传方案
    "departure_notice_hours": 36,  # 行前 1-2 天
}


@dataclass
class DispatchCard:
    """派单卡片（信息残缺，PRD 第 4 章 S1）。"""

    destination: str = ""
    origin: str = ""
    people: int | None = None
    budget: float | None = None
    preference: str = ""
    completeness: float = 0.5   # 信息完整度 0-1

    def missing_fields(self) -> list[str]:
        out = []
        if not self.origin:
            out.append("出发地")
        if self.people is None:
            out.append("人数")
        if self.budget is None:
            out.append("预算")
        if not self.preference:
            out.append("景点偏好")
        return out


@dataclass
class TaskTemplate:
    id: str
    task_type: str = "国内定制"
    inbound: bool = False
    country: str = ""
    language: str = "中文"
    difficulty: DifficultyLevel = DifficultyLevel.L1
    dispatch: DispatchCard = field(default_factory=DispatchCard)


@dataclass
class TaskInstance:
    id: str
    template_id: str
    user_id: str
    status: OrderStatus = OrderStatus.PENDING_GRAB
    current_step: StepId = StepId.S0_INIT
    inbound: bool = False
    language: str = "中文"
    trust: int = 70          # 客户信任分 0-100
    emotion: str = "平静"
    risk: str = "低"
    started_at: str = ""
    finished_at: str = ""