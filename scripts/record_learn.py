# -*- coding: utf-8 -*-
"""录制「学习地图 -> 教学部分」这一段真实前端操作。

做法：Playwright 开浏览器并开启连续录像（webm），注入假光标 + 点击涟漪，
用真实鼠标移动与真实点击驱动页面，结束后统一转成 mp4 / gif。

用法：
    python -X utf8 scripts/record_learn.py
    python -X utf8 scripts/record_learn.py --base http://127.0.0.1:5190
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
VID = ROOT / "output" / "learn-video"
OUT_MP4 = ROOT / "docs" / "demo" / "learn-teach.mp4"
OUT_GIF = ROOT / "docs" / "demo" / "learn-teach.gif"
FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"

VIEWPORT = {"width": 1440, "height": 900}

CURSOR_JS = """
(() => {
  if (window.__demoCursorReady) return;
  window.__demoCursorReady = true;
  const c = document.createElement('div');
  c.id = '__demo_cursor';
  c.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;' +
    'transform:translate(-100px,-100px);transition:transform .05s linear;' +
    'filter:drop-shadow(0 3px 6px rgba(8,49,97,.45))';
  c.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24">' +
    '<path d="M5 2.5l14.5 8.2-6.6 1.4L9.4 19z" fill="#083161" stroke="#ffffff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  const mount = () => { if (document.body) document.body.appendChild(c); };
  mount();
  document.addEventListener('DOMContentLoaded', mount);
  addEventListener('mousemove', (e) => {
    c.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
  }, true);
  addEventListener('click', (e) => {
    const wrap = document.createElement('div');
    wrap.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;pointer-events:none;z-index:2147483646`;
    wrap.innerHTML = '<span style="position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;' +
      'border-radius:50%;border:3px solid #083161;display:block;animation:__rip .8s cubic-bezier(.22,.61,.36,1) forwards">' +
      '</span><span style="position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;' +
      'border:3px solid #083161;display:block;opacity:.55;animation:__rip .8s cubic-bezier(.22,.61,.36,1) .12s forwards"></span>';
    if (!document.getElementById('__rip_kf')) {
      const st = document.createElement('style');
      st.id = '__rip_kf';
      st.textContent = '@keyframes __rip{from{transform:scale(.35);opacity:.95}to{transform:scale(5);opacity:0}}';
      document.head.appendChild(st);
    }
    document.body.appendChild(wrap);
    setTimeout(() => wrap.remove(), 1100);
  }, true);
})();
"""

TAGS = "a,button,[role=button],.node,.item,.qbtn,.row-item,.ptr,.act"


def find_point(page, texts, tags=TAGS):
    """按文字找可点元素，返回屏幕坐标（顺带滚到可视区）。"""
    if isinstance(texts, str):
        texts = [texts]
    return page.evaluate(
        """(args) => {
          const [texts, tags] = args;
          const els = [...document.querySelectorAll(tags)];
          for (const raw of texts) {
            const t = raw.replace(/\\s+/g, '');
            const el = els.find((e) => {
              const r = e.getBoundingClientRect();
              if (r.width < 2 || r.height < 2) return false;
              return (e.innerText || '').replace(/\\s+/g, '').includes(t);
            });
            if (el) {
              el.scrollIntoView({ block: 'center' });
              const r = el.getBoundingClientRect();
              return { x: r.left + Math.min(r.width / 2, 90), y: r.top + r.height / 2,
                       hit: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 30) };
            }
          }
          return null;
        }""",
        [texts, tags],
    )


def tap(page, texts, wait=1.4, tags=TAGS, label=""):
    pt = find_point(page, texts, tags)
    if not pt:
        print(f"  [miss] {label or texts}")
        return False
    page.mouse.move(pt["x"], pt["y"], steps=26)
    time.sleep(0.35)
    page.mouse.click(pt["x"], pt["y"])
    print(f"  [ok] {label or texts} -> {pt['hit']}")
    time.sleep(wait)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5190")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    if VID.exists():
        shutil.rmtree(VID)
    VID.mkdir(parents=True, exist_ok=True)
    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--window-size=1460,960"])
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1,
                                  record_video_dir=str(VID), record_video_size=VIEWPORT)
        page = ctx.new_page()
        page.add_init_script(CURSOR_JS)

        print("1) 打开学习地图")
        page.goto(args.base + "/#/learn", wait_until="domcontentloaded")
        page.wait_for_selector(".node", timeout=20000)
        page.wait_for_timeout(2200)

        print("2) 第一层点文化桥")
        tap(page, ["文化桥"], wait=1.8)

        print("3) 第二层点中马文化桥")
        if not tap(page, ["中马文化桥", "中马", "马来西亚"], wait=1.8):
            tap(page, ["文化桥"], wait=1.0)
            tap(page, ["中马文化桥", "中马", "马来西亚"], wait=1.8)

        print("4) 点「进入学习」进跨文化训练")
        tap(page, ["进入学习"], wait=1.8)
        try:
            page.wait_for_selector("textarea.ipt", timeout=15000)
        except Exception:
            print("   [warn] 没等到输入框，直接跳 C8.2")
            page.goto(args.base + "/#/learn/thread/C8.2", wait_until="domcontentloaded")
            page.wait_for_selector("textarea.ipt", timeout=15000)
        page.wait_for_timeout(1800)

        print("5) 点提示词")
        tap(page, ["讲解", "国别沟通", "沟通风格"], wait=1.6, tags="button,.qbtn,.ptr")

        print("6) 点发送")
        tap(page, ["发送"], wait=1.5, tags="button")

        print("7) 等司南多 Agent 过程与个性化资源")
        page.wait_for_timeout(12000)

        print("8) 展开溯源")
        tap(page, ["展开溯源"], wait=2.4, tags="button,.trace-toggle")
        page.wait_for_timeout(1200)

        print("9) 点左侧个性化资源")
        tap(page, ["实操指南", "讲义", "学习报告"], wait=4.0, tags="button,.qbtn")
        page.wait_for_timeout(1800)

        ctx.close()
        browser.close()

    webm = sorted(VID.glob("*.webm"))
    if not webm:
        raise SystemExit("没有拿到录像文件")
    src = webm[0]
    print("raw:", src)

    if Path(FFMPEG).exists():
        subprocess.run([FFMPEG, "-y", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "20", "-movflags", "+faststart", str(OUT_MP4)],
                       capture_output=True)
        subprocess.run([FFMPEG, "-y", "-i", str(src), "-vf",
                        "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=200[p];[b][p]paletteuse",
                        str(OUT_GIF)], capture_output=True)
        print("mp4:", OUT_MP4)
        print("gif:", OUT_GIF)
    else:
        print("ffmpeg 不在，保留 webm:", src)


if __name__ == "__main__":
    main()
