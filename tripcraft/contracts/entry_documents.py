"""来内地/大陆旅行的证件称谓与提示词边界（2026-10-17 核对）。

仅提供名称和适用身份；签证、免签资格及办理状态需按本人资料核验。
不在这里固化免签国家名单、停留天数或护照剩余有效期。
"""

from __future__ import annotations

import re
from collections.abc import Mapping


HK_MACAO_DOCUMENT = "港澳居民来往内地通行证（俗称回乡证）"
HK_MACAO_FOREIGN_DOCUMENT = "港澳居民来往内地通行证（非中国籍）"
TAIWAN_DOCUMENT = "台湾居民来往大陆通行证（简称台胞证）"
FOREIGN_DOCUMENTS = "有效护照或其他国际旅行证件；中国签证或免签条件按实际身份与行程核验"
CHINESE_DOCUMENTS = "有效中华人民共和国护照，或符合签发条件的中华人民共和国旅行证等中国旅行证件"

ENTRY_IDENTITY_FIELDS = ("citizenship", "traveler_type")
CHINESE_CITIZENSHIPS = frozenset({"中国", "中国籍", "中国公民", "中华人民共和国", "chinese", "china", "cn"})
OVERSEAS_CHINESE_TYPES = frozenset({"overseas_chinese", "旅外中国公民", "海外中国公民", "华侨"})
INBOUND_TRAVELER_TYPES = frozenset({"入境", "入境游", "inbound", "foreign"}) | OVERSEAS_CHINESE_TYPES
DOMESTIC_MARKETS = frozenset({
    "中国", "中国内地", "中国大陆", "大陆", "内地", "国内", "国内游客", "内地游客",
    "中国大陆居民", "中国内地居民", "mainland china", "china mainland", "china", "cn", "prc",
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古", "广西", "西藏", "宁夏", "新疆",
})
HK_MACAO_MARKETS = frozenset({"香港", "澳门", "中国香港", "中国澳门", "hong kong", "hongkong", "macao", "macau", "hk", "mo"})
TAIWAN_MARKETS = frozenset({"台湾", "中国台湾", "台灣", "taiwan", "tw"})

OFFICIAL_SOURCES = (
    ("港澳居民来往内地通行证", "https://www.nia.gov.cn/n741445/n741604/n1787219/n1795772/c1792480/content.html"),
    ("非中国籍港澳永久性居民通行证", "https://www.nia.gov.cn/n794014/n794021/c1659665/content.html"),
    ("台湾居民来往大陆通行证", "https://www.nia.gov.cn/n741440/n741587/n1316094/n1355872/c1356367/content.html"),
    ("出境入境管理法", "https://www.nia.gov.cn/n794014/n1050181/n1050479/c1013311/content.html"),
    ("外国人入境出境管理条例", "https://www.nia.gov.cn/n794014/n1050181/n1050479/c1014161/content.html"),
    ("往来港澳通行证及签注", "https://www.nia.gov.cn/n741440/n741587/n1316094/n1355872/c1559612/content.html"),
    ("外交部护照/旅行证", "https://www.mfa.gov.cn/wjbzwfwpt/byw/hzlxz/"),
)


def _text(value) -> str:
    return str(value or "").strip()


def _market(source_market: str) -> str:
    value = _text(source_market).lower()
    value = value.removesuffix("特别行政区").removesuffix("自治区").removesuffix("省").removesuffix("市")
    return {"广西壮族": "广西", "宁夏回族": "宁夏", "新疆维吾尔": "新疆"}.get(value, value)


def _citizenship(facts: Mapping) -> str:
    value = _text(facts.get("citizenship")).lower()
    return "" if value in {"未知", "待确认", "待核验", "未明确", "不详", "unknown", "unspecified"} else value


def is_domestic_traveler(source_market: str, facts: Mapping | None = None) -> bool:
    """仅按明确旅行类型或客源地识别国内单，不从目的地/语言推定。"""
    kind = _text((facts or {}).get("traveler_type")).lower()
    if kind in {"国内", "国内游", "国内游客", "内地游客", "domestic"}:
        return True
    if kind in INBOUND_TRAVELER_TYPES:
        return False
    return _market(source_market) in DOMESTIC_MARKETS


def is_overseas_chinese(source_market: str, facts: Mapping | None = None) -> bool:
    facts = facts or {}
    citizenship = _citizenship(facts)
    kind = _text(facts.get("traveler_type")).lower()
    if citizenship and citizenship not in CHINESE_CITIZENSHIPS:
        return False
    docs = _text(facts.get("documents"))
    return (kind in OVERSEAS_CHINESE_TYPES
            or _market(source_market) in {"华侨", "旅外中国公民", "海外中国公民"}
            or citizenship in CHINESE_CITIZENSHIPS
            or any(name in docs for name in ("中华人民共和国护照", "中国护照", "中华人民共和国旅行证", "中国旅行证")))


def document_type_for(source_market: str, facts: Mapping | None = None) -> str:
    """规范化证件类型；默认类型不表示客户已经持证或已满足入境条件。"""
    facts = facts or {}
    if is_domestic_traveler(source_market, facts):
        return ""
    value = _text(facts.get("documents"))
    market = _market(source_market)
    if market in HK_MACAO_MARKETS:
        if value == "非中国籍回乡证":
            return HK_MACAO_FOREIGN_DOCUMENT
        if value in {"", "回乡证", "回鄉證", "港澳通行证", "往来港澳通行证", "港澳居民来往内地通行证",
                     HK_MACAO_DOCUMENT, "港澳居民来往内地通行证（回乡证）"}:
            citizenship = _citizenship(facts)
            foreign = bool(citizenship) and citizenship not in CHINESE_CITIZENSHIPS
            return HK_MACAO_FOREIGN_DOCUMENT if foreign else HK_MACAO_DOCUMENT
    elif market in TAIWAN_MARKETS:
        if value in {"", "台胞证", "台胞證", "台湾通行证", "台湾居民来往大陆通行证"}:
            return TAIWAN_DOCUMENT
    elif not value or value == FOREIGN_DOCUMENTS:
        return CHINESE_DOCUMENTS if is_overseas_chinese(source_market, facts) else FOREIGN_DOCUMENTS
    # 旧派单资料的无条件结论只作待核验线索，不在模型上下文里延续为政策事实。
    return re.sub(r"[（(](?:需办理签证|需签证|免签入境)[）)]", "（签证或免签条件待核验）", value)


def entry_document_prompt(source_market: str, facts: Mapping | None = None) -> str:
    facts = facts or {}
    if is_domestic_traveler(source_market, facts):
        return ("【国内游客沟通范围】\n"
                "本单为内地游客在内地/大陆旅游，围绕目的地、人数、日期、预算和行程沟通。"
                "不主动提及证件、签证、出入境办理，也不把它们列成待确认需求。")
    market = _market(source_market)
    if market in HK_MACAO_MARKETS:
        applicable = (
            "中国籍香港、澳门居民来内地：有效《港澳居民来往内地通行证》（俗称回乡证）。\n"
            "非中国籍港澳永久性居民：已获签发的有效《港澳居民来往内地通行证（非中国籍）》"
            "可用于短期旅游等；其他情形按本人有效外国护照及适用的中国签证、免签或其他入境许可处理。\n"
            "《往来港澳通行证》和相应签注用于内地居民赴香港、澳门，与港澳居民来内地的证件名称和方向有区别。"
        )
    elif market in TAIWAN_MARKETS:
        applicable = "台湾居民来大陆：有效《台湾居民来往大陆通行证》（简称台胞证）。"
    else:
        chinese_rule = (
            "旅居海外的中国公民回国：有效《中华人民共和国护照》，或符合签发条件的有效《中华人民共和国旅行证》等中国旅行证件；"
            "保持中国国籍者回国不套用外国人办理中国签证的设定。"
        )
        foreign_rule = (
            "外国游客：有效护照或其他国际旅行证件，及适用的有效中国签证或其他入境许可；"
            "旅游通常对应L字签证。符合当期免签条件、持有效外国人居留证件等情形可免办签证。"
        )
        applicable = chinese_rule if is_overseas_chinese(source_market, facts) else foreign_rule + "\n" + chinese_rule
    return (
        "【入境证件名称与表达规则】\n" + applicable + "\n"
        "客源地仅表示来源或居住地；国籍、永久居民身份、本人已持证件和办理状态以明确资料为准。"
        "默认的证件类型仅供称谓参考，不代表本人或所有同行人已持有、已办妥或必然符合免签条件。\n"
        "资料未明确国籍、签证或免签资格时保留待核验状态，不从语言或客源地自行推定。"
        "资料存在身份与证件冲突时先核实，不擅自补全或混用。"
        "签证、签注、通行证和护照各自使用准确称谓；不要把所有境外游客都说成必须办理中国签证。\n"
        "这些背景知识按需引用。首呼先自然说明旅行意向；仅在对方问到、本人有明确疑问或行程确有需要时谈证件。"
        "按适用身份说相关名称，不罗列全部类别，不反复引回证件话题。\n"
        "免签国别、停留期限、办理材料、证件有效期要求按出行时官方政策核验，不编造固定天数或统一要求剩余六个月。"
    )
