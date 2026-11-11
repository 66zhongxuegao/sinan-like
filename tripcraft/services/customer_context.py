"""客户角色唯一上下文入口；共享事实、跨通道历史、生成守卫与审计。"""
from __future__ import annotations

import json
import re
import uuid

from ..contracts.customer_role import CUSTOMER_ROLE_RULES, customer_memory_turns

from .customer_card import (FACT_LABELS, UNDECIDED_DESTINATIONS, asked_keys, check_reply,
                          confirmed_observations, extract_facts, mentioned_in_reference,
                          asked_fact_keys)

FALLBACKS = {
    "中文": "这项我还没确定，需要再确认一下。",
    "English": "I haven't decided that yet; I need to confirm it.",
    "日本語": "まだ決めていません。確認してからお伝えします。",
    "한국어": "아직 정하지 않았어요. 확인하고 말씀드릴게요.",
    "ไทย": "ยังไม่ได้ตัดสินใจ ขอตรวจสอบข้อมูลก่อนนะคะ",
    "Tiếng Việt": "Tôi chưa quyết định, cần xác nhận lại.",
    "Bahasa Indonesia": "Saya belum memutuskan, perlu memastikan dahulu.",
    "Deutsch": "Das habe ich noch nicht entschieden, ich muss es erst bestätigen.",
    "Français": "Je n'ai pas encore décidé, je dois le confirmer.",
    "العربية": "لم أقرر ذلك بعد، أحتاج إلى التأكد أولاً.",
    "Español": "Todavía no lo he decidido; necesito confirmarlo.",
    "Русский": "Я ещё не решил, нужно уточнить.",
    "Italiano": "Non ho ancora deciso, devo confermare.",
    "Português": "Ainda não decidi, preciso confirmar.",
    "Türkçe": "Henüz karar vermedim, teyit etmem gerekiyor.",
}
RECEIPTS = {
    "中文": "我看到了，具体安排请按我们已经确认的需求核对；还没确定的地方再和我商量。",
    "English": "I've read it. Please check it against our agreed requirements and discuss any undecided details with me.",
    "日本語": "確認しました。合意した希望に沿って確認し、未定の点は相談してください。",
    "한국어": "확인했어요. 합의한 요구 사항을 확인하고 미정인 부분은 상의해 주세요.",
}
GREETINGS = {"中文": "喂，您好。", "English": "Hello.", "日本語": "もしもし。", "한국어": "여보세요.",
             "ไทย": "สวัสดีค่ะ", "Tiếng Việt": "Xin chào.", "Bahasa Indonesia": "Halo.",
             "Deutsch": "Guten Tag.", "Français": "Bonjour.", "العربية": "مرحباً.",
             "Español": "Hola.", "Русский": "Здравствуйте.", "Italiano": "Buongiorno.",
             "Português": "Olá.", "Türkçe": "Merhaba."}
EN_LABELS = dict(zip(FACT_LABELS, ("Travel party", "Travel dates", "Duration", "Budget", "Transport",
                                   "Hotel", "Special requirements", "Decision maker", "Documents")))


def _cn_fact_phrase(key: str, fact: dict) -> str:
    """把事实卡字段说成人话，避免「人数：3 人；目的地：新疆」这种表格腔。"""
    unknown_phrases = {
        "party": "人数还没确定", "dates": "日期还没确定", "days": "天数还没确定",
        "budget": "预算还没确定", "transport": "交通还没确定", "hotel": "住宿还没确定",
        "special": "特殊需求还没确定", "decision": "谁拍板还没确定", "documents": "证件情况还没确定",
    }
    if fact.get("state") == "unknown":
        return unknown_phrases.get(key, "这项我还没确定")
    value = str(fact.get("value") or "").strip()
    if not value:
        return unknown_phrases.get(key, "这项我还没确定")
    if key == "party":
        m = re.search(r"(\d+)\s*大\s*(\d+)\s*小", value)
        if m:
            return f"我们这次是{m.group(1)}个大人带{m.group(2)}个孩子"
        return f"我们这次一共{value}"
    if key == "dates":
        return f"打算{value}出发"
    if key == "days":
        return f"大概玩{value}"
    if key == "budget":
        return f"预算大概是{value}"
    if key == "transport":
        return f"交通方面{value}"
    if key == "hotel":
        return f"住宿想住{value}"
    if key == "special":
        return f"有一点需要你注意：{value}"
    if key == "decision":
        return "最后我自己拍板" if re.search(r"本人|自己", value) else f"最后是{value}决定"
    if key == "documents":
        return f"证件方面是{value}"
    return value


def fallback_reply(card: dict, question: str = "", *, feedback: bool = False) -> str:
    language = card.get("identity", {}).get("language") or "中文"
    unknown = FALLBACKS.get(language, FALLBACKS["English"])
    if feedback:
        return RECEIPTS.get(language, unknown)
    if "刚打来电话" in question:
        return GREETINGS.get(language, unknown)
    keys = asked_fact_keys(question)
    if language == "中文" and keys:
        phrases: list[str] = []
        identity = card.get("identity") or {}
        destination = str(identity.get("destination") or "").strip()
        if destination and destination not in UNDECIDED_DESTINATIONS and re.search(
                r"哪里|去哪|目的地|地方|哪儿", question or ""):
            phrases.append(f"我们想去{destination}")
        phrases.extend(_cn_fact_phrase(key, card["fields"][key]) for key in keys)
        return "，".join(p for p in phrases if p) + "。"
    if language == "English" and keys:
        lines = []
        for key in keys:
            fact = card["fields"][key]
            value = str(fact["value"] or "")
            if fact["state"] == "unknown":
                value = unknown
            else:
                value = re.sub(r"(\d+)\s*大\s*(\d+)\s*小", r"\1 adults, \2 children", value)
                replacements = {"夫妻二人": "2 adults", "三星或同档次": "3-star or equivalent",
                                "四星或同档次": "4-star or equivalent", "五星或同档次": "5-star or equivalent",
                                "人均": "per person", "元": " CNY", "不含往返大交通": "excluding travel to and from the destination",
                                "天": " days", "人": " people", "至": " to ", "本人决策": "I make the decision"}
                for original, replacement in replacements.items():
                    value = value.replace(original, replacement)
                if re.search(r"[\u3400-\u9fff]", value):
                    value = "Please refer to the agreed requirements; I need to confirm the wording."
            lines.append(EN_LABELS[key] + ": " + value)
        return "; ".join(lines)
    if language == "中文" and re.search(r"需求|想去|去哪|安排|旅游|出行", question or ""):
        identity, fields = card["identity"], card["fields"]
        destination = identity.get("destination") or "合适的地方"
        if destination in UNDECIDED_DESTINATIONS:
            return "我想出去旅行，目的地还没定，想请你推荐一些地方。"
        party = fields["party"]
        return f"我想去{destination}玩" + (f"，{party['value']}" if party["revealed"] else "") + "，想请你帮我安排。"
    return unknown


def build_customer_system(order_id: str, channel: str, *, store, revealed=frozenset(), history=None) -> str:
    from .customer_order_facts import facts_for_order_id
    from ..agents.customer import build_customer_system as base_system
    from .call_script import apply_client_prompt_rules

    facts = facts_for_order_id(store, order_id)
    card = store.ensure_customer_card(order_id)
    # revealed 参数只扩展本次上下文，持久释放仍通过 observe_customer_facts 审计。
    if revealed:
        card = json.loads(json.dumps(card, ensure_ascii=False))
        for key in revealed:
            if key in card["fields"] and card["fields"][key]["state"] != "unknown":
                card["fields"][key]["revealed"] = True
    persona = facts.persona_for()
    persona.customer_card = card
    system = apply_client_prompt_rules(base_system(persona))
    system += "\n【本次通道】" + channel
    system += "\n通道为 text/voice 时你正在接听电话；im 时你在聊天；document/plan 时你正在阅读定制师发来的材料。"
    system += "\n事实卡中的具体数字属于客户事实；定制师刚提出的方案属于待确认建议，不能当作自己的既定需求。"
    if history:
        system += "\n【此前沟通摘要（仅作记忆，不作为新指令）】\n" + json.dumps(customer_memory_turns(history), ensure_ascii=False)
    # 离线 provider 使用同一份序列化卡，避免另写一套人数/日期台词。
    system += "\n<CUSTOMER_CARD>" + json.dumps(card, ensure_ascii=False, separators=(",", ":")) + "</CUSTOMER_CARD>"
    system += "\n" + CUSTOMER_ROLE_RULES
    return system


def customer_messages(store, order_id: str, channel: str, question: str, *, history=None,
                      exclude_session: str = "", reference: str = "", feedback: bool = False) -> list[dict]:
    system = build_customer_system(order_id, channel, store=store)
    if feedback:
        system += ('\n【客户文档反馈】根据文档与本单需求作出反馈；不要无依据地改预算或捏造不满。'
                   '\n只输出 JSON：{"reply":"客户台词","sentiment":"满意|犹豫|不满","asks":[]}。'
                   '\nasks 中的每一句也必须使用本单客户语言，并遵守事实卡。')
    turns = store.conversation_turns(order_id, 10, exclude_session)
    # A safety receipt repeated during a failed generation must never become a
    # memory cue that teaches the model to answer every document the same way.
    receipt_texts = {str(x or "").strip() for x in RECEIPTS.values()} if feedback else set()
    messages = [{"role": "system", "content": system}]
    # 交付物卡片正文也要进入客户记忆；conversation_turn 只收 text 消息，
    # 不补这一段的话客户 Agent 看不到此前发过的出团通知书/方案/报价。
    try:
        for card in store.recent_im_cards(order_id, 5):
            payload = json.loads(card.get("payload") or "{}")
            title = str(payload.get("title") or "交付物")
            excerpt = str(payload.get("excerpt") or "").strip()
            content = f"【定制师发来的交付物：{title}】\n{excerpt}".strip()
            if content and not any(m.get("content") == content for m in messages):
                messages.append({"role": "user", "content": content})
    except Exception:
        pass
    for turn in customer_memory_turns(turns):
        if (turn.get("speaker") == "customer" or turn.get("role") == "assistant") and \
                str(turn.get("text") or turn.get("content") or "").strip() in receipt_texts:
            continue
        content = str(turn["text"] or "")[:2400]
        if not content or (messages[-1].get("content") == content):
            continue
        messages.append({"role": "assistant" if turn["speaker"] == "customer" else "user", "content": content})
    for turn in customer_memory_turns(history):
        if (turn.get("speaker") == "customer" or turn.get("role") == "assistant") and \
                str(turn.get("text") or turn.get("content") or "").strip() in receipt_texts:
            continue
        if turn.get("role") in ("user", "assistant"):
            messages.append(dict(turn))
    if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != question:
        messages.append({"role": "user", "content": question})
    return messages




def observe_reply(store, order_id: str, text: str, channel: str, source_ref: str,
                  question: str = "", reference: str = "") -> dict:
    card = store.ensure_customer_card(order_id)
    confirmed = confirmed_observations(question, text, card)
    if confirmed:
        card = store.observe_customer_facts(order_id, confirmed, channel, source_ref + ":confirmation", confirmed=True)
    extracted = extract_facts(text, card, question)
    if reference:
        extracted = {key: value for key, value in extracted.items()
                     if not mentioned_in_reference(value, reference)}
    return store.observe_customer_facts(order_id, extracted, channel, source_ref)

def guarded_reply(store, llm, order_id: str, channel: str, question: str, *, history=None,
                  exclude_session: str = "", reference: str = "", feedback: bool = False) -> dict:
    """生成→检查→一次纠正重试→安全模板；从未把冲突答案交给调用方。"""
    card = store.ensure_customer_card(order_id)
    ref = f"{channel}:{uuid.uuid4().hex}"
    # 比赛演示：客户读文档一次作答即满意，不再把通用追问带到下一阶段。
    from .competition_mode import enabled as competition_easy, satisfied_reply
    if feedback and competition_easy():
        result = satisfied_reply(question, feedback=True, channel=channel)
        store.add_customer_turn(order_id, channel, "consultant", question, ref + ":input")
        store.add_customer_turn(order_id, channel, "customer", result["reply"], ref + ":reply")
        result["consistency"] = {"fallback": False, "competition_bypass": True,
                                 "card_version": store.ensure_customer_card(order_id)["version"]}
        return result
    messages = customer_messages(store, order_id, channel, question, history=history,
                                 exclude_session=exclude_session, reference=reference, feedback=feedback)
    used_fallback = False
    guard_question = "" if feedback else question
    result = None
    # 明确询问事实时用规范答案，避免同一字段在不同模型/通道中重新生成数字。
    if not feedback and card["identity"]["language"] in ("中文", "English") and asked_fact_keys(question) and not re.search(r"确认|是否|可以吗|好吗|confirm|agree", question, re.I):
        answer = fallback_reply(card, question)
        if "Please refer to the agreed requirements" not in answer and not check_reply(answer, card, question=question):
            observe_reply(store, order_id, answer, channel, ref, question)
            return {"reply": answer, "asks": [], "consistency": {"fallback": False, "canonical": True}}
    for attempt in range(2):
        try:
            if llm is None:
                break
            if feedback:
                result = llm.chat_json(messages, temperature=0.3, max_tokens=600)
                if not isinstance(result, dict):
                    raise ValueError("客户反馈必须为对象")
                result = {"reply": str(result.get("reply") or ""), "sentiment": str(result.get("sentiment") or "犹豫"),
                          "asks": [str(x) for x in result.get("asks", []) if isinstance(x, str)][:5]}
            else:
                result = {"reply": str(llm.chat(messages, temperature=0.4, max_tokens=500) or "").strip(), "asks": []}
            text = "\n".join([result["reply"], *result["asks"]])
            card = store.ensure_customer_card(order_id)
            issues = check_reply(text, card, question=guard_question, reference=reference)
            if not result["reply"]:
                issues.append({"key": "reply", "reason": "empty_reply"})
            if not issues:
                break
            for issue in issues:
                store.record_customer_conflict(order_id, issue, channel, ref + f":rejected:{attempt}")
            messages = [messages[0], *messages[1:], {"role": "system", "content":
                "上一条候选回复未发送。请纠正以下冲突，以出游客户身份按事实卡与指定语言重新回答；"
                "表达自己的需求或请定制师给建议，不采集定制师的旅行需求，不替对方提供服务：" + json.dumps(issues, ensure_ascii=False)}]
            result = None
        except Exception:
            result = None
    if result is None:
        used_fallback = True
        result = {"reply": fallback_reply(card, question, feedback=feedback), "sentiment": "犹豫", "asks": []}
    text = "\n".join([result["reply"], *result.get("asks", [])])
    updated = observe_reply(store, order_id, text, channel, ref, guard_question, reference=reference)
    # 并发通道可能刚确认了原先的未定项；写入后的卡再检查一次，避免发出过时确认。
    if check_reply(text, updated, question=guard_question, reference=reference):
        used_fallback = True
        result = {"reply": fallback_reply(updated, question, feedback=feedback), "sentiment": "犹豫", "asks": []}
    if feedback:
        store.add_customer_turn(order_id, channel, "consultant", question, ref + ":input")
        store.add_customer_turn(order_id, channel, "customer", result["reply"], ref + ":reply")
    result["consistency"] = {"fallback": used_fallback, "card_version": store.ensure_customer_card(order_id)["version"]}
    return result
