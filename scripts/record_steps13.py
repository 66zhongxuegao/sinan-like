"""录制 13 步实战连续录屏（1920×1080 webm，真实逐项点击 + 逐步校验）。

对应 `video/web-story/13步录屏脚本要求.md`。与上一版的区别：

1. **同一单跑完**：刷新拿新派单 → 抢单 → 之后 13 步都用这一单，右下角流程进度真实推进。
2. **发送点对地方**：聊天统一点输入框右下角的 `.tc-btn.send`，不再点输入框上方的「＋发送」。
3. **交付物真填真投**：行程方案、分项报价、合同、出团通知书等每一项都逐字段输入再提交。
4. **每步都校验**：提交后断言「左侧标签已投递 + 服务端 gate/flow 已推进」，并各存一张截图到
   `video/web-story/steps13-check/`，方便逐张核对。

输出：
  - video/web-story/journey/steps13.webm
  - video/web-story/steps13-frames/S0..S12.png（抽帧）
  - video/web-story/steps13-check/*.png（每步校验截图）
  - video/web-story/journey/steps13-marks.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:5182"
OUT_DIR = ROOT / "video" / "web-story" / "journey"
FRAME_DIR = ROOT / "video" / "web-story" / "steps13-frames"
CHECK_DIR = ROOT / "video" / "web-story" / "steps13-check"
TMP_VIDEO = ROOT / "output" / "steps13-video"
FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"

CURSOR_JS = r"""
function initCursor(){
  if(document.getElementById('demo-cursor'))return;
  const st=document.createElement('style');
  st.textContent='#demo-cursor{position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:99999;filter:drop-shadow(0 2px 6px rgba(0,20,60,.45))}'+
    '#demo-cursor svg{position:absolute;left:0;top:0;transform:translate(-4px,-4px)}'+
    '.demo-ripple{position:fixed;width:24px;height:24px;border-radius:50%;border:3px solid #2577e3;background:rgba(37,119,227,.2);transform:translate(-50%,-50%);pointer-events:none;z-index:99998;animation:rip .7s ease-out forwards}'+
    '@keyframes rip{to{width:140px;height:140px;opacity:0}}';
  document.head.appendChild(st);
  const c=document.createElement('div');c.id='demo-cursor';
  c.innerHTML='<svg width="30" height="30" viewBox="0 0 24 24"><path d="M5 2 L21 11 L13.5 13 L8.5 21 Z" fill="#2577e3" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  document.addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px';});
  document.addEventListener('click',e=>{const r=document.createElement('div');r.className='demo-ripple';
    r.style.left=e.clientX+'px';r.style.top=e.clientY+'px';document.body.appendChild(r);setTimeout(()=>r.remove(),750);});
}
if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',initCursor);}else{initCursor();}
"""

FETCH_JS = """async ([path, method, body]) => {
  const init = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== null && body !== undefined) init.body = JSON.stringify(body);
  const r = await fetch('/api' + path, init);
  return await r.text();
}"""


class Rec:
    """一次录屏的动作集合：所有交互都走真实鼠标，所有结论都留下证据与截图。"""

    def __init__(self, page, base: str) -> None:
        self.page = page
        self.base = base
        self.marks: list[list] = []
        self.checks: list[tuple[str, bool, str]] = []
        self.t0 = time.time()

    # ---------------------------------------------------------------- 基础
    def hold(self, sec: float) -> None:
        if sec > 0:
            self.page.wait_for_timeout(int(sec * 1000))

    def mark(self, name: str) -> None:
        self.marks.append([name, round(time.time() - self.t0, 2)])
        print(f"[{name}] t={time.time() - self.t0:.1f}s")

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, bool(ok), detail))
        print(f"    {'OK ' if ok else '×  '}{name}{(' · ' + detail) if detail else ''}")
        return bool(ok)

    def goto(self, path: str, wait: float = 1.6) -> None:
        self.page.goto(self.base + path, wait_until="domcontentloaded")
        self.hold(wait)

    def snap(self, tag: str) -> Path:
        f = CHECK_DIR / f"{tag}.png"
        self.page.screenshot(path=str(f))
        return f

    def api(self, path: str, method: str = "GET", body=None):
        txt = self.page.evaluate(FETCH_JS, [path, method, body])
        try:
            return json.loads(txt)
        except Exception:
            return {"_raw": txt}

    # ---------------------------------------------------------------- 鼠标
    def _locate(self, sel: str, index: int = 0, by_text: str = ""):
        loc = self.page.locator(sel)
        if by_text:
            loc = loc.filter(has_text=by_text)
        return loc.nth(index)

    def _hover(self, loc) -> bool:
        try:
            b = loc.bounding_box(timeout=6000)
        except Exception:
            b = None
        if not b:
            return False
        self.page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=14)
        return True

    def click(self, sel: str, index: int = 0, by_text: str = "", settle: float = 0.5,
              move: float = 0.22, required: bool = True, also_text: str = "") -> bool:
        loc = self._locate(sel, index, by_text)
        if also_text:
            loc = loc.filter(has_text=also_text)
        if loc.count() == 0:
            if required:
                self.check(f"点击 {sel} {by_text}".strip(), False, "找不到元素")
            print(f"    ! 找不到 {sel} {by_text}")
            return False
        self._hover(loc)
        self.hold(move)
        try:
            loc.click(force=True, timeout=8000)
        except Exception as exc:
            self.check(f"点击 {sel} {by_text}".strip(), False, type(exc).__name__)
            print(f"    ! 点击失败 {sel} {by_text}: {type(exc).__name__}")
            return False
        self.hold(settle)
        return True

    def click_child(self, parent: str, child: str, parent_text: str = "", settle: float = 0.5,
                    required: bool = True) -> bool:
        """在某个父节点内部点按钮：抢单卡片的「抢单」、通讯录里的「添加」都用它。"""
        loc = self.page.locator(parent)
        if parent_text:
            loc = loc.filter(has_text=parent_text)
        child_loc = loc.first.locator(child).first
        if child_loc.count() == 0:
            if required:
                self.check(f"点击 {parent}[{parent_text}] > {child}", False, "找不到元素")
            print(f"    ! 找不到 {parent}[{parent_text}] > {child}")
            return False
        self._hover(child_loc)
        self.hold(0.22)
        try:
            child_loc.click(force=True, timeout=8000)
        except Exception as exc:
            self.check(f"点击 {parent}[{parent_text}] > {child}", False, type(exc).__name__)
            return False
        self.hold(settle)
        return True

    def type_in(self, sel: str, text: str, index: int = 0, by_text: str = "",
                delay: int = 20, settle: float = 0.2) -> bool:
        loc = self._locate(sel, index, by_text)
        if loc.count() == 0:
            self.check(f"输入 {sel} {by_text}".strip(), False, "找不到输入框")
            print(f"    ! 找不到输入框 {sel} {by_text}")
            return False
        self._hover(loc)
        self.hold(0.16)
        try:
            loc.click(timeout=8000)
            loc.fill("")
            loc.type(text, delay=delay)
        except Exception as exc:
            self.check(f"输入 {sel} {by_text}".strip(), False, type(exc).__name__)
            return False
        self.hold(settle)
        return True

    def scroll(self, px: int, times: int = 1, pause: float = 0.5) -> None:
        self.page.mouse.move(960, 620)
        for _ in range(times):
            self.page.mouse.wheel(0, px)
            self.hold(pause)

    def wait_for(self, sel: str, timeout: float = 20.0) -> bool:
        try:
            self.page.wait_for_selector(sel, timeout=int(timeout * 1000))
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- 交付物表单
    def field(self, label: str):
        return self.page.locator(".fld").filter(has=self.page.locator(".lb", has_text=label)).first

    def fill_field(self, label: str, value: str, delay: int = 18) -> bool:
        box = self.field(label)
        if box.count() == 0:
            self.check(f"填写「{label}」", False, "找不到字段")
            print(f"    ! 找不到字段 {label}")
            return False
        el = box.locator("input, textarea").first
        self._hover(el)
        self.hold(0.14)
        try:
            el.click(timeout=8000)
            # 日期框的分段输入用 type 会串位，直接 fill("YYYY-MM-DD")
            if (el.get_attribute("type") or "") == "date":
                el.fill(value)
            else:
                el.fill("")
                el.type(value, delay=delay)
        except Exception as exc:
            self.check(f"填写「{label}」", False, type(exc).__name__)
            return False
        self.hold(0.2)
        return True

    def row_count(self, label: str) -> int:
        return self.field(label).locator("tbody tr").count()

    def fill_rows(self, label: str, rows: list[list[str]], delay: int = 16) -> bool:
        box = self.field(label)
        if box.count() == 0:
            self.check(f"填写「{label}」表格", False, "找不到表格")
            return False
        while self.row_count(label) < len(rows):
            add = box.locator("button.add")
            if add.count() == 0:
                break
            self._hover(add.first)
            self.hold(0.16)
            add.first.click(force=True)
            self.hold(0.35)
        for r, values in enumerate(rows):
            tr = self.field(label).locator("tbody tr").nth(r)
            for c, value in enumerate(values):
                if not value:
                    continue
                cell = tr.locator("input").nth(c)
                self._hover(cell)
                self.hold(0.08)
                try:
                    cell.click(timeout=6000)
                    cell.fill("")
                    cell.type(value, delay=delay)
                except Exception:
                    return False
            self.hold(0.15)
        return True

    def select_field(self, label: str, value: str) -> bool:
        box = self.field(label)
        if box.count() == 0:
            self.check(f"选择「{label}」", False, "找不到下拉")
            return False
        sel = box.locator("select").first
        self._hover(sel)
        self.hold(0.14)
        try:
            sel.select_option(value=value, timeout=6000)
        except Exception as exc:
            self.check(f"选择「{label}」= {value}", False, type(exc).__name__)
            return False
        self.hold(0.2)
        return True


# ==================================================================== 13 步
def open_deliverable(rec: Rec, oid: str, code: str, title: str) -> bool:
    """切交付物必须点左侧标签：同一路由只换 query 不会重挂组件，表单不会跟着换。"""
    rec.goto(f"/#/practice/orders/{oid}/deliverables", 1.6)
    rec.click(".tab", by_text=title, settle=0.9, required=False)
    ok = False
    for _ in range(24):
        try:
            if rec.page.locator(".fh-title").first.inner_text(timeout=1500).strip() == title:
                ok = True
                break
        except Exception:
            pass
        rec.hold(0.5)
    rec.check(f"打开交付物「{title}」", ok, code)
    rec.hold(0.4)
    return ok


# 目的地对应的城市与景点：派单目的地由生成器给出，文案必须跟着它走，否则客户一眼看出矛盾
DEST_SPOTS: dict[str, tuple[str, str, str, str]] = {
    "西藏": ("拉萨", "布达拉宫 · 大昭寺", "纳木错", "羊卓雍措"),
    "云南": ("昆明", "大理古城", "丽江古城", "玉龙雪山"),
    "新疆": ("乌鲁木齐", "天山天池", "喀纳斯", "吐鲁番"),
    "四川": ("成都", "都江堰", "九寨沟", "峨眉山"),
    "浙江": ("杭州", "西湖 · 灵隐寺", "乌镇", "千岛湖"),
    "江苏": ("南京", "中山陵 · 夫子庙", "苏州园林", "扬州古运河"),
    "广西": ("桂林", "漓江 · 象鼻山", "阳朔西街", "龙脊梯田"),
    "贵州": ("贵阳", "甲秀楼 · 南明河", "西江千户苗寨", "黄果树瀑布"),
    "湖南": ("长沙", "岳麓山 · 橘子洲", "张家界", "凤凰古城"),
    "青海": ("西宁", "塔尔寺", "青海湖", "茶卡盐湖"),
    "重庆": ("重庆", "洪崖洞 · 解放碑", "武隆天生三桥", "大足石刻"),
    "福建": ("福州", "三坊七巷", "厦门鼓浪屿", "武夷山"),
    "陕西": ("西安", "兵马俑 · 城墙", "华山", "法门寺"),
    "北京": ("北京", "故宫 · 天安门", "八达岭长城", "颐和园"),
    "甘肃": ("兰州", "莫高窟", "张掲丹霞", "嘉峪关"),
    "内蒙古": ("呼和浩特", "希拉穆仁草原", "响沙湾", "成吉思汗陵"),
    "海南": ("海口", "三亚亚龙湾", "蜜支洲岛", "南山文化旅游区"),
    "广东": ("广州", "永庆坊 · 陈家祠", "开平碉楼", "丹霞山"),
    "安徽": ("合肥", "黄山", "宏村", "九华山"),
    "山东": ("济南", "泰山", "曲阜三孔", "青岛海滨"),
    "河北": ("石家庄", "正定古城", "承德避暑山庄", "崔院"),
    "河南": ("郑州", "嵩山少林寺", "龙门石窟", "开封清明上河园"),
}


def dest_profile(dest: str) -> tuple[str, str, str, str]:
    """按目的地给出可用的城市与景点组合；没有画像的目的地就不硬编具体景点。"""
    key = (dest or "").strip()
    for name, spots in DEST_SPOTS.items():
        if name and name in key:
            return spots
    return (key or "首站城市", f"{key}城市地标", f"{key}核心景区", f"{key}周边深度")


def submit_deliverable(rec: Rec, oid: str, code: str, title: str, tag: str,
                       expect: str = "", wait: float = 4.0) -> bool:
    """提交并投递：截图核对左侧标签已投递 + 右下角流程推进到了哪一步。"""
    # 让预览刷新一次，投递前画面停在"填好的文档 + 预览"上
    try:
        opened = rec.page.locator(".fh-title").first.inner_text(timeout=2000).strip()
    except Exception:
        opened = ""
    rec.check(f"当前表单是「{title}」", opened == title, opened or "读不到标题")
    rec.hold(0.8)
    rec.snap(f"{tag}-1-filled")
    rec.click("button", by_text="提交并投递", settle=0.8)

    # 等结果卡出现：语义校验与客户反馈都要走大模型，固定等待会截到「投递中…」
    settled = False
    for _ in range(90):
        if rec.page.locator(".result").count():
            settled = True
            break
        rec.hold(0.5)
    rec.check(f"{title} 投递返回结果", settled, "服务端已给出拦截网结论")
    rec.hold(0.8)

    blocked = rec.page.locator(".result.bad").count() > 0
    if blocked:
        why = rec.page.locator(".result.bad .r-why, .result.bad .r-line").first
        detail = ""
        try:
            detail = why.inner_text(timeout=2000).strip()
        except Exception:
            pass
        rec.check(f"{title} 通过拦截网并投递", False, detail or "被拦截")
        rec.snap(f"{tag}-2-blocked")
        return False

    delivered = rec.page.locator(".result.ok .r-tag").count() > 0
    rec.check(f"{title} 通过拦截网并投递", delivered, "结果卡显示已投递")

    tab_done = False
    for _ in range(20):
        if rec.page.locator(".tab.done").filter(has_text=title).count() > 0:
            tab_done = True
            break
        rec.hold(0.5)
    rec.check(f"左侧「{title}」标记为已投递", tab_done, "标签带对勾与版本号")
    rec.snap(f"{tag}-2-submitted")

    if expect:
        flow = rec.api(f"/practice/orders/{oid}/flow")
        cur = flow.get("current")
        rec.check(f"流程进度推进到 {expect}", cur == expect, f"服务端 current={cur}")
    return delivered and tab_done


# ---------------------------------------------------------------- 面板与聊天
def dock(rec: Rec, seconds: float = 1.8, tab: str = "", close: bool = True, shot: str = "") -> None:
    """展开右下角流程面板：先确认是收起态，再点开，让观众看到"这一步到哪了"。"""
    if rec.page.locator(".dock .panel").count():
        rec.click(".fab", settle=0.3)
    rec.click(".fab", settle=0.4)
    if tab:
        rec.click(".p-tab", by_text=tab, settle=0.45, required=False)
    rec.hold(seconds)
    if shot:
        rec.snap(shot)
    if close:
        rec.click(".fab", settle=0.3)


def chat_send(rec: Rec, text: str, settle: float = 5.0, tries: int = 12) -> bool:
    """在聊天界面发言：输入框写内容，点输入框右下角的「发送」。

    输入框上方那个带「＋」的「发送」是交付物/文件菜单，不是发消息。
    """
    btn = rec.page.locator("button.tc-btn.send").first
    typed = False
    for _ in range(tries):
        try:
            if btn.is_enabled():
                typed = rec.type_in("textarea.ipt", text)
                break
        except Exception:
            pass
        rec.hold(1.0)
    if not typed:
        rec.check("在输入框写消息", False, "输入框一直不可用")
        return False
    for _ in range(tries):
        if btn.is_enabled():
            break
        rec.hold(1.0)
    rec.click("button.tc-btn.send", settle=settle)
    rec.check("点输入框右下角的「发送」发消息", rec.page.locator(".bubble").count() > 0, text[:18])
    return True


def open_session(rec: Rec, name: str, settle: float = 1.6, hint: str = "") -> bool:
    ok = rec.click(".row-item", by_text=name, settle=settle, also_text=hint)
    rec.check(f"打开会话「{name}」", ok)
    return ok


def add_contact(rec: Rec, name: str, settle: float = 2.6) -> bool:
    """通讯录里的「添加」：加了好友才有单聊，也才能拉进群。"""
    for attempt in range(3):
        ok = rec.click_child(".row-item.ct", "button.mini", parent_text=name,
                             settle=settle, required=False)
        if ok:
            rec.check(f"添加联系人「{name}」", True)
            return True
        rec.hold(1.2)
    rows = [t.strip().replace("\n", " | ") for t in rec.page.locator(".row-item.ct").all_inner_texts()]
    rec.check(f"添加联系人「{name}」", False, "通讯录可见行：" + "；".join(rows)[:160])
    return False


def create_group(rec: Rec, name: str, members: list[str], settle: float = 2.4) -> bool:
    """发起群聊：填群名 → 勾成员 → 创建群聊。"""
    if not rec.click(".side-head .icon-btn", settle=0.6):
        return False
    rec.check("打开「拉群」弹窗", rec.wait_for(".dlg", 6))
    rec.type_in(".dlg-row input.ipt", name)
    for m in members:
        rec.click(".dlg .pick-row", by_text=m, settle=0.25, required=False)
    rec.click(".dlg-foot button", by_text="创建群聊", settle=settle)
    joined = rec.page.locator(".row-item").filter(has_text=name).count() > 0
    rec.check(f"建群「{name}」", joined, "、".join(members))
    return joined


def pick_targets(rec: Rec) -> None:
    """需要指定接收人的交付物：打开选择框，勾上全部会话再确认。"""
    if rec.page.locator("button.sr-edit").count() == 0:
        return
    rec.click("button.sr-edit", settle=0.6, required=False)
    if rec.wait_for(".modal", 5):
        rec.hold(0.4)
        picks = rec.page.locator(".modal .pick")
        for i in range(min(picks.count(), 3)):
            row = picks.nth(i)
            try:
                if "on" not in (row.get_attribute("class") or ""):
                    rec._hover(row)
                    rec.hold(0.2)
                    row.click(force=True)
                    rec.hold(0.35)
            except Exception:
                pass
        rec.click(".md-foot button.tc-btn", index=-1, settle=0.7)


def incident_body(rec: Rec, oid: str, step: str) -> str:
    """取导演注入的突发消息原文（用于把它滚进画面）。"""
    try:
        data = rec.api(f"/practice/orders/{oid}/timeline")
    except Exception:
        return ""
    for it in data.get("incidents", []):
        if it.get("step") == step and it.get("body"):
            return it["body"]
    return ""


def focus_message(rec: Rec, snippet: str, hold: float = 2.6) -> bool:
    """把某条消息滚进视野并停住，别让突发消息被后来的回复顶出画面。"""
    if not snippet:
        return False
    el = rec.page.locator(".msgs .row").filter(has_text=snippet[:12]).last
    if el.count() == 0:
        return False
    try:
        el.scroll_into_view_if_needed(timeout=4000)
        rec.hold(hold)
        return True
    except Exception:
        return False


def scroll_msgs_bottom(rec: Rec) -> None:
    try:
        rec.page.eval_on_selector(".msgs", "el => { el.scrollTop = el.scrollHeight }")
    except Exception:
        pass


def grab_card_ids(rec: Rec) -> list[str]:
    txt = rec.page.eval_on_selector_all(
        ".grab-card .msg-name", "els => els.map(e => (e.textContent || '').trim())")
    return ["".join(ch for ch in t if ch.isdigit()) for t in txt]


def wait_new_dispatch(rec: Rec, before: set[str], timeout: float = 180.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for i in grab_card_ids(rec):
            if i and i not in before:
                return i
        rec.hold(2.0)
    return ""


def do_call(rec: Rec, oid: str) -> bool:
    """首呼：语音通道先接通（有呼吸动效），再用通话输入框说第一句，最后挂断。"""
    rec.goto(f"/#/practice/orders/{oid}/call", 2.0)
    rec.hold(1.4)
    rec.snap("S2-call-idle")
    rec.click(".c-start", settle=1.2)

    ready = False
    for _ in range(24):
        if rec.page.locator(".c-controls .ctrl").first.is_enabled():
            ready = True
            break
        if rec.page.locator(".err").count():
            break
        rec.hold(1.0)
    if not ready:
        rec.check("语音通道接通", False, "改用文字模式兜底")
        rec.click(".mode", by_text="文字", settle=0.5, required=False)
        rec.click(".c-start", settle=3.0)
        rec.hold(1.0)
    else:
        rec.check("语音通道接通", True, "呼吸动效 + 语种与音色")
        rec.hold(2.4)

    line = ("您好，我这边是司南礼客国际旅行社的定制师小李，看到您咨询入境 5 天的行程。"
            "现在方便通电话吗？方便的话我们先确认人数、出行日期和预算口径。")
    for _ in range(20):
        if rec.page.locator(".c-input .send").first.is_enabled():
            break
        rec.hold(1.0)
    rec.type_in(".c-input .ipt", line, delay=22)
    rec.click(".c-input .send", settle=6.0)
    rec.hold(3.2)
    rec.snap("S2-call-talking")
    rec.click(".ctrl.hang", settle=2.0)

    gates = rec.api(f"/practice/orders/{oid}/gates")
    ok = any(c.get("action") == "first_call" and c.get("ok") for c in gates.get("checks", []))
    rec.check("首呼计入完成条件", ok, "通话轮次已登记")
    return ok


# ==================================================================== 主流程
def run(rec: Rec) -> str:
    page = rec.page

    # ------------------------------------------------ S0 任务初始化与规则交底
    rec.mark("S0")
    rec.goto("/#/practice/messages", 2.2)
    rec.hold(0.8)
    before = set(grab_card_ids(rec))
    rec.click(".refresh", settle=1.0)
    oid = wait_new_dispatch(rec, before, timeout=180)
    if not oid:
        raise RuntimeError("消息中心没有生成新派单")
    rec.check("消息中心按画像生成新派单", True, oid)
    print("  本单：", oid)

    detail = rec.api(f"/practice/orders/{oid}")
    cust = detail.get("customer") or "客户"
    market = detail.get("source_market") or "香港"
    dest = detail.get("destination") or "云南"
    docs = detail.get("documents") or "护照（签证要求按当期政策核验）"
    city, spot1, spot2, spot3 = dest_profile(dest)
    pool = rec.api(f"/practice/im/contacts?user_id=u-demo&order_id={oid}")
    names = {c.get("kind"): (c.get("display") or c.get("name") or "") for c in pool.get("contacts", [])}
    agent = names.get("地接社") or f"{dest}地接"
    guide = names.get("导游") or "导游"
    driver = names.get("司机") or "司机"
    print(f"  {cust} · {market} · {dest} · {city} | 地接 {agent} | 导游 {guide} | 司机 {driver}")

    card = page.locator(".grab-card").filter(has_text=oid).first
    try:
        b = card.bounding_box(timeout=6000)
        page.mouse.move(b["x"] + b["width"] * 0.5, b["y"] + b["height"] * 0.45, steps=16)
    except Exception:
        pass
    rec.hold(2.6)
    rec.snap("S0-dispatch")

    # ------------------------------------------------ S1 抢单接单
    rec.mark("S1")
    rec.click_child(".grab-card", "button.grab", parent_text=oid, settle=5.0)
    rec.check("点「抢单」接手本单", rec.wait_for(".order.card", 25), "自动进入订单管理")
    rec.hold(1.3)
    rec.click(".order.card", by_text=oid, settle=2.4)
    rec.check("进入订单详情", page.locator(".vb-crumb").count() > 0, oid)
    dock(rec, 2.8, tab="完成条件", shot="S1-dock-gates")
    dock(rec, 1.6, tab="流程进度")
    rec.snap("S1-order-detail")

    # ------------------------------------------------ S2 首呼与需求挖掘
    rec.mark("S2")
    do_call(rec, oid)
    rec.goto("/#/practice/im", 2.2)
    add_contact(rec, cust)
    add_contact(rec, agent)
    open_session(rec, cust, settle=1.6, hint=dest)
    chat_send(rec, f"{cust}您好，我是司南礼客国际旅行社的定制师小李。刚才电话里确认的 {dest} 5 天行程，"
                   f"我先整理一份需求确认单发您核对，有出入您直接回我。", settle=7.0)
    rec.hold(1.6)
    rec.snap("S2-im-customer")

    # ------------------------------------------------ S3 需求结构化确认
    rec.mark("S3")
    open_deliverable(rec, oid, "requirement_sheet", "需求确认单")
    rec.fill_field("客人称呼", cust)
    rec.fill_field("客源地", market)
    rec.fill_field("出行人数", "2 大 1 小")
    rec.fill_field("出行日期", "2026-11-08 至 11-12，5 天")
    rec.fill_field("目的地与城市", f"{city} / {spot1}")
    rec.fill_field("必须满足", f"{dest} 5 天 4 晚，四星住宿，含接送机、中文导游与境外旅游意外险，人均 6000–8000")
    rec.fill_field("希望满足", f"节奏轻松、少爬山，想去 {spot2}，餐食清淡")
    rec.fill_field("可替代", "酒店可降一档，用车可由 7 座换 5 座商务车")
    rec.fill_field("明确不要", "不接受购物店，不接受早于 08:00 的出发")
    rec.fill_field("预算口径", "人均 6000–8000，含境内交通与门票，不含国际段机票")
    rec.fill_field("证件与入境", docs)
    rec.fill_field("饮食与宗教禁忌", "无特殊禁忌，两位客人不吃辣")
    submit_deliverable(rec, oid, "requirement_sheet", "需求确认单", "S3", expect=3)

    # ------------------------------------------------ S4 资源询价与可行性核验
    rec.mark("S4")
    rec.goto("/#/practice/im", 2.0)
    open_session(rec, "资源对接群", settle=1.6)
    chat_send(rec, f"各位好，{market}客人 {cust} 的 {dest} 5 天单，2 大 1 小，11 月 8 日入住。"
                   f"请地接报一下用车和中文导游的档期与报价，写清楚含不含司机和油费，今天 18 点前回我。",
              settle=8.0)
    rec.hold(2.2)
    rec.snap("S4-supplier-group")

    open_deliverable(rec, oid, "resource_quote", "资源询价记录")
    rec.fill_field("资源方", agent)
    rec.select_field("资源类型", "组合")
    rec.fill_field("报价明细", "7 座商务车 800 元/天；中文导游 600 元/天，均含司机与油费")
    rec.fill_field("可用性与档期", "有")
    rec.fill_field("含项与不含项", "含司机、油费与过路费；不含餐补与超时费")
    rec.fill_field("回复时限", "今天 18 点前确认")
    rec.fill_rows("比价", [["本地地接", "1400 元/天", "含车含导", "提前 7 天可退", "口碑 4.8"],
                          ["外地车队", "1250 元/天", "车不含导", "提前 3 天可退", "口碑 4.5"]])
    rec.fill_field("备选方案与触发条件", "主选本地地接；若临时调不出车，改外地车队并补一次接送机")
    rec.fill_field("备注", "报价口径与地接群内回复一致，已留存记录")
    submit_deliverable(rec, oid, "resource_quote", "资源询价记录", "S4b")

    # ------------------------------------------------ S5 行程方案设计
    rec.mark("S5")
    open_deliverable(rec, oid, "itinerary", "行程方案")
    rec.fill_field("方案标题", f"{market}客人 {dest} 5 天 4 晚定制行程")
    rec.fill_field("出发 / 返程", "2026-11-08 – 2026-11-12")
    rec.fill_field("出行人数", "2 大 1 小")
    rec.fill_rows("逐日行程", [
        ["D1", "14:00", "专车接机 50 分钟", spot1, "晚餐 当地菜", f"{city}四星", guide],
        ["D2", "08:30", "专车 1.5 小时", spot2, "午餐 团餐", f"{city}四星", guide],
        ["D3", "08:30", "专车 2 小时", spot3, "晚餐 特色餐", f"{city}四星", guide],
        ["D4", "09:00", "专车 1 小时", f"{city}老城自由活动", "午餐 特色小吃", f"{city}四星", guide],
        ["D5", "10:00", "专车送机 50 分钟", "返程送机", "午餐 机场简餐", "—", guide],
    ])
    rec.fill_field("交通与用车", "7 座商务车含司机与油费，每天用车不超过 10 小时")
    rec.fill_field("住宿安排", f"{city}四星 4 晚，含双早，房态确认后再锁房")
    rec.fill_field("门票与预约", f"{spot2} 与 {spot3} 需实名预约，提前 3 天出票")
    rec.fill_field("保险与合规", "境外游客旅游意外险 30 万，出团前完成投保")
    rec.fill_field("入境与证件提醒", docs)
    rec.fill_field("备选方案", "主选 7 座商务车；若调不出来改 5 座商务车，价差按实际结算")
    submit_deliverable(rec, oid, "itinerary", "行程方案", "S5")

    # ------------------------------------------------ S6 分项报价与利润测算
    rec.mark("S6")
    open_deliverable(rec, oid, "quotation", "分项报价单")
    rec.fill_field("出行人数", "2 大 1 小")
    rec.fill_field("出行日期", "2026-11-08 至 11-12，5 天")
    rec.fill_rows("分项明细", [
        ["接待用车", "7 座商务车含司机油费", "5", "800", "4000"],
        ["中文导游", "全程跟团讲解", "5", "600", "3000"],
        ["酒店住宿", "四星含双早 4 晚", "4", "900", "3600"],
        ["门票", "核心景区门票与预约", "3", "400", "1200"],
        ["餐饮", "特色餐与团餐", "5", "500", "2500"],
        ["保险", "旅游意外险 30 万", "3", "60", "180"],
        ["定制服务费", "行程设计与地接协调", "1", "3800", "3800"],
    ])
    rec.fill_field("合计金额", "18280")
    rec.fill_field("人均", "6093")
    rec.fill_field("成本", "15000")
    rec.fill_field("保险项", "旅游意外险 30 万，60 元/人")
    rec.fill_field("待确认项与锁定时限", "酒店与用车待地接 2 小时内回复后锁定")
    rec.fill_field("汇率与支付", "按签合同当日汇率结算，对公转账，手续费我方承担")
    submit_deliverable(rec, oid, "quotation", "分项报价单", "S6")

    # ------------------------------------------------ S7 客户反馈与方案迭代
    rec.mark("S7")
    rec.goto("/#/practice/im", 2.0)
    open_session(rec, cust, settle=1.8, hint=dest)
    rec.hold(1.6)
    chat_send(rec, "收到，住宿按您说的那家四星定，交通改成高铁，报价我重算完再发您确认，"
                   "出行日期不受影响。", settle=7.0)
    rec.hold(1.8)
    rec.snap("S7-customer-feedback")
    dock(rec, 2.6, tab="完成条件", shot="S7-dock-before", close=False)
    rec.click_child(".g-row", "button.g-do", parent_text="客户确认最终方案", settle=2.6)
    rec.hold(0.8)
    rec.snap("S7-dock-confirmed")
    dock(rec, 1.6, tab="流程进度")
    flow = rec.api(f"/practice/orders/{oid}/flow")
    rec.check("客户确认方案后流程推进", flow.get("current", 0) >= 4, f"current={flow.get('current')}")

    # ------------------------------------------------ S8 成交确认与系统录单
    rec.mark("S8")
    open_deliverable(rec, oid, "contract", "合同与保险")
    rec.fill_field("合同编号", f"HT-20261009-{oid[-3:]}")
    rec.fill_field("签署日期", "2026-10-09")
    rec.select_field("签署方式", "线上电子签")
    rec.fill_field("保单号", "PL-88213456")
    rec.fill_field("承保公司", "平安境外旅游意外险")
    rec.fill_field("投保日期", "2026-10-09")
    rec.fill_field("保额", "意外 30 万 / 医疗 5 万")
    rec.fill_field("定金金额", "5484")
    rec.fill_field("到账时间", "2026-10-09 11:02")
    rec.select_field("客户签署状态", "已签署")
    rec.select_field("定金状态", "已到账")
    rec.select_field("付款方式", "对公转账")
    rec.fill_field("配合项说明", "先合同 → 再保险 → 后收定金，顺序已完成")
    submit_deliverable(rec, oid, "contract", "合同与保险", "S8", expect=7)

    # ------------------------------------------------ S9 资源锁定与行前准备
    rec.mark("S9")
    rec.goto("/#/practice/im", 2.0)
    add_contact(rec, guide)
    add_contact(rec, driver)
    create_group(rec, "司导沟通群", [cust, guide, driver])
    open_session(rec, "司导沟通群", settle=1.4, hint=cust)
    chat_send(rec, f"{guide}、{driver}好，这是 11 月 8 日到 12 日的用车与接待安排。"
                   f"客人 2 大 1 小不吃辣，请按行程单时间到店接人，有变化提前两小时在群里说。", settle=6.0)
    rec.hold(1.6)

    open_deliverable(rec, oid, "departure_notice", "出团通知书")
    pick_targets(rec)
    rec.fill_field("集合时间与地点", f"2026-11-08 14:00，{city}机场 T2 到达口")
    rec.fill_field("导游 / 司机与电话", f"导游 {guide} 13800000000 / 司机 {driver} 13900000000")
    rec.fill_field("紧急联络人", "定制师 小李 13700000000（24 小时）")
    rec.fill_field("每日要点", "每天 08:30 集合，行程重点见逐日安排，景区需实名预约")
    rec.fill_field("证件与随身物品", "通行证件、充电器、雨具、常用药，高原或山区早晚温差大")
    rec.fill_field("饮食与禁忌提醒", "已按不吃辣安排餐食，清真或素食需求提前一天在群里说")
    rec.fill_field("天气与穿着", "白天 12–20℃，早晚加一件外套，备防滑鞋")
    rec.fill_field("确认方式", "已发客户群与司导群，请回复「收到」")
    submit_deliverable(rec, oid, "departure_notice", "出团通知书", "S9", expect=9)

    # ------------------------------------------------ S10 行中执行与突发事件
    rec.mark("S10")
    rec.goto("/#/practice/im", 2.0)
    open_session(rec, "司导沟通群", settle=1.8, hint=cust)
    rec.hold(2.2)                     # 导演注入的突发消息停住看清楚
    body = incident_body(rec, oid, "S10")
    shown = focus_message(rec, body, hold=2.8)
    rec.check("行中突发消息在画面里可见", shown, body[:26])
    rec.snap("S10-incident")
    scroll_msgs_bottom(rec)
    rec.hold(0.6)
    chat_send(rec, "先按两小时内换车的方向处理，同时告诉客人预计几点能出发；"
                   "所有费用走地接结算单，我这边同步安抚客人。", settle=6.0)
    rec.hold(2.0)

    # ------------------------------------------------ S11 行后结算与回访
    rec.mark("S11")
    open_deliverable(rec, oid, "settlement", "地接结算核对单")
    rec.fill_field("结算单号", "JS-20261112-03")
    rec.fill_rows("逐项核对", [
        ["接待用车", "4000", "5000", "1000", "含司机油费，按对客口径折算"],
        ["中文导游", "3000", "3600", "600", "全程 5 天"],
        ["酒店住宿", "3600", "4800", "1200", "四星含双早 4 晚"],
        ["门票", "1200", "1500", "300", "含景区预约服务"],
        ["餐饮", "2500", "3000", "500", "两顿特色餐"],
        ["保险", "180", "380", "200", "旅游意外险 30 万"],
    ])
    rec.fill_field("地接结算合计", "14480")
    rec.fill_field("我方报价合计", "18280")
    rec.fill_field("合计差异", "3800")
    rec.fill_field("实际成本", "15000")
    rec.fill_field("实际毛利", "3280")
    rec.fill_field("差异原因", "用车超时 2 小时、景区门票当期调价")
    rec.fill_field("处理决定", "据实结算超时部分，门票差价由我方承担")
    submit_deliverable(rec, oid, "settlement", "地接结算核对单", "S11", expect=11)

    rec.goto(f"/#/practice/orders/{oid}/finance", 2.0)
    rec.hold(1.6)
    rec.click("button", by_text="结账并留档", settle=2.6, required=False)
    rec.hold(1.4)
    rec.snap("S11-finance")

    # ------------------------------------------------ S12 复盘评分与个性化补救
    rec.mark("S12")
    open_deliverable(rec, oid, "review", "回访与复盘记录")
    rec.fill_field("回访时间与方式", "2026-11-13 电话 15 分钟")
    rec.select_field("满意度", "满意")
    rec.fill_field("客户原话", "整体节奏舒服，导游讲得清楚，就是第二天出发早了一点")
    rec.fill_field("问题与投诉", "第二天集合时间偏早，客人在酒店大堂等了 20 分钟")
    rec.fill_field("补救措施", "第三天起集合推迟到 09:00，并赠送一次下午茶")
    rec.select_field("尾款状态", "已结清")
    rec.fill_field("实际利润", "3280")
    rec.fill_field("做得好的", f"{spot1} 的安排客户认可，行中换车响应及时")
    rec.fill_field("待改进的", "首呼时没有一次问全预算口径，导致报价改了一版")
    rec.fill_field("下一步动作", "补练 C1.2 顾问式提问与 S6 报价留涨价空间")
    submit_deliverable(rec, oid, "review", "回访与复盘记录", "S12", expect=12)
    rec.hold(0.8)

    report = rec.api(f"/practice/orders/{oid}/score", "POST", {})
    rec.check("评分 Agent 生成复盘报告", bool(report.get("ok")),
              str(report.get("skill_points") or "")[:40])
    rec.goto(f"/#/practice/orders/{oid}/score", 2.4)
    rec.hold(2.2)
    rec.scroll(260, times=2, pause=0.5)
    rec.hold(1.8)
    rec.snap("S12-score")
    return oid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--keep-video", action="store_true")
    args = ap.parse_args()

    for d in (TMP_VIDEO, OUT_DIR, FRAME_DIR, CHECK_DIR):
        if d == TMP_VIDEO and args.keep_video:
            continue
        shutil.rmtree(d, ignore_errors=True)
    for d in (TMP_VIDEO, OUT_DIR, FRAME_DIR, CHECK_DIR):
        d.mkdir(parents=True, exist_ok=True)

    oid = ""
    total = 0.0
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required", "--hide-scrollbars",
        ])
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
            record_video_dir=str(TMP_VIDEO),
            record_video_size={"width": 1920, "height": 1080},
        )
        ctx.add_init_script("try{localStorage.setItem('tc-user','u-demo')}catch(e){}")
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        rec = Rec(page, args.base)
        try:
            oid = run(rec)
        except Exception as exc:
            print(f"录制中断：{type(exc).__name__}: {str(exc)[:200]}")
            try:
                rec.snap("crash")
            except Exception:
                pass
        marks = rec.marks
        total = time.time() - rec.t0
        checks = rec.checks
        ctx.close()
        browser.close()

    _marks_path = OUT_DIR / "steps13-marks.json"
    videos = sorted(TMP_VIDEO.glob("*.webm"), key=lambda f: f.stat().st_size, reverse=True)
    if not videos:
        print("没拿到视频文件")
        return 1
    target = OUT_DIR / "steps13.webm"
    shutil.move(str(videos[0]), str(target))
    print(f"视频：{target}  {target.stat().st_size / 1024 / 1024:.1f} MB  时长约 {total:.0f}s  订单 {oid}")
    _marks_path.write_text(
        json.dumps({"order_id": oid, "checks": [[n, o, d] for n, o, d in checks],
                    "marks": marks, "recorded_seconds": round(total, 2)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    duration = 0.0
    try:
        probe = subprocess.run([FFMPEG, "-i", str(target)], capture_output=True, text=True)
        for line in probe.stderr.splitlines():
            if "Duration:" in line:
                hms = line.split("Duration:")[1].split(",")[0].strip().split(":")
                duration = int(hms[0]) * 3600 + int(hms[1]) * 60 + float(hms[2])
    except Exception:
        pass
    delta = max(duration - total, 0.0) if duration else 0.0
    if duration:
        print(f"实际时长 {duration:.1f}s（录像比 marks 多 {delta:.1f}s，抽帧已按该差值对齐）")
    for name, t in marks:
        out = FRAME_DIR / f"{name}.png"
        ss = min(t + delta + 2.0, max(duration - 0.5, 0.1))
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{ss:.2f}",
                        "-i", str(target), "-frames:v", "1", str(out)], check=False)
    print("校验帧：", FRAME_DIR)
    print("逐步截图：", CHECK_DIR)

    bad = [(n, d) for n, o, d in checks if not o]
    print(f"\n校验：{len(checks) - len(bad)}/{len(checks)} 通过")
    for n, d in bad:
        print(f"  × {n} · {d}")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
