"""交付物导出 PDF —— reportlab + STSong-Light（reportlab 内置的中文 CID 字体，不依赖系统字体文件）。"""

from __future__ import annotations

import io
import re

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

FONT = "STSong-Light"
_ready = False

INK = HexColor("#16223a")
ACCENT = HexColor("#1a63c4")
MUTED = HexColor("#9aa8bb")
SECOND = HexColor("#6b7a90")
RULE = HexColor("#dbe3ef")


def _ensure_font() -> None:
    global _ready
    if not _ready:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _ready = True


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles() -> dict[str, ParagraphStyle]:
    """所有样式都必须显式指定自定义字体，否则 reportlab 会退回 Helvetica，中文变方框。"""

    def mk(name: str, **kw) -> ParagraphStyle:
        params = {"fontName": FONT, "fontSize": 10.5, "leading": 14.6, "textColor": INK}
        params.update(kw)
        return ParagraphStyle(name, **params)

    return {
        "h1": mk("h1", fontSize=16.5, leading=23, spaceAfter=5),
        "h2": mk("h2", fontSize=12, leading=17, spaceBefore=5.5, spaceAfter=0.5, textColor=ACCENT),
        "quote": mk("quote", fontSize=10, leading=16, textColor=SECOND, leftIndent=8),
        "body": mk("body"),
        "muted": mk("muted", textColor=MUTED),
        # 表格单元格：字号略小、行距紧一点，长文本换行不溢出
        "cell": mk("cell", fontSize=9, leading=12),
        "cellhead": mk("cellhead", fontSize=9, leading=12, textColor=ACCENT),
    }


_PIPE_ROW = re.compile(r"^\|.*\|$")
_PIPE_SEP = re.compile(r"^\|[\s:\-|]+\|$")


def _split_pipe(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [c.strip() for c in body.split("|")]


def _table(rows: list[list[str]], avail: float, st: dict) -> Table:
    """把管道表格行变成真实表格：等宽列 + 细网格 + 表头浅底，单元格自动换行。"""
    width = avail / max(1, len(rows[0]))
    data = [[Paragraph(_esc(c) or " ", st["cellhead" if r == 0 else "cell"])
             for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[width] * len(rows[0]), repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#eef3fb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def markdown_to_pdf(markdown: str, *, title: str = "", order_id: str = "", customer: str = "") -> bytes:
    """把交付物渲染出的 Markdown 转成 A4 PDF。只认工作台自己产出的这几种行，不做通用 Markdown。"""
    _ensure_font()
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=title or "交付物", author="TripCraft · 司南礼客",
                            subject=f"{title} {order_id} {customer}".strip())
    avail = doc.width
    story: list = []
    lines = (markdown or "").splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            story.append(Spacer(1, 2))
            i += 1
            continue
        # 管道表格：连续 |...| 行 → 真表格（第一行表头；紧跟的 |---| 分隔行丢弃）
        if _PIPE_ROW.match(s):
            block: list[list[str]] = []
            while i < len(lines) and _PIPE_ROW.match(lines[i].strip()):
                row = _split_pipe(lines[i])
                if not _PIPE_SEP.match(lines[i].strip()):
                    block.append(row)
                i += 1
            if block:
                cols = max(len(r) for r in block)
                block = [r + [""] * (cols - len(r)) for r in block]
                story.append(Spacer(1, 3))
                story.append(_table(block, avail, st))
                story.append(Spacer(1, 5))
            continue
        if s.startswith("### "):
            story.append(Paragraph(_esc(s[4:]), st["h2"]))
        elif s.startswith("## "):
            story.append(Paragraph(_esc(s[3:]), st["h2"]))
        elif s.startswith("# "):
            story.append(Paragraph(_esc(s[2:]), st["h1"]))
        elif s.startswith("> "):
            story.append(Paragraph(_esc(s[2:]), st["quote"]))
        elif set(s) <= set("-—") and len(s) >= 3:
            story.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=6, spaceAfter=6))
        else:
            text = _esc(re.sub(r"\*\*(.+?)\*\*", r"\1", s))
            story.append(Paragraph(text, st["muted"] if s.startswith("（未填写）") else st["body"]))
        i += 1
    doc.build(story)
    return buf.getvalue()
