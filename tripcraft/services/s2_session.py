"""S2 首呼垂直切片 —— 「对话 → 需求单 → 评分 → 证据 → 画像」闭环（M1）。

对应 PRD 第 4 章 S2、第 17-21 章。
- 客户 Agent：扮演不耐心、需求模糊的客户
- 需求抽取：转写 -> 结构化需求单（交付物）
- 评分 Agent：按 S2 相关 Rubric 打分，每分带证据
- 画像写回：能力参数更新（未覆盖不更新由上层覆盖校验保证，见 M3）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.base import AgentContext
from ..agents.customer import CustomerAgent, CustomerPersona, persona_for
from ..agents.llm import DeepSeekClient
from ..agents.requirements import RequirementExtractor
from ..agents.scorer import ScoreResult, ScoringAgent
from ..contracts.deliverables import Deliverable
from ..contracts.enums import CheckpointType, DeliverableKind, Dimension, StepId
from ..contracts.profile import LearnerProfile
from ..contracts.rubric import RUBRICS, Rubric
from ..contracts.skill_points import SKILL_POINTS_BY_ID, by_step
from ..engine.state_machine import Run
from ..contracts.task import TaskInstance


def s2_skill_points(inbound: bool = True) -> list[str]:
    """S2（首呼）涉及的技能点 ID。

    本平台只做入境接待（港澳台/新加坡/海外客源），**中文单同样是入境单**，
    因此 C8 跨文化入境游沟通默认参评（D-021）。inbound=False 仅保留给历史用例。
    """
    ids = [sp.id for sp in by_step(StepId.S2_FIRST_CALL)]
    if not inbound:
        ids = [i for i in ids if SKILL_POINTS_BY_ID[i].dimension is not Dimension.C8_CROSS_CULTURE]
    return ids


@dataclass
class S2Session:
    user_id: str
    llm: DeepSeekClient
    inbound: bool = True
    instance_id: str = "s2-1"
    language: str = "中文"
    ctx: AgentContext = field(init=False)
    run: Run = field(init=False)
    customer: CustomerAgent = field(init=False)
    deliverables: list[Deliverable] = field(default_factory=list)
    scores: list[ScoreResult] = field(default_factory=list)
    requirement_sheet: dict = field(default_factory=dict)
    started: bool = False
    finished: bool = False

    def __post_init__(self) -> None:
        self.ctx = AgentContext(instance_id=self.instance_id, user_id=self.user_id,
                                language=self.language)
        inst = TaskInstance(id=self.instance_id, template_id="s2", user_id=self.user_id,
                            inbound=self.inbound, current_step=StepId.S2_FIRST_CALL)
        self.run = Run(instance=inst)
        # 客户人设与实战链路同源（agents/customer.py），不再用硬编码默认人设
        self.customer = CustomerAgent(self.llm, persona_for(
            "王女士", "云南", "香港", self.language, self.instance_id))

    # ---- 对话 ----

    def start(self) -> str:
        """创建会话；客户被动接听，等定制师先开口，这里返回客户的第一句。"""
        opening = self.customer.opening(self.ctx)
        self.started = True
        return opening

    def send(self, message: str) -> str:
        if not self.started:
            self.start()
        return self.customer.reply(self.ctx, message)

    # ---- 收口：需求单 + 评分 + 画像 ----

    def finish(self, profile: LearnerProfile | None = None) -> dict:
        if self.finished:
            return self.report()
        transcript = self.ctx.transcript()

        # 1) 需求单（交付物）
        sheet = RequirementExtractor(self.llm).extract(transcript)
        self.requirement_sheet = sheet
        self.deliverables.append(Deliverable(
            id=f"{self.instance_id}-req", instance_id=self.instance_id,
            kind=DeliverableKind.REQUIREMENT_SHEET, step=StepId.S3_REQUIREMENT,
            payload=sheet))

        # 2) 评分（每分带证据）
        targets = [RUBRICS[i] for i in s2_skill_points(self.inbound) if i in RUBRICS]
        self.scores = ScoringAgent(self.llm).score(
            transcript, targets,
            deliverables={"requirement_sheet": sheet})

        # 3) 校验证据（PRD 第 21.2 节：每分必有证据）
        for s in self.scores:
            s.validate()

        # 4) 画像写回（能力参数 = 本次得分）
        if profile is not None:
            for s in self.scores:
                if s.skill_point_id in SKILL_POINTS_BY_ID:
                    profile.set_ability(s.skill_point_id, s.score)

        self.finished = True
        return self.report()

    # ---- 输出 ----

    def report(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "user_id": self.user_id,
            "inbound": self.inbound,
            "turns": sum(1 for m in self.ctx.messages if m["role"] == "user"),
            "requirement_sheet": self.requirement_sheet,
            "scores": [
                {"skill_point_id": s.skill_point_id, "level": s.level, "score": s.score,
                 "evidence": s.evidence, "hit_negative": s.hit_negative, "comment": s.comment}
                for s in self.scores
            ],
            "average": round(sum(s.score for s in self.scores) / len(self.scores), 1) if self.scores else 0,
        }

    def snapshot(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "user_id": self.user_id,
            "started": self.started,
            "finished": self.finished,
            "turns": sum(1 for m in self.ctx.messages if m["role"] == "user"),
            "transcript": self.ctx.transcript(),
        }