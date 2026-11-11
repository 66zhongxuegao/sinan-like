# -*- coding: utf-8 -*-
"""入境游语音训练 · 语言-国籍-音色 配置（后端业务链通用）。

沙盒入口选择训练语言后：
  - 游客国籍从「母语为该语言的国家」中选取（替换原随机国籍）
  - 游客人设性别决定 Qwen 实时音色（女 -> female voice，男 -> male voice）

音色表为官方 Qwen3.5-Omni-Realtime Voice list 的精选用表（多语言音色，
按性别 + 语种风味匹配），后续可继续扩充。
"""

from __future__ import annotations

import random

# 语言码 -> 母语国家（中文标签，与沙盒 customer_pool.nationality 一致）
LANG_COUNTRIES: dict[str, list[str]] = {
    "en": ["美国", "英国", "澳大利亚"],
    "ja": ["日本"],
    "fr": ["法国"],
    "de": ["德国"],
    "ko": ["韩国"],
    "es": ["西班牙", "墨西哥"],
    "ru": ["俄罗斯"],
    "ar": ["沙特阿拉伯"],
    "zh": ["中国"],
    "it": ["意大利"],
    "pt": ["巴西"],
    "vi": ["越南"],
    "id": ["印度尼西亚"],
    "th": ["泰国"],
    "tr": ["土耳其"],
}

# 语言码 -> 英文名（用于提示词「只用 X 语回复」）
LANG_NAMES_EN: dict[str, str] = {
    "en": "English", "ja": "Japanese", "zh": "Mandarin Chinese", "fr": "French",
    "de": "German", "ko": "Korean", "es": "Spanish", "ru": "Russian", "ar": "Arabic",
    "it": "Italian", "pt": "Portuguese", "vi": "Vietnamese", "id": "Indonesian",
    "th": "Thai", "tr": "Turkish",
}

# 语言码 -> {male/female} -> Qwen 音色（官方 Voice list 精选）
VOICE_LANG: dict[str, dict[str, str]] = {
    "en": {"male": "Aiden", "female": "Jennifer"},
    "ja": {"male": "Evan", "female": "Ono Anna"},
    "fr": {"male": "Emilien", "female": "Serena"},
    "de": {"male": "Lenn", "female": "Maia"},
    "ko": {"male": "Raymond", "female": "Sohee"},
    "es": {"male": "Bodega", "female": "Sonrisa"},
    "ru": {"male": "Alek", "female": "Katerina"},
    "ar": {"male": "Radio Gol", "female": "Tina"},
    "zh": {"male": "Ethan", "female": "Serena"},
    "it": {"male": "Andre", "female": "Serena"},
    "pt": {"male": "Bodega", "female": "Sonrisa"},
    "vi": {"male": "Andre", "female": "Serena"},
    "id": {"male": "Rizky", "female": "Momo"},
    "th": {"male": "Andre", "female": "Serena"},
    "tr": {"male": "Andre", "female": "Serena"},
}

# 常见国家的中文名 -> 该语言的典型姓名（国籍被改写时替换姓名）
NAME_MALE: dict[str, str] = {
    "美国": "Michael", "英国": "James", "澳大利亚": "Jack", "日本": "Kenji",
    "韩国": "Minjun", "法国": "Luc", "德国": "Felix", "俄罗斯": "Ivan",
    "西班牙": "Mateo", "墨西哥": "Diego", "沙特阿拉伯": "Khalid", "中国": "小陈",
    "意大利": "Marco", "巴西": "Pedro", "越南": "Minh", "印度尼西亚": "Rizky",
    "泰国": "Somchai", "土耳其": "Emre",
}
NAME_FEMALE: dict[str, str] = {
    "美国": "Emma", "英国": "Olivia", "澳大利亚": "Mia", "日本": "Yuki",
    "韩国": "Seoyeon", "法国": "Camille", "德国": "Lena", "俄罗斯": "Anya",
    "西班牙": "Lucia", "墨西哥": "Sofia", "沙特阿拉伯": "Noor", "中国": "小周",
    "意大利": "Giulia", "巴西": "Larissa", "越南": "Linh", "印度尼西亚": "Sari",
    "泰国": "Mali", "土耳其": "Elif",
}


def supported_languages() -> list[str]:
    return sorted(LANG_COUNTRIES)


def country_for_language(lang: str, rng: random.Random | None = None) -> str:
    """返回该语言的母语国家（多个国家时随机一个）。"""
    if lang not in LANG_COUNTRIES:
        lang = "en"
    countries = LANG_COUNTRIES[lang]
    return (rng or random.Random()).choice(countries)


def name_for_country(country: str, gender: str) -> str:
    table = NAME_MALE if gender == "男" else NAME_FEMALE
    return table.get(country, "")


def normalize_gender(gender: str) -> str:
    """male/female/男/女/空 -> 男/女（空给 女 兜底）。"""
    g = (gender or "").strip()
    if g in ("男", "male", "M", "m"):
        return "男"
    if g in ("女", "female", "F", "f"):
        return "女"
    return "女"


def pick_voice(lang: str, gender: str) -> str:
    """按 语言 + 人设性别 选 Qwen 音色。"""
    lang = lang if lang in VOICE_LANG else "en"
    g = normalize_gender(gender)
    table = VOICE_LANG[lang]
    return table.get("male" if g == "男" else "female") or table["female"]