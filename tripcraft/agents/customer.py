"""AI 客户 Agent —— 扮演 S2 首呼中的客户（PRD 第 2.3.2 节）。

客户根据订单事实自然表达需求；性格影响语气与耐心，已知事实保持一致。
文字与语音首呼共用需求表达规则与事实说明。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from .base import AgentContext, BaseAgent
from .llm import DeepSeekClient
from ..contracts.customer_role import CUSTOMER_ROLE_RULES
from ..contracts.entry_documents import (
    ENTRY_IDENTITY_FIELDS, FOREIGN_DOCUMENTS, HK_MACAO_DOCUMENT, TAIWAN_DOCUMENT,
    document_type_for, entry_document_prompt, is_domestic_traveler,
)


DEFAULT_CUSTOMER_PERSONALITY = "自然礼貌，按自己的出行需求沟通"
DEFAULT_CUSTOMER_PREFERENCES = "关心行程节奏、住宿品质与预算是否合适"
DEFAULT_CUSTOMER_HIDDEN = "希望安排省心、行程舒适，具体顾虑按本单资料表达"
CUSTOMER_FACT_LABELS = (
    ("party", "出行人数"), ("dates", "出行日期"), ("days", "天数"),
    ("budget", "预算口径"), ("transport", "交通偏好"), ("hotel", "住宿标准"),
    ("special", "特殊需求"), ("decision", "决策人"), ("documents", "证件"),
)
CUSTOMER_DEMAND_RULES = """【客户需求表达规则（文字与语音共用）】
1. 你代表自己的出行需求与定制师沟通。对方询问需求时，主动表达出行意向，并自然补充一两项相关信息。
2. 目的地已确定时，说明自己想去哪；目的地尚未确定时，表达想旅行的意愿，请定制师推荐地方。例句只展示表达方式，具体事实以你的资料为准。
3. 对方询问人数、日期、天数、预算等信息时，直接回答资料中已明确的内容。已知预算可直接给出数字及已有口径；不要为了让对方追问而刻意改成模糊回答。
4. 区分“自己知道但尚未说出”和“自己尚未决定”。资料明确的信息属于前者；资料没有明确的信息按待确认处理，说明尚未确定或需要与同行人确认，不编造确定的人数、日期或预算。对话中自己已确认的事实保持一致。
5. 尚未决定的安排可以说明犹豫或已有范围，再邀请建议。例如“天数还没定，你建议玩几天？”；有明确限制时一并说明，资料没有的限制不要自行添加。
6. 你可以询问路线、价格、季节、住宿、交通及方案是否合适。自己的已知需求由自己陈述，不把“我去哪里、几个人、预算多少”等需求采集问题原样反问给定制师，也不连续列出这些问题让对方替你回答。
7. 每轮通常说 1—3 句，围绕当前问题自然补充。无需一次说完全部需求，也不刻意扣住已被问到的信息。对方复述确认时，确认正确内容并纠正错误内容。
8. 性格影响语气、耐心和表达习惯。催促、不耐烦或预算犹豫仅在具体人设、明确诉求或对话情境支持时表现；不要统一扮演赶时间、拒绝给预算的客户，也不按问题数量机械发脾气。
9. 你只关心自己的旅行安排，不向对方布置需求采集任务，不检验或点评对方能力。只输出客户本人会说的台词。
10. 用第一人称口语回答，不要输出「人数：」「目的地：」「预算：」这种字段清单；把已知事实合成自然句子。
"""


def customer_facts_block(facts: Mapping, source_market: str = "") -> str:
    """统一说明客户已知事实与待确认项，供文字和语音提示词使用。"""
    domestic = is_domestic_traveler(source_market, facts)
    labels = [(key, label) for key, label in CUSTOMER_FACT_LABELS if key != "documents"]
    given = [f"- {label}：{facts[key]}" for key, label in labels
             if str(facts.get(key) or "").strip()]
    missing = [label for key, label in labels
               if not str(facts.get(key) or "").strip()]
    lines = []
    if given:
        lines.append("订单里已经填过的信息（这是你自己的资料；被问到时直接回答，前后保持一致）：\n"
                     + "\n".join(given))
    if missing:
        lines.append("订单里没有明确的信息（按待确认处理；被问到时说明尚未确定或需要确认，"
                     "不编造确定数值）：" + "、".join(missing))
    if not domestic and str(facts.get("documents") or "").strip():
        docs = document_type_for(source_market, facts)
        lines.append("证件类型/资料线索（持有、办理及适用状态以明确资料为准）：" + docs)
    return "\n".join(lines)


def trip_intent(destination: str, source_market: str = "", facts: Mapping | None = None) -> str:
    destination = (destination or "").strip()
    origin = "想在国内" if is_domestic_traveler(source_market, facts) else "想来内地"
    if destination in ("", "待定", "未定", "未确定", "暂未确定", "未知", "未明确", "待推荐", "未选择"):
        return origin + "旅游，目的地尚未确定，希望定制师推荐合适的地方"
    return f"{origin}去{destination}玩"


@dataclass
class CustomerPersona:
    name: str = "王女士"
    nationality: str = "中国"
    age: str = "38"
    gender: str = "女"
    language: str = "中文"          # 客户说的语言标签（中文 / English / 日本語 …）
    personality: str = DEFAULT_CUSTOMER_PERSONALITY
    trip_hint: str = "想去云南玩"
    preferences: str = ""           # 语音提示词：偏好
    quirks: str = ""                # 语音提示词：说话习惯
    hidden: str = ""                # 语音提示词：隐藏诉求
    details: dict = field(default_factory=dict)
    # 订单事实（R02）：订单里**显式写了**的出行约束。空值有语义——
    # 「订单里没写」按待确认处理，避免模型临时编造确定事实。
    facts: dict = field(default_factory=dict)
    customer_card: dict = field(default_factory=dict)
    traits: list[str] = field(default_factory=lambda: [
        "根据自己的旅行意向自然表达需求",
        "已明确的信息直接回答，未确定的信息说明待确认",
        "语气与耐心遵循具体人设和对话情境",
    ])

    def facts_block(self) -> str:
        if self.customer_card:
            from ..services.customer_card import render_card
            return render_card(self.customer_card)
        return customer_facts_block(self.prompt_facts(), self.nationality)

    def prompt_facts(self) -> dict:
        """兼容旧调用仅在 details.docs 中提供证件资料的情况。"""
        facts = dict(self.facts or {})
        if not str(facts.get("documents") or "").strip():
            facts["documents"] = (self.details or {}).get("docs", "")
        return facts

    def voice_profile(self) -> dict:
        """给语音提示词用的字典视图 —— 与文本人设同源，避免两套人设打架。

        - 顶层保留 `name/nationality/age/gender/language/personality/preferences/quirks/hidden`
          与 `details`（既有语音提示词一直按这些 key 取值）；
        - 额外带 `facts`（订单事实，含空值），供语音提示词渲染「已填/未填」。
        """
        d = {"name": self.name, "nationality": self.nationality, "age": self.age,
             "gender": self.gender, "language": self.language,
             "personality": self.personality, "preferences": self.preferences,
             "quirks": self.quirks, "hidden": self.hidden,
             "facts": self.prompt_facts()}
        d.update(self.details or {})
        for key, value in self.prompt_facts().items():
            if str(value or "").strip():
                d[key] = value
        return d


def persona_block(persona: CustomerPersona) -> str:
    """客户人设字段的**统一渲染**（文本 / 语音 / IM 三个 prompt 共用同一份措辞）。

    统一是必要的：三通道如果各写各的标签与格式，就没法逐字段证明
    「订单里显式写的 age/gender/preferences/quirks/hidden 真的进了模型」。
    """
    prompt_facts = persona.prompt_facts()
    identity = "".join(f"- {label}：{prompt_facts[key]}\n"
                       for key, label in (("citizenship", "明确的国籍/公民身份"), ("traveler_type", "旅行类型"))
                       if str(prompt_facts.get(key) or "").strip())
    return (
        "【人设字段（必须保持，逐项对应）】\n"
        f"- 年龄：{persona.age}\n"
        f"- 性别：{persona.gender}\n"
        f"- 性格：{persona.personality}\n"
        f"- 偏好：{persona.preferences}\n"
        f"- 说话习惯：{persona.quirks}\n"
        f"- 隐藏诉求：{persona.hidden}\n"
        f"{identity}\n"
        + entry_document_prompt(persona.nationality, prompt_facts) + "\n"
    )


def build_customer_system(persona: CustomerPersona) -> str:
    traits = "\n".join("- " + t for t in persona.traits)
    facts_block = persona.facts_block()
    facts_section = f"\n【订单里已填/未填的事实】\n{facts_block}\n" if facts_block else ""
    # 人设字段逐条显式写出：文本通道以前没有 preferences/quirks/hidden，
    # 订单里显式写的这两项就进不了模型（Codex 审查整改点）。
    profile_section = "\n" + persona_block(persona)
    return f"""你是一位正在与定制师沟通旅行安排的客户。

{CUSTOMER_ROLE_RULES}

【你的身份】
{persona.name}，{persona.age}岁，{persona.gender}，来自{persona.nationality}。
出行意向：{persona.trip_hint}
{profile_section}{facts_section}
【你的特征（必须保持）】
{traits}

【语言（硬约束，最高优先级）】
- 你只会说{persona.language}。**无论对方用什么语言提问，你一律用{persona.language}回答**，
  不要翻译成中文，也不要为了迁就对方改说中文。
- 保持这个语言的口语习惯与称呼方式，不要写成书面语。

【对话规则】
1. 你始终是客户，不出戏，不点评对方表现，不扮演教练。
2. 用口语、简短回复（1-3 句），根据自己的实际感受和人设自然回应。
3. 只输出你的台词，不要任何旁白、括号说明或 JSON。

{CUSTOMER_DEMAND_RULES}

每轮都保持出游客户的视角；只输出客户本人这一轮会说的话。
"""


class CustomerAgent(BaseAgent):
    name = "customer"

    def __init__(self, llm: DeepSeekClient, persona: CustomerPersona | None = None) -> None:
        super().__init__(llm)
        self.persona = persona or CustomerPersona()
        # R06 硬约束（追加）：客户始终是客户、不泄评测规则与幕后信息。
        # 只追加不改写既有措辞，避免与既有测试/提示词基线冲突。
        from ..services.call_script import apply_client_prompt_rules

        self._system = apply_client_prompt_rules(build_customer_system(self.persona))

    def opening(self, ctx: AgentContext) -> str:
        """客户被动接听：由定制师先开口，这里只给一个简短应答。"""
        reply = self._llm.chat(
            [{"role": "system", "content": self._system},
             {"role": "user", "content": "（定制师刚打来电话，你先接起）请给出你的第一句应答。"}],
            temperature=0.8, max_tokens=120)
        ctx.add("assistant", reply.strip())
        return reply.strip()

    def reply(self, ctx: AgentContext, guide_message: str) -> str:
        ctx.add("user", guide_message)
        messages = [{"role": "system", "content": self._system}] + ctx.messages
        reply = self._llm.chat(messages, temperature=0.8, max_tokens=200)
        ctx.add("assistant", reply.strip())
        return reply.strip()


# 内地游客采用国内沟通规则；港澳台/海外客源按实际身份引用入境证件名称。
# 客源地 -> 该客源市场的典型习惯（决定客户 Agent 会怎么问、在意什么）
SOURCE_PROFILES: dict[str, dict[str, str]] = {
    "香港": {"docs": HK_MACAO_DOCUMENT, "pay": "八达通与信用卡",
             "im": "WhatsApp", "note": "对内地景区预约制、实名制不熟，习惯先看行程再谈价"},
    "澳门": {"docs": HK_MACAO_DOCUMENT, "pay": "澳门信用卡，习惯港币/澳门币",
             "im": "WeChat / WhatsApp", "note": "出行节奏偏慢，重视餐饮与住宿品质"},
    "台湾": {"docs": TAIWAN_DOCUMENT, "pay": "台湾信用卡",
             "im": "Line", "note": "按具体需求沟通交通与高铁安排"},
    "新加坡": {"docs": FOREIGN_DOCUMENTS, "pay": "信用卡与 PayNow",
               "im": "WhatsApp / Telegram", "note": "英文与中文混用，重视效率与明确报价"},
}
DEFAULT_SOURCE_PROFILE = {"docs": FOREIGN_DOCUMENTS, "pay": "国际信用卡", "im": "WhatsApp / Email",
                          "note": "按本人实际需求沟通行程与服务安排"}
DOMESTIC_SOURCE_PROFILE = {"docs": "", "pay": "按本人习惯使用移动支付、银行卡或现金",
                           "im": "按本人习惯选择联系方式", "note": "围绕国内旅行的具体需求沟通"}


def source_profile_for(source_market: str, facts: Mapping | None = None) -> dict[str, str]:
    if is_domestic_traveler(source_market, facts):
        return DOMESTIC_SOURCE_PROFILE
    return SOURCE_PROFILES.get(source_market, DEFAULT_SOURCE_PROFILE)

_AGES = ("29", "34", "38", "42", "47", "53")


def _s(value) -> str:
    return str(value or "").strip()


def stable_gender_age(order_id: str) -> tuple[str, str]:
    """按订单号稳定派生性别与年龄：同一单每次进来都是同一个人，不同单会换人。"""
    seed = int(hashlib.md5((order_id or "order").encode("utf-8")).hexdigest()[:8], 16)
    return ("男" if seed % 2 else "女"), _AGES[(seed >> 3) % len(_AGES)]


def persona_for(customer: str, destination: str, source_market: str = "香港",
                language: str = "中文", order_id: str = "", personality: str = "",
                *, facts: dict | None = None) -> CustomerPersona:
    """订单级客户人设 —— 语音通话、文本通话、群聊共用这一份。

    `facts` 是订单里显式写下的客户事实（age/gender/personality/preferences/quirks/hidden
    以及 party/dates/days/budget/documents…）。文本、语音、IM 三条通道都必须传**同一份**。

    优先级（本函数的核心约定，Codex 审查整改点）：
    1. 订单/调用方**显式给出**的值优先：age、gender、personality、preferences、quirks、hidden；
    2. 缺失时才走派生：年龄/性别由 `stable_gender_age(order_id)` 确定性派生（同输入同输出），
       preferences/quirks/hidden 落到客源地画像默认值，证件落客源地默认值。
    """
    payload = dict(facts or {})
    prof = source_profile_for(source_market, payload)
    domestic = is_domestic_traveler(source_market, payload)
    derived_gender, derived_age = stable_gender_age(order_id or f"{source_market}-{customer}")

    # 显式优先，缺失才派生（派生确定性：同 order_id + 同客源地必得同一个人）
    age = _s(payload.get("age")) or derived_age
    gender = _s(payload.get("gender")) or derived_gender
    lang = (language or "中文").strip() or "中文"

    order_facts = {
        "party": _s(payload.get("party")),
        "dates": _s(payload.get("dates")),
        "days": _s(payload.get("days")),
        "budget": _s(payload.get("budget")),
        "transport": _s(payload.get("transport")),
        "hotel": _s(payload.get("hotel")),
        "special": _s(payload.get("special")),
        "decision": _s(payload.get("decision")),
        "documents": document_type_for(source_market, payload),
    }
    order_facts.update({key: _s(payload.get(key)) for key in ENTRY_IDENTITY_FIELDS if _s(payload.get(key))})
    personality_value = (_s(personality) or _s(payload.get("personality"))
                         or DEFAULT_CUSTOMER_PERSONALITY)
    preferences_value = (_s(payload.get("preferences"))
                         or DEFAULT_CUSTOMER_PREFERENCES)
    quirks_value = _s(payload.get("quirks")) or f"用{lang}保持本地口音与用词习惯"
    hidden_value = _s(payload.get("hidden")) or DEFAULT_CUSTOMER_HIDDEN

    traits = [
        (f"你是在内地/大陆旅行的国内游客，日常用{lang}沟通" if domestic
         else f"你来自{source_market}，计划来内地/大陆旅游，日常用{lang}沟通；国籍以明确资料为准"),
        f"支付习惯参考：{prof['pay']}；仅在对话需要时沟通支付安排",
        f"常用通讯工具参考：{prof['im']}；按实际需要商量联系方式",
        prof["note"],
        "自然表达自己的出行需求，直接回答已明确的信息",
        "未确定的安排说明待确认，并根据需要邀请建议",
        "语气与耐心遵循具体人设和对话情境",
    ]
    if lang != "中文":
        traits.insert(0, f"你只说{lang}；对方用中文提问你也用{lang}回答，不做翻译")
    return CustomerPersona(
        name=customer,
        nationality=source_market,
        age=age,
        gender=gender,
        language=lang,
        personality=personality_value,
        trip_hint=trip_intent(destination, source_market, payload),
        preferences=preferences_value,
        quirks=quirks_value,
        hidden=hidden_value,
        details={"docs": order_facts["documents"]},
        facts=order_facts,
        customer_card=payload.get("_customer_card") or {},
        traits=traits,
    )
