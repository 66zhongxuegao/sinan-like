"""TripCraft 核心枚举 —— 全系统统一词汇表。

口径来源：PRD 第 3 章（状态机）、第 5.3 节（关键枚举）、
第 17 章（8 维 61 技能点）、第 18 章（Rubric / 掌握度 M1-M5）、
第 7 章（难度 L1-L4）、第 19 章（A/B 考点）。

约定：所有跨模块共享的取值都定义在本文件，禁止在别处重复定义（单一数据源）。
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """兼容 Python 3.11+ 的字符串枚举（便于 JSON/DB 直接存取）。"""

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return self.value


# ---------------------------------------------------------------- 流程步骤（13 步）

class StepId(StrEnum):
    """13 个主状态（PRD 第 3.2 节）。"""

    S0_INIT = "S0"
    S1_GRAB = "S1"
    S2_FIRST_CALL = "S2"
    S3_REQUIREMENT = "S3"
    S4_RESOURCE = "S4"
    S5_ITINERARY = "S5"
    S6_QUOTATION = "S6"
    S7_ITERATION = "S7"
    S8_ORDER = "S8"
    S9_LOCK = "S9"
    S10_ON_TRIP = "S10"
    S11_SETTLEMENT = "S11"
    S12_REVIEW = "S12"


STEP_ORDER: tuple[StepId, ...] = tuple(StepId)

STEP_NAMES: dict[StepId, str] = {
    StepId.S0_INIT: "任务初始化与规则交底",
    StepId.S1_GRAB: "抢单接单",
    StepId.S2_FIRST_CALL: "首呼与需求挖掘",
    StepId.S3_REQUIREMENT: "需求结构化确认",
    StepId.S4_RESOURCE: "资源询价与可行性核验",
    StepId.S5_ITINERARY: "行程方案设计",
    StepId.S6_QUOTATION: "分项报价与利润测算",
    StepId.S7_ITERATION: "客户反馈与方案迭代",
    StepId.S8_ORDER: "成交确认与系统录单",
    StepId.S9_LOCK: "资源锁定与行前准备",
    StepId.S10_ON_TRIP: "行中执行与突发事件处理",
    StepId.S11_SETTLEMENT: "行后结算与回访",
    StepId.S12_REVIEW: "复盘评分与个性化补救",
}


class StepStatus(StrEnum):
    NOT_STARTED = "未开始"
    IN_PROGRESS = "进行中"
    PASSED = "已通过"
    ROLLED_BACK = "已回退"
    FAILED = "失败"


class OrderStatus(StrEnum):
    """订单状态（PRD 第 5.3 节）。"""

    PENDING_GRAB = "待抢单"
    GRABBED = "已抢单"
    FIRST_CALL = "首呼中"
    REQUIREMENT = "需求确认中"
    RESOURCE = "资源询价中"
    ITINERARY = "方案设计中"
    QUOTATION = "报价中"
    ITERATION = "迭代中"
    DEAL = "已成交"
    LOCKING = "资源锁定中"
    ON_TRIP = "行中"
    SETTLEMENT = "行后结算中"
    CLOSED = "已结单"
    REVIEWED = "已复盘"
    LOST = "丢单"
    COMPLAINT = "投诉升级"


# ---------------------------------------------------------------- 能力维度与技能点

class Dimension(StrEnum):
    """8 大能力维度（PRD 第 17.2 节；C8 仅入境单启用）。"""

    C1_COMMUNICATION = "C1"
    C2_REQUIREMENT = "C2"
    C3_ITINERARY = "C3"
    C4_RESOURCE = "C4"
    C5_QUOTATION = "C5"
    C6_EMERGENCY = "C6"
    C7_COMPLIANCE = "C7"
    C8_CROSS_CULTURE = "C8"


DIMENSION_NAMES: dict[Dimension, str] = {
    Dimension.C1_COMMUNICATION: "沟通信任",
    Dimension.C2_REQUIREMENT: "需求洞察",
    Dimension.C3_ITINERARY: "方案能力",
    Dimension.C4_RESOURCE: "资源整合",
    Dimension.C5_QUOTATION: "报价利润",
    Dimension.C6_EMERGENCY: "应急解决",
    Dimension.C7_COMPLIANCE: "合规效率",
    Dimension.C8_CROSS_CULTURE: "跨文化入境游沟通",
}

# 维度参考权重（PRD 第 17.2 节；国内单 C8 不启用，其余按比例归一化）
DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.C1_COMMUNICATION: 0.14,
    Dimension.C2_REQUIREMENT: 0.14,
    Dimension.C3_ITINERARY: 0.14,
    Dimension.C4_RESOURCE: 0.12,
    Dimension.C5_QUOTATION: 0.13,
    Dimension.C6_EMERGENCY: 0.12,
    Dimension.C7_COMPLIANCE: 0.13,
    Dimension.C8_CROSS_CULTURE: 0.08,
}


class CheckpointType(StrEnum):
    """考点类型（PRD 第 19.1 节）。"""

    A_DELIVERABLE = "A"   # 交付物直查型
    B_EVENT = "B"         # 事件埋点型


class MasteryLevel(StrEnum):
    """掌握度五级（PRD 第 17.4 节）。"""

    M1 = "M1"  # 未掌握  <60
    M2 = "M2"  # 初步    60-69
    M3 = "M3"  # 基本掌握 70-79
    M4 = "M4"  # 掌握    80-89
    M5 = "M5"  # 熟练    >=90


MASTERY_BANDS: tuple[tuple[MasteryLevel, float, float], ...] = (
    (MasteryLevel.M1, 0.0, 59.999),
    (MasteryLevel.M2, 60.0, 69.999),
    (MasteryLevel.M3, 70.0, 79.999),
    (MasteryLevel.M4, 80.0, 89.999),
    (MasteryLevel.M5, 90.0, 100.0),
)

MASTERY_NAMES: dict[MasteryLevel, str] = {
    MasteryLevel.M1: "未掌握",
    MasteryLevel.M2: "初步",
    MasteryLevel.M3: "基本掌握",
    MasteryLevel.M4: "掌握",
    MasteryLevel.M5: "熟练",
}


def mastery_of(value: float) -> MasteryLevel:
    """按能力值（0-100）判定掌握度档位（PRD 第 17.4 节）。"""
    v = max(0.0, min(100.0, float(value)))
    for level, lo, hi in MASTERY_BANDS:
        if lo <= v <= hi:
            return level
    return MasteryLevel.M1


class DifficultyLevel(StrEnum):
    """难度四级（PRD 第 7.2 / 18.5 节）。"""

    L1 = "L1"  # 入门
    L2 = "L2"  # 进阶
    L3 = "L3"  # 熟练
    L4 = "L4"  # 高压


DIFFICULTY_NAMES: dict[DifficultyLevel, str] = {
    DifficultyLevel.L1: "入门",
    DifficultyLevel.L2: "进阶",
    DifficultyLevel.L3: "熟练",
    DifficultyLevel.L4: "高压",
}


# ---------------------------------------------------------------- 需求 / 资源 / 交付物

class RequirementAttribute(StrEnum):
    MUST = "必须满足"
    WANT = "希望满足"
    ALTERNATIVE = "可替代"
    EXCLUDE = "明确不要"
    UNKNOWN = "待确认"


class RequirementStatus(StrEnum):
    UNKNOWN = "未知"
    PENDING = "待确认"
    CONFIRMED = "已确认"
    CONFLICT = "冲突"
    CHANGED = "已变更"


class ResourceType(StrEnum):
    SUPPLIER = "地接"
    HOTEL = "酒店"
    VEHICLE = "车辆"
    TICKET = "门票"
    GUIDE = "导游"
    MEAL = "餐饮"
    INSURANCE = "保险"
    TRANSPORT = "交通"


class ResourceAvailability(StrEnum):
    AVAILABLE = "有货"
    TIGHT = "紧张"
    OUT_OF_STOCK = "无货"
    NO_SCHEDULE = "无档期"


class BookingStatus(StrEnum):
    PENDING = "待预留"
    RESERVED = "已预留"
    LOCKED = "已锁定"
    CANCELLED = "已取消"


class DeliverableKind(StrEnum):
    """MVP 必须交付的 6 类工作物（PRD 第 11 章）。"""

    REQUIREMENT_SHEET = "需求单"
    RESOURCE_TABLE = "资源表"
    ITINERARY_PLAN = "行程方案"
    QUOTATION = "报价单"
    INCIDENT_LOG = "应急记录"
    SETTLEMENT = "结算表"


class VersionStatus(StrEnum):
    DRAFT = "草稿"
    SENT = "已发出"
    FEEDBACK = "已反馈"
    CONFIRMED = "已确认"
    REJECTED = "已拒绝"
    EXPIRED = "已过期"
    ARCHIVED = "已归档"


class IncidentType(StrEnum):
    VEHICLE_BROKEN = "车坏"
    HOTEL_OVERBOOKED = "酒店超售"
    NO_TICKET = "无票"
    VEHICLE_DOWNGRADE = "车辆降级"
    WEATHER = "天气"
    CUSTOMER_EMOTION = "客户情绪升级"


class IncidentStatus(StrEnum):
    TRIGGERED = "已触发"
    HANDLING = "处理中"
    RESOLVED = "已解决"
    ESCALATED = "已升级投诉"
    CLOSED = "已关闭"


class SettlementStatus(StrEnum):
    PENDING = "待对账"
    DIFF = "有差异"
    RECONCILED = "已核对"
    FINAL_PAID = "已付尾款"
    CLOSED = "已结清"


# ---------------------------------------------------------------- 门控 / 证据

class GateResult(StrEnum):
    PASS = "通过"
    FAIL = "不通过"


class EvidenceKind(StrEnum):
    """证据来源类型（PRD 第 20.6 节追溯链）。"""

    MESSAGE = "消息"
    ACTION = "动作"
    DELIVERABLE = "交付物"


class CoverageStatus(StrEnum):
    """覆盖校验结果（PRD 第 19.4 节）。"""

    COVERED = "已覆盖"
    NOT_COVERED = "未覆盖"
    PARTIAL = "部分覆盖"