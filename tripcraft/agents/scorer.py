"""评分 Agent —— 按 Rubric 锚点给学员表现打分，且每分必引证据。

口径来源：PRD 第 18 章（BARS）、第 21.2 节（每分必有证据）。
约束：锚点由系统给定（来自入库 Rubric），模型只做「对照 + 引用证据」，
不自由发明标准。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..contracts.enums import STEP_NAMES, MasteryLevel, mastery_of
from ..contracts.steps import STEP_EVIDENCE
from ..contracts.rubric import Rubric
from .base import BaseAgent
from .llm import DeepSeekClient


@dataclass
class ScoreResult:
    skill_point_id: str
    level: str
    score: float
    evidence: list[dict] = field(default_factory=list)
    hit_negative: bool = False
    comment: str = ""
    confidence: float = 0.8

    def validate(self) -> None:
        if not self.evidence:
            raise ValueError(f"{self.skill_point_id} 缺证据（PRD 第 21.2 节：每分必有证据）")

    @property
    def mastery(self) -> MasteryLevel:
        return mastery_of(self.score)


def _rubric_block(rubrics: list[Rubric]) -> str:
    parts = []
    for r in rubrics:
        anchors = "\n".join(f"  {a.level.value}: {a.behavior}" for a in r.anchors)
        trig = f"\n  触发条件: {r.trigger}" if r.trigger else ""
        # 考核定位：这一步是哪一步、证据应该去哪找（否则模型只能凭交付物字面猜）
        steps = "、".join(f"{st.value} {STEP_NAMES.get(st, '')}".strip() for st in r.steps)
        where = "；".join(STEP_EVIDENCE.get(st.value, "") for st in r.steps
                          if STEP_EVIDENCE.get(st.value))
        parts.append(
            f"【{r.skill_point_id}】{r.target}{trig}\n"
            f"  考核步骤: {steps or '—'}\n"
            f"  证据去向: {where or '—'}\n"
            f"  锚点:\n{anchors}\n"
            f"  正例: {r.positive}\n  反例: {r.negative}\n"
            f"  证据要求: {r.evidence_required}"
        )
    return "\n\n".join(parts)


SYSTEM_TMPL = """你是定制师实训的评分专家。请依据给定的 Rubric 锚点，为每个技能点判定学员本次表现属于 M1-M5 哪一档，并给出 0-100 分与证据。

【本次要评的技能点与其 Rubric】
{rubrics}

【评分规则】
1. 锚点是**逐级细化**的：先逐档看「该档锚点描述的全部条件是否都能在证据里核对到」，取**条件全部满足的最高档**。切勿因为低一档的锚点字面上部分吻合就主动降档——高档描述的情形本身就会包含低档的场景，这是级别关系，不是冲突。只有当高档锚点的必要条件**缺少证据**时才取较低档，并在 confidence 上体现该不确定。
2. 每个技能点必须给出 evidence：引用学员原话或交付物片段（≤40 字）作为依据；没有证据不得给分。
3. 若学员命中反例，hit_negative 置 true。
4. score 与 level 必须一致：M1<60，M2 60-69，M3 70-79，M4 80-89，M5>=90。
5. comment 用一句话说明判定理由（20-50 字）。
6. confidence 是你对本次判定的把握（0-1）：证据直接、锚点匹配清晰给 0.85 以上；
   证据模糊、跨档难分、需要推测学员意图的给 0.6 以下。系统会用这个值决定是否转人工复核。
7. 若附带了 `resource_facts`（本单资源方的客观口径：询到的价、可用性、已发生的突发事件），
   可以拿它核对学员的报价与方案是否与资源事实一致（例如报价低于资源方给的房价、
   未经核实就报死价、涨价后没留空间）。**它只作核对参照，不是学员证据，不能单独用它给分。**

【输出 JSON】
{{"scores": [{{"skill_point_id": "", "level": "M2", "score": 65,
              "evidence": [{{"kind": "message", "quote": ""}}],
              "hit_negative": false, "comment": "", "confidence": 0.85}}]}}

只输出 JSON。
"""


class ScoringAgent(BaseAgent):
    name = "scorer"

    def __init__(self, llm: DeepSeekClient) -> None:
        super().__init__(llm)

    def score(self, transcript: str, rubrics: list[Rubric],
              deliverables: dict | None = None, facts: str = "") -> list[ScoreResult]:
        """facts = 本单资源方的客观口径（核对用，不是学员证据）。"""
        system = SYSTEM_TMPL.format(rubrics=_rubric_block(rubrics))
        payload = {
            "transcript": transcript,
            "deliverables": deliverables or {},
        }
        if facts:
            payload["resource_facts"] = facts
            payload["resource_facts_note"] = (
                "以上是本单资源方给出的客观口径，仅用于核对学员的报价/方案是否与资源事实一致；"
                "它不是学员证据，不能单独作为给分依据。")
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        data = self._llm.chat_json(messages, temperature=0.1, max_tokens=3000)
        out = self._collect(data)

        if not out:
            # 模型偶发返回空结果（合法 JSON 但没有 scores）：补一次更严格的请求
            retry = messages + [{
                "role": "user",
                "content": ("上一次没有返回任何 scores。请严格只输出 "
                            '{"scores":[{"skill_point_id":"","level":"M1-M5","score":0-100,'
                            '"evidence":[{"kind":"message","quote":""}],"hit_negative":false,'
                            '"comment":"","confidence":0-1}]}，'
                            "且必须为上面列出的每一个技能点各给一条判定。"),
            }]
            data = self._llm.chat_json(retry, temperature=0.1, max_tokens=3000)
            out = self._collect(data)

        # 漏判补救：模型偶尔只回一部分技能点（校准集实测出现过），
        # 对缺失的点做一次定向重试——否则那些点会被记成「未返回」。
        got = {r.skill_point_id for r in out}
        missing = [r for r in rubrics if r.skill_point_id not in got]
        if missing and out:
            system = SYSTEM_TMPL.format(rubrics=_rubric_block(missing))
            ask = [{"role": "system", "content": system},
                   {"role": "user", "content": json.dumps(
                       {"transcript": transcript, "deliverables": deliverables or {},
                        "resource_facts": facts or "",
                        "note": "只评下面这几个技能点，每个都必须给一条判定。"}, ensure_ascii=False)}]
            out.extend(self._collect(self._llm.chat_json(ask, temperature=0.1, max_tokens=2000)))
        return out

    def _collect(self, data) -> list[ScoreResult]:
        out: list[ScoreResult] = []
        for item in (data.get("scores") if isinstance(data, dict) else []) or []:
            sp_id = item.get("skill_point_id", "")
            if not sp_id:
                continue
            ev = item.get("evidence") or []
            if isinstance(ev, dict):
                ev = [ev]
            try:
                score = float(item.get("score", 0))
            except (TypeError, ValueError):
                score = 0.0
            level = str(item.get("level") or mastery_of(score).value)
            try:
                conf = float(item.get("confidence", 0.8))
            except (TypeError, ValueError):
                conf = 0.8
            out.append(ScoreResult(
                skill_point_id=sp_id, level=level, score=score, evidence=ev,
                hit_negative=bool(item.get("hit_negative")),
                comment=str(item.get("comment", "")),
                confidence=max(0.0, min(1.0, conf))))
        return out
