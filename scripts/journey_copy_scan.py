"""学员可见文案扫描（可重跑）：实现语言不得出现在学生看得到的地方。

监督者 item 4：学生界面不得出现「契约 / 口径 / 原子评分 / DTO / 接口未返回 / 阶段归属」这类实现语言。

判定口径（只认**学生真的会看到**的两类文本，避免把代码误判）：
  A. JS/TS 里含中文的字符串字面量（单引号、双引号、反引号）——这些通常就是文案；
  B. `.vue` 模板里的纯文本节点（剥掉 `<script>`/`<style>`/注释与标签之后剩下的文本）。
注释、变量名、属性名（如 `r.next_action`）一律不算。

用法：
    python scripts/journey_copy_scan.py                     # 扫 journey 域学员界面
    python scripts/journey_copy_scan.py <file> [file ...]    # 扫指定文件
退出码：0 = 无命中；1 = 有命中（逐条打印 文件:行: [关键词] 原文）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BANNED = ("契约", "口径", "原子评分", "原子", "DTO", "阶段归属", "接口未返回", "接口返回",
          "落库", "schema", "payload", "后端", "端点", "接口", "服务端", "render", "字段")

CJK = r"\u4e00-\u9fff"
STRING_RE = re.compile(r"['\"`]([^'\"`\n]*)['\"`]")
SCRIPT_RE = re.compile(r"<script.*?</script>", flags=re.S | re.I)
STYLE_RE = re.compile(r"<style.*?</style>", flags=re.S | re.I)
TAG_RE = re.compile(r"<[^>]*>")

DEFAULT_FILES = (
    "frontend/src/views/practice/DeliverableWorkbenchView.vue",
    "frontend/src/views/vbooking/PlanNewView.vue",
    "frontend/src/views/vbooking/OrderDetailView.vue",
    "frontend/src/views/vbooking/orderDetailDocs.ts",
    "frontend/src/views/practice/PracticeView.vue",
    "frontend/src/views/practice/FinanceView.vue",
    "frontend/src/components/ProgressDock.vue",
    "frontend/src/components/StageNav.vue",
    "frontend/src/components/StepBar.vue",
    "frontend/src/views/HomeView.vue",
)


def strip_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)//.*$", "", text)


def quoted_cjk_strings(text: str):
    """含中文的字符串字面量（行号, 内容）。"""
    for i, line in enumerate(text.splitlines(), 1):
        for m in STRING_RE.finditer(line):
            s = m.group(1)
            if s and re.search(f"[{CJK}]", s):
                yield i, s


def template_text(text: str):
    """.vue 模板里的纯文本节点（行号, 文本）。"""
    tpl = SCRIPT_RE.sub("", text)
    tpl = STYLE_RE.sub("", tpl)
    for i, line in enumerate(tpl.splitlines(), 1):
        plain = TAG_RE.sub("\n", line)
        for part in plain.split("\n"):
            part = part.strip()
            if part and re.search(f"[{CJK}]", part):
                yield i, part


def scan(paths) -> list[str]:
    hits: list[str] = []
    for rel in paths:
        p = Path(rel)
        if not p.is_absolute():
            p = ROOT / rel
        if not p.exists():
            hits.append(f"{rel}: 文件不存在")
            continue
        body = strip_comments(p.read_text(encoding="utf-8", errors="ignore"))
        seen = set()
        for i, s in quoted_cjk_strings(body):
            for kw in BANNED:
                if kw in s and (i, kw, s) not in seen:
                    seen.add((i, kw, s))
                    hits.append(f"{rel}:{i}: [字符串·{kw}] {s.strip()[:120]}")
        if p.suffix == ".vue":
            for i, s in template_text(body):
                for kw in BANNED:
                    if kw in s and (i, kw, s) not in seen:
                        seen.add((i, kw, s))
                        hits.append(f"{rel}:{i}: [模板文本·{kw}] {s.strip()[:120]}")
    return hits


def main(argv: list[str]) -> int:
    paths = argv[1:] or list(DEFAULT_FILES)
    hits = scan(paths)
    print(f"扫描文件 {len(paths)} 个；命中 {len(hits)} 条")
    for h in hits:
        print("  " + h)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
