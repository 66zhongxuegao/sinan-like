"""联网检索（供数据基座生成器用）。

可用源（本网络实测）：
- cn.bing.com       通用网页搜索（标题 + 摘要）
- 百度百科 API       词条摘要（结构化）
- 高德 Web 服务       POI / 目的地（见 tools/external.py）

说明：维基/DDG 在本网络不可达，故不采用。
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _get(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


@dataclass
class SearchHit:
    title: str
    snippet: str
    url: str = ""


@dataclass
class SearchResult:
    query: str
    hits: list[SearchHit] = field(default_factory=list)

    def context(self, limit: int = 5) -> str:
        lines = []
        for h in self.hits[:limit]:
            lines.append(f"- {h.title}：{h.snippet}" + (f"（{h.url}）" if h.url else ""))
        return "\n".join(lines)


def bing_search(query: str, limit: int = 5) -> SearchResult:
    """cn.bing.com 网页搜索。"""
    out = SearchResult(query=query)
    try:
        t = _get("https://cn.bing.com/search?q=" + urllib.parse.quote(query))
    except Exception:
        return out
    blocks = re.findall(r'<li class="b_algo".*?</li>', t, re.S)
    for b in blocks[:limit]:
        m = re.search(r"<h2[^>]*>(.*?)</h2>", b, re.S)
        title = _clean(m.group(1)) if m else ""
        p = re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        snippet = _clean(p.group(1)) if p else ""
        href = re.search(r'<a[^>]+href="(http[^"]+)"', b)
        if title:
            out.hits.append(SearchHit(title=title, snippet=snippet, url=href.group(1) if href else ""))
    return out


def baike(lemma: str) -> SearchHit | None:
    """百度百科词条摘要。"""
    try:
        u = "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi?" + urllib.parse.urlencode(
            {"scope": 103, "format": "json", "appid": 379020, "bk_key": lemma})
        d = json.loads(_get(u))
        title = d.get("title") or lemma
        abstract = (d.get("abstract") or "").strip()
        if not abstract:
            return None
        return SearchHit(title=title, snippet=abstract,
                         url="https://baike.baidu.com/item/" + urllib.parse.quote(title))
    except Exception:
        return None


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def research(queries: list[str], per_query: int = 3, sleep: float = 0.8) -> list[SearchHit]:
    """多查询检索 + 去重。"""
    seen: set[str] = set()
    out: list[SearchHit] = []
    for q in queries:
        for h in bing_search(q, per_query).hits:
            key = h.title[:30]
            if key and key not in seen:
                seen.add(key)
                out.append(h)
        time.sleep(sleep)
    return out