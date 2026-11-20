"""学员个性化画像契约：学习风格（Felder–Silverman）+ 职业背景 + 目标客源国与语言水平。

画像分三部分，彼此独立、各管教学的一个侧面：
  1. 学习风格：控制每个技能点「怎么教」（图 / 话术 / 动手 / 原理 …）。
  2. 目标客源国 + 语言水平：控制每个技能点里「加什么语言提示、文化提示」。
  3. 八维掌握度（原来的 12 道测评题，见 agents/profiler.py）：控制「学什么、先学哪个」，
     不管什么风格、什么客源国，八维技能点最终都要学完。

本模块只放**确定性**的东西：题面、选项、打分、中文标签。没有模型参与，结果可复算。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- 学习风格

# 每个维度一道题、四个选项：a=明显偏前者、b=略偏前者、c=略偏后者、d=明显偏后者
# 打分：a=-2 b=-1 c=+1 d=+2（负数偏前者，正数偏后者；没有 0，逼学员选边）
STYLE_VALUES = {"a": -2, "b": -1, "c": 1, "d": 2}

STYLE_DIMS: tuple[dict[str, Any], ...] = (
    {"id": "AR", "name": "信息加工", "en": "Active–Reflective", "ask": "我习惯怎样加工信息？",
     "poles": ("主动型", "反思型"),
     "gist": ("通过尝试、讨论、应用来理解", "先独立思考、整理，再行动")},
    {"id": "SI", "name": "内容偏好", "en": "Sensing–Intuitive", "ask": "我更喜欢接触什么内容？",
     "poles": ("感知型", "直觉型"),
     "gist": ("具体事实、实例、操作方法", "概念、原理、关系与可能性")},
    {"id": "VV", "name": "表达形式", "en": "Visual–Verbal", "ask": "我更喜欢怎样的信息表达？",
     "poles": ("视觉型", "言语型"),
     "gist": ("图像、图表、结构图、演示", "文字说明、口头解释、语言讨论")},
    {"id": "SG", "name": "理解路径", "en": "Sequential–Global", "ask": "我习惯怎样建立理解？",
     "poles": ("序列型", "整体型"),
     "gist": ("沿着相互衔接的步骤逐步理解", "先寻找整体联系，再逐渐贯通细节")},
)
STYLE_BY_ID = {d["id"]: d for d in STYLE_DIMS}

STYLE_QUESTIONS: tuple[dict[str, Any], ...] = (
    {"id": "ST1", "style": "AR", "part": "style",
     "title": "要学一个新技能（比如怎么问清客户的预算），你更愿意怎么开始？",
     "options": [
         {"key": "a", "label": "直接上手试，拉上同学或同事模拟一遍，边做边改"},
         {"key": "b", "label": "先看一个例子，然后很快找机会练一练"},
         {"key": "c", "label": "先自己想清楚、记笔记，心里有把握了再动手"},
         {"key": "d", "label": "需要安静地独立琢磨一阵，想透了才愿意开始做"},
     ]},
    {"id": "ST2", "style": "SI", "part": "style",
     "title": "老师讲一个知识点，你更喜欢听到哪一种？",
     "options": [
         {"key": "a", "label": "具体的步骤、清单和真实案例，直接告诉我「第一步做什么」"},
         {"key": "b", "label": "以案例为主，再配一点道理"},
         {"key": "c", "label": "以原理和逻辑为主，再配一个案例帮我理解"},
         {"key": "d", "label": "先讲清为什么这样做、和别的知识怎么关联，案例我自己能推出来"},
     ]},
    {"id": "ST3", "style": "VV", "part": "style",
     "title": "同一份内容，哪种呈现方式你记得最牢？",
     "options": [
         {"key": "a", "label": "图：流程图、结构图、示意图，一眼就懂"},
         {"key": "b", "label": "图为主，配少量文字"},
         {"key": "c", "label": "文字说明为主，配一两个表格"},
         {"key": "d", "label": "文字讲解，或者有人口头讲给我听、一起讨论"},
     ]},
    {"id": "ST4", "style": "SG", "part": "style",
     "title": "面对一个很大的新主题，你习惯怎么建立理解？",
     "options": [
         {"key": "a", "label": "按顺序一步一步来，前一步弄懂了才往下走"},
         {"key": "b", "label": "大体按顺序学，偶尔回头看看"},
         {"key": "c", "label": "先翻一遍看全貌，再回头补细节"},
         {"key": "d", "label": "先搞清整体和各部分的联系，细节过后自然贯通，学的顺序可以跳"},
     ]},
)

# ---------------------------------------------------------------- 职业背景

BACKGROUND_STATUS = {
    "student": "在校学生",
    "travel": "旅游/酒店行业在职（新人）",
    "other_job": "其他行业在职，准备转行做入境游定制",
    "switching": "已转行或待业，正在系统学习",
}

BACKGROUND_QUESTION: dict[str, Any] = {
    "id": "BG1", "part": "background", "type": "choice_text",
    "title": "你目前的情况是？",
    "options": [{"key": k, "label": v} for k, v in BACKGROUND_STATUS.items()],
    "text_label": "专业，或转行前从事的行业与岗位（选填）",
    "text_placeholder": "例如：酒店管理专业 / 之前做销售 / 日语专业",
}

# 讲解时怎么用这份背景
BACKGROUND_HINT = {
    "student": "学员是在校学生，缺少真实接单经验：术语要先解释再用，多给「像在学校里做小组作业」式的类比，"
               "例子从零开始，不默认他见过订单或客户。",
    "travel": "学员已在旅游/酒店行业工作：基础名词不必解释，直接讲定制师特有的做法与易错点，"
              "可以拿他熟悉的接待、前台、计调场景做对照。",
    "other_job": "学员来自其他行业、准备转行：用他原行业的做法做类比来搭桥，再指出定制师岗位上不一样的地方。",
    "switching": "学员已离开原岗位、系统学习中：节奏可以快一些，强调可迁移的原有经验，并帮他把经验落到定制师的具体动作上。",
}

# ---------------------------------------------------------------- 语言水平

LANG_LEVEL_NAMES = ("零基础", "入门", "日常交流", "工作交流", "流利")
# 三道题各 0–3 分，合计 0–9，分档：0–1 零基础 / 2–3 入门 / 4–5 日常 / 6–7 工作 / 8–9 流利
LANG_BANDS = ((0, 1, 0), (2, 3, 1), (4, 5, 2), (6, 7, 3), (8, 9, 4))

LANG_QUESTIONS: tuple[dict[str, Any], ...] = (
    {"id": "LG1", "skill": "listen", "part": "language", "skill_name": "听",
     "title": "客人用{lang}讲一段 30 秒的行程需求，你大概能听懂多少？",
     "options": [
         {"key": "a", "label": "几乎听不懂，或者没学过", "level": 0},
         {"key": "b", "label": "能听出一些单词和很熟悉的短句", "level": 1},
         {"key": "c", "label": "对方放慢语速时，大意基本能懂", "level": 2},
         {"key": "d", "label": "正常语速也基本能懂，关键数字和细节能抓住", "level": 3},
     ]},
    {"id": "LG2", "skill": "speak", "part": "language", "skill_name": "说",
     "title": "要用{lang}向客人介绍一天的行程并确认预算，你能做到哪一步？",
     "options": [
         {"key": "a", "label": "完全不能", "level": 0},
         {"key": "b", "label": "只能说问候语和几个单词", "level": 1},
         {"key": "c", "label": "能说简单的句子，复杂的要靠翻译软件", "level": 2},
         {"key": "d", "label": "能比较流畅地沟通，偶尔查个词", "level": 3},
     ]},
    {"id": "LG3", "skill": "write", "part": "language", "skill_name": "读写",
     "title": "客人发来一段{lang}的消息，问行程细节，你怎么处理？",
     "options": [
         {"key": "a", "label": "全靠翻译软件，自己基本看不懂", "level": 0},
         {"key": "b", "label": "能看懂大意，回复要用翻译软件逐句生成", "level": 1},
         {"key": "c", "label": "能自己写简短的回复，偶尔有错", "level": 2},
         {"key": "d", "label": "能独立写出准确、得体的商务回复", "level": 3},
     ]},
)
LANG_BY_ID = {q["id"]: q for q in LANG_QUESTIONS}


def lang_level_of(total: int) -> tuple[int, str]:
    for lo, hi, level in LANG_BANDS:
        if lo <= total <= hi:
            return level, LANG_LEVEL_NAMES[level]
    return 0, LANG_LEVEL_NAMES[0]


# ---------------------------------------------------------------- 打分与描述

def score_style(answers: dict[str, str]) -> dict[str, int]:
    """{题号: 选项} → {AR: -2, SI: 1, ...}。缺题或选项不合法的维度直接缺省（不猜）。"""
    out: dict[str, int] = {}
    for q in STYLE_QUESTIONS:
        v = STYLE_VALUES.get(str((answers or {}).get(q["id"], "")).strip().lower())
        if v is not None:
            out[q["style"]] = v
    return out


def describe_style(style: dict[str, int]) -> list[dict[str, Any]]:
    """把分数翻成中文描述，给画像页、证据和提示词共用。"""
    rows = []
    for d in STYLE_DIMS:
        v = style.get(d["id"])
        if v is None:
            continue
        side = 0 if v < 0 else 1
        strength = "明显" if abs(v) >= 2 else "略偏"
        rows.append({
            "id": d["id"], "name": d["name"], "en": d["en"], "value": v,
            "pole": d["poles"][side], "other": d["poles"][1 - side], "strong": abs(v) >= 2,
            "strength": strength, "gist": d["gist"][side],
            "text": f"{d['poles'][0]}—{d['poles'][1]}：{strength}{d['poles'][side]}（{d['gist'][side]}）",
        })
    return rows


def score_language(answers: dict[str, str]) -> dict[str, Any] | None:
    """三道语言题 → 水平档。三题没答齐返回 None。"""
    parts: dict[str, int] = {}
    for q in LANG_QUESTIONS:
        key = str((answers or {}).get(q["id"], "")).strip().lower()
        opt = next((o for o in q["options"] if o["key"] == key), None)
        if opt is None:
            return None
        parts[q["skill"]] = int(opt["level"])
    total = sum(parts.values())
    level, name = lang_level_of(total)
    return {"level": level, "level_name": name, "total": total, "skills": parts}


def lang_questions_public(lang: str) -> list[dict]:
    """语言题面（把{lang}换成具体语种，去掉 level）。"""
    return [{"id": q["id"], "part": "language", "skill_name": q["skill_name"],
             "title": q["title"].replace("{lang}", lang or "外语"),
             "options": [{"key": o["key"], "label": o["label"]} for o in q["options"]]}
            for q in LANG_QUESTIONS]


def style_questions_public() -> list[dict]:
    return [{"id": q["id"], "part": "style", "style": q["style"],
             "dim_name": f"学习风格 · {STYLE_BY_ID[q['style']]['name']}",
             "title": q["title"],
             "options": [{"key": o["key"], "label": o["label"]} for o in q["options"]]}
            for q in STYLE_QUESTIONS]


def background_question_public() -> dict:
    q = BACKGROUND_QUESTION
    return {"id": q["id"], "part": "background", "type": q["type"], "dim_name": "你的背景",
            "title": q["title"], "options": list(q["options"]),
            "text_label": q["text_label"], "text_placeholder": q["text_placeholder"]}


def build_profile(*, style_answers: dict[str, str] | None = None,
                  background_status: str = "", background_note: str = "",
                  market_code: str = "", market: dict | None = None,
                  language_answers: dict[str, str] | None = None) -> dict[str, Any]:
    """把测评答案收成一份可落库的画像 JSON。三块各自可缺省：没答的块不出现，教学端就不做对应定制。"""
    profile: dict[str, Any] = {"version": 1}
    style = score_style(style_answers or {})
    if style:
        profile["style"] = style
    status = str(background_status or "").strip()
    note = str(background_note or "").strip()[:60]
    if status in BACKGROUND_STATUS or note:
        profile["background"] = {"status": status if status in BACKGROUND_STATUS else "",
                                 "status_label": BACKGROUND_STATUS.get(status, ""), "note": note}
    if market_code and market:
        m: dict[str, Any] = {"code": market_code, "country": market.get("country", ""),
                             "language": market.get("service_language", ""),
                             "lang_short": market.get("lang_short", "")}
        lang = score_language(language_answers or {})
        if lang:
            m.update({"language_level": lang["level"], "language_level_name": lang["level_name"],
                      "language_skills": lang["skills"]})
        profile["market"] = m
    return profile


def is_empty(profile: dict | None) -> bool:
    return not profile or not any(k in profile for k in ("style", "background", "market"))
