"""学员个性化 → 教学：把画像翻成「怎么讲」的硬性要求、讲后核对、以及中文可读的证据。

三块画像各管一个侧面（见 contracts/learner_profile.py）：
  学习风格   → 讲义的结构与呈现（图 / 话术 / 动手 / 原理 / 步骤 / 全景）
  客源国+语言 → 每个技能点里的语言提示、文化提示（按语言水平给不同深度）
  职业背景   → 类比与起点

对讲义、实操指南做**确定性核对**（必须出现哪些固定小节、SVG 是否能解析等），不合格带原因返工一次，
这样不同画像的学员对同一技能点拿到的讲义才会「明显不一样」，而不是只在开头换一句话。
八维掌握度判档完全不读这里的任何东西：风格、客源国都不能影响「你学到哪一档」。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ..contracts.learner_profile import (
    BACKGROUND_HINT, LANG_LEVEL_NAMES, STYLE_BY_ID, describe_style, is_empty,
)
from . import market_kb

STRICT_KINDS = ("lecture", "guide")          # 讲义、实操指南：做结构核对
SVG_FENCE = re.compile(r"```svg[ \t]*\r?\n(.*?)```", re.S | re.I)

# 每个风格取向（维度, 偏哪一侧）对应的：硬性要求（明显/略偏）、对话里的轻量要求、证据里写的「落到了哪」
# 固定小节标题要和 check_content 里的关键词一致。
STYLE_RULES: dict[tuple[str, int], dict[str, str]] = {
    ("AR", 0): {
        "marker": "现在就试",
        "strong": "【主动型·明显】全文以动手为主线：开头三句话内就给出第一个能马上做的小任务；必须有二级标题「## 现在就试」，"
                  "给 2–3 个小任务（可拉同学或同事模拟，写清谁扮演谁、怎么算做对）；理论压缩到最少，穿插在任务之间。",
        "slight": "【主动型·略偏】讲解之后安排二级标题「## 现在就试」，给 1–2 个小任务。",
        "chat": "回答里给出一个可以马上试一试的小动作。",
        "note": "讲义以「现在就试」小任务为主线，理论压缩",
    },
    ("AR", 1): {
        "marker": "先想一想",
        "strong": "【反思型·明显】必须有二级标题「## 先想一想」，给 2–3 个需要独立思考、写下来再对照的问题，放在行动清单之前；"
                  "不要催学员立刻动手，行动清单放到最后，并写明「想清楚之后再做」。",
        "slight": "【反思型·略偏】在行动清单前安排二级标题「## 先想一想」，给 1–2 个思考题。",
        "chat": "回答里先给一个值得停下来想一想的问题，再给结论。",
        "note": "先安排「先想一想」独立思考，再给行动清单",
    },
    ("SI", 0): {
        "marker": "真实案例",
        "strong": "【感知型·明显】必须有二级标题「## 真实案例」，至少 2 个具体案例（写出客户类型、客户的原话、数字与结果）；"
                  "每个知识点都先给例子再用一句话提炼；步骤写成具体动作，不写空泛原则。",
        "slight": "【感知型·略偏】必须有二级标题「## 真实案例」，至少 1 个具体案例（含客户原话与结果）。",
        "chat": "回答用一个具体例子开头，再提炼要点。",
        "note": "每个知识点先给真实案例，再提炼；步骤写成具体动作",
    },
    ("SI", 1): {
        "marker": "背后的原理",
        "strong": "【直觉型·明显】必须有二级标题「## 背后的原理」，讲清为什么这样做、和哪些技能点相关、有哪些变体与适用边界；"
                  "先讲框架与关系，案例最多一个且要简短。",
        "slight": "【直觉型·略偏】必须有二级标题「## 背后的原理」，用几句话讲清为什么这样做。",
        "chat": "回答先讲为什么，再给一个简短例子。",
        "note": "先讲「背后的原理」与技能点之间的关系，案例从简",
    },
    ("VV", 0): {
        "marker": "```svg",
        "strong": "【视觉型·明显】必须画至少 2 张 SVG 示意图（流程图、对比图、结构图均可），各放在讲到对应内容的位置；"
                  "每张图前一行写「图 n：标题」；文字尽量精简，能用图表达的不要写大段文字。",
        "slight": "【视觉型·略偏】必须画至少 1 张 SVG 示意图，图前一行写「图 n：标题」，其余用文字补充。",
        "chat": "回答里如果有流程或对比，请附一张 SVG 小图。",
        "note": "用 SVG 示意图承载核心内容，文字精简",
    },
    ("VV", 1): {
        "marker": "话术示范",
        "strong": "【言语型·明显】必须有二级标题「## 话术示范」，给 2 段可以直接照读的对话（客户一句、你一句），"
                  "并逐句说明为什么这样说；不要画图，用清楚的文字段落，必要时用表格。",
        "slight": "【言语型·略偏】必须有二级标题「## 话术示范」，给 1 段可照读的对话；图最多 1 张。",
        "chat": "回答用口头讲解的方式，给一两句可以直接照说的话。",
        "note": "用「话术示范」对话与文字讲解，不画图",
    },
    ("SG", 0): {
        "marker": "步骤 1",
        "strong": "【序列型·明显】必须用「步骤 1、步骤 2、步骤 3 …」线性推进，每一步写清：做什么 / 怎么算做完 / 常见错误；"
                  "前一步没讲完，不要提前引入后面的概念。",
        "slight": "【序列型·略偏】主体部分用「步骤 1、步骤 2 …」按顺序展开，每步一个动作。",
        "chat": "回答按先后顺序，一步一步说。",
        "note": "按「步骤 1、2、3…」线性推进，每步给完成标准",
    },
    ("SG", 1): {
        "marker": "全景图",
        "strong": "【整体型·明显】必须以二级标题「## 全景图」开头：先用一小段话说明这个技能点在整个定制流程里的位置、和哪些技能点相连、"
                  "最终要达成什么；之后再讲细节，细节按「场景」组织而不是机械编号，结尾回扣全景。",
        "slight": "【整体型·略偏】开头用二级标题「## 全景图」写一小段整体说明，再讲细节。",
        "chat": "回答先说它在整体里处于什么位置，再讲细节。",
        "note": "以「全景图」开头，再按场景展开细节并回扣整体",
    },
}

SVG_GUIDE = """SVG 画法（严格遵守，否则会被退回）：
- 用 ```svg 代码块输出，代码块内只放一个 <svg>，必须带 viewBox="0 0 640 H"（H 取 240–420），不要写 width/height。
- 只用 rect / circle / line / path / polygon / text / g；禁止 script、style、image、use、foreignObject、任何 href 与 on* 属性。
- 文字用 <text>，font-size 不小于 15，每行不超过 12 个汉字，长句拆成多个 <text>；text 一律设 font-family="sans-serif"。
- 配色只用这几个：#133450（深）#2f6fa3（主）#5b95c9（浅）#e7eef4（底）#e08a1e（强调）#12a76a（通过）#e04b4b（风险）。
- 箭头用 path 画线再加一个 polygon 三角形，不要用 marker。
- 每张图至少 3 处文字标签；图要表达本技能点的真实内容（步骤、判断分支或对比），不是装饰。
示例：
```svg
<svg viewBox="0 0 640 240" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
  <rect x="20" y="80" width="170" height="80" rx="10" fill="#e7eef4" stroke="#133450" stroke-width="2"/>
  <text x="105" y="127" text-anchor="middle" font-size="18" fill="#133450">核对派单字段</text>
  <path d="M190 120 H250" stroke="#2f6fa3" stroke-width="3" fill="none"/>
  <polygon points="250,111 268,120 250,129" fill="#2f6fa3"/>
  <rect x="270" y="80" width="170" height="80" rx="10" fill="#2f6fa3"/>
  <text x="355" y="127" text-anchor="middle" font-size="18" fill="#ffffff">首呼逐项补问</text>
</svg>
```"""


# ---------------------------------------------------------------- 画像 → 文字

def _levels(profile: dict) -> tuple[int | None, str]:
    m = (profile or {}).get("market") or {}
    lv = m.get("language_level")
    return (int(lv) if isinstance(lv, int) else None), str(m.get("language_level_name") or "")


def background_text(profile: dict) -> str:
    b = (profile or {}).get("background") or {}
    parts = [b.get("status_label", ""), b.get("note", "")]
    return " · ".join(x for x in parts if x)


def preface(profile: dict | None, market: dict | None) -> str:
    """讲义最前面的一句「为什么这样讲」。没做个性化测评的账号，提示去做，而不是悄悄给通用版。"""
    if is_empty(profile):
        return ("> **这是一份通用讲义。** 你还没有完成「学习风格 / 客源国 / 背景」测评，"
                "到「学情画像」里补做后，讲义会按你的画像重新定制。\n\n")
    bits = []
    rows = describe_style((profile or {}).get("style") or {})
    if rows:
        bits.append("学习风格：" + "、".join(f"{r['strength']}{r['pole']}" for r in rows))
    bg = background_text(profile or {})
    if bg:
        bits.append("背景：" + bg)
    m = (profile or {}).get("market") or {}
    if m.get("country"):
        lv = m.get("language_level_name")
        bits.append(f"目标客源国：{m['country']}" + (f"（{m.get('lang_short') or m.get('language', '')}水平：{lv}）" if lv else ""))
    return "> **本讲义已按你的画像定制** —— " + "；".join(bits) + "。展开下方「依据」可以看每一条是怎么用到的。\n\n"


def render_block(profile: dict | None, market: dict | None, kind: str, skill_name: str = "") -> str:
    """喂给模型的「学员个性化画像与讲法要求」。kind: lecture/guide 严格；其他轻量。"""
    if is_empty(profile):
        return ""
    strict = kind in STRICT_KINDS
    lines: list[str] = []
    rows = describe_style((profile or {}).get("style") or {})
    if strict:
        lines.append("【学员个性化画像与讲法要求】以下决定**怎么讲**，不改变本技能点要讲的内容范围；Rubric 与知识点基座里的事实不得改动。"
                     "不同画像的学员读同一技能点，必须得到结构、例子、语言/文化提示都明显不同的讲义。")
    else:
        lines.append("【学员个性化画像】请按下列偏好调整讲法，不改变事实内容。")
    for r in rows:
        rule = STYLE_RULES.get((r["id"], 0 if r["value"] < 0 else 1))
        if not rule:
            continue
        lines.append("- " + (rule["strong" if r["strong"] else "slight"] if strict else rule["chat"]))
    visual = [r for r in rows if r["id"] == "VV" and r["value"] < 0]
    if visual and (strict or visual[0]["strong"]):       # 对话里只有「明显偏视觉」才值得画图
        lines.append(SVG_GUIDE)
    if strict and any(r["id"] == "VV" and r["value"] > 0 for r in rows):
        lines.append("（言语型学员：除非明显必要，不要画 SVG。）")

    bg = (profile or {}).get("background") or {}
    if bg:
        hint = BACKGROUND_HINT.get(bg.get("status", ""), "")
        who = background_text(profile or {})
        if strict:
            lines.append(f"【学员背景】{who}。{hint} 必须单列二级标题「## 结合你的背景」，用 2–4 句话，"
                         f"拿他熟悉的{('「' + bg['note'] + '」') if bg.get('note') else '原有'}场景做一个具体的类比或对照，再指出定制师岗位上不一样的地方。")
        else:
            lines.append(f"【学员背景】{who}。{hint}")

    m = (profile or {}).get("market") or {}
    if m.get("country") and market:
        lines.append(_market_block(m, market, strict, skill_name))
    return "\n".join(lines)


def _market_block(m: dict, market: dict, strict: bool, skill_name: str) -> str:
    country, lang = market.get("country", ""), market.get("service_language", "")
    level, level_name = m.get("language_level"), m.get("language_level_name", "")
    skills = m.get("language_skills") or {}
    head = f"【目标客源国】{country}（服务语言：{lang}）。"
    if level is not None:
        head += (f"学员的{lang}水平：{level_name}"
                 f"（听 {skills.get('listen', '?')}/说 {skills.get('speak', '?')}/读写 {skills.get('write', '?')}，各 0–3 分）。")
    if not strict:
        return head + f"出题或举例时，客人来自{country}，情景里自然带入一个与{country}相关的语言或文化细节。"
    kb = ["下面是国别知识库（只依据这些写，不要自己补写具体政策数字）："]
    phrases = (market.get("language") or {}).get("phrases") or []
    if phrases:
        kb.append("· 常用客服用语：" + "；".join(
            f"{p['scene']}「{p['zh']}」= {p['text']}" + (f"（{p['read']}）" if p.get("read") else "") for p in phrases))
    for key, name in (("culture", "文化"), ("customs", "习俗"), ("policy", "政策")):
        items = market.get(key) or []
        if items:
            kb.append(f"· {name}：" + "；".join(f"{i['title']}——{i['body']}" for i in items))
    need = (f"必须单列二级标题「## 面向{country}客人的提示」，其中分条写：\n"
            f"  1) 「语言提示」：{_language_rule(level, lang, skill_name)}\n"
            f"  2) 「文化提示」：从上面的文化/习俗里挑 1–2 条与「{skill_name}」最相关的，写成可以直接照做的动作，不要写成风俗介绍。\n"
            f"  3) 「政策提示」（只在与本技能点相关时写）：只转述知识库里的框架，并写明「以国家移民管理局最新公告为准」，不得补写具体天数、名单、金额。")
    return "\n".join([head, need] + kb)


def _language_rule(level: int | None, lang: str, skill_name: str) -> str:
    if level is None or level <= 1:
        return (f"学员的{lang}水平很低：必须原样引用上面「常用客服用语」中至少 3 句（写出中文意思、{lang}原文，有读音的写读音），"
                f"并说明在「{skill_name}」的哪一步该说哪一句；不要出现长段外语。")
    if level == 2:
        return (f"学员能做日常交流：原样引用上面常用客服用语中至少 2 句，再补 1 个可套用的整句模板"
                f"（把空格处替换成具体内容）；外语表达标注「请由母语者校对」。")
    return (f"学员{lang}水平较高：不再给基础用语；给 2–3 条与「{skill_name}」相关的更专业、更地道的表达，"
            f"并指出中国人常犯的{lang}表达错误或礼貌层次问题；外语表达标注「请由母语者校对」。")


# ---------------------------------------------------------------- 讲后核对

def validate_svg(src: str) -> str | None:
    """SVG 能否被浏览器安全渲染的确定性检查；合格返回 None，否则返回原因。"""
    s = (src or "").strip()
    if not s:
        return "SVG 代码块是空的"
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", s, re.I):
        return "SVG 里不能有 DOCTYPE / ENTITY"
    try:
        root = ET.fromstring(s)
    except ET.ParseError as exc:
        return f"SVG 不是合法的 XML（{exc}），常见原因是文字里的 & < > 没有转义"
    if root.tag.split("}")[-1].lower() != "svg":
        return "代码块里的根元素必须是 <svg>"
    if not root.get("viewBox"):
        return "SVG 缺少 viewBox"
    texts = 0
    bad = {"script", "foreignobject", "iframe", "image", "use", "style", "a", "animate", "set", "animatetransform"}
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        if tag in bad:
            return f"SVG 里不允许出现 <{tag}>"
        for k in el.attrib:
            kl = k.lower()
            if kl.startswith("on") or "href" in kl:
                return f"SVG 里不允许出现属性 {k}"
        if tag == "text":
            texts += 1
    if texts < 3:
        return "SVG 里文字标签太少（至少 3 处），图需要表达真实内容"
    return None


def svg_blocks(content: str) -> list[str]:
    return SVG_FENCE.findall(content or "")


# 这些小节是练习、思考题、对话示范、类比、案例叙述：不是对世界的事实陈述，不参与「支持率」核验
ILLUSTRATIVE_HEADINGS = ("现在就试", "先想一想", "话术示范", "结合你的背景", "真实案例")
_HIGH_RISK_WORDS = ("签证", "入境", "海关", "证件", "移民", "法律", "保险", "安全", "宗教", "清真",
                    "医疗", "疫苗", "开放时间", "门票", "赔付", "合同", "政策", "禁令", "违法")


def factual_text(content: str) -> str:
    """给审查与证据闸门用的文本：去掉 SVG、图题和「示范性」小节；示范小节里带高风险词的句子仍保留。"""
    text = SVG_FENCE.sub("", content or "")
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        m = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", line)
        if m:
            skipping = any(k in m.group(1) for k in ILLUSTRATIVE_HEADINGS)
            if not skipping:
                out.append(line)
            continue
        if re.match(r"^\s*图\s*\d+\s*[：:]", line):
            continue
        if not skipping or any(w in line for w in _HIGH_RISK_WORDS):
            out.append(line)
    return "\n".join(out)


def check_content(content: str, profile: dict | None, market: dict | None, kind: str) -> list[str]:
    """讲义/实操指南是否按画像做了定制。返回问题清单（空＝合格），用于带原因返工。"""
    if kind not in STRICT_KINDS or is_empty(profile):
        return []
    text = content or ""
    issues: list[str] = []
    svgs = svg_blocks(text)
    for r in describe_style((profile or {}).get("style") or {}):
        side = 0 if r["value"] < 0 else 1
        key = (r["id"], side)
        strong = r["strong"]
        if key == ("VV", 0):
            need = 2 if strong else 1
            if len(svgs) < need:
                issues.append(f"视觉型学员需要至少 {need} 张 SVG 示意图（```svg 代码块），现在只有 {len(svgs)} 张")
        elif key == ("VV", 1):
            if "话术示范" not in text:
                issues.append("言语型学员必须有「## 话术示范」小节")
            if strong and svgs:
                issues.append("明显偏言语型的学员不要画图，请改成文字与对话")
            elif len(svgs) > 1:
                issues.append("言语型学员最多 1 张图")
        elif key == ("SG", 0):
            n = len(re.findall(r"步骤\s*\d", text))
            if n < 3:
                issues.append(f"序列型学员必须用「步骤 1、步骤 2、步骤 3…」线性推进，现在只写了 {n} 个步骤编号")
        elif key == ("SG", 1):
            head = text.lstrip()[:200]
            if "全景" not in head:
                issues.append("整体型学员必须以「## 全景图」开头")
        else:
            marker = STYLE_RULES[key]["marker"]
            if marker not in text:
                issues.append(f"缺少「{marker}」小节（{r['pole']}学员的固定内容）")
    for i, src in enumerate(svgs, 1):
        why = validate_svg(src)
        if why:
            issues.append(f"第 {i} 张 SVG 无法使用：{why}")
    bg = (profile or {}).get("background") or {}
    if bg and "结合你的背景" not in text:
        issues.append("缺少「## 结合你的背景」小节")
    m = (profile or {}).get("market") or {}
    if m.get("country") and market:
        country = market.get("country", "")
        if f"面向{country}客人的提示" not in text:
            issues.append(f"缺少「## 面向{country}客人的提示」小节")
        else:
            level = m.get("language_level")
            phrases = (market.get("language") or {}).get("phrases") or []
            used = sum(1 for p in phrases if p.get("text") and p["text"] in text)
            need = 3 if (level is None or level <= 1) else 2 if level == 2 else 0
            if need and used < need:
                issues.append(f"语言提示需要原样引用国别知识库里的常用客服用语至少 {need} 句，现在只引用了 {used} 句")
    return issues


# ---------------------------------------------------------------- 证据（中文可读）

GROUP_ORDER = ("P", "M", "R", "K", "G", "W", "H", "O")
GROUP_NAME = {"P": "学员画像", "M": "国别知识库", "R": "评分标准", "K": "技能知识库",
              "G": "技能图", "W": "网络来源", "H": "学习记录", "O": "实战记录"}
KB_PART_NAME = {"标题": "标题", "练习": "练习题", "讲解": "概念讲解", "要点": "关键要点", "示例": "示例"}


def _kb_parts(sources: list[str]) -> str:
    seen: list[str] = []
    for s in sources or []:
        tail = str(s).split("·")[-1].strip()
        name = KB_PART_NAME.get(tail, tail)
        if name and name not in seen:
            seen.append(name)
    return "、".join(seen)


def learner_effects(profile: dict | None, market: dict | None) -> list[dict[str, str]]:
    """画像里每一项「对教学改了什么」。画像页和讲义证据共用，保证两处说法一致。"""
    out: list[dict[str, str]] = []
    for r in describe_style((profile or {}).get("style") or {}):
        rule = STYLE_RULES.get((r["id"], 0 if r["value"] < 0 else 1))
        out.append({"group": "学习风格", "title": f"{r['name']}：{r['strength']}{r['pole']}",
                    "effect": (rule or {}).get("note", "")})
    bg = (profile or {}).get("background") or {}
    if bg:
        status = bg.get("status", "")
        eff = {"student": "术语先解释再用，类比从学校场景出发", "travel": "跳过基础名词，直接讲定制师特有的做法与易错点",
               "other_job": "用原行业的做法搭桥类比，再指出定制师岗位的不同", "switching": "节奏加快，强调可迁移的原有经验"}.get(status, "按所填背景做类比")
        out.append({"group": "职业背景", "title": background_text(profile or {}) or "已填写", "effect": eff})
    m = (profile or {}).get("market") or {}
    if m.get("country"):
        level = m.get("language_level")
        lang = m.get("lang_short") or m.get("language", "")
        if level is None:
            eff = "加入该国文化提示与政策提示"
        elif level <= 1:
            eff = f"每个技能点给现成的{lang}客服用语（含中文意思与读音），并加入该国文化提示"
        elif level == 2:
            eff = f"给{lang}可套用的整句模板，并加入该国文化提示"
        else:
            eff = f"不再给基础{lang}用语，改给更地道的专业表达与常见错误，并加入该国文化提示"
        title = f"{m['country']}" + (f" · {lang}水平：{m.get('language_level_name')}" if level is not None else "")
        out.append({"group": "目标客源国", "title": title, "effect": eff})
    return out


def build_evidence_items(ctx: Any, profile: dict | None, market: dict | None, kind: str,
                         content: str = "") -> list[dict[str, str]]:
    """讲义/回复下方「依据」：编号 + 能一眼看懂来源的中文说明；网络来源带链接。

    画像相关的条目写明「落到了讲义的哪里」，这样学员能核对讲义确实按自己的画像定制过。
    """
    items: list[dict[str, str]] = []
    count: dict[str, int] = {}

    def add(prefix: str, label: str, detail: str = "", url: str = "") -> None:
        count[prefix] = count.get(prefix, 0) + 1
        items.append({"no": f"{prefix}{count[prefix]}", "group": GROUP_NAME[prefix],
                      "label": label, "detail": detail, "url": url})

    strict = kind in STRICT_KINDS
    for e in learner_effects(profile, market):
        if e["group"] == "目标客源国":
            continue
        add("P", f"{e['group']} · {e['title']}", ("本次落实：" + e["effect"]) if strict and e["effect"] else e["effect"])
    m = (profile or {}).get("market") or {}
    if m.get("country") and market:
        eff = next((e for e in learner_effects(profile, market) if e["group"] == "目标客源国"), None)
        if eff:
            add("P", f"目标客源国 · {eff['title']}", eff["effect"])
        country = market.get("country", "")
        phrases = (market.get("language") or {}).get("phrases") or []
        used = sum(1 for p in phrases if p.get("text") and p["text"] in (content or ""))
        add("M", f"国别知识库 · {country} · 语言：常用客服用语",
            f"共 {len(phrases)} 句" + (f"，本次按你的水平引用了 {used} 句" if content else ""))
        for key, name in (("culture", "文化"), ("customs", "习俗"), ("policy", "政策")):
            titles = [i["title"] for i in market.get(key) or []]
            if titles:
                add("M", f"国别知识库 · {country} · {name}", "；".join(titles))

    rubric = getattr(ctx, "rubric", None) or {}
    if getattr(ctx, "is_bridge", False):
        add("R", f"文化桥 · {ctx.name}", "十大客源国共通点与易踩的坑")
    elif rubric:
        add("R", f"评分标准 · {ctx.name}（{ctx.sp}）", "M1–M5 五档行为锚点与正反例")
    know = getattr(ctx, "knowledge", None) or {}
    if know.get("text") and not getattr(ctx, "is_bridge", False):
        add("K", f"技能知识库 · {ctx.name}", "引用：" + (_kb_parts(know.get("sources") or []) or "知识点正文"))
    nodes = (getattr(ctx, "skill_graph", None) or {}).get("nodes") or []
    if nodes:
        names = "、".join(str(n.get("name", n.get("id", ""))) for n in nodes[:4])
        add("G", f"技能图 · {ctx.sp} 及相邻技能点", f"共 {len(nodes)} 个节点：{names}")

    seen: set[str] = set()
    if m.get("country") and market:
        for s in market.get("sources") or []:
            if s.get("url") and s["url"] not in seen:
                seen.add(s["url"])
                add("W", f"网络来源 · {s.get('title', '')}", "政策类信息请以此为准核验", s["url"])
    for node in nodes:
        for ref in node.get("source_refs") or []:
            if isinstance(ref, dict) and ref.get("url") and ref["url"] not in seen and len(seen) < 8:
                seen.add(ref["url"])
                add("W", f"网络来源 · {ref.get('title') or ref['url']}", "", ref["url"])

    quiz = getattr(ctx, "quiz", None) or {}
    if quiz.get("count"):
        add("H", f"本技能点答题记录 · 共 {quiz['count']} 题、答对 {quiz.get('correct', 0)} 题", "")
    ab = getattr(ctx, "ability", None) or {}
    if ab.get("teach") or ab.get("real_v"):
        add("H", f"当前掌握度 · 教学 {ab.get('teach', 0):.0f} / 实战 {ab.get('real_v', 0):.0f}", "")
    for ev in (getattr(ctx, "evidence", None) or [])[:3]:
        add("O", f"实战订单 · {ev.get('summary', '')}", "")
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    items.sort(key=lambda it: order.get(it["no"][0], 99))
    return items
