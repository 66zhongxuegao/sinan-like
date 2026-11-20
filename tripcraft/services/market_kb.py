"""国别知识库：常见入境客源国的语言、文化、政策、习俗（data/markets/*.json）。

每个国家一个文件，内容不求多，但每条都有标题头，能在讲义里直接引用并标出来源：
  language  服务语言 + 6 句常用客服用语（带中文意思与读音，供低水平学员照读）
  culture   文化要点（标题 + 一两句话）
  policy    入境/通讯/支付等政策要点；一律 verify=true，只写稳定框架，具体名单与天数以官方公告为准
  customs   习俗与禁忌
  sources   网络来源链接（官方机构 + 该国旅游推广机构）

教学端按学员选的目标客源国取用，并把用到的条目逐条列进讲义下方的「证据」里。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

MARKET_DIR = Path(__file__).resolve().parents[2] / "data" / "markets"

# 讲义里用到的四类内容及其中文名，证据和画像页共用
SECTION_NAMES = {"language": "语言", "culture": "文化", "policy": "政策", "customs": "习俗"}


@lru_cache(maxsize=1)
def _all() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if MARKET_DIR.exists():
        for p in sorted(MARKET_DIR.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d.get("code"):
                out[str(d["code"]).upper()] = d
    return out


def get_market(code: str) -> dict[str, Any] | None:
    return _all().get(str(code or "").strip().upper())


def public_list() -> list[dict[str, str]]:
    """给前端选国家用：只带最少的字段。"""
    return [{"code": m["code"], "country": m["country"], "region": m.get("region", ""),
             "service_language": m.get("service_language", ""), "lang_short": m.get("lang_short", "")}
            for m in _all().values()]


def source_by_id(market: dict, sid: str) -> dict[str, str] | None:
    return next((s for s in market.get("sources", []) if s.get("id") == sid), None)


def phrases_for(market: dict, level: int) -> list[dict[str, str]]:
    """按语言水平决定给学员几句现成用语：越低给得越全，流利水平不再给。"""
    items = list((market.get("language") or {}).get("phrases") or [])
    if level <= 1:
        return items
    if level == 2:
        return items[:3]
    return []


def evidence_rows(market: dict) -> list[dict[str, str]]:
    """给证据闸门的可追溯材料。

    这些条目是项目内人工整理的知识库，所以按 curated 等级入闸；
    但政策类正文本身只写框架并要求核验，讲义也被要求照此转述，不得补写具体天数/名单。
    """
    code = market.get("code", "")
    rows: list[dict[str, str]] = []
    for key in ("culture", "policy", "customs"):
        for i, item in enumerate(market.get(key) or []):
            rows.append({"id": f"M:{code}:{key}:{i}", "source": f"contract:market:{code}:{key}",
                         "text": f"{item.get('title', '')}：{item.get('body', '')}", "trust": "curated"})
    for i, ph in enumerate((market.get("language") or {}).get("phrases") or []):
        rows.append({"id": f"M:{code}:language:{i}", "source": f"contract:market:{code}:language",
                     "text": f"{ph.get('scene', '')}：{ph.get('zh', '')} {ph.get('text', '')}", "trust": "curated"})
    return rows
