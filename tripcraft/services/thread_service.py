"""技能点对话线程服务 —— 学习 / 做题 / 复盘 / 问答 / 个性资源。

对应 PRD 第 27 章。核心是「一次对话前，把 6 类来源装配成上下文」：
  ① Rubric  ② 知识点基座  ③ 本线程历史  ④ 答题情况  ⑤ 画像掌握度  ⑥ 实战证据
所有回复必须引用来源（evidence），不得凭空编造。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..agents.llm import DeepSeekClient
from ..agents.review import SixHatsReview
from ..contracts.enums import mastery_of
from ..contracts.rubric import RUBRICS
from ..contracts.culture_bridges import get as get_bridge
from ..contracts.skill_points import SKILL_POINTS_BY_ID
from ..storage.db import Store
from ..orchestration import AgentResult, AgentTask, Blackboard, Conductor, Plan
from .retrieval import get_retriever
from .adaptive_diagnosis import observation_update
from .capability_compounding import compile_learning_signal, persist_learning_signal
from .evidence_verifier import classify_source, get_verifier
from .experience_compiler import get_skill_graph
from .source_registry import OfficialSourceRegistry

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


# ---------------- 判分链路的错误（带 HTTP 状态，由路由层映射） ----------------
# P0：题目必须在服务端出题时就落库，判分只按 question_id 取回服务端题库。
# 客户端无法通过自带 answer/reference 影响判分，也无法用别人的 question_id 作答。

class QuizError(RuntimeError):
    """判分链路错误基类。`status` 由路由层映射成 HTTP 状态码。"""

    status = 400


class QuizQuestionMissing(QuizError):
    """请求体里没有 question_id（题目必须来自服务端出题）。"""

    status = 400

    def __init__(self, msg: str = "缺少 question_id：题目必须来自服务端出题") -> None:
        super().__init__(msg)


class QuizQuestionNotFound(QuizError):
    """question_id 在服务端题库里不存在（含存档损坏）。"""

    status = 404

    def __init__(self, msg: str = "题目不存在或已失效，请重新出题") -> None:
        super().__init__(msg)


class QuizQuestionForbidden(QuizError):
    """question_id 属于别的用户或别的技能点。"""

    status = 403

    def __init__(self, msg: str = "无权作答其他用户或其他技能点的题目") -> None:
        super().__init__(msg)


class QuizQuestionAnswered(QuizError):
    """同一道题已经交过卷：同题只计分一次（幂等口径＝拒绝重复提交，不改任何分数与趋势）。"""

    status = 409

    def __init__(self, msg: str = "这道题已经交过了：同题只计分一次，请重新出题") -> None:
        super().__init__(msg)


QUIZ_ANSWER_KEYS = ("answer", "reference", "rubric_points", "explain")


def strip_quiz_answers(card: dict | None) -> dict:
    """题卡下发投影：剥掉答案与评分要点（服务层自身也做一遍，纵深防御）。"""
    out = dict(card or {})
    for key in QUIZ_ANSWER_KEYS:
        out.pop(key, None)
    return out

ASSET_TYPES = {"lecture": "讲义", "guide": "实操指南", "report": "学习报告", "wrong_book": "错题本"}

# 文化桥不是 M1–M5 评分技能点，教学口径单独写清楚，避免教师照搬 Rubric 话术
BRIDGE_NOTE = ("【本技能点的性质】文化桥不做 M1–M5 评分锚点。教学目标是让学员先找到中国与"
               "该客源国的**共通点**，再谈差异，并能落到行程安排、餐食与沟通话术上。"
               "讲评时先讲共通点、再讲对方那边的差异和容易踩的坑，不要写成风俗百科，也不要编造官方政策。")


def bridge_knowledge(b) -> dict:
    """把一座文化桥的底座转成教师可用的资料块（原来这块是空的）。"""
    lines = [f"{b.name} · {b.country}（{b.language}）", f"定位：{b.summary}", ""]
    for i, p in enumerate(b.points, 1):
        lines.append(f"共通点 {i}：{p.get('point', '')}")
        lines.append(f"  中国这边：{p.get('china', '')}")
        lines.append(f"  {b.country}这边：{p.get('theirs', '')}")
        lines.append(f"  怎么用：{p.get('use', '')}")
        lines.append("")
    if b.pitfalls:
        lines.append("容易踩的坑：")
        lines += [f"  - {x}" for x in b.pitfalls]
    sources = [f"文化桥:{b.code}", f"共通点 {len(b.points)} 条"]
    if b.pitfalls:
        sources.append(f"踩坑 {len(b.pitfalls)} 条")
    return {"text": chr(10).join(lines).strip(), "sources": sources}


@dataclass
class ThreadContext:
    sp: str
    name: str
    is_bridge: bool = False
    rubric: dict = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    quiz: dict = field(default_factory=dict)
    ability: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    skill_graph: dict = field(default_factory=dict)

    def sources(self) -> list[str]:
        out = [f"bridge:{self.sp}" if self.is_bridge else f"rubric:{self.sp}"]
        for s in (self.knowledge or {}).get("sources", [])[:4]:
            out.append(f"知识:{s}")
        if self.skill_graph.get("nodes"):
            out.append(f"skill_graph:{self.sp}:{len(self.skill_graph['nodes'])}节点")
        out.append(f"thread:{len(self.history)}条")
        out.append(f"quiz:{self.quiz.get('count', 0)}题")
        out.append(f"mastery:教学{self.ability.get('teach', 0):.0f}/实战{self.ability.get('real_v', 0):.0f}")
        for e in self.evidence[:3]:
            out.append(f"order:{e.get('order_id', '')}")
        return out

    def evidence_payload(self) -> list[dict]:
        """给证据闸门的可追溯材料；不把“来源标签”当成证据。

        每个材料带 trust 等级：普通知识召回是 teaching，Rubric / 技能图是
        curated，订单现场记录是 observed，政府来源是 official。高风险 claim
        只允许 curated / observed / official 通过，见 EvidenceVerifier。
        """
        rows: list[dict] = []
        if self.rubric:
            r = self.rubric
            bits = [r.get("target", ""), r.get("positive", ""), r.get("negative", "")]
            bits += [a.get("behavior", "") for a in r.get("anchors", [])]
            text = "；".join(x for x in bits if x)
            if text:
                rows.append({"id": f"R:{self.sp}", "source": f"rubric:{self.sp}",
                             "text": text, "trust": "curated"})
        if self.knowledge.get("text"):
            rows.append({"id": f"K:{self.sp}", "source": "knowledge:" + self.sp,
                         "text": str(self.knowledge["text"]), "trust": "teaching"})
        # 技能图里的“证据要求”是教学约束；节点 source_refs 才是可追溯来源。
        # 将二者分开送入闸门，避免把知识点文本误当成外部事实原文。
        seen_sources: set[str] = set()
        for node in self.skill_graph.get("nodes", []):
            for req in node.get("evidence_requirements", []):
                source = str(req.get("source", ""))
                rows.append({"id": req.get("id", ""), "source": source,
                             "text": req.get("requirement", ""),
                             "trust": classify_source(source)})
            for ref in node.get("source_refs", []):
                if not isinstance(ref, dict):
                    continue
                title = str(ref.get("title") or "").strip()
                url = str(ref.get("url") or "").strip()
                source = url or title
                if not source or source in seen_sources:
                    continue
                seen_sources.add(source)
                text = title or url
                rows.append({"id": f"SRC:{node.get('id')}:{len(seen_sources)}",
                             "source": source, "url": url, "text": text,
                             "trust": classify_source(source)})
        for item in self.evidence[:3]:
            summary = str(item.get("summary") or "").strip()
            if summary:
                oid = str(item.get("order_id") or "unknown")
                rows.append({"id": f"O:{oid}", "source": f"order:{oid}",
                             "text": summary, "trust": "observed"})
        return [r for r in rows if r.get("text")]

    def render(self) -> str:
        lines: list[str] = [f"【本次技能点】{self.name}（{self.sp}）"]
        if self.rubric:
            r = self.rubric
            anchors = "\n".join(f"  {a['level']}: {a['behavior']}" for a in r.get("anchors", []))
            lines.append(f"【该技能点 Rubric】{r.get('target', '')}\n{anchors}\n正例：{r.get('positive', '')}\n反例：{r.get('negative', '')}")
        if self.is_bridge:
            lines.append(BRIDGE_NOTE)
        if self.skill_graph.get("nodes"):
            rows = []
            for node in self.skill_graph.get("nodes", [])[:4]:
                prereq = "、".join(node.get("prerequisites", [])) or "无"
                reqs = "；".join(x.get("requirement", "") for x in node.get("evidence_requirements", [])[:3]) or "按 Rubric 留存证据"
                rows.append(f"  {node.get('id')} {node.get('name')}｜前置：{prereq}｜证据：{reqs}｜边界：{node.get('negative', '')[:80]}")
            lines.append("【技能图约束（生成/判断必须在此结构内）】\n" + "\n".join(rows))
        k = self.knowledge
        if k and k.get("text"):
            lines.append(f"【知识点基座（召回）】\n{k['text']}")
        if self.history:
            h = "\n".join(f"  {m['role']}: {m['content'][:80]}" for m in self.history[-6:])
            lines.append("【本线程历史（最近）】\n" + h)
        q = self.quiz
        if q.get("count"):
            lines.append(f"【答题情况】共 {q['count']} 题，正确 {q['correct']} 题，最近：{q.get('recent') or '无'}")
        lines.append(f"【画像掌握度】教学 {self.ability.get('teach', 0):.0f} / 实战 {self.ability.get('real_v', 0):.0f}")
        if self.evidence:
            ev = "\n".join(f"  {e.get('order_id')}：{e.get('summary', '')}" for e in self.evidence[:3])
            lines.append("【实战证据】\n" + ev)
        return "\n\n".join(lines)


TEACHER_SYSTEM = """你是「司南」，定制师实训系统的带教老师，一对一陪学员学。

【教学铁律】
1. 学员问知识点 → 先讲清楚：先给结论 → 2-3 个要点 → 举一个例子 → 点出常见易错点。
2. 讲解要用自己的话重新组织，禁止照搬资料原文；可以打比方、举例子。
3. 讲完必须问一句「要不要做两道题检验一下？」（学员说先不练就不问）。
4. 不讲与当前技能点无关的内容；严格对照给定的 Rubric 锚点。
5. 涉及事实时只依据提供的资料，不得编造；资料不足就说「这块资料还不全」。
6. 用口语短句，别写列表式提纲，别用「作为AI」这类套话。

【输出格式】
用 Markdown 回复（可用小标题、加粗、列表、引用）。
结尾另起一行用 <div class="refs">参考来源：…</div> 标出本次用到的来源。
"""

ASSET_SYSTEM = """你是定制师培训教研专家，负责按技能点生成学习资料。

【要求】
- 输出 **Markdown**（含标题、小标题、表格、引用、列表）。
- 内容必须围绕该技能点的 Rubric 锚点与知识点基座，不得跑题、不得编造事实。
- 末尾必须有一节「参考来源」，列出用到的 Rubric 锚点 / 知识点。
- 只输出 Markdown 正文，不要额外解释。
"""

JUDGE_SYSTEM = """你是评分专家。依据给定 Rubric 的 M1–M5 锚点，判断学员当前掌握到哪一档。

【规则】
- 就低不就高；证据不足时取较低档。
- 结合给定「答题情况」与「实战证据」。

【输出 JSON】{"level":"M3","score":75,"reason":"一句话理由"}
只输出 JSON。
"""

QUESTION_SYSTEM = """你是实战出题老师，给学员出一道贴近真实工作场景的题。

【规则】
- 必须围绕该技能点，用一个具体的客户/订单/突发场景出题，考「遇到这种情况该怎么做」，不考概念背诵。
- 难度只是你出题时的复杂度标尺（绝对不要把难度分级、M1-M5、Rubric 档位这些内部词说给学员听）：
  L1 基础：场景明确，直接套标准动作
  L2 简单辨析：带一个干扰点
  L3 进阶：带两个干扰点，需比较取舍
  L4 高阶：加时间压力 / 资源紧张 / 情绪升级
  L5 高压综合：多冲突并发，要排优先级并书面闭环
- 选择题 options 必须 4 个，answer 用 A/B/C/D；简答题给参考答案与评分要点。
- 题干里绝对不要出现「M1/M2/M3/M4/M5」「档位」「Rubric」等内部评分词。

【输出 JSON】
{"type":"choice","stem":"","options":["","","",""],"answer":"A","explain":"","difficulty":"L2"}
或 {"type":"short","stem":"","reference":"","rubric_points":["",""],"difficulty":"L3"}
只输出 JSON。
"""


ROUTER_SYSTEM = """你是定制师实训系统的教学 Orchestra 调度器，由 Conductor 统一调用。
根据学员这句话，判断本轮需要哪些协作者声部（教师 Agent 最后汇总输出，不是总指挥）：

- retrieval：知识召回 —— 需要查知识点/规则/定义/步骤时
- profile：画像顾问 —— 学员提到掌握度、薄弱点、复盘、下一步建议、我的学习情况时
只列确实需要的；普通知识点提问通常只要 retrieval。
输出 JSON：{"agents":["retrieval","profile"]}
只输出 JSON。"""

PROFILE_SYSTEM = """你是画像顾问。根据学员当前画像，给出一条针对当前技能点的可操作学习建议。
要求：具体、口语化、不超过 40 字。只输出建议本身，不要解释。"""

AGENT_META = {
    "retrieval": {"id": "retrieval", "name": "知识召回", "icon": "search"},
    "profile": {"id": "profile", "name": "画像顾问", "icon": "user"},
    "teacher": {"id": "teacher", "name": "司南老师", "icon": "book"},
    "asset": {"id": "asset", "name": "教研生成", "icon": "notebook"},
    "judge": {"id": "judge", "name": "掌握度判档", "icon": "target"},
    "question": {"id": "question", "name": "Rubric 出题", "icon": "filetext"},
    "answer": {"id": "answer", "name": "答题判分", "icon": "check"},
}
HAT_ICON = {"white": "eye", "black": "shield", "green": "sparkle", "yellow": "star", "red": "user", "blue": "compass"}


def _difficulty_of(level: str) -> str:
    return {"M1": "L1", "M2": "L2", "M3": "L3", "M4": "L4", "M5": "L5"}.get(level, "L1")


class ThreadService:
    def __init__(self, store: Store, llm: DeepSeekClient | None = None,
                 conductor: Conductor | None = None) -> None:
        self._store = store
        self._llm = llm
        self._conductor = conductor or Conductor()
        self._bind_agents()

    def _require_llm(self) -> DeepSeekClient:
        if self._llm is None:
            raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
        return self._llm

    # ---------- Multi-Agent Orchestra 绑定 ----------

    def _bind_agents(self) -> None:
        """把教学声部绑定到共享 Conductor；Agent 之间不互相调用。"""
        self._conductor.registry.bind("teaching.router", self._agent_router)
        self._conductor.registry.bind("teaching.retrieval", self._agent_retrieval)
        self._conductor.registry.bind("teaching.context", self._agent_context)
        self._conductor.registry.bind("teaching.profile", self._agent_profile)
        self._conductor.registry.bind("teaching.teacher", self._agent_teacher)

    def _agent_router(self, task: AgentTask, board: Blackboard) -> AgentResult:
        message = str(task.payload.get("message") or "")
        return AgentResult(task.id, task.agent, output={"agents": self._plan(message)})

    def _agent_retrieval(self, task: AgentTask, board: Blackboard) -> AgentResult:
        sp = str(task.payload.get("sp") or "")
        query = str(task.payload.get("query") or "")
        return AgentResult(task.id, task.agent, output=self._knowledge(sp, query))

    def _agent_context(self, task: AgentTask, board: Blackboard) -> AgentResult:
        ctx = self.build_context(
            str(task.payload.get("user_id") or ""),
            str(task.payload.get("sp") or ""),
            query=str(task.payload.get("query") or ""),
            knowledge=board.get("retrieval") or {},
        )
        return AgentResult(task.id, task.agent, output=ctx)

    def _agent_profile(self, task: AgentTask, board: Blackboard) -> AgentResult:
        ctx = board.get("context")
        advice = self._profile_advice(
            str(task.payload.get("user_id") or ""),
            str(task.payload.get("sp") or ""),
            ctx,
        )
        return AgentResult(task.id, task.agent, output={"advice": advice})

    def _agent_teacher(self, task: AgentTask, board: Blackboard) -> AgentResult:
        ctx = board.get("context")
        profile = board.get("profile") or {}
        out = self._teacher_reply(
            str(task.payload.get("user_id") or ""),
            str(task.payload.get("sp") or ""),
            str(task.payload.get("message") or ""),
            ctx,
            str(profile.get("advice") or ""),
        )
        return AgentResult(task.id, task.agent, output=out,
                           evidence=list(out.get("evidence") or []))

    # ---------- 上下文装配 ----------

    def _knowledge(self, sp: str, query: str = "") -> dict:
        try:
            return get_retriever().render(sp, query, top_k=8)
        except Exception:
            return {}

    def _rubric(self, sp: str) -> dict:
        r = RUBRICS.get(sp)
        if not r:
            return {}
        return {
            "target": r.target, "trigger": r.trigger, "positive": r.positive,
            "negative": r.negative, "knowledge": r.knowledge,
            "anchors": [{"level": a.level.value, "behavior": a.behavior} for a in r.anchors],
        }

    def _quiz_stats(self, user_id: str, sp: str) -> dict:
        rows = self._store.attempts(user_id, sp)
        correct = sum(1 for r in rows if r["correct"])
        recent = ""
        if rows:
            last = rows[-1]
            recent = ("答对" if last["correct"] else "答错") + f"（{str(last['question'])[:40]}…）"
        return {"count": len(rows), "correct": correct, "recent": recent}

    def _practical_evidence(self, user_id: str, sp: str) -> list[dict]:
        """实战证据：从订单分数里取与该技能点相关的记录（当前用订单状态摘要）。"""
        out = []
        for o in self._store.orders(user_id)[:3]:
            out.append({"order_id": o["order_id"], "summary": f"{o['customer']}·{o['destination']}，当前阶段 {o['stage_index'] + 1}/8"})
        return out

    def build_context(self, user_id: str, sp: str, query: str = "",
                      *, knowledge: dict | None = None) -> ThreadContext:
        thread = self._store.get_or_create_thread(user_id, sp)
        ab = self._store.abilities(user_id).get(sp, {})
        skill = SKILL_POINTS_BY_ID.get(sp)
        bridge = get_bridge(sp)
        if knowledge is None:
            knowledge = self._knowledge(sp, query)
        # 文化桥没有知识点基座文件，直接把桥的底座喂给教师，否则资料块是空的
        if bridge is not None and not (knowledge or {}).get("text"):
            knowledge = bridge_knowledge(bridge)
        return ThreadContext(
            sp=sp,
            name=(skill.name if skill else (bridge.name if bridge else sp)),
            is_bridge=bridge is not None,
            rubric=self._rubric(sp), knowledge=knowledge,
            history=self._store.messages(thread["thread_id"]),
            quiz=self._quiz_stats(user_id, sp),
            ability={"teach": float(ab.get("teach") or 0), "real_v": float(ab.get("real_v") or 0)},
            evidence=self._practical_evidence(user_id, sp),
            skill_graph=(get_skill_graph().subgraph(sp, depth=1) if skill else {}),
        )

    # ---------- 对话 ----------

    def snapshot(self, user_id: str, sp: str) -> dict:
        ctx = self.build_context(user_id, sp)
        ab = ctx.ability
        assets = self._store.assets(user_id, sp)
        bridge = get_bridge(sp)
        return {
            "skill_point_id": sp, "name": ctx.name,
            "kind": "bridge" if bridge is not None else "skill",
            "bridge": ({"code": bridge.code, "country": bridge.country, "language": bridge.language,
                        "summary": bridge.summary} if bridge is not None else None),
            "mastery": {"teach": round(ab["teach"], 1), "real": round(ab["real_v"], 1),
                        "level": mastery_of(ab["teach"]).value},
            "messages": [{"role": m["role"], "content": m["content"],
                          "evidence": json.loads(m["evidence"] or "[]"), "created_at": m["created_at"],
                          "kind": (m["kind"] or "text") if "kind" in m.keys() else "text",
                          "payload": (m["payload"] or "") if "payload" in m.keys() else ""}
                         for m in ctx.history],
            "assets": [{"asset_id": a["asset_id"], "type": a["type"], "title": a["title"],
                        "content": a["content"], "evidence": json.loads(a["evidence"] or "[]"),
                        "created_at": a["created_at"]} for a in assets],
            "quiz": ctx.quiz,
        }

    def _plan(self, message: str) -> list[str]:
        try:
            data = self._require_llm().chat_json(
                [{"role": "system", "content": ROUTER_SYSTEM},
                 {"role": "user", "content": f"学员这句话：{message[:200]}"}],
                temperature=0.1, max_tokens=80)
            agents = list(data.get("agents") or [])
        except Exception:
            agents = []
        plan = [a for a in agents if a in ("retrieval", "profile")]
        if "retrieval" not in plan:
            plan.insert(0, "retrieval")
        return plan

    def _profile_advice(self, user_id: str, sp: str, ctx: ThreadContext) -> str:
        ab = ctx.ability
        brief = (f"当前技能点 {sp}（{ctx.name}）：教学 {ab.get('teach', 0):.0f}，实战 {ab.get('real_v', 0):.0f}；"
                 f"答题 {ctx.quiz.get('count', 0)} 题、正确 {ctx.quiz.get('correct', 0)} 题。")
        try:
            return self._require_llm().chat(
                [{"role": "system", "content": PROFILE_SYSTEM},
                 {"role": "user", "content": brief}],
                temperature=0.4, max_tokens=120).strip()
        except Exception:
            return ""

    # ---------- 统一入口：一条消息决定走哪条流水线 ----------

    # 学员点「讲义 / 实操指南 / 学习报告 / 错题本」时，输入框里发出来的就是这类说法
    ASSET_HINTS: tuple[tuple[str, str], ...] = (
        ("错题本", "wrong_book"), ("学习报告", "report"),
        ("实操指南", "guide"), ("讲义", "lecture"),
    )
    QUIZ_HINTS: tuple[str, ...] = ("出题", "做题", "练一题", "考考我", "出一道", "测试我")

    @classmethod
    def route_intent(cls, message: str) -> tuple[str, str]:
        """把学员这句话归到 生成资源 / 出题 / 普通问答 三类。"""
        text = (message or "").strip()
        for word, kind in cls.ASSET_HINTS:
            if word in text:
                return "asset", kind
        if any(h in text for h in cls.QUIZ_HINTS):
            return "quiz", ""
        return "chat", ""

    def chat(self, user_id: str, sp: str, message: str) -> dict:
        """教学界面的唯一入口：讲解、问答、做题、生成讲义都从这一句话进来。

        这样前端按钮只负责「把话填进输入框」，发送之后的分流由服务端决定，
        学员手打同样的句子也会走同一条流水线。
        """
        kind, arg = self.route_intent(message)
        if kind in ("asset", "quiz"):
            thread = self._store.get_or_create_thread(user_id, sp)
            self._store.add_message(thread["thread_id"], "user", message)

        if kind == "asset":
            asset = self.generate_asset(user_id, sp, arg)
            content = (f"已经按你的要求生成 **{asset['title']}**，放在右侧「个性资源栏」里，随时点开看。"
                       f"\n\n---\n\n{asset.get('content', '')}")
            evidence = asset.get("evidence") or []
            self._store.add_message(thread["thread_id"], "ai", content, evidence)
            self._store.touch_thread(thread["thread_id"])
            return {"kind": "asset", "content": content, "asset": asset, "evidence": evidence,
                    "pipeline": asset.get("pipeline") or []}

        if kind == "quiz":
            q = self.pick_question(user_id, sp)
            content = (f"按你现在的掌握度出了一道 **{q.get('difficulty', 'L1')}** 难度的题，"
                       f"见下方题目卡，做完点「交卷」。")
            evidence = [f"bridge:{sp}" if get_bridge(sp) else f"rubric:{sp}", "出题：Rubric + 掌握度判档"]
            # 题目存成 kind=quiz 的结构化消息：聊天记录里每道题各占一张卡，不会被下一题顶掉
            self._store.add_message(thread["thread_id"], "ai", content, evidence,
                                    kind="quiz", payload=json.dumps(q, ensure_ascii=False))
            self._store.touch_thread(thread["thread_id"])
            return {"kind": "quiz", "content": content, "quiz": q, "evidence": evidence,
                    "pipeline": q.get("pipeline") or []}

        out = self.reply(user_id, sp, message)
        out["kind"] = "chat"
        return out

    def _teacher_reply(self, user_id: str, sp: str, message: str,
                       ctx: ThreadContext, profile_advice: str = "") -> dict:
        """主讲 Agent 的唯一输出口：汇总黑板，生成一次带来源的回答。"""
        thread = self._store.get_or_create_thread(user_id, sp)
        self._store.add_message(thread["thread_id"], "user", message)

        context_text = ctx.render()
        if profile_advice:
            context_text += f"\n\n【画像顾问建议】{profile_advice}"

        messages = [
            {"role": "system", "content": TEACHER_SYSTEM},
            {"role": "system", "content": "以下是本次回复可用的资料（务必只依据这些）：\n\n" + context_text},
        ]
        for m in ctx.history[-10:]:
            messages.append({"role": "assistant" if m["role"] == "ai" else "user", "content": m["content"]})
        messages.append({"role": "user", "content": message})

        content = self._require_llm().chat(messages, temperature=0.6, max_tokens=1600)
        sources = ctx.sources()
        self._store.add_message(thread["thread_id"], "ai", content, sources)
        self._store.touch_thread(thread["thread_id"])
        return {"content": content, "evidence": sources}

    def reply(self, user_id: str, sp: str, message: str) -> dict:
        """教学线程的统一 Orchestra 入口。"""
        board = Blackboard({"user_id": user_id, "sp": sp, "message": message})
        planner = AgentTask("plan", "teaching.router", "plan", {"message": message})

        def build_plan(router_out, current):
            agents = list((router_out or {}).get("agents") or [])
            tasks = [
                AgentTask("retrieval", "teaching.retrieval", "retrieve",
                          {"sp": sp, "query": message}),
                AgentTask("context", "teaching.context", "assemble",
                          {"user_id": user_id, "sp": sp, "query": message},
                          depends_on=("retrieval",)),
            ]
            if "profile" in agents:
                tasks.append(AgentTask("profile", "teaching.profile", "advise",
                                       {"user_id": user_id, "sp": sp},
                                       depends_on=("context",), optional=True))
            tasks.append(AgentTask("teacher", "teaching.teacher", "respond",
                                   {"user_id": user_id, "sp": sp, "message": message},
                                   depends_on=("context",)))
            return Plan("teaching.reply", "teaching", tuple(tasks))

        result = self._conductor.run_dynamic(planner, build_plan, board)
        if not result.ok:
            raise RuntimeError(result.error or "教学 Orchestra 执行失败")
        teacher = result.outputs.get("teacher") or {}
        profile = (result.outputs.get("profile") or {}).get("advice") or ""
        plan_agents = list((result.outputs.get("plan") or {}).get("agents") or [])
        pipeline = [dict(AGENT_META[a]) for a in plan_agents if a in AGENT_META]
        pipeline.append(dict(AGENT_META["teacher"]))
        return {
            "content": teacher.get("content", ""),
            "evidence": teacher.get("evidence", []),
            "pipeline": pipeline,
            "profile_advice": profile,
            "orchestra": {"run_id": result.run_id, "trace": result.trace_dicts()},
        }

    # ---------- 资产 ----------

    def generate_asset(self, user_id: str, sp: str, kind: str) -> dict:
        if kind not in ASSET_TYPES:
            raise ValueError(f"未知资产类型: {kind}")
        ctx = self.build_context(user_id, sp, query=f"生成{ASSET_TYPES[kind]}")
        thread = self._store.get_or_create_thread(user_id, sp)
        ask = f"请为技能点「{ctx.name}（{sp}）」生成一份「{ASSET_TYPES[kind]}」。"
        if kind == "report":
            ask += f"\n结合：答题情况 {ctx.quiz}；掌握度 教学{ctx.ability['teach']:.0f}/实战{ctx.ability['real_v']:.0f}；实战证据 {ctx.evidence}。"

        reviewer = SixHatsReview(self._require_llm())
        verifier = get_verifier()
        content = ""
        review: dict = {}
        evidence_audit: dict = {}
        regenerated = False
        attempts = 0

        # 先审查、后核验；任一门失败都只触发一次带具体原因的返工。
        # 关键点是：evidence_audit 必须针对最终 content，而不是第一稿。
        for attempt in range(2):
            attempts = attempt + 1
            prompt = ask
            if attempt:
                reasons: list[str] = []
                if review.get("critical_fail"):
                    reasons.append("六帽审查的硬门槛未通过")
                if evidence_audit.get("decision") != "allow":
                    reasons.append(f"证据闸门：{evidence_audit.get('reason', '未通过')}")
                prompt += ("\n（上一版未通过：" + "；".join(reasons) +
                           "。请只修正失败项，保留已核验内容，重新输出完整材料。）")
            content = self._require_llm().chat(
                [{"role": "system", "content": ASSET_SYSTEM},
                 {"role": "system", "content": "资料依据：\n\n" + ctx.render()},
                 {"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=2600)
            review = reviewer.review(content, ctx.render())
            registry = OfficialSourceRegistry(self._store)
            evidence_audit = verifier.audit(
                content, ctx.evidence_payload(), strict_provenance=True,
                snapshot_resolver=registry.resolve,
            )
            if not review.get("critical_fail") and evidence_audit.get("decision") == "allow":
                break
            regenerated = True

        sources = ctx.sources()
        aid = "asset_" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]
        self._store.add_asset(aid, user_id, thread["thread_id"], sp, kind,
                              ASSET_TYPES[kind], content, sources)
        pipeline = [dict(AGENT_META["retrieval"]), dict(AGENT_META["asset"])]
        if kind == "report":
            pipeline.insert(1, dict(AGENT_META["profile"]))
        pipeline += [{"id": h["id"], "name": h["name"], "icon": HAT_ICON.get(h["id"], "circle")}
                     for h in review.get("hats", [])]
        pipeline.append({"id": "evidence", "name": "Claim 证据闸门", "icon": "shield"})
        safe = (review.get("verdict") == "合格" and evidence_audit.get("decision") == "allow")
        return {"asset_id": aid, "type": kind, "title": ASSET_TYPES[kind], "content": content,
                "evidence": sources, "evidence_audit": evidence_audit,
                "status": "ready" if safe else "needs_review",
                "review": {"verdict": review.get("verdict", "需修改"),
                           "regenerated": regenerated, "attempts": attempts,
                           "hats": review.get("hats", [])},
                "pipeline": pipeline}

    # ---------- 做题 ----------

    def judge_mastery(self, user_id: str, sp: str) -> dict:
        ctx = self.build_context(user_id, sp)
        data = self._require_llm().chat_json(
            [{"role": "system", "content": JUDGE_SYSTEM},
             {"role": "system", "content": "资料：\n\n" + ctx.render()},
             {"role": "user", "content": "请判断学员当前掌握度档位。"}],
            temperature=0.2, max_tokens=300)
        level = str(data.get("level") or "M1")
        try:
            score = float(data.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        return {"level": level, "score": score, "reason": str(data.get("reason", "")),
                "difficulty": _difficulty_of(level),
                "pipeline": [{"id": "judge", "name": "掌握度判档"}]}

    def pick_question(self, user_id: str, sp: str) -> dict:
        j = self.judge_mastery(user_id, sp)
        ctx = self.build_context(user_id, sp)
        q = self._require_llm().chat_json(
            [{"role": "system", "content": QUESTION_SYSTEM},
             {"role": "system", "content": "资料：\n\n" + ctx.render()},
             {"role": "user", "content": f"请出一档难度为 {j['difficulty']} 的题。"}],
            temperature=0.5, max_tokens=900)
        q["difficulty"] = j["difficulty"]
        q["judged_level"] = j["level"]
        q["question_id"] = f"{sp}-{uuid.uuid4().hex}"
        q["pipeline"] = [{"id": "judge", "name": "掌握度判档"}, {"id": "question", "name": "Rubric 出题"}]
        # P0：题目与答案**只存服务端**。这里按 question_id 落库（带 user_id + 技能点归属），
        # 下发前剥离答案；判分时按 question_id 取回这份存档，永不采信客户端传来的题目内容。
        self._store.save_quiz_question(
            q["question_id"], user_id, sp, q,
            answer=str(q.get("answer") or ""), reference=str(q.get("reference") or ""))
        return strip_quiz_answers(q)

    def submit_answer(self, user_id: str, sp: str, question: dict, answer: str) -> dict:
        """判分**只信服务端**：按 question_id 取回出题时落库的题卡，客户端传的一律忽略。

        拒绝规则：缺 question_id → 400；不存在 → 404；属于别人或别的技能点 → 403。
        客户端传来的 `stem` / `answer` / `reference` / `explain` 都不参与判分，
        所以伪造答案键、篡改题干都无法改变判分结果。
        """
        qid = str((question or {}).get("question_id") or "").strip()
        if not qid:
            raise QuizQuestionMissing()
        row = self._store.quiz_question(qid)
        if not row:
            raise QuizQuestionNotFound()
        if (row.get("user_id") or "") != user_id or (row.get("skill_point_id") or "") != sp:
            raise QuizQuestionForbidden()
        try:
            stored = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            stored = {}
        if not isinstance(stored, dict) or not stored:
            # 存档坏了也不能「回退到信客户端」，直接拒绝
            raise QuizQuestionNotFound("题目存档损坏，请重新出题")

        # **幂等闸门（选择「拒绝重复提交」而不是幂等回放）**：
        # 用单条带 WHERE 的 UPDATE 原子抢占；抢占失败＝这题已经交过卷。
        # 为什么选 409 而不是幂等回放首次结果：
        #   1) 回放需要在库里额外落一份完整判分结果（含讲解/难度/趋势），才可能与首次逐字一致；
        #      否则「幂等」只是部分幂等，反而更难验证；
        #   2) 409 语义明确：前端可以提示「这题已经交过，请出新题」，不会让用户误以为又被计分；
        #   3) 关键不变量（不重复 add_attempt / set_ability / memory）在两种方案下完全相同。
        # 无论选哪种，抢占失败后都**不得**再写 attempts、ability、memory —— 这样趋势与掌握度不会被打脏。
        if not self._store.claim_quiz_question(qid):
            first = "答对" if int(row.get("correct") or 0) == 1 else "答错"
            raise QuizQuestionAnswered(
                f"这道题已经交过了（首次判分：{first}）：同题只计分一次，请重新出题")

        try:
            correct = False
            explain = str(stored.get("explain") or row.get("reference") or stored.get("reference") or "")
            if str(stored.get("type") or "") == "choice":
                # 学员的选项来自请求体（这是他的作答）；**正确答案只来自服务端存档**
                correct = (str(answer).strip().upper()[:1]
                           == str(stored.get("answer") or row.get("answer") or "").strip().upper()[:1])
            else:
                res = self._require_llm().chat_json(
                    [{"role": "system", "content": "你是实战评判老师。判断学员的简答是否达标，并给出针对性的讲解（错了讲清为什么、该怎么改）。输出 JSON：{\"correct\":true,\"reason\":\"\"}"},
                     {"role": "user", "content": f"题干：{stored.get('stem')}\n参考答案：{stored.get('reference') or row.get('reference')}\n学员答案：{answer}"}],
                    temperature=0.1, max_tokens=320)
                correct = bool(res.get("correct"))
                explain = str(res.get("reason") or explain)
        except Exception:
            # 判分失败要把抢占还回去，否则这题会卡成「已作答但没判分」
            self._store.release_quiz_claim(qid)
            raise
        score = 92.0 if correct else 40.0
        # 落账的题目用**服务端存档**，不用客户端传的 question
        self._store.add_attempt(user_id, sp, qid, stored, answer, correct, score)

        ab = self._store.abilities(user_id).get(sp, {})
        old = float(ab.get("teach") or 0)
        # 答对：掌握度升、难度跟着升；答错：给讲解、掌握度降、难度跟着降
        # 用 BKT 把一次答题作为软证据更新掌握概率；首次作答以 35 分先验启动。
        prior_score = old if old > 0 else 35.0
        diagnosis = observation_update(prior_score, correct,
                                        attempts_after=len(self._store.attempts(user_id, sp)))
        new = float(diagnosis["posterior_score"])
        self._store.set_ability(user_id, sp, teach=new)
        self._store.mark_quiz_answered(qid, correct)
        if not correct:
            self._store.add_memory(user_id, "progress_note", f"{sp} 答错：{str(stored.get('stem'))[:40]}", f"thread:{sp}")
        lvl = mastery_of(new)
        old_lvl = mastery_of(old)
        new_diff = _difficulty_of(lvl.value)
        old_diff = _difficulty_of(old_lvl.value)
        if new_diff != old_diff:
            trend = "up" if int(new_diff[1]) > int(old_diff[1]) else "down"
        else:
            trend = "flat"
        result = {"correct": correct, "score": score, "explain": explain,
                  "teach": new, "level": lvl.value,
                  "difficulty": new_diff, "prev_difficulty": old_diff,
                  "trend": trend, "diagnosis": diagnosis,
                  "reteach": (not correct),
                  "pipeline": [dict(AGENT_META["answer"]), dict(AGENT_META["profile"]),
                               {"id": "diagnosis", "name": "BKT 学情诊断", "icon": "activity"}]}
        # 答题结果不只是一条记录：编译成学习信号，进入能力复利候选池。
        try:
            signal = compile_learning_signal(
                user_id, sp, correct, score, [f"quiz:{qid}", f"rubric:{sp}"],
                context=str(stored.get("stem") or ""), source="quiz",
                confidence=0.8 if str(stored.get("type")) == "choice" else 0.65)
            result["learning_signal"] = persist_learning_signal(self._store, signal)
        except Exception as exc:  # 反馈写入失败不能吞掉已完成的有效作答
            result["feedback_error"] = f"{type(exc).__name__}: {exc}"
        # 判分结果按 question_id 挂回那张题卡：答过的题留在聊天记录里可回看
        try:
            thread = self._store.get_or_create_thread(user_id, sp)
            payload = {"question_id": qid, "answer": answer,
                       "correct": correct, "explain": explain, "score": score,
                       "teach": new, "level": lvl.value, "difficulty": new_diff,
                       "prev_difficulty": old_diff, "trend": trend, "reteach": (not correct)}
            self._store.add_message(
                thread["thread_id"], "ai",
                f"{'答对' if correct else '答错'} · 掌握度 {new:.0f} · 难度 {new_diff}",
                [f"quiz:{qid}"],
                kind="quiz_result", payload=json.dumps(payload, ensure_ascii=False))
            self._store.touch_thread(thread["thread_id"])
        except Exception:
            pass
        return result