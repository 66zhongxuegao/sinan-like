"""录制 README 用的演示动图（GIF）。

做法：Playwright 驱动真实页面 → 按固定节奏连续截图（PNG 帧）→ ffmpeg 合成带调色板的 GIF。
为了让动图看起来像"新手引导"，会注入一个假光标 + 点击涟漪，并把鼠标移动做成有轨迹的动画。

用法：
    python -X utf8 scripts/record_demo.py --flow practice --out docs/demo/03-practice.gif
    python -X utf8 scripts/record_demo.py --list
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "output" / "demo-frames"
FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
BASE = "http://127.0.0.1:5190"

VIEWPORT = {"width": 1280, "height": 760}
FPS = 6                     # 采集帧率（截图本身约 100ms/张，6fps 够用）
PALETTE_COLORS = 160
OUT_WIDTH = 960

CURSOR_JS = """
(() => {
  if (window.__demoCursorReady) return;
  window.__demoCursorReady = true;
  const c = document.createElement('div');
  c.id = '__demo_cursor';
  c.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;' +
    'transform:translate(-100px,-100px);transition:transform .06s linear;' +
    'filter:drop-shadow(0 2px 4px rgba(0,0,0,.35))';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M5 2.5l14.5 8.2-6.6 1.4L9.4 19z" fill="#1a63c4" stroke="#fff" stroke-width="1.6"/></svg>';
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(c));
  if (document.body) document.body.appendChild(c);
  addEventListener('mousemove', (e) => {
    c.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
  }, true);
  addEventListener('click', (e) => {
    const r = document.createElement('div');
    r.style.cssText = `position:fixed;left:${e.clientX - 14}px;top:${e.clientY - 14}px;width:28px;height:28px;` +
      'border-radius:50%;border:3px solid #2577e3;opacity:.9;pointer-events:none;z-index:2147483646';
    document.body.appendChild(r);
    r.animate([{transform:'scale(.6)',opacity:.95},{transform:'scale(2.1)',opacity:0}],
              {duration:420,easing:'cubic-bezier(.2,.7,.3,1)'}).onfinish = () => r.remove();
  }, true);
})();
"""


class Recorder:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.n = 0

    def shot(self, page) -> None:
        self.n += 1
        page.screenshot(path=str(self.out_dir / f"{self.n:04d}.png"))

    def hold(self, page, seconds: float) -> None:
        """保持当前画面若干秒（按采集帧率持续截图）。"""
        end = time.time() + seconds
        interval = 1.0 / FPS
        while time.time() < end:
            t0 = time.time()
            self.shot(page)
            time.sleep(max(0.0, interval - (time.time() - t0)))

    def move_to(self, page, selector: str, steps: int = 14) -> None:
        try:
            box = page.locator(selector).first.bounding_box(timeout=4000)
        except Exception:
            return
        if not box:
            return
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y, steps=steps)

    def click(self, page, selector: str, settle: float = 0.5, force: bool = False,
              optional: bool = False) -> None:
        self.move_to(page, selector)
        self.hold(page, 0.35)
        try:
            page.locator(selector).first.click(force=force, timeout=6000)
        except Exception as exc:
            tag = "可选步骤跳过" if optional else "警告：这一步没点成功"
            print(f"    {tag} [{selector}] {type(exc).__name__}")
            if not optional:
                self.hold(page, settle)
            return
        self.hold(page, settle)

    def try_click(self, page, selector: str, settle: float = 0.6, force: bool = False) -> bool:
        """可选步骤：元素不在、或点了没反应，都跳过，不阻塞录制。"""
        if page.locator(selector).count() == 0:
            return False
        self.click(page, selector, settle=settle, force=force, optional=True)
        return True

    def click_label(self, page, css: str, text: str, settle: float = 1.0, force: bool = True) -> bool:
        """在 css 集合里按文案找一个点（例如交付物的 8 个 .tab）。"""
        loc = page.locator(css).filter(has_text=text).first
        try:
            if loc.count() == 0:
                return False
            box = loc.bounding_box(timeout=4000)
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
            self.hold(page, 0.3)
            loc.click(force=force, timeout=6000)
        except Exception as exc:
            print(f"    可选步骤跳过 [{css} ~ {text}] {type(exc).__name__}")
            return False
        self.hold(page, settle)
        return True

    def type_text(self, page, selector: str, text: str, per_char: float = 0.06, index: int = 0) -> None:
        if page.locator(selector).count() <= index:
            print(f"    警告：输入框不存在 [{selector}]")
            return
        target = page.locator(selector).nth(index)
        try:
            box = target.bounding_box(timeout=4000)
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
            self.hold(page, 0.3)
            target.click(timeout=5000)
        except Exception as exc:
            print(f"    警告：输入框点不进去 [{selector}#{index}] {type(exc).__name__}")
            return
        for ch in text:
            page.keyboard.type(ch)
            if self.n % 3 == 0:
                self.shot(page)
            time.sleep(per_char)
        self.hold(page, 0.4)


def build_flow(page, rec: Recorder, name: str, user: str) -> None:
    # 注意：user 已经由 add_init_script 在页面脚本之前写进 localStorage，
    # 所以这里不再需要先打开首页——否则每张动图开头都会有几帧首页画面。
    if name == "quiz":
        page.goto(f"{BASE}/#/", wait_until="domcontentloaded")
        rec.hold(page, 1.4)                                 # 首页
        rec.click(page, ".hero-cta", settle=1.8)            # 首页「画像」→ 初始画像测评
        for _ in range(12):                                 # 12 题快速作答（每题选中后自动翻页）
            rec.click(page, ".opt", settle=0.40)
        rec.try_click(page, ".qcard .tc-btn", settle=0.8)   # 提交并生成画像
        rec.hold(page, 9.0)                                 # 画像 Agent 生成中：双环旋转 + 阶段提示
        rec.hold(page, 2.5)                                 # 结果页：掌握度环 + 八维雷达 + 学习建议

    elif name == "learn":
        page.goto(f"{BASE}/#/learn", wait_until="domcontentloaded")
        rec.hold(page, 1.6)                                 # 学习地图：双环节点
        rec.click(page, ".node.dim", settle=2.0, force=True)   # 展开一个维度（三级节点扇形铺开）
        rec.click(page, ".node.sp", settle=1.4, force=True)    # 点开一个技能点 → 小卡
        rec.hold(page, 1.0)
        rec.click(page, ".pc-btn", settle=2.0, force=True)     # 进入学习对话工作台
        rec.hold(page, 1.2)                                    # 右侧：教学/实战双环 + 题目难度曲线
        rec.click(page, ".tool-btn", settle=1.0, force=True)   # 生成个性化资源（讲义）
        rec.hold(page, 5.5)                                    # 多 Agent 调度浮层：召回 → 教研 → 六帽审查
        rec.try_click(page, ".a-item", settle=2.0, force=True)             # 生成结果：讲义预览

    elif name == "practice":
        page.goto(f"{BASE}/#/practice/messages", wait_until="domcontentloaded")
        rec.hold(page, 1.8)                                 # 消息中心
        rec.click(page, ".refresh", settle=2.2)             # 刷新＝按画像生成新派单
        rec.hold(page, 0.8)
        rec.click(page, ".grab-card .grab", settle=2.2)     # 抢单（会跳到订单管理）

    elif name == "call":
        page.goto(f"{BASE}/#/practice/orders/9000000000000005/call", wait_until="domcontentloaded")
        rec.hold(page, 1.4)                                 # 拨打前：品牌蓝按钮 + 语种/人设（English · 美国 · 男 · 47 岁）
        rec.click(page, ".c-start", settle=3.2, force=True)   # 点击拨打 → 呼吸动效 + 实时语音中继
        rec.hold(page, 3.5)                                    # 通话中：声波动画 + 状态在「客户正在说话 / 轮到你说话」之间切换
        rec.try_click(page, ".ctrl:not(.hang)", settle=1.2, force=True)   # 开/关麦克风
        rec.hold(page, 1.5)

    elif name == "system-calibration":                       # 人工校准集：指标 + 主链准入 + 跑校准
        page.goto(f"{BASE}/#/system", wait_until="domcontentloaded")
        rec.hold(page, 1.3)
        page.mouse.move(700, 500)
        for _ in range(3):                                  # 滚到「评分公信力 · 校准集」
            page.mouse.wheel(0, 300)
            rec.hold(page, 0.45)
        rec.hold(page, 1.6)                                 # 样本规模 / 档位覆盖 / 语言与客源覆盖
        rec.click_label(page, "button", "跑校准", settle=2.6)  # 触发一轮校准（评测中…）
        rec.hold(page, 1.0)

    elif name == "system-mcp":                               # MCP 工具契约：11 个工具
        page.goto(f"{BASE}/#/system", wait_until="domcontentloaded")
        rec.hold(page, 1.2)
        page.mouse.move(700, 500)
        for _ in range(6):                                  # 滚到「MCP 接口 · 资源能力标准化」
            page.mouse.wheel(0, 300)
            rec.hold(page, 0.4)
        rec.hold(page, 0.8)
        rec.try_click(page, ".mcp-row", settle=0.6, force=True)
        rec.hold(page, 1.4)
        rec.click_label(page, "button", "刷新", settle=1.4)
        rec.hold(page, 1.2)

    elif name == "profile-scroll":                          # 学情画像：往下滚动 + 展开能力维度
        page.goto(f"{BASE}/#/profile", wait_until="domcontentloaded")
        rec.hold(page, 1.6)                                 # 顶部：双环综合掌握度
        page.mouse.move(700, 500)
        for _ in range(4):                                  # 平滑下滚到能力维度明细
            page.mouse.wheel(0, 260)
            rec.hold(page, 0.5)
        rec.hold(page, 0.6)
        rec.click(page, ".dim-head", settle=1.8, force=True)  # 展开一个维度 → 逐技能点条形
        rec.hold(page, 1.6)
        page.mouse.wheel(0, 240)
        rec.hold(page, 1.2)

    elif name == "im-group":                                # 群聊：拉群 + 建群后在群里说话
        page.goto(f"{BASE}/#/practice/im", wait_until="domcontentloaded")
        rec.hold(page, 1.5)                                 # 聊天界面：会话与联系人
        rec.click(page, '.icon-btn[title="发起群聊"]', settle=1.2, force=True)
        rec.type_text(page, ".dlg input.ipt", "浙江 5 天 · 客户服务群")
        for i in range(2):                                  # 勾两位成员
            rec.try_click(page, f".pick-row:nth-child({i + 1}) input", settle=0.5, force=True)
        rec.hold(page, 0.6)
        rec.click_label(page, "button", "创建群聊", settle=2.0)
        rec.hold(page, 1.0)
        rec.type_text(page, ".ipt", "各位好，这单的行程与住宿我先同步一下，有问题随时在群里说。")
        rec.try_click(page, ".send", settle=3.5, force=True)
        rec.hold(page, 1.0)

    elif name == "vbooking-intake":                           # 接单流程 + vbooking 工作台界面
        page.goto(f"{BASE}/#/practice/messages", wait_until="domcontentloaded")
        rec.hold(page, 1.8)                                 # 消息中心：通知分类 + 待接单通知
        rec.click(page, ".refresh", settle=2.0)             # 刷新 → 新派单进入待接单
        rec.hold(page, 0.8)
        rec.click(page, ".grab-card .grab", settle=2.0, force=True)   # 抢单 → 订单管理（新单高亮）
        rec.hold(page, 1.2)
        rec.click(page, ".order.card", settle=2.2, force=True)        # 进入订单详情（平台字段）
        rec.hold(page, 2.0)
        page.mouse.move(700, 500)
        for _ in range(3):                                  # 向下浏览：客户信息 / 证件 / 跟进信息
            page.mouse.wheel(0, 260)
            rec.hold(page, 0.5)
        rec.hold(page, 1.5)

    elif name == "tools-score":                              # 外部数据查询 + 评分调用核验
        page.goto(f"{BASE}/#/toolbox", wait_until="domcontentloaded")
        rec.hold(page, 1.5)                                 # 工具台：路线 / 天气 / 汇率
        rec.type_text(page, "input.ipt", "上海外滩", index=0)
        rec.type_text(page, "input.ipt", "杭州西湖", index=1)
        rec.try_click(page, ".tc-btn.go", settle=3.8, force=True)   # 真实高德路线 + 静态地图 + 途经点
        rec.type_text(page, "input.ipt.sm", "杭州市", index=0)
        rec.try_click(page, ".mini-btn", settle=2.8, force=True)    # 真实天气（Open-Meteo + 高德地理编码）
        rec.hold(page, 0.8)
        page.goto(f"{BASE}/#/practice/orders/9000000000000004/score", wait_until="domcontentloaded")
        rec.hold(page, 1.7)                                 # 评分复盘：证据条数 / 覆盖校验 / 校准状态
        rec.try_click(page, "button.run", settle=1.2, force=True)   # 调用评分 Agent（服务端 API）
        rec.hold(page, 10.0)                                # 评分中 → 出分与档位
        rec.try_click(page, ".lnk", settle=1.6, force=True)         # 查看未覆盖项 → 去补考
        rec.hold(page, 1.5)

    elif name == "s0-brief":                                # S0/S1 接单交底：订单详情 + 完成条件进度
        page.goto(f"{BASE}/#/practice/orders/9000000000000001", wait_until="domcontentloaded")
        rec.hold(page, 1.6)                                 # 订单详情：客户、语言、证件、派单信息
        rec.try_click(page, ".fab", settle=1.6, force=True)  # 右下角进度：13 步走到哪 + 本步完成条件
        rec.hold(page, 2.2)

    elif name in DOC_FLOWS:                                  # 交付物：需求确认单 / 分项报价 / 合同与保险 / 出团通知书
        tab, order = DOC_FLOWS[name]
        page.goto(f"{BASE}/#/practice/orders/{order}/deliverables", wait_until="domcontentloaded")
        rec.hold(page, 1.5)                                  # 产出与投递：8 类真实交付物
        rec.click_label(page, ".tab", tab, settle=1.4)       # 切到本步骤要交的那份
        rec.hold(page, 0.6)
        rec.type_text(page, "input", "云南 5 日亲子游 · 2 大 1 小", index=0)
        rec.type_text(page, "input", "4 月中旬", index=1)
        rec.type_text(page, "textarea", "客户确认：人均 6-8k，住四星，含接送机与保险。", index=0)
        rec.try_click(page, ".submit-btn", settle=2.2, force=True)   # 提交并投递（先过双层拦截网）
        rec.try_click(page, ".modal .tc-btn", settle=1.6, force=True) # 若有「发在给谁」弹窗则确认
        rec.hold(page, 1.4)

    elif name == "s4-quote":                                 # 资源询价：在资源大群问地接社
        page.goto(f"{BASE}/#/practice/im", wait_until="domcontentloaded")
        rec.hold(page, 1.5)
        rec.click(page, ".row-item", settle=1.4, force=True)  # 打开资源大群
        rec.type_text(page, ".ipt", "地接社您好，云南 5 天 2 大 1 小，4 月中旬，想确认下用车+导游的报价和档期？")
        rec.try_click(page, ".send", settle=4.5, force=True)  # 资源方 Agent 给回执
        rec.hold(page, 1.2)

    elif name == "s5-plan":                                  # 行程方案：创建 → 发送给客户 → 客户已读
        page.goto(f"{BASE}/#/practice/orders/9000000000000001/plan/new", wait_until="domcontentloaded")
        rec.hold(page, 1.5)
        rec.type_text(page, "input", "云南 5 日亲子游 · 初稿", index=0)
        rec.hold(page, 0.5)
        rec.click_label(page, "button", "发送方案", settle=2.0)
        rec.hold(page, 6.0)                                  # 跳到客户单聊 → 客户已读并反馈
        rec.hold(page, 1.0)

    elif name == "s7-iterate":                              # S7 客户对方案有异议 → 学员给取舍方案
        page.goto(f"{BASE}/#/practice/im", wait_until="domcontentloaded")
        rec.hold(page, 1.5)
        rec.click_label(page, ".row-item", "客户P", settle=1.8)   # 客户P 单聊：里面有客户的异议
        rec.type_text(page, ".ipt", "收到，住宿我换成您之前看中的那家四星，交通改成高铁，报价重算完发您确认。")
        rec.try_click(page, ".send", settle=4.5, force=True)
        rec.hold(page, 1.2)

    elif name == "s10-incident":                            # S10 行中突发：车坏 → 安抚客户 + 压车队换车
        page.goto(f"{BASE}/#/practice/im", wait_until="domcontentloaded")
        rec.hold(page, 1.5)
        rec.click_label(page, ".row-item", "车出问题了", settle=1.8)   # 司导单聊：车辆故障
        rec.type_text(page, ".ipt", "先按两小时内换车的方向谈，同时告诉客人大概几点能走；我这边同步安抚客人。")
        rec.try_click(page, ".send", settle=4.5, force=True)
        rec.hold(page, 1.2)

    elif name == "s11-settle":                               # 行后结算：处理损失项 → 结账留档
        page.goto(f"{BASE}/#/practice/orders/9000000000000004/finance", wait_until="domcontentloaded")
        rec.hold(page, 1.6)
        rec.try_click(page, ".entry", settle=1.0, force=True)
        rec.click_label(page, "button", "结账并留档", settle=2.2)
        rec.hold(page, 1.4)

    elif name == "score":
        page.goto(f"{BASE}/#/score", wait_until="domcontentloaded")
        rec.hold(page, 1.6)                                 # 评分复盘：按订单下钻
        rec.try_click(page, ".order.card", settle=2.4)      # 展开某单 → 逐技能点分数与档位
        rec.hold(page, 1.6)

    elif name == "profile":
        page.goto(f"{BASE}/#/profile", wait_until="domcontentloaded")
        rec.hold(page, 1.8)                                 # 学情画像：双环总览 + 画像记忆
        rec.click(page, ".mem-refresh", settle=1.0)         # 更新画像（按钮转圈）
        rec.hold(page, 9.0)                                 # 画像 Agent 重读掌握度/实战/答题后重出结论
        rec.hold(page, 2.0)


# 名称 -> (说明, 播放倍速)。录制是按 6fps 实时采集，倍速只影响播放快慢（帧数不变）
# 13 步实战里"交付物"类步骤：tab 名 -> 用哪一单（挑阶段匹配的订单，界面才有意义）
DOC_FLOWS = {
    "s3-need":     ("需求确认单", "9000000000000001"),   # 阶段1 定制师提供方案
    "s6-price":    ("分项报价单", "9000000000000001"),
    "s8-contract": ("合同与保险", "9000000000000004"),   # 阶段4 客户确认合同
    "s9-notice":   ("出团通知书", "9000000000000004"),
}

FLOWS = {
    "quiz":     ("1 首页 → 初始画像测评 → 生成画像", 1.8),
    "learn":    ("2 学习地图 → 技能点对话 → 生成个性化资源（多 Agent）", 1.4),
    "practice": ("3 消息中心刷新派单 → 抢单 → 订单管理", 1.0),
    "call":     ("4 拨打电话 → 语音界面 → 切文字与客户对话", 1.2),
    "score":    ("5 评分复盘按订单下钻", 1.0),
    "profile":  ("6 更新画像 → 画像记忆刷新", 1.8),
    "system-calibration": ("人工校准集：指标与跑校准", 1.6),
    "system-mcp":  ("MCP 工具契约与工具列表", 1.8),
    "profile-scroll": ("学情画像：下滑 + 展开维度", 1.2),
    "im-group":    ("群聊：拉群 → 群里发消息", 1.3),
    "vbooking-intake": ("接单流程与 vbooking 工作台界面", 1.4),
    "tools-score": ("工具台查询（真实高德/天气）+ 评分调用与覆盖校验", 1.6),
    "s0-brief":    ("S0 接单交底 → 订单详情 + 完成条件进度", 1.3),
    "s3-need":     ("S3 需求结构化确认 → 需求确认单", 1.3),
    "s4-quote":    ("S4 资源询价 → 资源大群问地接社", 1.2),
    "s5-plan":     ("S5 行程方案 → 发送方案 → 客户已读", 1.4),
    "s6-price":    ("S6 分项报价 → 提交报价单", 1.3),
    "s8-contract": ("S8 合同与保险 → 提交", 1.3),
    "s9-notice":   ("S9 出团通知书 → 发群", 1.3),
    "s7-iterate":  ("S7 客户反馈与迭代 → 给取舍方案", 1.2),
    "s10-incident":("S10 行中突发 → 车坏应急处理", 1.2),
    "s11-settle":  ("S11 行后结算 → 结账留档", 1.2),
}


def encode(frames_dir: Path, out_gif: Path, speed: float = 1.0) -> None:
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"fps={FPS * speed:.2f},scale={OUT_WIDTH}:-1:flags=lanczos,split[a][b];"
          f"[a]palettegen=max_colors={PALETTE_COLORS}:stats_mode=diff[p];"
          f"[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle")
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS),
           "-i", str(frames_dir / "%04d.png"), "-vf", vf, "-loop", "0", str(out_gif)]
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg 失败：", r.stderr[-400:])
        raise SystemExit(1)
    print(f"  {out_gif.name}  {out_gif.stat().st_size / 1024:.0f} KB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list or not args.flow:
        for k, (desc, sp) in FLOWS.items():
            print(f"  {k:9} {sp}x  {desc}")
        return 0

    if args.flow not in FLOWS:
        print(f"未知流程：{args.flow}")
        return 1

    # 初始画像只对新账号开放，所以每次录制都用一个新 user id
    user = f"u-gif-{int(time.time())}" if args.flow == "quiz" else "u-demo"
    if FRAMES.exists():
        shutil.rmtree(FRAMES, ignore_errors=True)
    FRAMES.mkdir(parents=True)

    rec = Recorder(FRAMES)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--use-fake-ui-for-media-stream",       # 免权限弹窗，方便录语音界面
            "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
        ])
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        # 在页面脚本之前把当前用户写进 localStorage：这样无需先访问首页，动图开头不会多出首页画面
        ctx.add_init_script(f"try {{ localStorage.setItem('tc-user', '{user}'); }} catch (e) {{}}")
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        t0 = time.time()
        build_flow(page, rec, args.flow, user)
        browser.close()

    print(f"采集 {rec.n} 帧，用时 {time.time() - t0:.0f}s")
    out = Path(args.out) if args.out else ROOT / "docs" / "demo" / f"{args.flow}.gif"
    speed = args.speed if args.speed != 1.0 else FLOWS[args.flow][1]
    print(f"播放倍速 {speed}x")
    encode(FRAMES, out, speed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
