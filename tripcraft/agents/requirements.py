"""需求结构化抽取 —— 从首呼转写生成需求单（PRD 第 4 章 S3、第 5 章需求表）。

约束：只抽取转写里出现过的信息；没出现的归入 missing，不得编造。
"""

from __future__ import annotations

from .base import BaseAgent
from .llm import DeepSeekClient

CATEGORIES = ("人数", "出行人关系", "出发地", "目的地", "日期", "天数", "预算",
              "交通", "酒店", "景点偏好", "餐饮", "禁忌", "特殊需求", "决策人")

SYSTEM = f"""你是需求结构化专家。把定制师与客户的首呼转写，整理成结构化需求单。

【字段类别】
{" / ".join(CATEGORIES)}

【要求】
1. 只抽取转写中真实出现过的信息；没出现的一律不写进 items，而是列入 missing。
2. attribute 取值：必须满足 / 希望满足 / 可替代 / 明确不要 / 待确认。判断依据是客户原话的语气与措辞。
3. status 取值：未知 / 待确认 / 已确认。客户明确认可才算「已确认」。
4. 每条要给 evidence：引用客户或定制师的原话片段（≤40 字）。
5. 识别 risks：客户前后矛盾、预算与期望不匹配、关键信息缺失等。

【输出 JSON】
{{"items": [{{"category": "", "content": "", "attribute": "", "status": "", "evidence": ""}}],
  "missing": [],
  "risks": []}}

只输出 JSON。
"""


class RequirementExtractor(BaseAgent):
    name = "requirements"

    def __init__(self, llm: DeepSeekClient) -> None:
        super().__init__(llm)

    def extract(self, transcript: str) -> dict:
        data = self._llm.chat_json(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": "首呼转写如下：\n" + transcript}],
            temperature=0.2, max_tokens=2500)
        if not isinstance(data, dict):
            return {"items": [], "missing": [], "risks": []}
        data.setdefault("items", [])
        data.setdefault("missing", [])
        data.setdefault("risks", [])
        return data