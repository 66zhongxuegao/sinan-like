"""BM25 多路召回 —— 从 61 个技能点知识点基座里检索与当前提问最相关的片段。

对齐旧版「字符二元组 BM25 + 三重加权」思路，但目标从旧题库换成新知识点基座：
  - 标题（技能点名）×5
  - 要点（key_points）×3
  - 正文（explain / 示例 / 资源 / 练习）×1
支持按技能点过滤（线程内只召回本技能点 + 可选的跨技能点相关），
所有结果带来源标签，供教学对话的「溯源」使用。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"

_CJK_RE = re.compile(r"[一-鿿]")
_ALNUM_RE = re.compile(r"[a-zA-Z0-9]+")
_LATIN_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into",
    "are", "you", "your", "what", "how", "which", "where", "when",
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    cjk = "".join(_CJK_RE.findall(text))
    if len(cjk) >= 2:
        tokens.extend(cjk[i:i + 2] for i in range(len(cjk) - 1))
    elif len(cjk) == 1:
        tokens.append(cjk)
    for w in _ALNUM_RE.findall(text.lower()):
        if w not in _LATIN_STOP and len(w) >= 2:
            tokens.append(w)
    return tokens


@dataclass
class Chunk:
    sp: str
    field: str
    label: str
    text: str


def _segments(text: str, n: int = 2) -> list[str]:
    """把长文本按句切段，控制注入长度。"""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？；])", text)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [text]
    if len(parts) <= n:
        return parts
    # 均匀合并成 n 段
    out, step = [], max(1, len(parts) // n)
    for i in range(0, len(parts), step):
        out.append("".join(parts[i:i + step]))
    return out[:n]


def _chunks_for(doc: dict) -> list[Chunk]:
    sp = doc.get("skill_point_id", "")
    name = doc.get("name", "")
    out: list[Chunk] = []
    if name:
        out.append(Chunk(sp, "title", "标题", name))
    for seg in _segments(doc.get("explain", ""), 3):
        out.append(Chunk(sp, "explain", "讲解", seg))
    for kp in doc.get("key_points", []) or []:
        out.append(Chunk(sp, "key_point", "要点", str(kp)))
    for ex in doc.get("examples", []) or []:
        txt = f"{ex.get('scene', '')}：{ex.get('good', '')}"
        out.append(Chunk(sp, "example", "示例", txt))
    for r in doc.get("resources", []) or []:
        out.append(Chunk(sp, "resource", "资源", f"{r.get('title', '')}｜{r.get('content', '')}"))
    for e in doc.get("exercises", []) or []:
        txt = e.get("stem") or e.get("question") or str(e)
        out.append(Chunk(sp, "exercise", "练习", txt))
    return out


FIELD_WEIGHT = {"title": 5.0, "key_point": 3.0, "resource": 1.5, "explain": 1.0, "example": 1.0, "exercise": 1.0}


class Retriever:
    K1 = 1.5
    B = 0.75

    def __init__(self, knowledge_dir: Path | None = None) -> None:
        self._dir = knowledge_dir or KNOWLEDGE_DIR
        self._chunks: list[Chunk] = []
        self._terms: list[Counter[str]] = []
        self._lens: list[int] = []
        self._df: Counter[str] = Counter()
        self._build()

    def _build(self) -> None:
        for p in sorted(self._dir.glob("*.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for ch in _chunks_for(doc):
                w = FIELD_WEIGHT.get(ch.field, 1.0)
                terms = Counter()
                for t in tokenize(ch.text):
                    terms[t] += w
                self._chunks.append(ch)
                self._terms.append(terms)
                self._lens.append(sum(terms.values()))
                for t in terms:
                    self._df[t] += 1
        total = sum(self._lens)
        self._avgdl = total / max(len(self._lens), 1)

    def search(self, sp: str, query: str, top_k: int = 8) -> list[tuple[Chunk, float]]:
        qterms = tokenize(query or "")
        n = len(self._chunks)
        scored: list[tuple[Chunk, float]] = []
        for i, ch in enumerate(self._chunks):
            if ch.sp != sp:
                continue
            terms = self._terms[i]
            dl = self._lens[i]
            denom = dl + self.K1 * (1 - self.B + self.B * dl / max(self._avgdl, 1))
            score = 0.0
            for t in set(qterms):
                tf = terms.get(t, 0.0)
                if tf <= 0:
                    continue
                df = self._df.get(t, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * (tf * (self.K1 + 1)) / (tf + denom)
            if score > 0:
                scored.append((ch, score))
        scored.sort(key=lambda x: -x[1])
        if not scored:
            # 空查询/无命中：回退到标题 + 前几条要点（稳定、可解释）
            fallback = [c for c in self._chunks if c.sp == sp and c.field in ("title", "key_point")]
            return [(c, 0.0) for c in fallback[:top_k]]
        return scored[:top_k]

    def render(self, sp: str, query: str, top_k: int = 8) -> dict:
        hits = self.search(sp, query, top_k)
        seen: set[str] = set()
        lines: list[str] = []
        sources: list[str] = []
        for ch, _ in hits:
            key = (ch.field, ch.text[:30])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"· {ch.text}")
            sources.append(f"{sp}·{ch.label}")
        return {"text": "\n".join(lines[:top_k]), "sources": list(dict.fromkeys(sources))}


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
