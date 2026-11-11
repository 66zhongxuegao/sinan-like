"""画像 Agent —— 初始画像测评与动态学情画像刷新（D-066）。

三层判断的分工（对齐 D-003 / D-008）：
- 确定性层：题目 → 维度基线分（硬编码权重，可复算、可追溯）；模型不参与算术。
- 生成层：定性描述 / 维度点评 / 学习建议（LLM）；无模型时回退模板，离线也能演示。
- 落库层：教学掌握度写 ability.teach；报告写 memory(type=profile_report)。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from tripcraft.contracts.enums import DIMENSION_NAMES, Dimension

from .base import BaseAgent

# ---------------- 题库（12 题覆盖 8 维） ----------------
# 选项的 level(0–4) 只留在后端：前端只拿到 key 与文案，避免"挑高分选项"。

QUIZ: list[dict[str, Any]] = [
    {"id": "Q1", "dim": "C1", "title": "和刚提交需求的陌生客户通电话，你通常怎么开场？",
     "options": [
         {"key": "a", "label": "自报公司、姓名、定制师身份，确认称呼与是否方便，并约定下次联系时间", "level": 4},
         {"key": "b", "label": "自报公司姓名，然后直接问出行需求", "level": 3},
         {"key": "c", "label": "先问对方需求，身份有空再补", "level": 1},
         {"key": "d", "label": "基本没打过，客户问什么我答什么", "level": 0},
     ]},
    {"id": "Q2", "dim": "C1", "title": "客户语气很冲、上来就抱怨方案太贵，你第一反应是？",
     "options": [
         {"key": "a", "label": "先接住情绪、把对方的顾虑复述一遍，再谈方案怎么调", "level": 4},
         {"key": "b", "label": "先安抚两句，然后解释为什么是这个价", "level": 3},
         {"key": "c", "label": "直接说可以打折或者换便宜酒店", "level": 1},
         {"key": "d", "label": "不知道说什么，容易跟着慌", "level": 0},
     ]},
    {"id": "Q3", "dim": "C2", "title": "客户说「预算别太贵、住得好一点」。你怎么接？",
     "options": [
         {"key": "a", "label": "追问人均预算区间、出行人数、日期、住宿档次口径，再复述确认", "level": 4},
         {"key": "b", "label": "问一下人数和大概预算，然后先出一版方案", "level": 3},
         {"key": "c", "label": "按经验先报价，不合适再改", "level": 1},
         {"key": "d", "label": "这类模糊需求经常谈不下去", "level": 0},
     ]},
    {"id": "Q4", "dim": "C2", "title": "需求谈完一轮，你通常怎么收口？",
     "options": [
         {"key": "a", "label": "整理成必须满足 / 希望满足 / 可替代 / 明确不要，发给客户确认", "level": 4},
         {"key": "b", "label": "口头总结一遍，记在备忘录里", "level": 3},
         {"key": "c", "label": "直接进入做方案", "level": 1},
         {"key": "d", "label": "没有固定动作", "level": 0},
     ]},
    {"id": "Q5", "dim": "C3", "title": "做一份 5 天行程，你最先确定什么？",
     "options": [
         {"key": "a", "label": "先排城市顺序与每天交通耗时，再看景点和住宿落位", "level": 4},
         {"key": "b", "label": "先把想去的景点列出来，再串成线路", "level": 3},
         {"key": "c", "label": "参考同行现成线路改一下", "level": 1},
         {"key": "d", "label": "没独立做过完整行程", "level": 0},
     ]},
    {"id": "Q6", "dim": "C3", "title": "行程里出现「一天跑三个相距很远的景点」，你会怎么处理？",
     "options": [
         {"key": "a", "label": "算实际车程，减点或换点位，把节奏和餐食一起重排", "level": 4},
         {"key": "b", "label": "提醒客户当天会比较赶，让客户自己决定", "level": 3},
         {"key": "c", "label": "客户想去就排上，到了再说", "level": 1},
         {"key": "d", "label": "没遇到过这类判断", "level": 0},
     ]},
    {"id": "Q7", "dim": "C4", "title": "报价前，酒店、车、票、导游这些资源你会怎么处理？",
     "options": [
         {"key": "a", "label": "逐项问清房态、车况、票务档期，确认过再写进报价", "level": 4},
         {"key": "b", "label": "先按常规价报，客户确认后再去订", "level": 3},
         {"key": "c", "label": "凭经验估个价，能订到就行", "level": 1},
         {"key": "d", "label": "没直接对接过资源方", "level": 0},
     ]},
    {"id": "Q8", "dim": "C5", "title": "客户问「这个价包含什么、你们的利润有多少」，你怎么答？",
     "options": [
         {"key": "a", "label": "分项列清导游、用车、住宿、餐饮、门票、保险、服务费，说明口径与浮动空间", "level": 4},
         {"key": "b", "label": "给一个总价，说明包含的主要项目", "level": 3},
         {"key": "c", "label": "报个总价，客户砍价再谈", "level": 1},
         {"key": "d", "label": "报价这块主要靠同事帮忙", "level": 0},
     ]},
    {"id": "Q9", "dim": "C5", "title": "一单做完，你一般怎么确认这单赚了多少？",
     "options": [
         {"key": "a", "label": "拿地接结算单和报价逐项核对，算清实际成本、毛利与损失", "level": 4},
         {"key": "b", "label": "看收款减付款，估个大概", "level": 3},
         {"key": "c", "label": "公司统一算，我不太看", "level": 1},
         {"key": "d", "label": "没算过", "level": 0},
     ]},
    {"id": "Q10", "dim": "C6", "title": "出发前一天车队说车坏了，你的处理顺序是？",
     "options": [
         {"key": "a", "label": "先给客户替代方案并安抚，同时压车队当日内换车，再回头改对接单", "level": 4},
         {"key": "b", "label": "先找车队确认能不能换车，确定了再告诉客户", "level": 3},
         {"key": "c", "label": "先把情况告诉客户，等车队消息", "level": 1},
         {"key": "d", "label": "没独立处理过突发", "level": 0},
     ]},
    {"id": "Q11", "dim": "C7", "title": "给客户报方案前，合规上你会先确认哪些？",
     "options": [
         {"key": "a", "label": "保险是否必买、合同与定金节点、目的地是否可接、承诺口径是否越界", "level": 4},
         {"key": "b", "label": "记得提醒客户买保险，其他按公司流程走", "level": 3},
         {"key": "c", "label": "客户没问就不主动提", "level": 1},
         {"key": "d", "label": "这些通常由公司后台把关", "level": 0},
     ]},
    {"id": "Q12", "dim": "C8", "title": "接到一位沙特的客户，除了行程你还会额外确认什么？",
     "options": [
         {"key": "a", "label": "签证免签与证件有效期、宗教饮食禁忌、礼仪隐私习惯、结算币种与汇率口径", "level": 4},
         {"key": "b", "label": "确认签证和有没有忌口", "level": 3},
         {"key": "c", "label": "和接待国内客户差不多，主要看预算", "level": 1},
         {"key": "d", "label": "没接过境外客源", "level": 0},
     ]},
]

DIM_ORDER: list[str] = [d.value for d in Dimension]
FLOOR, CEIL = 20.0, 95.0
EMPTY_DIM_SCORE = 45.0


def questions_public() -> list[dict]:
    """给前端的题面：去掉 level。"""
    return [{"id": q["id"], "dim": q["dim"], "dim_name": DIMENSION_NAMES[Dimension(q["dim"])],
             "title": q["title"],
             "options": [{"key": o["key"], "label": o["label"]} for o in q["options"]]}
            for q in QUIZ]


def answer_digest(answers: list[dict]) -> list[dict]:
    """题目 + 所选文案（给模型看，也留作证据）。"""
    qm = {q["id"]: q for q in QUIZ}
    out = []
    for a in answers or []:
        q = qm.get(str(a.get("qid", "")))
        if not q:
            continue
        opt = next((o for o in q["options"] if o["key"] == str(a.get("key", ""))), None)
        if not opt:
            continue
        out.append({"id": q["id"], "dim": q["dim"], "question": q["title"],
                    "answer": opt["label"], "level": int(opt["level"])})
    return out


def score_answers(answers: list[dict]) -> dict[str, float]:
    """维度 → 教学掌握度基线（0–100）。纯算术，可复算。"""
    buckets: dict[str, list[int]] = {}
    for d in answer_digest(answers):
        buckets.setdefault(d["dim"], []).append(d["level"])
    out: dict[str, float] = {}
    for dim in DIM_ORDER:
        levels = buckets.get(dim) or []
        raw = 100.0 * (sum(levels) / len(levels)) / 4.0 if levels else EMPTY_DIM_SCORE
        out[dim] = round(min(CEIL, max(FLOOR, raw)), 1)
    return out


def dim_scores_from_abilities(abilities: dict[str, dict], skill_points) -> dict[str, dict]:
    """从 ability 表实算每维教学/实战均分（刷新画像用）。"""
    out: dict[str, dict] = {}
    for d in Dimension:
        pts = [sp for sp in skill_points if sp.dimension is d]
        if not pts:
            continue
        t = [float((abilities.get(sp.id) or {}).get("teach") or 0) for sp in pts]
        r = [float((abilities.get(sp.id) or {}).get("real_v") or 0) for sp in pts]
        out[d.value] = {"name": DIMENSION_NAMES[d],
                        "teach": round(sum(t) / len(t), 1), "real": round(sum(r) / len(r), 1)}
    return out


def _weakest_point(skill_points, dim: str, abilities: dict[str, dict]) -> dict:
    pts = [sp for sp in skill_points if sp.dimension.value == dim]
    if not pts:
        return {"id": "", "name": ""}
    scored = sorted(pts, key=lambda sp: float((abilities.get(sp.id) or {}).get("teach") or 0))
    return {"id": scored[0].id, "name": scored[0].name}


def extract_json(raw: str) -> dict | None:
    """容错解析：模型偶尔会带 ```json 围栏，或前后多写一句话。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    candidates = [s]
    if "{" in s and "}" in s:
        candidates.append(s[s.find("{"):s.rfind("}") + 1])
    for c in candidates:
        if not c:
            continue
        try:
            data = json.loads(c)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def dim_comments(raw) -> dict[str, str]:
    """兼容两种写法：数组 [{"dim":"C1","comment":...}] 与对象 {"C1": "..."}。

    模型有时把整句点评写进 key（"C1 沟通信任：教学 75 vs 实战 0，……"），
    这里也顺手拆出来，避免整份报告退化成模板。
    """
    out: dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            dim = str(item.get("dim", "")).strip().upper()[:2]
            c = str(item.get("comment") or item.get("text") or item.get("value") or "").strip()
            if dim in DIM_ORDER and c:
                out[dim] = c
    elif isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k).strip()
            dim = key.upper()[:2]
            if dim not in DIM_ORDER:
                continue
            c = v.strip() if isinstance(v, str) else ""
            if not c:                                   # 整句写在 key 里
                for sep in ("：", ":"):
                    if sep in key:
                        c = key.split(sep, 1)[1].strip()
                        break
                else:
                    c = key[2:].strip(" ：:-—")
            if c:
                out[dim] = c
    return out


BAND_TEXT = (
    (40, "刚入门：基本动作还没成形，需要从知识点补起。"),
    (60, "能做但不稳：常规场景走得完，遇到追问或变化容易露怯。"),
    (80, "熟练：大部分场景能独立完成，压力场景和细节还要磨。"),
    (101, "好手：动作稳定，可以开始接更难的客人。"),
)


def band_comment(score: float) -> str:
    """按档位给一句定性描述 —— 刻意不写分数，分数交给界面上的图表。"""
    for upper, text in BAND_TEXT:
        if score < upper:
            return text
    return BAND_TEXT[-1][1]


def suggestion(dim: str, title, why, how, scores: dict[str, float], skill_points,
               abilities: dict[str, dict]) -> dict:
    """统一装配一条学习建议：技能点由后端按该维最弱项挂上，不交给模型编。"""
    point = _weakest_point(skill_points, dim, abilities)
    name = DIMENSION_NAMES[Dimension(dim)]
    return {"dim": dim, "dim_name": name,
            "skill_point_id": point["id"], "skill_point_name": point["name"],
            "title": (str(title).strip()[:40] or f"先补 {name}"),
            "why": (str(why).strip()[:200] or f"{name}在八个维度里排名靠后，是当前最拖后腿的一项。"),
            "how": (str(how).strip()[:200] or
                    f"先去学习地图练 {point['id'] or name} 对应的知识点，再进实战验证。")}


ASSESS_SYSTEM = """你是入境游定制师训练系统的「画像 Agent」。学员刚做完一轮初始画像测评，你要给出**初始学情画像**。

【你能用的证据】
- 只用学员在测评里的**实际选择**和下面给定的**维度基线分**。
- 维度基线分是系统按硬编码权重算出来的，**不要改动、不要重算**，你的任务是解读它。

【怎么写】
1. summary：2–4 句定性描述。写清这个人的经验底色（做过什么、没做过什么）、当前最明显的一个长板和一到两个短板。语气像带教老师给建议，不夸张、不客套。
2. dimensions：**数组**，8 项齐全，每项 {"dim": "C1", "comment": "..."}。comment 一句话说清"现在在哪一档、卡在哪"。20–40 分是入门，40–60 是能做但不稳，60–80 是熟练，80 以上是好手。
3. strengths：1–3 条，直接写长板，不要写套话。
4. suggestions：3–5 条学习建议。每条给出 dim（只能填 C1–C8 之一）、title（一句标题）、why（为什么先练这个，引用学员的选择或分数）、how（具体怎么练，指向真实动作，例如"先在地图里练 C2.1 的需求结构化确认，再进首呼实战"）。
5. focus：优先补的 2–3 个维度代码。

【硬约束】
- 不编造学员没说过的经历、公司、年限。
- **正文里不要出现任何分数、百分比、档位代号（M1–M5）**：掌握程度一律用文字说（"刚入门""能独立完成但不够稳""相当熟练"），分数交给界面上的图表。
- 不写"你很棒""继续努力"这类空话。
- dimensions 的 dim 字段只能是 C1–C8 这 8 个代码，**不要把点评写进 dim 字段**。
- 只输出 JSON，不要解释、不要 Markdown 代码块。

JSON 结构（照抄字段名与嵌套）：
{"summary": "……", "dimensions": [{"dim": "C1", "comment": "……"}, {"dim": "C2", "comment": "……"}, {"dim": "C3", "comment": "……"}, {"dim": "C4", "comment": "……"}, {"dim": "C5", "comment": "……"}, {"dim": "C6", "comment": "……"}, {"dim": "C7", "comment": "……"}, {"dim": "C8", "comment": "……"}], "strengths": ["……"], "suggestions": [{"dim": "C3", "title": "……", "why": "……", "how": "……"}], "focus": ["C3", "C5"]}
"""

REFRESH_SYSTEM = """你是入境游定制师训练系统的「画像 Agent」。学员已有画像数据，你要**刷新动态学情画像**。

【你能用的证据】
- 各维度的教学掌握度与实战掌握度（都是系统实算，不要改动）
- 最近的实战订单评分、答题记录、以及之前的画像记忆
- 说明「教学涨了但实战没跟上」「实战暴露了教学没覆盖的点」这类**差值**，这是本次刷新最有价值的部分。

【怎么写】
1. summary：2–4 句。先给结论（当前水平、变化方向），再说教学与实战的落差说明什么。
2. dimensions：**数组**，8 项齐全，每项 {"dim": "C1", "comment": "..."}，重点写教学与实战的**落差**意味着什么（用文字，例如"练过但没在订单里用过"）。
3. strengths：1–3 条。
4. suggestions：3–5 条，每条给 dim（C1–C8）、title、why（可以引用订单里的具体表现，但不要写分数）、how（可执行动作）。
5. focus：优先补的 2–3 个维度代码。

【硬约束】
- dimensions 的 dim 字段只能是 C1–C8 这 8 个代码，不要把点评写进 dim 字段。
- **正文里不要出现任何分数、百分比或档位代号**：教学与实战的高低用文字说（"教学走在前头、实战还没跟上"）。
只输出 JSON，不要解释、不要 Markdown 代码块。结构同前：
{"summary": "……", "dimensions": [{"dim": "C1", "comment": "……"}, …8 项…], "strengths": ["……"], "suggestions": [{"dim": "C1", "title": "……", "why": "……", "how": "……"}], "focus": ["C1"]}
"""


class ProfileAgent(BaseAgent):
    name = "profile"

    # ---------- 初始画像 ----------
    def assess(self, answers: list[dict], scores: dict[str, float], skill_points,
               language: str = "中文") -> dict:
        digest = answer_digest(answers)
        lines = [f"- [{d['dim']}] {d['question']}\n  学员选择：{d['answer']}" for d in digest] or ["（未作答）"]
        score_lines = [f"- {dim} {DIMENSION_NAMES[Dimension(dim)]}：{scores[dim]}" for dim in DIM_ORDER]
        prompt = ("【学员的测评选择】\n" + "\n".join(lines) +
                  "\n\n【系统算出的维度基线分】\n" + "\n".join(score_lines) +
                  f"\n\n【训练语言】{language}\n请输出初始学情画像 JSON。")
        data = self._ask(ASSESS_SYSTEM, prompt)
        report = self._normalize(data, scores, kind="initial", skill_points=skill_points)
        report["answers"] = digest
        return report

    # ---------- 刷新画像 ----------
    def refresh(self, dims: dict[str, dict], skill_points, abilities: dict[str, dict],
                orders: list[dict] | None = None, attempts: list[dict] | None = None,
                previous: dict | None = None, language: str = "中文") -> dict:
        scores = {d: float(v.get("teach") or 0) for d, v in dims.items()}
        dim_lines = [f"- {d} {v['name']}：教学 {v['teach']} / 实战 {v['real']}"
                     for d, v in dims.items()]
        order_lines = []
        for o in (orders or [])[:8]:
            order_lines.append(f"- {o.get('order_id', '')} {o.get('destination', '')} "
                               f"{o.get('level', '')} {o.get('score', '')} {o.get('comment', '')}".strip())
        attempt_lines = [f"- {a.get('skill_point_id', '')} {'答对' if a.get('correct') else '答错'}："
                         f"{(a.get('question') or '')[:60]}" for a in (attempts or [])[-8:]]
        prev = (previous or {}).get("summary", "")
        prompt = ("【各维度掌握度】\n" + ("\n".join(dim_lines) or "（暂无）") +
                  "\n\n【最近的实战评分】\n" + ("\n".join(order_lines) or "（暂无）") +
                  "\n\n【最近的答题记录】\n" + ("\n".join(attempt_lines) or "（暂无）") +
                  (f"\n\n【上一次的画像描述】\n{prev}" if prev else "") +
                  f"\n\n【训练语言】{language}\n请输出刷新后的学情画像 JSON。")
        data = self._ask(REFRESH_SYSTEM, prompt)
        return self._normalize(data, scores, kind="refresh", skill_points=skill_points,
                               abilities=abilities, dims=dims)

    # ---------- 内部 ----------
    def _ask(self, system: str, prompt: str) -> dict | None:
        if self._llm is None:
            return None
        try:
            raw = self._llm.chat([{"role": "system", "content": system},
                                  {"role": "user", "content": prompt}],
                                 temperature=0.3, max_tokens=1800, json_mode=True)
            return extract_json(raw)
        except Exception:
            return None

    def _normalize(self, data: dict | None, scores: dict[str, float], kind: str, skill_points,
                   abilities: dict[str, dict] | None = None, dims: dict[str, dict] | None = None) -> dict:
        data = data or {}
        abilities = abilities or {}
        if not str(data.get("summary") or "").strip():
            return self._fallback(scores, kind, skill_points, abilities, dims)

        comments = dim_comments(data.get("dimensions"))
        dims_out: dict[str, str] = {}
        for dim in DIM_ORDER:
            dims_out[dim] = (comments.get(dim) or band_comment(scores.get(dim, 0)))[:220]

        sug: list[dict] = []
        for s in (data.get("suggestions") or []):
            if not isinstance(s, dict):
                continue
            dim = str(s.get("dim", "")).strip().upper()[:2]
            if dim not in DIM_ORDER or any(x["dim"] == dim for x in sug):
                continue
            sug.append(suggestion(dim, s.get("title", ""), s.get("why", ""), s.get("how", ""),
                                  scores, skill_points, abilities))

        ranked = sorted(DIM_ORDER, key=lambda d: scores.get(d, 0))
        for dim in ranked:                      # 模型给的条数不够时用确定性建议补齐
            if len(sug) >= 3:
                break
            if any(x["dim"] == dim for x in sug):
                continue
            sug.append(suggestion(dim, "", "", "", scores, skill_points, abilities))

        focus: list[str] = []
        for f in (data.get("focus") or []):
            code = str(f).strip().upper()[:2]
            if code in DIM_ORDER and code not in focus:
                focus.append(code)
        return {
            "kind": kind,
            "summary": str(data.get("summary")).strip()[:600],
            "dimensions": dims_out,
            "strengths": [str(x).strip()[:90] for x in (data.get("strengths") or []) if str(x).strip()][:3],
            "suggestions": sug[:5],
            "focus": (focus or ranked)[:3],
            "scores": scores,
            "dim_meta": dims or {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _fallback(self, scores: dict[str, float], kind: str, skill_points,
                  abilities: dict[str, dict], dims: dict[str, dict] | None = None) -> dict:
        ranked = sorted(DIM_ORDER, key=lambda d: scores.get(d, 0))
        worst, best = ranked[:3], ranked[-1]
        name = lambda d: DIMENSION_NAMES[Dimension(d)]
        if kind == "initial":
            summary = (f"初始画像：经验底色集中在 {name(best)}，"
                       f"需要优先补的是 {name(worst[0])} 与 {name(worst[1])}。"
                       "这份判断来自测评选择，后续会随着学习和实战不断修正。")
        else:
            t = sum((dims or {}).get(d, {}).get("teach", 0) for d in DIM_ORDER) / len(DIM_ORDER)
            r = sum((dims or {}).get(d, {}).get("real", 0) for d in DIM_ORDER) / len(DIM_ORDER)
            gap = t - r
            summary = ("本次刷新："
                       + ("教学明显走在前头，说明知识进来了，但还没在订单里用出来。"
                          if gap > 5 else "教学与实战大致同步，能力已经能落到订单上。")
                       + f"当前长板是 {name(best)}，最该补的是 {name(worst[0])} 与 {name(worst[1])}。")
        dims_out = {d: band_comment(scores.get(d, 0)) for d in DIM_ORDER}
        sug = [suggestion(d, "", "", "", scores, skill_points, abilities) for d in worst]
        return {"kind": kind, "summary": summary, "dimensions": dims_out,
                "strengths": [f"{name(best)}是当前长板。"], "suggestions": sug,
                "focus": worst, "scores": scores, "dim_meta": dims or {},
                "created_at": datetime.now().isoformat(timespec="seconds")}
