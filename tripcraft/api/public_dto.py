"""公开 DTO 投影（API 边界层，conversation 域 · R08）。

原则：**白名单构造**，不是黑名单删字段。给前端的对象只能由本模块的函数产出，
服务层的 dataclass（`CustomerPersona` / `CallSession` / 订单行 / 线程消息）一律不外泄。

被显式挡在边界外的内容：
- 客户隐藏人设：`hidden` / `traits` / `quirks` / `preferences` / `trip_hint`
  （`CustomerPersona` 与 `voice_profile()` 里有这些字段，但它们只允许进模型提示词）；
- 评分答案：题目卡里的 `answer` / `reference` / `rubric_points` / `explain`；
- 系统提示词：任何 `*_system` / `system_prompt`（模型侧内容不下发）；
- 内置成本底牌、全局配置、密钥：`cost` / `api_key` / `token` / `secret` / `password*`；
- 内部身份：`user_id` 不作为前端可见字段（终端的身份由会话决定，不需要前端传/看）。

字段级对照证据见 `scripts/verify_public_dto.py` 与
`output/acceptance/conversation/public-dto-keys.md`。
"""

from __future__ import annotations

# 客户公开字段白名单（学员在通话前需要知道：对方是谁、说什么语言、来自哪里、证件口径）
PUBLIC_CUSTOMER_FIELDS: tuple[str, ...] = (
    "name", "nationality", "age", "gender", "language", "docs",
)

# 模型侧/内部字段：出现在任何响应里即为越界（供自检脚本递归扫描用）
FORBIDDEN_KEYS: frozenset[str] = frozenset({
    # 客户隐藏人设 / 提示词素材
    "hidden", "traits", "quirks", "trip_hint",
    # 评分答案
    "answer", "reference", "rubric_points", "explain",
    # 系统提示词与模型配置
    "system", "system_prompt", "instructions", "prompt",
    # 内置成本底牌 / 配置 / 密钥
    "cost", "cost_base", "floor_price", "api_key", "apikey", "secret",
    "password", "password_hash", "password_salt", "token", "token_hash",
})


def public_customer(facts=None, fallback_name: str = "客户") -> dict:
    """客户公开资料投影：只出白名单字段（customer_order_facts.CustomerFacts 入参）。

    注意：`personality` 属于模型侧人设（客户性格细节），**不下发前端**，
    因此不在白名单里；`docs` 是客源证件口径，属于学员需要知道的基本信息。
    """
    if facts is None:
        return {"name": fallback_name, "nationality": "", "age": "", "gender": "",
                "language": "中文", "docs": ""}
    return {
        "name": facts.customer or fallback_name,
        "nationality": facts.source_market,
        "age": facts.age,
        "gender": facts.gender,
        "language": facts.language,
        "docs": facts.public_facts()["documents"],
    }


def public_customer_from_facts(facts) -> dict:
    """从 `CustomerFacts` 投影客户公开资料（订单详情用）。"""
    return {
        "name": facts.customer or "客户",
        "nationality": facts.source_market,
        "age": facts.age,
        "gender": facts.gender,
        "language": facts.language,
        "docs": facts.public_facts()["documents"],
    }


def public_call_snapshot(snapshot: dict | None) -> dict:
    """通话会话快照的公开投影：结构化白名单，不透传内部字段。"""
    snap = snapshot or {}
    return {
        "session_id": snap.get("session_id", ""),
        "order_id": snap.get("order_id", ""),
        "customer": snap.get("customer", "客户"),
        "destination": snap.get("destination", ""),
        "source_market": snap.get("source_market", ""),
        "language": snap.get("language", "中文"),
        "mode": snap.get("mode", "text"),
        "turns": int(snap.get("turns") or 0),
        "ended": bool(snap.get("ended")),
        "lines": [
            {"who": str(l.get("who", "")), "text": str(l.get("text", ""))}
            for l in (snap.get("lines") or [])
            if isinstance(l, dict)
        ],
    }


def public_quiz_card(question: dict | None) -> dict:
    """题卡公开投影：剥掉答案与评分要点，只留题干与选项。"""
    q = dict(question or {})
    for key in ("answer", "reference", "rubric_points", "explain"):
        q.pop(key, None)
    return q


def scan_forbidden_keys(payload, path: str = "$") -> list[str]:
    """递归找出响应里出现的内网/隐藏字段（自检与验收脚本共用）。"""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                found.append(f"{path}.{key}")
            found.extend(scan_forbidden_keys(value, f"{path}.{key}"))
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            found.extend(scan_forbidden_keys(item, f"{path}[{i}]"))
    return found
