"""像评委一样把公网演示走一遍，收集控制台/网络错误与界面异常。

    python -X utf8 scripts/judge_walkthrough.py [base_url]

默认走隧道地址（评委看到的版本）；截图落在 output/judge-walk/。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "judge-walk"
BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://tin-consequently-tomorrow-remedies.trycloudflare.com").rstrip("/")

errors: list[str] = []
notes: list[str] = []


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        ctx = browser.new_context(viewport={"width": 1600, "height": 950}, locale="zh-CN")
        page = ctx.new_page()

        page.on("console", lambda m: errors.append(f"[console.{m.type}] {m.text[:200]}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {str(e)[:200]}"))
        page.on(
            "response",
            lambda r: errors.append(f"[http {r.status}] {r.url.replace(BASE, '')[:160]}")
            if r.status >= 400
            else None,
        )

        def step(name: str, path: str, wait: float = 2.5, shot: bool = True) -> None:
            url = f"{BASE}/#{path}"
            try:
                page.goto(url, wait_until="load", timeout=45000)
                page.wait_for_timeout(int(wait * 1000))
                body = page.inner_text("body")[:4000]
                if shot:
                    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
                flags = []
                for kw in ("暂无", "失败", "错误", "超时", "加载中"):
                    if kw in body:
                        flags.append(kw)
                notes.append(f"{name:22s} {path:34s} 文本 {len(body):5d} 字  {('含: ' + ','.join(flags)) if flags else ''}")
            except Exception as exc:
                notes.append(f"{name:22s} {path:34s} 打不开: {str(exc)[:120]}")
                errors.append(f"[step {name}] {str(exc)[:160]}")

        # --- 评委路径 ---
        step("01-首页", "/")
        step("02-消息中心", "/practice/messages", wait=3.5)
        # 刷新生成新派单（消息中心里的刷新按钮）
        try:
            btn = page.get_by_text("刷新", exact=False).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(4000)
                page.screenshot(path=str(OUT / "03-刷新后.png"))
                notes.append("03-刷新派单           已点击刷新")
        except Exception as exc:
            notes.append(f"03-刷新派单           点不到: {str(exc)[:80]}")

        step("04-订单管理", "/practice", wait=3.0)
        order_id = ""
        try:
            links = page.eval_on_selector_all(
                "a[href*='/practice/orders/']",
                "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
            )
            ids = []
            for href in links:
                part = href.split("/practice/orders/")[-1].split("/")[0].split("?")[0]
                if part.isdigit() and part not in ids:
                    ids.append(part)
            order_id = ids[0] if ids else ""
            notes.append(f"04b-订单 id           {ids[:4]}")
        except Exception as exc:
            notes.append(f"04b-订单 id           取不到: {str(exc)[:80]}")

        if order_id:
            for name, sub in (("05-订单详情", ""), ("06-通话页", "/call"),
                              ("07-产出与投递", "/deliverables"), ("08-成本结算", "/finance")):
                step(name, f"/practice/orders/{order_id}{sub}", wait=3.0)

        # 真拨一次电话（假麦克风，验证隧道下语音可用）
        if order_id:
            try:
                page.goto(f"{BASE}/#/practice/orders/{order_id}/call", wait_until="load", timeout=45000)
                page.wait_for_timeout(2000)
                start = page.get_by_text("点击拨打", exact=False).first
                if start.is_visible():
                    start.click()
                    page.wait_for_timeout(9000)
                    page.screenshot(path=str(OUT / "09-通话中.png"))
                    body = page.inner_text("body")
                    notes.append("09-拨打电话           已点击，页面含'接通'=" + str("接通" in body) + " 含'说话'=" + str("说话" in body))
                else:
                    notes.append("09-拨打电话           找不到按钮")
            except Exception as exc:
                notes.append(f"09-拨打电话           失败: {str(exc)[:100]}")

        step("10-聊天界面", "/practice/im", wait=3.5)
        step("11-学习地图", "/learn", wait=3.0)
        step("12-技能点工作台", "/learn/thread/C1.1", wait=3.5)
        step("13-学情画像", "/profile", wait=3.5)
        step("14-工具台", "/toolbox", wait=3.0)
        step("15-系统状态", "/system", wait=3.0)

        browser.close()

    print("=== 每一步 ===")
    for n in notes:
        print("  " + n)
    print()
    print("=== 错误 ===")
    seen = []
    for e in errors:
        if e not in seen:
            seen.append(e)
    for e in seen[:40]:
        print("  " + e)
    print(f"  合计 {len(seen)} 类")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())