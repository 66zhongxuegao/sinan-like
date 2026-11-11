"""订单客户事实卡：确定性建卡、三态、释放、冲突检查。此模块不调用模型。"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta

from ..contracts.customer_role import customer_role_issues

FACT_LABELS = {
    "party": "出行人数", "dates": "出行日期", "days": "天数", "budget": "预算口径",
    "transport": "交通偏好", "hotel": "住宿标准", "special": "特殊需求",
    "decision": "决策人", "documents": "证件",
}
FACT_KEYS = tuple(FACT_LABELS)
STATES = frozenset(("fixed", "canonical_hidden", "unknown"))
UNDECIDED_DESTINATIONS = frozenset(("", "待定", "未定", "未确定", "暂未确定", "未知", "未明确", "待推荐", "未选择"))
FACT_CUES = {
    "party": r"人数|几个?人|几位|多少个?人|同行|几口|成人|孩子|people|persons|travelers|travellers|adults|children|何人",
    "dates": r"日期|哪天|几号|什么时候|何时|出发|date|when|depart|日付|いつ",
    "days": r"几天|多少天|天数|多久|how many days|duration|何日",
    "budget": r"预算|多少钱|价位|花费|总价|人均|budget|spend|予算",
    "hotel": r"住宿|酒店|几星|hotel|accommodation|ホテル",
    "transport": r"交通|用车|接送|高铁|航班|飞机|transport|transfer|train|flight|交通",
    "special": r"特殊|禁忌|健康|饮食|老人|轮椅|special|diet|health|mobility",
    "decision": r"决策|谁决定|谁做主|拍板|decision|decide",
    "documents": r"证件|护照|签证|回乡证|台胞证|passport|visa|document|パスポート",
}


def load_payload(row: dict | None) -> dict:
    raw = (row or {}).get("payload") or {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def _hash(order_id: str, key: str) -> int:
    return int(hashlib.sha256(f"{order_id}|{key}".encode()).hexdigest()[:16], 16)


def date_span_days(value: str) -> int | None:
    """只识别完整明确的日期范围；月中/月底等描述保持原样。"""
    dates = re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value or "")
    try:
        if len(dates) == 2:
            start, end = (datetime.strptime(d.replace("/", "-"), "%Y-%m-%d") for d in dates)
            days = (end - start).days + 1
            return days if days > 0 else None
        match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*[-–—~至到]\s*(?:(\d{1,2})\s*月)?\s*(\d{1,2})\s*[日号]", value or "")
        if match:
            month, start_day, end_month, end_day = match.groups()
            start = datetime(2028, int(month), int(start_day))
            end = datetime(2028, int(end_month or month), int(end_day))
            return (end - start).days + 1 if end >= start else None
    except ValueError:
        pass
    return None


def build_card(row: dict, *, fill_hidden: bool = False) -> dict:
    """旧单留空保持 unknown；新派单的未公开答案由订单号确定性补齐。"""
    payload = load_payload(row)
    order_id = str(row.get("order_id") or "")
    answers = payload.get("customer_answers") or {}
    answers = dict(answers) if isinstance(answers, dict) else {}
    day_options = (4, 5, 6, 7)
    day_count = day_options[_hash(order_id, "days") % len(day_options)]
    match = re.search(r"\d+", str(payload.get("days") or answers.get("days") or ""))
    if match:
        day_count = int(match.group())
    span = date_span_days(str(payload.get("dates") or answers.get("dates") or ""))
    issues = []
    if span is not None:
        if not payload.get("days"):
            day_count = span
            if fill_hidden:
                answers["days"] = f"{span} 天"
        elif span != day_count:
            if payload.get("dates"):
                issues.append({"key": "days", "reason": "existing_date_duration_conflict",
                               "value": str(payload["days"]), "expected": f"{span} 天"})
            else:
                answers.pop("dates", None)
    try:
        anchor = datetime.fromisoformat(str(row.get("created_at") or payload.get("created_at"))).date()
    except (ValueError, TypeError):
        # 仅用于没有创建日期的兼容输入，使用固定锚点以保证重复建卡不变。
        anchor = datetime(2026, 1, 1).date()
    start = anchor + timedelta(days=30 + _hash(order_id, "dates") % 60)
    defaults = {
        "party": ("2 人", "3 人", "3 大 1 小", "4 人")[_hash(order_id, "party") % 4],
        "days": f"{day_count} 天",
        "dates": f"{start.isoformat()} 至 {(start + timedelta(days=max(0, day_count - 1))).isoformat()}",
        "budget": f"人均 {4000 + 500 * (_hash(order_id, 'budget') % 7)} 元，不含往返大交通",
        "transport": "希望含接送机，市内用车按行程安排",
        "hotel": ("三星或同档次", "四星或同档次", "五星或同档次")[_hash(order_id, "hotel") % 3],
        "special": "希望行程不要太赶，其他特殊要求待确认",
        "decision": "本人决策",
    }
    identity_keys = ("source_market", "language", "age", "gender", "personality", "preferences",
                     "quirks", "hidden", "citizenship", "traveler_type", "passport_country",
                     "document_status", "visa_status")
    identity = {key: str(payload.get(key) or "").strip() for key in identity_keys}
    identity.update(customer=str(row.get("customer") or "客户"), destination=str(row.get("destination") or ""))
    from ..agents.customer import (stable_gender_age, DEFAULT_CUSTOMER_PERSONALITY,
                                   DEFAULT_CUSTOMER_PREFERENCES, DEFAULT_CUSTOMER_HIDDEN)
    gender, age = stable_gender_age(order_id or "order")
    defaults_identity = {"source_market": "香港", "language": "中文", "age": age, "gender": gender,
                         "personality": DEFAULT_CUSTOMER_PERSONALITY, "preferences": DEFAULT_CUSTOMER_PREFERENCES,
                         "hidden": DEFAULT_CUSTOMER_HIDDEN}
    for key, value in defaults_identity.items():
        identity[key] = identity.get(key) or value
    fields = {}
    for key in FACT_KEYS:
        explicit = str(payload.get(key) or "").strip()
        hidden = str(answers.get(key) or "").strip()
        value = explicit or hidden or (defaults.get(key, "") if fill_hidden else "")
        state = "fixed" if explicit else "canonical_hidden" if value else "unknown"
        fields[key] = {"value": value, "state": state, "revealed": state == "fixed",
                       "origin": "order" if explicit else "generator" if hidden else "derived" if value else "unknown"}
    return {"order_id": order_id, "identity": identity, "fields": fields, "version": 1, "issues": issues}


def render_intent(card: dict) -> str:
    identity, fields = card["identity"], card["fields"]
    destination = identity.get("destination") or ""
    parts = (["想出去旅行，目的地还没定，希望推荐一些地方"] if destination in UNDECIDED_DESTINATIONS
             else [f"想去{destination}玩"])
    for key in ("party", "dates", "days"):
        fact = fields[key]
        if fact["state"] == "fixed" and fact["value"]:
            parts.append(fact["value"])
    return "，".join(parts) + "，想请你帮忙安排一下行程。"


def render_card(card: dict) -> str:
    visible, hidden, unknown = [], [], []
    for key, fact in card["fields"].items():
        label = FACT_LABELS.get(key, key)
        if fact["state"] == "unknown":
            unknown.append(label)
        elif fact["state"] == "fixed" or fact.get("revealed"):
            visible.append(f"- {label}：{fact['value']}")
        else:
            hidden.append(f"- {label}：{fact['value']}（对方明确询问该项时直接回答；不要故意为难对方）")
    return ("【已告知对方／可直接确认】\n" + ("\n".join(visible) or "暂无")
            + "\n【你心里有数但还没主动说】\n" + ("\n".join(hidden) or "暂无")
            + "\n【你确实没定／没有确定】\n" + ("、".join(unknown) or "暂无")
            + "\n未定项只能表达尚未确定、没有确定或邀请建议，禁止编造具体人数、日期、价格与身份结论。")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower()
    def numeral(match):
        digits = dict(zip("零一二两三四五六七八九", (0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
        total = section = number = 0
        for char in match.group():
            if char in digits:
                number = digits[char]
            elif char == "万":
                total += (section + number) * 10000
                section = number = 0
            else:
                section += (number or 1) * {"十": 10, "百": 100, "千": 1000}[char]
                number = 0
        return str(total + section + number)
    text = re.sub(r"[零一二两三四五六七八九十百千万]+(?=\s*(?:个人|人|位|名|大|小|天|星|口|月|日|号|元|块))", numeral, text)
    return re.sub(r"\s+", "", text)


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", _normalize(text)))


def mentioned_in_reference(candidate: str, reference: str) -> bool:
    """Return True when a candidate merely restates document proposal content.

    Feedback frequently quotes the proposal's dates, prices or party size. Those
    values can differ from the customer's original brief without being a change
    to the customer's confirmed requirements.
    """
    if not candidate or not reference:
        return False
    needle = _normalize(candidate)
    haystack = _normalize(reference)
    if needle and needle in haystack:
        return True
    nums = numbers(candidate)
    return bool(nums) and nums.issubset(numbers(reference))

def asked_keys(question: str) -> list[str]:
    return [key for key, cue in FACT_CUES.items() if re.search(cue, question or "", re.I)]


FACT_QUESTIONS = {
    "party": r"人数|几个人|几位(?:出行|客人|成人)?|多少人|几大几小|几口人|\d+\s*(?:人|位)|成人.{0,8}(?:几位|几个?人)|孩子.{0,8}(?:几位|几个?人|几岁)|how many people|number of (?:people|travelers)",
    "dates": r"哪天|哪一天|几号|什么时候|何时|出行日期|出发日期|日期是|when (?:do|will|are)|travel dates",
    "days": r"几天|多少天|行程几天|天数|how many days",
    "budget": r"预算|人均|总价|多少钱|价位|what budget",
    "hotel": r"住什么|住哪|住宿|酒店|几星|what hotel",
    "transport": r"怎么去|什么车|车型|交通|用车|接送|航班|车次|what transport",
    "special": r"有什么特殊|特殊(?:需求|要求)|忌口|忌讳|禁忌|饮食(?:禁忌|要求)|过敏|行动不便|轮椅|无障碍|医疗|健康|儿童餐|婴儿床|special requirements",
    "decision": r"谁决定|谁做主|拍板|决策人",
    "documents": r"需要什么证件|证件(?:是|有|需要)|护照(?:是|有|需要)|签证(?:是|有|需要)|回乡证(?:是|有|需要)",
}


def asked_fact_keys(question: str) -> list[str]:
    """只识别明确提问，避免把“您和孩子”误判成询问人数。"""
    return [key for key, cue in FACT_QUESTIONS.items() if re.search(cue, question or "", re.I)]


def extract_facts(text: str, card: dict, question: str = "") -> dict:
    """仅提取客户已说出的字面事实，不从定制师的建议推断客户已确认。"""
    norm = _normalize(text)
    out = {}
    for key, fact in card["fields"].items():
        value = str(fact.get("value") or "")
        if value and _normalize(value) in norm:
            out[key] = value
    # 简单数值槽位既用于释放，也用于发现“人数/天数/预算”冲突。
    patterns = {
        "party": r"\d+\s*(?:大|成人).{0,5}\d+\s*(?:小|儿童)|\d+\s*(?:个人|人|位|口)|\d+\s*(?:adults?|people|persons?)",
        "days": r"\d+\s*(?:天|days?)",
        "budget": r"(?:预算|人均|总价|budget)[^\d\n]{0,12}\d+(?:\s*[-~至]\s*\d+)?(?:\s*(?:元|块|yuan|rmb))?",
        "dates": r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s*(?:至|到|to|[-~])\s*\d{4}[-/]\d{1,2}[-/]\d{1,2})?|\d{1,2}\s*月\s*\d{1,2}\s*[日号]",
        "hotel": r"\d+\s*(?:星|-?star)",
    }
    asked = set(asked_keys(question))
    for key, pattern in patterns.items():
        match = re.search(pattern, _normalize(text), re.I)
        if match and (key in asked or re.search(FACT_CUES[key], text, re.I)):
            candidate = match.group()
            expected = card["fields"][key].get("value") or ""
            same_numbers = numbers(candidate) == numbers(expected)
            if key == "party":
                expected_counts = [int(n) for n in re.findall(r"\d+", _normalize(expected))]
                candidate_counts = [int(n) for n in re.findall(r"\d+", candidate)]
                same_numbers = candidate_counts == expected_counts or (
                    len(expected_counts) == 2 and len(candidate_counts) == 1 and candidate_counts[0] == sum(expected_counts))
            if key == "budget":
                per_person = bool(re.search(r"人均|perperson", _normalize(candidate)))
                total = bool(re.search(r"总价|总预算|total", _normalize(candidate)))
                expected_per_person = bool(re.search(r"人均|perperson", _normalize(expected)))
                if (total and expected_per_person) or (per_person and re.search(r"总价|总预算|total", expected)):
                    same_numbers = False
            if expected and same_numbers:
                # 保留完整规范口径，避免把“人均/含不含交通”截断后回写。
                out[key] = expected
            else:
                out[key] = candidate
    return out


def check_reply(text: str, card: dict, *, question: str = "", reference: str = "") -> list[dict]:
    """核对事实、语言和明确角色越权；其余语义仍需实际对话验收。"""
    issues = customer_role_issues(text)
    proposed = confirmed_observations(question, text, card)
    if proposed:
        card, proposal_events = reconcile(card, proposed, confirmed=True)
        issues.extend({"key": e["fact_key"], "reason": "confirmation_conflict", "value": e["value"],
                       "expected": e.get("expected", "")} for e in proposal_events if e["kind"] == "conflict")
    extracted = extract_facts(text, card, question)
    for key, candidate in extracted.items():
        if reference and mentioned_in_reference(candidate, reference):
            continue
        fact = card["fields"][key]
        if fact["state"] == "unknown":
            issues.append({"key": key, "reason": "unknown_concrete_value", "value": candidate})
        elif candidate != fact["value"]:
            issues.append({"key": key, "reason": "fact_conflict", "value": candidate, "expected": fact["value"]})
        elif fact["state"] == "canonical_hidden" and not fact.get("revealed") and key not in asked_keys(question) and not reference:
            issues.append({"key": key, "reason": "premature_hidden_disclosure", "value": candidate})
    allowed = set()
    for fact in card["fields"].values():
        if fact["state"] != "unknown":
            allowed.update(numbers(fact["value"]))
    allowed.update(numbers(reference))
    allowed.update(numbers(card.get("identity", {}).get("age") or ""))
    for number in numbers(text) - allowed:
        issues.append({"key": "numeric", "reason": "unsupported_number", "value": number})
    if card["fields"]["documents"]["state"] == "unknown" and re.search(
            r"(?:持有|拿着|带着|办好了|已办妥|有效的).{0,12}(?:护照|签证|回乡证|台胞证)|"
            r"(?:护照|签证|回乡证|台胞证).{0,8}(?:办好了|有效|齐全)|"
            r"(?:have|hold).{0,15}(?:passport|visa)", text, re.I):
        if not re.search(r"还没|尚未|未定|不确定|没有|don't|not yet", text, re.I):
            issues.append({"key": "documents", "reason": "unknown_concrete_value", "value": text})
    language = card.get("identity", {}).get("language") or "中文"
    if language != "中文" and re.search(r"[\u3400-\u9fff]", text or "") and language not in ("日本語",):
        issues.append({"key": "language", "reason": "unexpected_chinese"})
    return issues


def confirmed_observations(question: str, reply: str, card: dict) -> dict:
    if not re.search(r"确认|确定|是否|可以吗|好吗|confirm|agree", question or "", re.I):
        return {}
    if re.search(r"不|没|再想|未定|no\b|not\b|don't", reply or "", re.I):
        return {}
    if not re.search(r"确认|确定|可以|同意|就按|好的|对|yes\b|confirm|agree", reply or "", re.I):
        return {}
    observations = extract_facts(question, card, question)
    for key in asked_keys(question):
        if key in observations or card["fields"][key]["state"] != "unknown":
            continue
        match = re.search(re.escape(FACT_LABELS[key]) + r"\s*[：:]\s*([^。；;\n]+)", question, re.I)
        if match:
            value = re.split(r"[，,]?\s*(?:确认|确定|可以吗|好吗|是否)", match.group(1))[0].strip(" ，,？?")
            if value:
                observations[key] = value
    return observations


def reconcile(card: dict, observations: dict, *, confirmed: bool = False) -> tuple[dict, list[dict]]:
    """固定值与已确定隐藏值保持不变；unknown 只接纳经调用方确认的字面值。"""
    card = json.loads(json.dumps(card, ensure_ascii=False))
    events, changed = [], False
    for key, value in observations.items():
        if key not in FACT_KEYS or not isinstance(value, str) or not value.strip():
            continue
        fact = card["fields"][key]
        if confirmed and fact["state"] == "unknown":
            fact.update(value=value, state="fixed", revealed=True, origin="conversation_confirmation")
            changed = True
            events.append({"fact_key": key, "value": value, "state": "fixed", "kind": "confirmed"})
            continue
        if fact["state"] == "unknown" or _normalize(value) != _normalize(fact["value"]):
            # 未经明确确认的抽取不能把 unknown 或旧答案悄悄变成新答案。
            events.append({"fact_key": key, "value": value, "state": fact["state"], "kind": "conflict",
                           "expected": fact["value"]})
            continue
        if not fact.get("revealed"):
            fact["revealed"] = True
            changed = True
            events.append({"fact_key": key, "value": fact["value"], "state": fact["state"], "kind": "released"})
    if changed:
        card["version"] += 1
    return card, events