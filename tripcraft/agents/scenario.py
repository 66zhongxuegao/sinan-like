"""派单生成 Agent —— 按学习画像生成入境游客与需求单（PRD 2.2 派单 / 20 章难度 / 21.1 DI-01）。

**关键：不是随机出题，而是由画像反推。**
输入是 `learner_brief.LearnerBrief`（画像 → 目标技能点 + 各压力旋钮档位），输出是：

    ┌ 游客人设 ─ 客源国 / 语言 / 证件 / 情绪强度
    ├ 派单残缺度 ─ 由 C2 掌握度决定给几项、缺几项
    ├ 时限压力 ── 由 C7/C2 掌握度决定首呼时限（补救放宽、熟练收紧）
    └ 预置冲突 ── 由 C4/C6 掌握度决定本单准备安排几起突发

同一份画像必然得到同一类派单；画像变了，派单的客源复杂度、残缺度、时限都会跟着变。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from typing import TYPE_CHECKING

from .base import BaseAgent
from .llm import DeepSeekClient
from ..contracts.entry_documents import FOREIGN_DOCUMENTS, HK_MACAO_DOCUMENT, TAIWAN_DOCUMENT

if TYPE_CHECKING:   # 只用于类型标注：避免与 services 循环导入
    from ..services.learner_brief import LearnerBrief

# 客源地 -> (语言, 常用入境证件, 复杂度档)
SOURCE_MARKETS: dict[str, tuple[str, str, int]] = {
    # 0–1 档：中文客源，沟通门槛最低（补救分支用）
    "香港": ("中文", HK_MACAO_DOCUMENT, 0),
    "澳门": ("中文", HK_MACAO_DOCUMENT, 0),
    "台湾": ("中文", TAIWAN_DOCUMENT, 0),
    "新加坡": ("中文", FOREIGN_DOCUMENTS, 1),
    "马来西亚": ("中文", FOREIGN_DOCUMENTS, 1),
    # 2 档：近程外语客源
    "日本": ("日本語", FOREIGN_DOCUMENTS, 2),
    "韩国": ("한국어", FOREIGN_DOCUMENTS, 2),
    "泰国": ("ไทย", FOREIGN_DOCUMENTS, 2),
    "越南": ("Tiếng Việt", FOREIGN_DOCUMENTS, 2),
    "印度尼西亚": ("Bahasa Indonesia", FOREIGN_DOCUMENTS, 2),
    # 3 档：远程英语客源
    "美国": ("English", FOREIGN_DOCUMENTS, 3),
    "英国": ("English", FOREIGN_DOCUMENTS, 3),
    "澳大利亚": ("English", FOREIGN_DOCUMENTS, 3),
    # 4 档：小语种 / 高文化复杂度（宗教、礼仪、支付红线密集）
    "德国": ("Deutsch", FOREIGN_DOCUMENTS, 4),
    "法国": ("Français", FOREIGN_DOCUMENTS, 4),
    "沙特阿拉伯": ("العربية", FOREIGN_DOCUMENTS, 4),
    "印度": ("English", FOREIGN_DOCUMENTS, 4),
    "西班牙": ("Español", FOREIGN_DOCUMENTS, 4),
    "墨西哥": ("Español", FOREIGN_DOCUMENTS, 4),
    "俄罗斯": ("Русский", FOREIGN_DOCUMENTS, 4),
    "意大利": ("Italiano", FOREIGN_DOCUMENTS, 4),
    "巴西": ("Português", FOREIGN_DOCUMENTS, 4),
    "土耳其": ("Türkçe", FOREIGN_DOCUMENTS, 4),
}

# 客源语言（前端"客源语言"下拉用同一份口径；一个语言可能对应多个国家）
LANGUAGES: tuple[str, ...] = tuple(dict.fromkeys(v[0] for v in SOURCE_MARKETS.values()))


def markets_for(language: str = "") -> list[str]:
    """挑客源市场：指定语言就只给说这种语言的；不指定就是全部（随机出各国的）。

    **不再按学员的客源复杂度档过滤**——那是"补救档只剩港澳台"的根因。
    难度仍然通过派单残缺度 / 首呼时限 / 情绪 / 预置事件来体现。
    """
    if language:
        hit = [m for m, v in SOURCE_MARKETS.items() if v[0] == language]
        if hit:
            return hit
    return list(SOURCE_MARKETS)


DESTINATIONS = (
    "云南", "四川", "贵州", "广西", "陕西", "福建", "湖南", "浙江", "江苏",
    "北京", "甘肃", "青海", "内蒙古", "海南", "新疆", "西藏", "山西", "重庆",
)

# 派单里「应该给但经常没给」的字段：给几项由 dispatch_gap 旋钮决定
DISPATCH_FIELDS: tuple[tuple[str, str], ...] = (
    ("party", "出行人构成"),
    ("dates", "出行日期"),
    ("days", "天数"),
    ("budget", "预算口径"),
    ("transport", "交通偏好"),
    ("hotel", "住宿标准"),
    ("special", "特殊需求"),
    ("decision", "决策人"),
)

# 情绪强度 → 客户性格（进客户 Agent 人设）
EMOTION_TRAITS = (
    "说话客气、有耐心，愿意把需求说清楚",
    "说话直接，时间不多，但基本配合",
    "说话较急，会催进度，追问多了会不耐烦",
    "时间很紧，语气偏冲，容易打断你说话",
    "脾气急、预算敏感，一不满意就会质疑你的专业度",
)

# 需求模糊度 → 平台提交的那句意向
VAGUE_INTENT = (
    "想去{dest}玩，{party}，想请你帮忙安排一下行程。",
    "计划去{dest}，{party}，你看着给个方案吧。",
    "{party}想去{dest}，别太赶也别太贵就行。",
    "想去{dest}，{party}，具体玩什么还没想好，你先给点建议。",
    "就想去{dest}转转，{party}，其他都还没定，你安排吧。",
)

# 预算紧度 → 派单里可能给出的预算线索（0 直接给区间，4 只给一句模糊话）
BUDGET_HINTS = (
    "人均预算 6000-8000（客人已在平台填写）",
    "人均 5000 左右",
    "人均 4000-5000",
    "",
    "",
)


@dataclass
class TouristSpec:
    customer: str
    source_market: str
    language: str
    destination: str
    documents: str = ""
    party: str = ""
    dates: str = ""
    days: str = ""
    budget: str = ""
    transport: str = ""
    hotel: str = ""
    special: str = ""
    decision: str = ""
    intent: str = ""
    personality: str = ""
    first_call_limit_min: int = 60
    preset_incidents: tuple[str, ...] = ()
    difficulty_label: str = ""
    rationale: str = ""
    source_complexity: int = 0
    dispatch_gap: int = 0
    # 附加标记（标准案例/演示数据用）：并入 payload，不改动既有字段语义
    extra: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        out = {k: v for k, v in asdict(self).items()
               if k != "extra" and v not in ("", (), None, {})}
        out.update(self.extra or {})
        return out


SYSTEM = """你是携程定制游平台的派单系统，要把一条新需求派给某位定制师。

【这位定制师的情况】
主考技能点：{targets}
整单难度：{difficulty}
画像依据：{rationale}

【你必须按下面的口径生成，不能自行调整难度】
1. **客源地只能从这几地选**：{markets}{lang_hint}
   —— 档位越高，语言与文化复杂度越高；语言与客源地匹配。
   证件类型仅作身份参考，客源地不自动证明国籍、已持有证件或免签资格；不编造签证办理状态。
2. **派单信息只给 {given} 项**，其余留空（""）。可填项：出行人构成 party / 出行日期 dates /
   天数 days / 预算口径 budget / 交通偏好 transport / 住宿标准 hotel / 特殊需求 special / 决策人 decision。
   留空越多，这位定制师越要自己打电话问出来。
3. 客户性格按这个方向写进 personality：{personality}
4. intent 是客户在平台提交的一句话意向，口语、模糊（模糊度 {vagueness}/4），不要写得太全。
5. 目的地从这些里选，且不要与「已有派单」重复客源地+目的地组合：{destinations}
6. customer 用「客户 + 字母」，不要编真实姓名。

【已有派单】
{existing}

【输出 JSON】
{{"customer":"", "source_market":"", "destination":"", "party":"", "dates":"", "days":"",
  "budget":"", "transport":"", "hotel":"", "special":"", "decision":"",
  "intent":"", "personality":""}}
只输出 JSON；`{given}` 之外的字段一律留空字符串。
"""

_LETTERS = "KLMNOPQRSTUVWXYZ"


class DispatchGenerator(BaseAgent):
    name = "dispatch_generator"

    def __init__(self, llm: DeepSeekClient | None = None) -> None:
        if llm is not None:
            super().__init__(llm)
        else:
            self._llm = None

    # ---------- 主入口 ----------

    def generate(self, brief: "LearnerBrief", existing: list[dict] | None = None,
                 seq: int = 0, language: str = "") -> TouristSpec:
        """language 为空=随机出各国；指定了就只出说这种语言的客源。"""
        existing = existing or []
        avoid = {(e.get("source_market"), e.get("destination")) for e in existing}
        used_dest = {e.get("destination") for e in existing}
        spec = None
        if self._llm is not None:
            try:
                spec = self._from_llm(brief, existing, avoid, seq, language)
            except Exception:
                spec = None
        if spec is None:
            spec = self._fallback(brief, avoid, used_dest, seq, language)
        spec.difficulty_label = brief.label
        spec.rationale = brief.rationale
        spec.source_complexity = brief.knobs["source_complexity"]
        spec.dispatch_gap = brief.knobs["dispatch_gap"]
        spec.first_call_limit_min = _first_call_limit(brief.knobs["time_pressure"])
        spec.preset_incidents = _preset_incidents(brief.knobs["resource_conflict"])
        return spec

    # ---------- 模型生成 ----------

    def _from_llm(self, brief: "LearnerBrief", existing: list[dict], avoid: set, seq: int,
                  language: str = ""):
        complexity = brief.knobs["source_complexity"]
        pool = markets_for(language)
        markets = "、".join(f"{k}（{v[0]}，{v[1]}）" for k in pool for v in [SOURCE_MARKETS[k]])
        lang_hint = f"，而且语言必须是 {language}" if language else "（客源国随机，可以是任意语言）"
        given = max(2, len(DISPATCH_FIELDS) - (2 + brief.knobs["dispatch_gap"]))
        lines = [f"- {e.get('source_market', '')} → {e.get('destination', '')}" for e in existing] or ["（暂无）"]

        data = self._llm.chat_json(
            [{"role": "system", "content": SYSTEM.format(
                targets="、".join(f"{i} {n}" for i, n in
                                zip(brief.target_skill_points, brief.target_names)),
                difficulty=brief.label, rationale=brief.rationale,
                complexity=complexity, markets=markets, given=given,
                personality=EMOTION_TRAITS[min(brief.knobs["emotion_intensity"], 4)],
                lang_hint=lang_hint,
                vagueness=min(brief.knobs["demand_vagueness"], 4),
                destinations="、".join(DESTINATIONS), existing="\n".join(lines))},
             {"role": "user", "content": f"生成第 {seq + 1} 条派单。"}],
            temperature=1.0, max_tokens=700)
        if not isinstance(data, dict):
            return None

        market = str(data.get("source_market", "")).strip()
        if market not in SOURCE_MARKETS:
            return None
        if language and SOURCE_MARKETS[market][0] != language:
            return None                      # 模型跑偏了：交给确定性兜底，保证语言筛选一定生效
        dest = str(data.get("destination", "")).strip().rstrip("省市")
        if dest not in DESTINATIONS or (market, dest) in avoid:
            return None

        lang, docs, _ = SOURCE_MARKETS[market]
        # 只保留该给的那几项，其余一律清空（防止模型好心把信息补全，破坏难度）
        hint = BUDGET_HINTS[min(brief.knobs["budget_tightness"], 4)]
        allowed = _allowed_fields(given, hint)
        keep = {k: str(data.get(k) or "").strip() for k in allowed}
        # 模型有时把该给的项也留空 —— 用确定性值补上，保证「说给几项就真给几项」
        fill = _defaults(seq)
        for k in allowed:
            if not keep.get(k) and k in fill:
                keep[k] = fill[k]
        from ..services.customer_card import date_span_days
        span = date_span_days(keep.get("dates", ""))
        declared_days = re.search(r"\d+", keep.get("days", ""))
        if span is not None and declared_days and int(declared_days.group()) != span:
            return None
        name = str(data.get("customer") or "").strip()
        if not name.startswith("客户"):
            name = f"客户 {_LETTERS[seq % len(_LETTERS)]}"
        return TouristSpec(
            customer=name,
            source_market=market, language=lang, destination=dest, documents=docs,
            intent="",
            personality=str(data.get("personality") or ""),
            extra={"customer_answers": {key: str(data.get(key) or "").strip()
                                         for key, _ in DISPATCH_FIELDS if key not in allowed}},
            **keep,
        )

    # ---------- 确定性兜底（无模型也能演示） ----------

    def _fallback(self, brief: "LearnerBrief", avoid: set, used_dest: set, seq: int,
                  language: str = "") -> TouristSpec:
        pool = markets_for(language)
        dests = [d for d in DESTINATIONS if d not in used_dest] or list(DESTINATIONS)
        market, dest = pool[seq % len(pool)], dests[(seq * 3) % len(dests)]
        for i in range(len(pool) * len(dests)):
            if (market, dest) not in avoid:
                break
            dest = dests[(seq * 3 + i + 1) % len(dests)]
        lang, docs, _ = SOURCE_MARKETS[market]

        given = max(2, len(DISPATCH_FIELDS) - (2 + brief.knobs["dispatch_gap"]))
        hint = BUDGET_HINTS[min(brief.knobs["budget_tightness"], 4)]
        allowed = _allowed_fields(given, hint)
        fill = _defaults(seq)
        if hint:
            fill["budget"] = hint
        keep = {k: fill.get(k, "") for k in allowed}

        return TouristSpec(
            customer=f"客户 {_LETTERS[seq % len(_LETTERS)]}",
            source_market=market, language=lang, destination=dest, documents=docs,
            intent="",  # 派单落库后统一从客户事实卡渲染。
            personality=EMOTION_TRAITS[min(brief.knobs["emotion_intensity"], 4)],
            **keep,
        )


def _allowed_fields(given: int, budget_hint: str) -> list[str]:
    """该给哪几项：条数**严格等于 given**。

    预算这条比较特殊——客户不肯说的时候它本身就是一个缺口，
    那就让后面的字段顺位补上，保证不会“说好给 6 项结果只给了 3 项”。
    """
    allowed: list[str] = []
    for key, _ in DISPATCH_FIELDS:
        if len(allowed) >= given:
            break
        if key == "budget" and not budget_hint:
            continue
        allowed.append(key)
    return allowed


def _defaults(seq: int) -> dict:
    """该给的字段如果没有，就用这些确定性值补上（避免「说给4项结果给了0项」）。"""
    return {
        "party": ["2 人", "3 大 1 小", "4 人", "夫妻二人", "3 人"][seq % 5],
        "dates": ["11 月中旬", "下个月初", "12 月上旬", "春节前后", "10 月底"][seq % 5],
        "days": ["5 天", "6 天", "4 天", "7 天"][seq % 4],
        "budget": "人均 5000-6000",
        "transport": "希望含接送机",
        "hotel": "四星或同档次",
        "special": "有一位老人同行",
        "decision": "本人决策",
    }


def _first_call_limit(time_pressure: int) -> int:
    """时限压力档位 → 首呼时限（PRD 20.2：补救放宽、熟练收紧）。"""
    return (120, 60, 45, 30, 20)[max(0, min(4, time_pressure))]


def _preset_incidents(resource_conflict: int) -> tuple[str, ...]:
    """资源冲突档位 → 本单准备埋几起突发事件（交给导演按步骤注入）。"""
    pool = ("INC-TICKET-FAIL", "INC-HOTEL-OVERBOOK", "INC-VEHICLE-BREAKDOWN",
            "INC-SETTLEMENT-DISPUTE")
    n = (1, 1, 2, 2, 3)[max(0, min(4, resource_conflict))]   # 最少 1 起：补救也要考，只是给线索
    return pool[:n]


def missing_fields(payload: dict) -> list[str]:
    """派单信息里还缺哪些字段（首呼要补问的就是这些）。"""
    return [label for key, label in DISPATCH_FIELDS
            if not str(payload.get(key) or "").strip()]


# ---------------------------------------------------------------- 标准案例（确定性）

DEMO_LABEL = "标准案例/演示数据"
SCENARIO_PAYLOAD_KEYS = ("scenario_id", "scenario_label", "demo_data", "fixed_dates")


def spec_from_case(case: dict) -> TouristSpec:
    """把标准案例的固定资料转成派单规范（**确定性**：同一份案例永远得到同一份 spec）。

    与 `DispatchGenerator` 的区别：这里不做随机、不调模型、不按画像调难度。
    案例里声明的客源地/目的地/语言/证件必须与 `SOURCE_MARKETS` 口径一致，
    不一致就报错而不是"就近改一下"——标准案例的可复现性优先于容错。
    """
    tourist = (case or {}).get("tourist") or {}
    market = str(tourist.get("source_market") or "").strip()
    if market not in SOURCE_MARKETS:
        raise ValueError(f"标准案例的客源地不在契约口径内: {market!r}")
    dest = str(tourist.get("destination") or "").strip().rstrip("省市")
    if dest not in DESTINATIONS:
        raise ValueError(f"标准案例的目的地不在契约口径内: {dest!r}")
    lang, docs, complexity = SOURCE_MARKETS[market]
    declared_lang = str(tourist.get("language") or lang).strip()
    if declared_lang and declared_lang != lang:
        raise ValueError(f"标准案例语言 {declared_lang!r} 与客源地 {market} 的口径 {lang!r} 不一致")
    declared_docs = str(tourist.get("documents") or docs).strip()
    preset = tuple(tourist.get("preset_incidents") or ())
    try:
        fc_limit = int(tourist.get("first_call_limit_min") or 60)
    except (TypeError, ValueError):
        fc_limit = 60

    extra = {
        "scenario_id": str(case.get("case_id") or ""),
        "scenario_label": str(case.get("demo_label") or DEMO_LABEL),
        "demo_data": True,
    }
    return TouristSpec(
        customer=str(tourist.get("customer") or "客户"),
        source_market=market, language=lang, destination=dest, documents=declared_docs,
        party=str(tourist.get("party") or ""),
        dates=str(tourist.get("dates") or ""),
        days=str(tourist.get("days") or ""),
        budget=str(tourist.get("budget") or ""),
        transport=str(tourist.get("transport") or ""),
        hotel=str(tourist.get("hotel") or ""),
        special=str(tourist.get("special") or ""),
        decision=str(tourist.get("decision") or ""),
        intent=str(tourist.get("intent") or ""),
        personality=str(tourist.get("personality") or ""),
        first_call_limit_min=fc_limit,
        preset_incidents=preset,
        difficulty_label=str(tourist.get("difficulty_label") or ""),
        rationale=str(tourist.get("rationale") or ""),
        source_complexity=int(tourist.get("source_complexity") or complexity),
        dispatch_gap=int(tourist.get("dispatch_gap") or 0),
        extra=extra,
    )
