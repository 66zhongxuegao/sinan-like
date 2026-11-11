"""Orchestra 角色目录。

目录是产品与调试面的单一来源：前端/答辩可以列出「有哪些声部」，
但实际执行仍以 Registry 中已绑定的 handler 为准。
"""

from __future__ import annotations

from .contracts import AgentSpec


TEACHING_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("teaching.router", "教学调度器", "teaching", ("route", "intent"),
              "判断本轮需要哪些协作者，不直接作答"),
    AgentSpec("teaching.retrieval", "知识召回", "teaching", ("knowledge", "bm25"),
              "从知识点基座检索依据，返回可追溯来源"),
    AgentSpec("teaching.context", "上下文装配", "teaching", ("context", "rubric"),
              "把六类资料装成一份可追溯上下文"),
    AgentSpec("teaching.profile", "画像顾问", "teaching", ("profile", "advice"),
              "读取掌握度与答题记录，给出薄弱点建议"),
    AgentSpec("teaching.teacher", "主讲 Agent（教师）", "teaching", ("teach", "synthesis"),
              "汇总各声部输入，输出一次带来源的讲解"),
    AgentSpec("teaching.quiz", "出题 Agent", "teaching", ("quiz", "rubric"),
              "按 Rubric 与掌握度出题"),
    AgentSpec("teaching.answer", "判分 Agent", "teaching", ("judge", "quiz"),
              "判题并给出针对性讲解"),
    AgentSpec("teaching.asset", "教研 Agent", "teaching", ("asset",),
              "生成讲义、实操指南、学习报告与错题本"),
    AgentSpec("teaching.review", "六帽审查", "teaching", ("review", "fact"),
              "白帽事实、黑帽逻辑等六顶帽子审查"),
)

PRACTICE_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("practice.hub", "资源大群调度", "practice", ("hub", "route"),
              "资源大群按订单与发言对象定位资源方"),
    AgentSpec("practice.customer", "客户 Agent", "practice", ("customer", "im"),
              "按订单人设与事实回复客户群"),
    AgentSpec("practice.supplier", "资源方 Agent", "practice", ("supplier", "quote"),
              "按订单报价、库存与档期回复"),
    AgentSpec("practice.guide", "司导 Agent", "practice", ("guide", "incident"),
              "只报现象、请定制师拍板"),
    AgentSpec("practice.phone_customer", "电话客户 Agent", "practice", ("customer", "phone"),
              "同一客户人设在电话通道的适配器；不是第二个客户"),
)

AGENT_SPECS: dict[str, AgentSpec] = {
    spec.id: spec for spec in (TEACHING_AGENTS + PRACTICE_AGENTS)
}


def get_spec(agent_id: str) -> AgentSpec | None:
    return AGENT_SPECS.get(agent_id)


def catalog() -> list[dict]:
    return [
        {
            "id": spec.id,
            "name": spec.name,
            "section": spec.section,
            "capabilities": list(spec.capabilities),
            "description": spec.description,
        }
        for spec in AGENT_SPECS.values()
    ]

