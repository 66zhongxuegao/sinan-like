"""按路由截图，用于 UI 走查与录屏前核对。

用法：python -X utf8 scripts/shot_pages.py [--base http://127.0.0.1:5182] route1 route2 ...
不带参数时截默认一组关键页面。
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "shots"

DEFAULT = [
    "/#/practice/orders/9000000000000004",
    "/#/practice/orders/9000000000000004/deliverables",
    "/#/practice/orders/9000000000000004/call",
    "/#/practice/im",
    "/#/practice/messages",
]


def slug(route: str) -> str:
    s = route.split("#")[-1].strip("/").replace("/", "-").replace("?", "_").replace("=", "-")
    return s or "index"


def main() -> int:
    args = [a for a in sys.argv[1:]]
    base = "http://127.0.0.1:5182"
    if "--base" in args:
        i = args.index("--base")
        base = args[i + 1]
        del args[i:i + 2]
    routes = args or DEFAULT
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--hide-scrollbars"])
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        ctx.add_init_script("try{localStorage.setItem('tc-user','u-demo')}catch(e){}")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        for r in routes:
            page.goto(base + r, wait_until="networkidle")
            page.wait_for_timeout(1200)
            f = OUT / f"{slug(r)}.png"
            page.screenshot(path=str(f))
            print("shot:", f)
        if errors:
            print("console errors:")
            for e in errors[:20]:
                print("  ", e)
        ctx.close()
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
