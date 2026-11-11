"""客户事实单一来源（conversation 域 · R02）。

背景（重构前的真实问题）：
- 文本通话取 `order_detail()` 的 `source_market` / `language`（默认“香港”/“中文”）；
- 实时语音取 `store.order()` 的 `payload`，`source_market` 默认空串，
  `persona_for` 再兜底成“中国” → 空客源地时语音客人变成“中国游客”；
- IM 群聊取 `payload`（默认“香港”/“中文”）；
- call_service 落库把 `user_id` 写死成 `u-demo`，AgentContext 也写死 `u-demo`。

三条链路各自从不同容器、用不同默认值取同一份事实，任何一处缺字段就会让同一个客人在
不同通道变成不同的人（国籍/语言/证件/年龄/性别漂移）。

本模块是**唯一**的客户事实投影：
- `facts_for_order_id(store, order_id)`：从订单行派生（三通道统一入口）；
- `facts_from_order_row(row)`：已拿到行时复用，避免重复读库；
- `public_facts()` / `public_customer_payload()`：给前端的白名单字段（不含隐藏诉求/性格细节）；
- `persona_for_order(store, order_id)`：给模型提示词的完整人设（含隐藏诉求，**不得下发前端**）。

契约（v1，owner: conversation）：
- 客户基本信息一律以订单行为准：`customer` / `destination` 取列，`source_market` /
  `language` / `personality` / `documents` 取 payload，缺字段时用同一套默认值兜底。
- 性别/年龄优先采用订单明确值，缺失时由 `agents.customer.stable_gender_age(order_id)`
  稳定派生；公开资料、模型人设与语音使用同一份身份。
- 本模块只读订单，不写库；不 import api 层（避免反向依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from ..contracts.entry_documents import ENTRY_IDENTITY_FIELDS, document_type_for, is_domestic_traveler

# 与 practice_service.DEFAULT_SOURCE_MARKET / 各链路默认口径保持一致（唯一常量）
DEFAULT_SOURCE_MARKET = "香港"
DEFAULT_LANGUAGE = "中文"

# 公开字段（可以给学员看：通话前要显示“对方大概是什么人、说什么语言”）
PUBLIC_FIELDS: tuple[str, ...] = (
    "customer", "destination", "source_market", "language",
    "age", "gender", "documents", "party",
)
# 订单事实字段（进模型提示词；空值按待确认处理，避免编造确定事实）
FACT_FIELDS: tuple[str, ...] = (
    "party", "dates", "days", "budget", "transport", "hotel", "special",
    "decision", "documents",
)
# 人设字段：订单里显式写了就优先，缺失才派生（Codex 审查整改：以前被固定派生值吞掉）
PERSONA_FIELDS: tuple[str, ...] = (
    "age", "gender", "personality", "preferences", "quirks", "hidden",
)
# 私有字段（只进模型提示词，绝不下发前端：隐藏诉求 / 性格细节 / 口音 / 偏好）
PRIVATE_FIELDS: tuple[str, ...] = (
    "personality", "preferences", "quirks", "hidden", "traits", "trip_hint",
)


def _s(value) -> str:
    """字符串归一：None/非字符串都收敛成去空白字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _payload_of(row: dict | None) -> dict:
    if not row:
        return {}
    raw = row.get("payload")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _order_id_of(row: dict | None) -> str:
    if not row:
        return ""
    oid = _s(row.get("order_id"))
    if oid:
        return oid
    return _s(_payload_of(row).get("order_id"))


@dataclass(frozen=True)
class CustomerFacts:
    """一个订单的客户事实（口径唯一，三通道共用）。"""

    order_id: str = ""
    user_id: str = ""
    customer: str = "客户"
    destination: str = ""
    source_market: str = DEFAULT_SOURCE_MARKET
    language: str = DEFAULT_LANGUAGE
    personality: str = ""
    documents: str = ""
    age: str = ""
    gender: str = ""
    trip_facts: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    customer_card: dict = field(default_factory=dict)
    original_payload: dict | None = None

    # ---------- 通道口径 ----------

    def persona_args(self) -> tuple:
        """传给 `agents.customer.persona_for` 的位置参数（三通道必须同一套）。"""
        return (self.customer, self.destination, self.source_market,
                self.language, self.order_id, self.personality)

    def persona_kwargs(self) -> dict:
        """传给 `persona_for` 的关键字参数。

        `facts` 必须包含**人设字段**（age/gender/personality/preferences/quirks/hidden）
        与订单事实字段，否则显式覆盖在 `persona_for` 里就看不到（Codex 审查整改点）。
        """
        return {"facts": self.model_facts()}

    def explicit_persona(self) -> dict:
        """订单里**显式写明**的人设字段（缺省为空串，表示要走派生）。"""
        source = self.payload if self.original_payload is None else self.original_payload
        return {k: _s(source.get(k)) for k in PERSONA_FIELDS}

    def model_facts(self) -> dict:
        """订单事实（模型可见）：空值保留，用来说明「订单里没写」。

        同时带上显式人设字段，`persona_for` 才能做到「显式优先、缺失派生」。
        """
        out = {k: _s(self.trip_facts.get(k)) for k in FACT_FIELDS}
        out["documents"] = _s(self.trip_facts.get("documents")) or self.documents
        out.update({k: _s(self.payload.get(k)) for k in PERSONA_FIELDS})
        out.update({key: _s(self.payload.get(key)) for key in ENTRY_IDENTITY_FIELDS
                    if _s(self.payload.get(key))})
        if self.customer_card:
            out["_customer_card"] = self.customer_card
        return out

    def public_facts(self) -> dict:
        """给学员的公开字段白名单。"""
        return {
            "customer": self.customer,
            "destination": self.destination,
            "source_market": self.source_market,
            "language": self.language,
            "age": self.age,
            "gender": self.gender,
            "documents": document_type_for(self.source_market, self.model_facts()),
            "party": (_s(self.trip_facts.get("party")) if not self.customer_card or
                      self.customer_card["fields"]["party"].get("revealed") else ""),
        }

    def private_flags(self) -> dict:
        """私有字段的**存在性**标记（用于一致性核对，不泄露内容）。"""
        return {k: bool(self.payload.get(k)) for k in PRIVATE_FIELDS}

    def persona_view(self) -> dict:
        """完整人设视图（含隐藏诉求与订单事实）——只允许进提示词。

        **不自证**：所有值都直接来自真实人设对象 `persona_for()` 的字段，
        绝不在视图层再拼一遍「期望值」；视图与人设不一致即为 bug（Codex 审查整改点）。
        """
        p = self.persona_for()
        view = {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "name": p.name,
            "nationality": p.nationality,
            "age": p.age,
            "gender": p.gender,
            "language": p.language,
            "documents": (p.details or {}).get("docs", ""),
            "personality": p.personality,
            "preferences": p.preferences,
            "quirks": p.quirks,
            "hidden": p.hidden,
            "facts": dict(p.facts),
            "facts_block": p.facts_block(),
        }
        # 视图 vs 真实人设：逐字段自校验，任何人设字段不一致都在这里暴露
        mismatched = [k for k in ("age", "gender", "personality", "preferences",
                                  "quirks", "hidden")
                      if _s(view.get(k)) != _s(getattr(p, k, ""))]
        view["view_matches_persona"] = not mismatched
        view["view_mismatched_fields"] = mismatched
        return view

    def respected_matrix(self) -> dict:
        """逐字段判定「显式优先 / 缺失派生」，并给出最终进入模型的值。

        判定标准（可被外部复核）：
        - 订单显式写了该字段 → 真实人设必须等于订单值（source=explicit）；
        - 订单没写 → 真实人设必须等于同源的稳定派生值（source=derived）；
          age/gender 用 `stable_gender_age(order_id)` 复算，其余用同源默认值复算。
        """
        from ..agents.customer import (
            DEFAULT_CUSTOMER_PERSONALITY, DEFAULT_CUSTOMER_PREFERENCES, DEFAULT_CUSTOMER_HIDDEN,
            stable_gender_age,
        )

        p = self.persona_for()
        explicit = self.explicit_persona()
        derived_gender, derived_age = stable_gender_age(self.order_id or "order")
        lang = self.language
        defaults = {
            "age": derived_age,
            "gender": derived_gender,
            "personality": DEFAULT_CUSTOMER_PERSONALITY,
            "preferences": DEFAULT_CUSTOMER_PREFERENCES,
            "quirks": f"用{lang}保持本地口音与用词习惯",
            "hidden": DEFAULT_CUSTOMER_HIDDEN,
            "documents": document_type_for(self.source_market, self.model_facts()),
        }
        persona_fields = {
            "age": p.age, "gender": p.gender, "personality": p.personality,
            "preferences": p.preferences, "quirks": p.quirks, "hidden": p.hidden,
            "documents": (p.details or {}).get("docs", ""),
        }
        model_view = self.model_view()
        out: dict[str, dict] = {}
        for key, default_value in defaults.items():
            given = (_s(explicit.get(key)) if key in PERSONA_FIELDS
                     else _s(self.trip_facts.get(key)))
            expected = default_value if key == "documents" else (given or default_value)
            persona_value = _s(persona_fields.get(key))
            model_value = _s(model_view.get(key))
            out[key] = {
                "source": ("not_applicable" if key == "documents" and is_domestic_traveler(self.source_market, self.model_facts())
                           else "explicit" if given else "derived"),
                "expected": expected,
                "persona": persona_value,
                "model_visible": model_value,
                "respected": persona_value == expected and model_value == expected,
            }
        return out

    def model_view(self) -> dict:
        """模型实际会看到的客户字段（人设 + 订单事实），供验证脚本取用。"""
        p = self.persona_for()
        view = {
            "name": p.name, "nationality": p.nationality, "age": p.age,
            "gender": p.gender, "language": p.language,
            "personality": p.personality,
            "preferences": p.preferences, "quirks": p.quirks, "hidden": p.hidden,
            "documents": (p.details or {}).get("docs", ""),
        }
        view.update(dict(p.facts))
        return view

    def persona_for(self):
        """按本事实组装 `CustomerPersona`（文本/语音/IM 三通道共用同一入口）。"""
        from ..agents.customer import persona_for

        return persona_for(*self.persona_args(), **self.persona_kwargs())


def facts_from_order_row(row: dict | None) -> CustomerFacts:
    """已拿到订单行时派生客户事实（三通道统一口径，不再各自取字段）。"""
    if not row:
        return CustomerFacts()

    payload = _payload_of(row)
    original_payload = dict(payload)
    order_id = _order_id_of(row)
    from .customer_card import build_card
    card = row.get("_customer_card") or build_card(row, fill_hidden=False)
    payload.update(card.get("identity") or {})
    payload.update({key: value["value"] if value["state"] != "unknown" else ""
                    for key, value in card["fields"].items()})
    # 订单 payload 是显式字段的权威来源。卡片可能是迁移前生成的旧派生值，
    # 不能让它覆盖用户后来明确写入的年龄/性别/偏好等字段。
    payload.update({key: value for key, value in original_payload.items()
                    if value not in (None, "")})
    # 只有真正派生时才需要 agents 包；放函数内避免模块级依赖
    from ..agents.customer import stable_gender_age

    seed = order_id or f"customer:{_s(row.get('customer'))}"
    gender, age = stable_gender_age(seed)
    return CustomerFacts(
        order_id=order_id,
        user_id=_s(row.get("user_id")),
        customer=_s(row.get("customer")) or "客户",
        destination=_s(row.get("destination")),
        source_market=_s(payload.get("source_market")) or DEFAULT_SOURCE_MARKET,
        language=_s(payload.get("language")) or DEFAULT_LANGUAGE,
        personality=_s(payload.get("personality")),
        documents=_s(payload.get("documents")),
        age=_s(payload.get("age")) or age,
        gender=_s(payload.get("gender")) or gender,
        trip_facts={k: _s(payload.get(k)) for k in FACT_FIELDS},
        payload=payload,
        customer_card=card,
        original_payload=original_payload,
    )


def facts_for_order_id(store, order_id: str) -> CustomerFacts:
    """三通道统一入口：按订单号取客户事实。订单不存在时返回空事实（order_id 保留）。"""
    oid = _s(order_id)
    if store is None or not oid:
        return CustomerFacts(order_id=oid)
    facts = facts_from_order_row(store.order(oid))
    if facts.order_id:
        return facts
    return CustomerFacts(order_id=oid)


def card_for_order(store, order_id: str) -> dict:
    return store.ensure_customer_card(order_id)


def persona_for_order(store, order_id: str):
    """按订单号组装 `CustomerPersona`（文本通话 / 语音 / IM 共用同一份）。"""
    return facts_for_order_id(store, order_id).persona_for()


def terms_for_order(store, order_id: str) -> dict:
    """给调用方的关键字参数字典，便于把三通道统一接到同一入口。"""
    facts = facts_for_order_id(store, order_id)
    return {
        "order_id": facts.order_id, "user_id": facts.user_id,
        "customer": facts.customer, "destination": facts.destination,
        "source_market": facts.source_market, "language": facts.language,
        "personality": facts.personality,
    }


def public_customer_payload(store, order_id: str) -> dict:
    """订单详情里下发给前端的客户公开资料。"""
    return facts_for_order_id(store, order_id).public_facts()


# ---------------------------------------------------------------- 通道一致性
#
# 注意（监督者审查整改）：**不要**在这里比较「同一个 dict 复制三份」——
# 那是同义反复，不能证明三通道一致。真实的通道验证在
# `scripts/verify_channel_context.py`：直接驱动 CallService / VoiceBridge /
# SupplierService，捕获模型适配器实际收到的 messages / instructions，再逐字段比对。

def compare_persona_views(store, order_id: str) -> dict:
    """本单的模型侧人设视图 + 公开字段视图（**不是**三通道一致性的证明）。

    三通道一致性的真实证明见 `scripts/verify_channel_context.py`：
    直接驱动 CallService / VoiceBridge / SupplierService，捕获它们实际喂给模型的
    messages / instructions，再逐字段比对。这里只导出单通道的口径供引用。
    """
    facts = facts_for_order_id(store, order_id)
    persona = facts.persona_for()
    voice_view = persona.voice_profile()
    view = facts.persona_view()
    return {
        "order_id": order_id,
        "persona": {"voice_profile": voice_view, "private_flags": facts.private_flags()},
        "public": facts.public_facts(),
        "model_facts": facts.model_facts(),
        "model_view": {k: view.get(k) for k in
                       ("order_id", "name", "age", "gender", "language",
                        "personality", "hidden")},
        "facts_block": view.get("facts_block", ""),
    }
