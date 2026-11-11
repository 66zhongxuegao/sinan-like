"""8 维 61 技能点目录 —— 学情画像的原子层。

口径来源：PRD 第 17.3 节。每个技能点四要素合一：
学习资料（material）/ 能力参数（值见 profile.py）/ Rubric（rubric.py 的考核定位）/ 画像节点（本对象）。

类型（checkpoint）：A=交付物直查型，B=事件埋点型（PRD 第 19.1 节）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import CheckpointType, Dimension, StepId


@dataclass(frozen=True)
class SkillPoint:
    id: str
    name: str
    dimension: Dimension
    checkpoint: CheckpointType
    material: str
    steps: tuple[StepId, ...]
    target: str  # Rubric 考核定位（步骤·考核对象）


S = StepId

SKILL_POINTS: tuple[SkillPoint, ...] = (
    # ---------------- C1 沟通信任 ----------------
    SkillPoint("C1.1", "开场与身份确认", Dimension.C1_COMMUNICATION, CheckpointType.A_DELIVERABLE, "沟通服务·首呼", (S.S2_FIRST_CALL,), "开场问候+身份+时间确认"),
    SkillPoint("C1.2", "顾问式提问", Dimension.C1_COMMUNICATION, CheckpointType.A_DELIVERABLE, "沟通服务·提问核实", (S.S2_FIRST_CALL,), "开放式问题挖 8 类信息"),
    SkillPoint("C1.3", "情绪安抚", Dimension.C1_COMMUNICATION, CheckpointType.B_EVENT, "沟通服务·顾问式沟通", (S.S2_FIRST_CALL, S.S10_ON_TRIP), "语气冲时不争辩、先确认诉求"),
    SkillPoint("C1.4", "成交促成与确认", Dimension.C1_COMMUNICATION, CheckpointType.A_DELIVERABLE, "沟通服务·成交", (S.S7_ITERATION, S.S8_ORDER), "复述版本并取得明确确认"),
    SkillPoint("C1.5", "投诉处理与售后", Dimension.C1_COMMUNICATION, CheckpointType.B_EVENT, "沟通服务·投诉", (S.S11_SETTLEMENT,), "投诉闭环"),
    SkillPoint("C1.6", "应对不耐烦/追问过度", Dimension.C1_COMMUNICATION, CheckpointType.B_EVENT, "沟通服务·首呼", (S.S2_FIRST_CALL,), "不耐烦时不连续追问"),
    SkillPoint("C1.7", "倾听真实诉求", Dimension.C1_COMMUNICATION, CheckpointType.B_EVENT, "沟通服务·顾问式沟通", (S.S7_ITERATION,), "先听清反对原因再给方案"),
    SkillPoint("C1.8", "回访闭环", Dimension.C1_COMMUNICATION, CheckpointType.B_EVENT, "沟通服务·投诉", (S.S11_SETTLEMENT,), "差评→补救→复访"),

    # ---------------- C2 需求洞察 ----------------
    SkillPoint("C2.1", "信息挖掘（缺失字段识别）", Dimension.C2_REQUIREMENT, CheckpointType.A_DELIVERABLE, "需求管理·需求分析", (S.S1_GRAB, S.S2_FIRST_CALL), "识别缺失字段并补问"),
    SkillPoint("C2.2", "预算口径识别", Dimension.C2_REQUIREMENT, CheckpointType.B_EVENT, "需求管理·期望管理", (S.S2_FIRST_CALL, S.S6_QUOTATION), "未把「性价比高」当预算明确"),
    SkillPoint("C2.3", "硬软区分", Dimension.C2_REQUIREMENT, CheckpointType.A_DELIVERABLE, "需求管理·KANO", (S.S3_REQUIREMENT,), "必须/希望/可替代/不要四分类"),
    SkillPoint("C2.4", "冲突识别", Dimension.C2_REQUIREMENT, CheckpointType.B_EVENT, "需求管理·期望管理", (S.S3_REQUIREMENT,), "识别低预算+高星级等冲突"),
    SkillPoint("C2.5", "冲突取舍沟通", Dimension.C2_REQUIREMENT, CheckpointType.B_EVENT, "需求管理·期望管理", (S.S3_REQUIREMENT,), "把冲突摊开、给取舍"),
    SkillPoint("C2.6", "结构化确认", Dimension.C2_REQUIREMENT, CheckpointType.A_DELIVERABLE, "需求管理·结构化", (S.S3_REQUIREMENT,), "复述需求并取得确认"),
    SkillPoint("C2.7", "需求单遗漏自查", Dimension.C2_REQUIREMENT, CheckpointType.A_DELIVERABLE, "需求管理·结构化", (S.S3_REQUIREMENT,), "交付前逐项核对完整性"),

    # ---------------- C3 方案能力 ----------------
    SkillPoint("C3.1", "逐日行程设计", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "方案设计·行程", (S.S5_ITINERARY,), "逐日时间/交通/景点/餐/酒店/导游"),
    SkillPoint("C3.2", "路线合理性", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "方案设计·路线", (S.S5_ITINERARY,), "无折返、节奏合理"),
    SkillPoint("C3.3", "开放时间/交通耗时核验", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "目的地资源·资源", (S.S5_ITINERARY,), "开放时间与交通耗时可执行"),
    SkillPoint("C3.4", "硬约束覆盖与排除", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "方案设计·原则", (S.S5_ITINERARY,), "覆盖硬约束+排除「不要」"),
    SkillPoint("C3.5", "特殊人群适配", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "方案设计·路线", (S.S5_ITINERARY,), "老人/儿童/企业团节奏适配"),
    SkillPoint("C3.6", "备选方案设计", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "方案设计·资源整合", (S.S5_ITINERARY,), "不确定资源设备选"),
    SkillPoint("C3.7", "取舍方案设计", Dimension.C3_ITINERARY, CheckpointType.B_EVENT, "方案设计·资源整合", (S.S7_ITERATION,), "五星改四星、换景点、换交通、调天数"),
    SkillPoint("C3.8", "版本管理", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "方案设计·原则", (S.S7_ITERATION,), "每次修改生成新版本、可追溯"),
    SkillPoint("C3.9", "视觉呈现", Dimension.C3_ITINERARY, CheckpointType.A_DELIVERABLE, "视觉呈现·排版", (S.S5_ITINERARY,), "PPT/PDF 可读+多语言"),

    # ---------------- C4 资源整合 ----------------
    SkillPoint("C4.1", "询价发起", Dimension.C4_RESOURCE, CheckpointType.A_DELIVERABLE, "目的地资源·资源", (S.S4_RESOURCE,), "向资源方发起询价"),
    SkillPoint("C4.2", "资源比价", Dimension.C4_RESOURCE, CheckpointType.A_DELIVERABLE, "目的地资源·整合", (S.S4_RESOURCE,), "比较 >=2 套组合"),
    SkillPoint("C4.3", "可用性确认", Dimension.C4_RESOURCE, CheckpointType.A_DELIVERABLE, "目的地资源·核验", (S.S4_RESOURCE,), "房态/车/票/档期确认"),
    SkillPoint("C4.4", "模糊口径追问", Dimension.C4_RESOURCE, CheckpointType.B_EVENT, "实操注意·红线", (S.S4_RESOURCE,), "把「应该没问题」追问成明确确认"),
    SkillPoint("C4.5", "隐藏费用识别", Dimension.C4_RESOURCE, CheckpointType.A_DELIVERABLE, "实操注意·易错点", (S.S4_RESOURCE,), "确认含税/接送/附加费"),
    SkillPoint("C4.6", "备选资源兜底", Dimension.C4_RESOURCE, CheckpointType.B_EVENT, "目的地资源·整合", (S.S4_RESOURCE,), "热门时段无房/无车时找备选"),
    SkillPoint("C4.7", "死报价拦截", Dimension.C4_RESOURCE, CheckpointType.A_DELIVERABLE, "实操注意·红线", (S.S4_RESOURCE, S.S6_QUOTATION), "未确认资源不报死价"),
    SkillPoint("C4.8", "资源锁定与预留", Dimension.C4_RESOURCE, CheckpointType.A_DELIVERABLE, "实操注意·锁定", (S.S9_LOCK,), "订房/车/票/导游+80%预留回执"),

    # ---------------- C5 报价利润 ----------------
    SkillPoint("C5.1", "分项报价完整", Dimension.C5_QUOTATION, CheckpointType.A_DELIVERABLE, "方案设计·报价", (S.S6_QUOTATION,), "七项报价齐全"),
    SkillPoint("C5.2", "成本核算", Dimension.C5_QUOTATION, CheckpointType.A_DELIVERABLE, "方案设计·报价", (S.S6_QUOTATION,), "成本准确、无漏项"),
    SkillPoint("C5.3", "毛利测算", Dimension.C5_QUOTATION, CheckpointType.A_DELIVERABLE, "方案设计·报价", (S.S6_QUOTATION,), "毛利合理"),
    SkillPoint("C5.4", "波动成本对冲", Dimension.C5_QUOTATION, CheckpointType.A_DELIVERABLE, "方案设计·报价", (S.S6_QUOTATION,), "机票/高铁涨价预留空间"),
    SkillPoint("C5.5", "超预算解释", Dimension.C5_QUOTATION, CheckpointType.B_EVENT, "方案设计·报价", (S.S6_QUOTATION, S.S7_ITERATION), "超预算时给取舍理由"),
    SkillPoint("C5.6", "保险必选", Dimension.C5_QUOTATION, CheckpointType.A_DELIVERABLE, "实操注意·红线", (S.S6_QUOTATION, S.S8_ORDER), "保险必买"),
    SkillPoint("C5.7", "结算对账", Dimension.C5_QUOTATION, CheckpointType.A_DELIVERABLE, "实操注意·结算", (S.S11_SETTLEMENT,), "逐项核对+付尾款"),
    SkillPoint("C5.8", "差异解释与复核", Dimension.C5_QUOTATION, CheckpointType.B_EVENT, "实操注意·结算", (S.S11_SETTLEMENT,), "地接结算差异逐项找原因"),

    # ---------------- C6 应急解决（全 B） ----------------
    SkillPoint("C6.1", "快速响应安抚", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·突发", (S.S10_ON_TRIP,), "第一时间回应、安抚、不推诿"),
    SkillPoint("C6.2", "事实核实", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·突发", (S.S10_ON_TRIP,), "核实事件/影响/剩余时间"),
    SkillPoint("C6.3", "替代方案生成", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·突发", (S.S10_ON_TRIP,), "联系资源方给替代并比较"),
    SkillPoint("C6.4", "变更沟通与补偿", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·突发", (S.S10_ON_TRIP,), "说明变更原因+合理补偿"),
    SkillPoint("C6.5", "擅自变更规避", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·红线", (S.S10_ON_TRIP,), "先确认再变更"),
    SkillPoint("C6.6", "投诉升级阻断", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·投诉升级", (S.S10_ON_TRIP,), "情绪升级时降级处理"),
    SkillPoint("C6.7", "成本记录闭环", Dimension.C6_EMERGENCY, CheckpointType.B_EVENT, "实操注意·突发", (S.S10_ON_TRIP,), "额外成本有记录+跟进到解决"),

    # ---------------- C7 合规效率 ----------------
    SkillPoint("C7.1", "时限管理", Dimension.C7_COMPLIANCE, CheckpointType.A_DELIVERABLE, "行业认知·规则", (S.S0_INIT, S.S1_GRAB, S.S9_LOCK), "首呼1h/方案4h/通知1-2天"),
    SkillPoint("C7.2", "硬规则复述", Dimension.C7_COMPLIANCE, CheckpointType.A_DELIVERABLE, "行业认知·规则", (S.S0_INIT,), "复述硬规则"),
    SkillPoint("C7.3", "录单一致", Dimension.C7_COMPLIANCE, CheckpointType.A_DELIVERABLE, "实操注意·系统", (S.S8_ORDER,), "字段与最终方案一致"),
    SkillPoint("C7.4", "合同保险付款", Dimension.C7_COMPLIANCE, CheckpointType.A_DELIVERABLE, "实操注意·合规", (S.S8_ORDER,), "合同/保险/付款齐全"),
    SkillPoint("C7.5", "出团通知确认", Dimension.C7_COMPLIANCE, CheckpointType.A_DELIVERABLE, "实操注意·行前", (S.S9_LOCK,), "通知按时送达+客户确认"),
    SkillPoint("C7.6", "模糊确认澄清", Dimension.C7_COMPLIANCE, CheckpointType.B_EVENT, "实操注意·易错点", (S.S8_ORDER,), "把「应该可以」追问成明确确认"),
    SkillPoint("C7.7", "行前二次核验", Dimension.C7_COMPLIANCE, CheckpointType.A_DELIVERABLE, "实操注意·行前", (S.S9_LOCK,), "房型/车座/导游语言/接送时间再核对"),

    # ---------------- C8 跨文化入境游沟通（仅入境单） ----------------
    SkillPoint("C8.1", "外籍客户多语种首呼", Dimension.C8_CROSS_CULTURE, CheckpointType.A_DELIVERABLE, "沟通服务·外籍首呼 + 入境中国", (S.S2_FIRST_CALL,), "语言选择与多语种开场"),
    SkillPoint("C8.2", "国别沟通风格适配", Dimension.C8_CROSS_CULTURE, CheckpointType.B_EVENT, "国别文化·沟通风格", (S.S2_FIRST_CALL, S.S7_ITERATION), "按客源国风格调话术"),
    SkillPoint("C8.3", "实操红线规避", Dimension.C8_CROSS_CULTURE, CheckpointType.B_EVENT, "国别文化·禁忌 + 实操注意·红线", (S.S5_ITINERARY, S.S6_QUOTATION, S.S9_LOCK), "宗教饮食禁忌/礼仪红线不触发"),
    SkillPoint("C8.4", "时差与通讯工具切换", Dimension.C8_CROSS_CULTURE, CheckpointType.B_EVENT, "入境中国·通讯", (S.S2_FIRST_CALL, S.S9_LOCK), "微信/邮件/IM 切换、时差礼仪"),
    SkillPoint("C8.5", "签证免签政策应用", Dimension.C8_CROSS_CULTURE, CheckpointType.A_DELIVERABLE, "目的地资源·签证 + 入境中国·政策", (S.S5_ITINERARY,), "签证/免签/过境/证件有效期核验"),
    SkillPoint("C8.6", "外币结算与汇率沟通", Dimension.C8_CROSS_CULTURE, CheckpointType.B_EVENT, "入境中国·支付", (S.S6_QUOTATION, S.S11_SETTLEMENT), "汇率、国际支付、发票收据差异"),
    SkillPoint("C8.7", "跨文化投诉与信任补救", Dimension.C8_CROSS_CULTURE, CheckpointType.B_EVENT, "国别文化·礼仪 + 沟通服务·投诉", (S.S10_ON_TRIP, S.S11_SETTLEMENT), "用客户母语解释变更与补偿"),
)


SKILL_POINTS_BY_ID: dict[str, SkillPoint] = {sp.id: sp for sp in SKILL_POINTS}


def by_dimension(dimension: Dimension) -> tuple[SkillPoint, ...]:
    return tuple(sp for sp in SKILL_POINTS if sp.dimension == dimension)


def by_step(step: StepId) -> tuple[SkillPoint, ...]:
    return tuple(sp for sp in SKILL_POINTS if step in sp.steps)


def _validate() -> None:
    ids = [sp.id for sp in SKILL_POINTS]
    assert len(ids) == len(set(ids)), "技能点 ID 重复"
    assert len(SKILL_POINTS) == 61, f"技能点数量应为 61，实际 {len(SKILL_POINTS)}"
    for dim in Dimension:
        assert by_dimension(dim), f"维度 {dim} 无技能点"


_validate()