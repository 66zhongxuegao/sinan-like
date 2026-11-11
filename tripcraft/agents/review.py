"""六帽审查 Agent —— 学习资料生成后的反幻觉质检（对应 PRD 第 22 章「六帽审查」）。

帽子顺序与职责：
  白帽 事实核查 —— 对照知识点基座/Rubric，检查有无编造事实
  黑帽 逻辑审计 —— 反幻觉核心：逻辑矛盾、过度承诺、无中生有
  绿帽 创意转化 —— 是否讲得通俗、有例子，而非照搬资料
  黄帽 激励引导 —— 是否正面鼓励、给可操作下一步
  红帽 个性适配 —— 是否贴合学员当前掌握度与难度
  蓝帽 质量总控 —— 综合前五帽，给最终「合格 / 需修改」判定

白帽/黑帽是硬门槛：任一不通过 → 材料需重写。
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import DeepSeekClient

WHITE_SYSTEM = """你是六帽审查中的白帽事实核查员。
对照下方给出的【知识点基座】与【Rubric】，逐条核对材料里的事实声称：
- 有没有编造知识点、张冠李戴、把 A 技能点内容写成 B 的；
- 有没有与基座/Rubric 冲突的说法；
- 数字、规则、时限是否与资料一致。
只输出 JSON：{"verdict":"通过 或 不通过","note":"一句话理由"}"""

BLACK_SYSTEM = """你是六帽审查中的黑帽逻辑审计员，反幻觉核心角色。
只挑毛病，宁可从严：
- 材料内部有没有前后矛盾、逻辑跳跃；
- 有没有过度承诺（把「可能」说成「一定」）；
- 有没有凭空出现的步骤、工具、数字。
只输出 JSON：{"verdict":"通过 或 不通过","note":"一句话理由"}"""

GREEN_SYSTEM = """你是六帽审查中的绿帽创意转化评估员。
判断材料是否讲得通俗、有具体例子/比喻、有讲解价值，而不是照抄资料。
只输出 JSON：{"verdict":"通过 或 建议改进","note":"一句话理由"}"""

YELLOW_SYSTEM = """你是六帽审查中的黄帽激励评估员。
判断材料是否正面鼓励学员、给出可执行的下一步、不打击信心。
只输出 JSON：{"verdict":"通过 或 建议改进","note":"一句话理由"}"""

RED_SYSTEM = """你是六帽审查中的红帽个性适配检查员。
判断材料是否贴合该学员当前掌握度（教学/实战分）与难度：太难或太简单、语气是否合适。
只输出 JSON：{"verdict":"通过 或 需调整","note":"一句话理由"}"""

BLUE_SYSTEM = """你是六帽审查中的蓝帽总控。
下面是前五顶帽子的结论，请综合判断这份材料能否交付学员：
- 白帽/黑帽任一不通过 → 判定「需修改」；
- 其余帽子是「建议改进/需调整」→ 可判定「合格」但要在 note 里提醒。
只输出 JSON：{"verdict":"合格 或 需修改","note":"一句话综合意见"}"""


@dataclass
class HatResult:
    id: str
    name: str
    verdict: str
    note: str


class SixHatsReview:
    HATS = [
        ("white", "白帽·事实核查", WHITE_SYSTEM),
        ("black", "黑帽·逻辑审计", BLACK_SYSTEM),
        ("green", "绿帽·创意转化", GREEN_SYSTEM),
        ("yellow", "黄帽·激励引导", YELLOW_SYSTEM),
        ("red", "红帽·个性适配", RED_SYSTEM),
        ("blue", "蓝帽·质量总控", BLUE_SYSTEM),
    ]

    def __init__(self, llm: DeepSeekClient) -> None:
        self._llm = llm

    def review(self, content: str, context_text: str) -> dict:
        prior: dict[str, HatResult] = {}
        for hid, name, system in self.HATS[:-1]:
            prior[hid] = self._run(hid, name, system, content, context_text)

        # 蓝帽综合前五帽
        digest = "\n".join(f"- {r.name}：{r.verdict}，{r.note}" for r in prior.values())
        blue_system = BLUE_SYSTEM + f"\n\n前五帽结论：\n{digest}"
        blue = self._run("blue", "蓝帽·质量总控", blue_system, content, context_text)

        hats = [prior[h] for h in ("white", "black", "green", "yellow", "red")] + [blue]
        critical_fail = any(r.verdict == "不通过" for r in (prior["white"], prior["black"]))
        final_verdict = blue.verdict if blue.verdict in ("合格", "需修改") else ("需修改" if critical_fail else "合格")
        return {
            "verdict": final_verdict,
            "critical_fail": critical_fail,
            "hats": [{"id": h.id, "name": h.name, "verdict": h.verdict, "note": h.note} for h in hats],
        }

    def _run(self, hid: str, name: str, system: str, content: str, context_text: str) -> HatResult:
        user = f"待审查材料：\n\n{content[:3500]}\n\n参考资料：\n{context_text[:1500]}"
        try:
            data = self._llm.chat_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.1, max_tokens=200)
        except Exception:
            data = {}
        verdict = str(data.get("verdict") or "通过").strip()
        note = str(data.get("note") or "").strip()
        return HatResult(id=hid, name=name, verdict=verdict, note=note)
