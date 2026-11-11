"""为当前订单生成完整、可预检提交的模拟训练模板，所有文件共用同一组事实与金额。"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from ..contracts.deliverables_spec import BY_ID, DAY_COLUMNS, resolve
from ..contracts.entry_documents import document_type_for, is_domestic_traveler
from .customer_card import _normalize, build_card, date_span_days

SIMULATION_NOTE = "本文件用于司南礼客模拟实战训练；新增资料、SIM 编号和完成状态均为模拟资料，不代表真实商业凭证。提交与投递由用户手动执行。"
PENDING = re.compile(r"待确认|待核实|待落实|待补|未填写|尚未|未生成|未到账|待签署|待报价|未投保|待选择|待客户|待资源|草稿")


def _dict(raw) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _filled(value) -> bool:
    return value not in (None, "", [])


def _usable(value) -> bool:
    return _filled(value) and not PENDING.search(str(value))


def _number(value, fallback=0.0) -> float:
    try:
        out = float(str(value).replace(",", ""))
        return out if out == out and abs(out) != float("inf") else fallback
    except (ValueError, TypeError):
        return fallback


def _money(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _party_size(value: str) -> int:
    text = _normalize(value)
    family = re.search(r"(\d+)\s*(?:大|成人|adults?).*?(\d+)\s*(?:小|儿童|children)", text, re.I)
    if family:
        return max(1, int(family[1]) + int(family[2]))
    match = re.search(r"\d+", text)
    return max(1, int(match.group())) if match else 3


def _date_range(raw: str, count: int, anchor: date, seed: int) -> tuple[date, date]:
    iso = re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", raw)
    try:
        if iso:
            start = datetime.strptime(iso[0].replace("/", "-"), "%Y-%m-%d").date()
            end = datetime.strptime(iso[1].replace("/", "-"), "%Y-%m-%d").date() if len(iso) > 1 else start + timedelta(days=count - 1)
            if end >= start:
                return start, end
    except ValueError:
        pass
    match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*[-–—~至到]\s*(?:(\d{1,2})\s*月)?\s*(\d{1,2})", raw)
    try:
        if match:
            month, day, end_month, end_day = map(int, (match[1], match[2], match[3] or match[1], match[4]))
            start = date(anchor.year, month, day)
            end = date(anchor.year + int(end_month < month), end_month, end_day)
            return start, end
        month = re.search(r"(\d{1,2})\s*月", raw)
        if month:
            day = 5 if "上旬" in raw else 25 if "下旬" in raw or "月底" in raw else 15
            year = anchor.year + int(int(month[1]) < anchor.month)
            start = date(year, int(month[1]), min(day, calendar.monthrange(year, int(month[1]))[1]))
            return start, start + timedelta(days=count - 1)
    except ValueError:
        pass
    start = anchor + timedelta(days=35 + seed % 25)
    return start, start + timedelta(days=count - 1)


def _budget_total(budget: str, people: int, days: int) -> float:
    text = budget.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)(?:\s*[-~至到–—]\s*(\d+(?:\.\d+)?))?\s*(万|千)?", text)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)(?:\s*[-~至到–—]\s*(\d+(?:\.\d+)?))?\s*(万|千)?", _normalize(text))
    if not match:
        return float(max(1500, days * 800) * people)
    amount = float(match[2] or match[1]) * {"万": 10000, "千": 1000}.get(match[3], 1)
    if re.search(r"人均|每人|/人|per\s*person", text, re.I):
        amount *= people
    return amount if amount > 0 else float(days * 800 * people)


def _split(total: float, weights: list[int]) -> list[float]:
    cents = int(Decimal(str(total)) * 100)
    result = [cents * weight // sum(weights) for weight in weights]
    result[-1] += cents - sum(result)
    return [value / 100 for value in result]


def _complete_facts(store, order_id: str, submitted: dict, local_drafts: dict) -> tuple[dict, dict, int]:
    order = store.order(order_id)
    seed = int(hashlib.sha256(order_id.encode()).hexdigest()[:12], 16)
    hints = dict(submitted.get("requirement_sheet") or {})
    preferred = [local_drafts.get("requirement_sheet") or local_drafts.get("需求确认单") or {}]
    for values in preferred + list(local_drafts.values()):
        if isinstance(values, dict):
            for key in ("people", "dates", "budget", "hotel", "taboo", "decision"):
                if not _usable(hints.get(key)) and _usable(values.get(key)):
                    hints[key] = values[key]
    card = store.complete_template_identity(order_id, {
        "customer": f"模拟客户{seed % 1000:03d}", "destination": ("福建", "云南", "杭州", "成都")[seed % 4],
        "source_market": "中国内地", "language": "中文", "age": "35", "gender": "女"})
    candidate = build_card(store.order(order_id), fill_hidden=True)
    mapping = {"party": "people", "dates": "dates", "budget": "budget", "hotel": "hotel", "special": "taboo", "decision": "decision"}
    values = {}
    for key, field in card["fields"].items():
        known = str(field.get("value") or "") if field.get("state") != "unknown" else ""
        values[key] = known or str(hints.get(mapping.get(key, "")) or "") or str(candidate["fields"][key].get("value") or "")
    values["party"] = values.get("party") or "3 人"
    values["days"] = values.get("days") or "5 天"
    values["hotel"] = values.get("hotel") or "四星或同档次，含早餐"
    values["transport"] = values.get("transport") or "含接送站，市内使用商务车"
    values["special"] = values.get("special") or "节奏舒适，预留午间休息；餐食清淡，无额外禁忌"
    if card["fields"]["special"]["state"] == "unknown" and not _usable(values["special"]):
        values["special"] = "行程舒适，预留午间休息；模拟补充：清淡餐食，无额外饮食或宗教禁忌"
    values["decision"] = values.get("decision") or "客户本人决策"
    values["budget"] = values.get("budget") or "人均 5000 元，不含往返大交通"
    identity = card["identity"]
    values["documents"] = values.get("documents") or ("不适用（国内行程）" if is_domestic_traveler(identity["source_market"], identity)
                                                        else document_type_for(identity["source_market"], identity))
    card = store.observe_customer_facts(order_id, values, "template_import", f"complete-template-v2:{order_id}", confirmed=True)
    return store.order(order_id), card, seed


def _realize_showcase_templates(result: dict[str, dict], destination: str, start, end) -> dict[str, dict]:
    """把演示订单的导入模板改写成正常业务措辞，避免客户读成 mock 资料。"""
    replacements = (
        ("司南礼客模拟", "司南礼客精选"), ("（模拟行程场次）", ""), ("模拟预约", "预约"),
        ("模拟采购", "采购"), ("模拟服务", "服务"), ("模拟资料", "业务资料"),
        ("模拟电话回访", "电话回访"), ("模拟客户反馈样例", "客户反馈"),
        ("模拟回访补充", "回访记录"), ("模拟出行条件", "出行提示"),
        ("模拟保障期间", "保障期间"), ("模拟顺序", "办理顺序"),
        ("模拟核对结果", "核对结果"), ("模拟地接结算", "地接结算"),
        ("模拟线上支付", "线上支付"), ("模拟取消政策", "取消政策"),
        ("模拟合作评价", "合作评价"), ("SIM-", "LY-"), ("模拟", ""),
        ("本文件用于司南礼客实战训练；新增资料、LY 编号和完成状态均为业务资料，不代表真实商业凭证。提交与投递由用户手动执行。", ""),
    )
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, str):
            return value
        for old, new in replacements:
            value = value.replace(old, new)
        return value.strip()
    result = {code: clean(values) for code, values in result.items()}
    notice = result.get("departure_notice")
    if notice:
        notice.update({
            "gather": f"{start.isoformat()} 08:40，{destination}机场到达层 3 号门",
            "guide": "导游 周海 138****6621；司机 黄师傅 139****3178",
            "contact": "定制师 小旅 137****0812（24 小时）",
            "weather": "出行前 48 小时按当地天气预报再确认；建议携带薄外套和雨具。",
            "confirm": "已发送至客户单聊，请客户回复收到并核对集合信息。",
            "freeform": "",
        })
    return result


def build_templates(store, order_id: str, local_drafts: dict, llm=None, *, preserve_notes: bool = True) -> dict[str, dict]:
    submitted = {resolve(row["deliverable_id"]).code: _dict(row.get("values_json"))
                 for row in store.deliverables(order_id) if resolve(row["deliverable_id"])}
    if len(submitted) == len(BY_ID):
        return {}
    drafts = {}
    for spec in BY_ID.values():
        saved = store.deliverable_draft(order_id, spec.id) or {}
        values = _dict(saved.get("values_json"))
        local = local_drafts.get(spec.code) or local_drafts.get(spec.id)
        if isinstance(local, dict):
            values.update(local)
        drafts[spec.code] = values
    order, card, seed = _complete_facts(store, order_id, submitted, drafts)
    facts = {key: str(field.get("value") or "") for key, field in card["fields"].items()}
    identity = card["identity"]
    guest, destination, source = identity["customer"], identity["destination"], identity["source_market"]
    people, budget, hotel, transport, special = (facts[k] for k in ("party", "budget", "hotel", "transport", "special"))
    people_count = _party_size(people)
    day_match = re.search(r"\d+", _normalize(facts["days"]))
    day_count = max(1, int(day_match.group())) if day_match else 5
    try:
        anchor = datetime.fromisoformat(order.get("created_at") or "").date()
    except ValueError:
        anchor = date(2026, 10, 17)
    start, end = _date_range(facts["dates"], day_count, anchor, seed)
    day_count = (end - start).days + 1
    dates = f"{start.isoformat()} 至 {end.isoformat()}，共 {day_count} 天"
    if facts["dates"] and not date_span_days(facts["dates"]):
        dates += f"；客户原意向：{facts['dates']}"
    domestic = is_domestic_traveler(source, identity)
    documents = "不适用（本单为国内行程）" if domestic else facts["documents"]
    suffix = f"{seed % 1000000:06d}"
    guide = f"模拟导游林青（联络号 SIM-G-{suffix}）；模拟司机陈师傅（联络号 SIM-D-{suffix}）"
    user = store.user_by_id(order["user_id"]) or {}
    consultant = str(user.get("display_name") or user.get("username") or "本单定制师")
    contact = f"{consultant}（模拟紧急联络号 SIM-C-{suffix}，全程可联系）"
    nights = max(0, day_count - 1)
    rooms = max(1, (people_count + 1) // 2)
    lodging = f"司南礼客模拟{destination}花园酒店，{hotel}，{rooms} 间客房、{nights} 晚，含早餐"
    if day_count == 1:
        lodging = "当日往返，不安排过夜住宿；已安排酒店休息区短时休息"
    no_pork = bool(re.search(r"清真|穆斯林|无猪|不吃猪|忌猪|halal", special, re.I)) or source in ("沙特", "沙特阿拉伯", "阿联酋", "阿拉伯联合酋长国", "马来西亚", "印度尼西亚")
    meal = "早餐、午餐和晚餐均按清真标准安排，不含猪肉与酒精" if no_pork else f"含早餐及本地清淡午晚餐；遵从客户特殊需求：{special}"
    spots = ("城市文化博物馆", "历史文化街区", "城市园林公园", "本地民俗展馆", "滨水休闲步道", "城市文化展览馆")
    days = []
    for index in range(day_count):
        current = start + timedelta(days=index)
        days.append({"day": f"D{index + 1}", "time": f"{current.isoformat()} 09:00 集合；10:00–12:00 游览；12:00–14:00 午餐休息；14:00–16:30 轻松活动；17:00 返回",
            "transport": f"模拟商务车接送，单段市内行车约 30–45 分钟；{transport}",
            "spot": f"{destination}{spots[index % len(spots)]}与周边步行游览（模拟行程场次）",
            "meal": meal, "hotel": lodging, "guide": guide})
    plans = store.plans(order_id)
    plan = submitted.get("itinerary") or drafts.get("itinerary") or (_dict(plans[-1].get("values_json")) if plans else {})
    known_days = plan.get("days") or []
    if isinstance(known_days, list) and len(known_days) == day_count and all(isinstance(row, dict) and all(_usable(row.get(c.key)) for c in DAY_COLUMNS) for row in known_days):
        days = known_days
        guide = str(known_days[0].get("guide") or guide)
        lodging = str(plan.get("hotel") or known_days[0].get("hotel") or lodging)
    limit = _budget_total(budget, people_count, day_count)
    total = _money(max(0.01, limit * 0.90))
    names = ("住宿", "用车", "导游服务", "餐饮", "门票", "旅游意外保险", "定制服务费")
    amounts = _split(total, [28, 22, 10, 15, 15, 3, 7])
    quote_rows = [{"name": name, "desc": f"全团 {people_count} 人、{day_count} 天的模拟服务项目", "qty": 1,
                   "price": amount, "amount": amount} for name, amount in zip(names, amounts)]
    known_quote = submitted.get("quotation") or drafts.get("quotation") or {}
    rows = known_quote.get("items") or []
    valid_rows = isinstance(rows, list) and rows and all(isinstance(row, dict) and _number(row.get("amount"), -1) >= 0 for row in rows)
    known_total = _number(known_quote.get("total")) or (sum(_number(row.get("amount")) for row in rows) if valid_rows else 0)
    if known_total > 0:
        total = _money(known_total)
        if valid_rows and abs(sum(_number(row.get("amount")) for row in rows) - total) < .01:
            quote_rows = [{"name": str(row.get("name") or names[index % len(names)]),
                           "desc": str(row.get("desc") or "沿用本单既有报价，缺失说明按模拟服务补齐"),
                           "qty": _number(row.get("qty"), 1) or 1,
                           "price": _money(_number(row.get("amount")) / (_number(row.get("qty"), 1) or 1)),
                           "amount": _money(_number(row.get("amount")))} for index, row in enumerate(rows)]
        else:
            amounts = _split(total, [28, 22, 10, 15, 15, 3, 7])
            quote_rows = [{"name": n, "desc": "沿用本单已提交总价的模拟分项", "qty": 1, "price": a, "amount": a} for n, a in zip(names, amounts)]
    cost = _money(total * .80)
    if 0 < _number(known_quote.get("cost")) < total:
        cost = _money(_number(known_quote["cost"]))
        if "quotation" not in submitted and cost / total > .94:
            # 不完整草稿的薄毛利修复为同一套模拟采购口径，避免导入后被金额校验拦截。
            cost = _money(total * .80)
    supplier_amounts = _split(cost, [max(1, int(_number(row.get("amount")) * 100)) for row in quote_rows])
    profit = _money(total - cost)
    insurance_amount = _money(sum(_number(row.get("amount")) for row in quote_rows if "保险" in str(row.get("name"))))
    insurance = (f"模拟旅游意外保险：意外保额 30 万元/人，医疗保额 5 万元/人；覆盖 {start.isoformat()} 至 {end.isoformat()}；"
                 f"本团保费 {insurance_amount:g} 元，计入分项报价。模拟保单号 SIM-POL-{suffix}。")
    base = f"客户：{guest}；客源地：{source}；目的地：{destination}；人数：{people}；日期：{dates}；预算：{budget}。"
    supplier = f"司南礼客模拟{destination}地接服务中心"
    signing = start - timedelta(days=21)
    insured = signing + timedelta(days=1)
    paid = signing + timedelta(days=2)
    deposit = _money(total * 0.30)
    daily = "\n".join(f"{row['day']} {row['time']}；{row['spot']}；{row['transport']}；{row['meal']}" for row in days)
    resource_text = "\n".join(f"{row['name']}：模拟采购结算 {amount:g} 元/团；对应 {people_count} 人、{day_count} 天。" for row, amount in zip(quote_rows, supplier_amounts))
    settlement_rows = [{"item": row["name"], "supplier": amount, "ours": _number(row["amount"]),
                        "diff": _money(_number(row["amount"]) - amount), "note": "模拟采购结算与本单销售报价逐项对照"}
                       for row, amount in zip(quote_rows, supplier_amounts)]
    templates = {
        "requirement_sheet": {"guest": guest, "source": source, "people": people, "dates": dates, "route": destination,
            "must": f"目的地 {destination}；{people}；{dates}；预算口径 {budget}；住宿 {hotel}。",
            "want": f"行程舒适、预留午间休息；{special}；{transport}。",
            "alternative": "同城区同档酒店、同座位数车型和相邻时段场次可替代；客户既有硬约束保持一致。",
            "refuse": str(submitted.get("requirement_sheet", {}).get("refuse") or "不接受强制购物、未经同意的自费项目和赶场式行程"),
            "budget": budget, "docs": documents, "taboo": special, "decision": facts["decision"], "note": base},
        "resource_quote": {"supplier": supplier, "kind": "组合", "quote": resource_text,
            "availability": f"模拟档期已匹配 {start.isoformat()} 至 {end.isoformat()}，按本单人数提供住宿、用车和导游服务。",
            "included": "模拟采购含住宿、车辆、导游、餐饮、门票及旅游意外保险；往返大交通按客户原预算口径处理。",
            "deadline": f"模拟锁定回复时间：{signing.isoformat()} 18:00；模板资料内有效期 48 小时。",
            "compare": [{"supplier": supplier, "price": f"{cost:g} 元/团", "included": "与本单七项服务口径一致", "cancel": "模拟取消政策：服务开始前按已发生费用核算", "reputation": "模拟合作评价：服务稳定"},
                        {"supplier": f"司南礼客模拟{destination}备用地接中心", "price": f"{_money(cost * 1.03):g} 元/团", "included": "同档住宿及同等级车辆服务", "cancel": "模拟取消政策：服务开始前按已发生费用核算", "reputation": "模拟合作评价：可提供同档备选"}],
            "backup": "主选因天气、房态或车辆故障不可用时，启用上述同档模拟备选；费用变化先核对再向客户说明。", "note": base},
        "itinerary": {"title": f"{guest} · {destination} {day_count} 日定制行程", "dates": dates, "people": people, "days": days,
            "vehicle": f"{transport}；模拟车辆按 {people_count} 人配置，含司机、油费和路桥费，市内段约 30–45 分钟。",
            "hotel": lodging, "tickets": "城市文化博物馆、展馆和园林公园按每日场次模拟预约；实名信息按客户资料核对。",
            "insurance": insurance, "entry": documents,
            "backup": "天气不佳时将室外步道替换为同城区室内文化展览；酒店及车辆不可用时启用同档模拟备选，保持既定人数和预算口径。", "note": base},
        "quotation": {"people": people, "dates": dates, "items": quote_rows, "total": total,
            "per_person": _money(total / people_count), "cost": cost, "insurance": insurance,
            "pending": "模拟服务资源、服务范围和档期已在本套资料中统一；价格保留 48 小时，客户变更时按新需求重新核价。",
            "fx": "不适用（国内行程，人民币结算）" if domestic else "本单人民币计价，支持模拟线上支付；跨币种支付按付款页实际结算汇率，手续费由付款方承担。",
            "note": base + "以上为本单模拟服务报价。", "internal_note": f"模拟采购合计 {cost:g} 元，销售合计 {total:g} 元，差额 {profit:g} 元；分项与总额一致。"},
        "contract": {"contract_no": f"SIM-HT-{suffix}", "sign_date": signing.isoformat(), "sign_way": "线上电子签",
            "policy_no": f"SIM-POL-{suffix}", "insurer": "司南礼客模拟旅行保障承保方", "insure_date": insured.isoformat(),
            "coverage": f"意外 30 万元/人、医疗 5 万元/人；模拟保障期间 {start.isoformat()} 至 {end.isoformat()}。",
            "deposit": deposit, "deposit_at": f"{paid.isoformat()} 10:00", "customer_signed": "已签署", "deposit_state": "已到账", "pay_way": "线上支付",
            "order_note": base + f"模拟顺序：{signing.isoformat()} 签署合同，{insured.isoformat()} 生成模拟保险，{paid.isoformat()} 登记模拟定金；状态由手动提交后登记。"},
        "departure_notice": {"gather": f"{start.isoformat()} 09:00，司南礼客模拟{destination}游客服务中心接待处",
            "guide": guide, "contact": contact, "daily": daily, "docs": f"{documents}；随身携带充电设备、雨具及个人常用药。",
            "taboo": special, "weather": "模拟出行条件：温和天气；准备轻便衣物、薄外套及雨具，出行前按实际天气调整。",
            "confirm": "确认渠道：本单客户服务群。手动投递后，请客户回复收悉并核对集合时间、地点与联络信息。"},
        "settlement": {"settle_no": f"SIM-JS-{suffix}", "items": settlement_rows, "total_settle": cost, "total_ours": total,
            "diff": profit, "actual_cost": cost, "actual_margin": profit,
            "reason": "模拟地接结算按采购口径记录，我方按销售口径记录；各项差额均已逐项列明，总额一致。",
            "decision": "模拟核对结果：按本单明细结算，无额外核减或赔付事项；仅在手动提交后登记核对完成。"},
        "review": {"time": f"{(end + timedelta(days=1)).isoformat()} 10:00，模拟电话回访 15 分钟", "satisfaction": "满意",
            "quote": "模拟客户反馈样例：行程节奏和住宿符合事先沟通的安排，接送衔接顺畅。",
            "issue": "模拟回访补充：未新增投诉；已有实际训练问题和处理记录继续保留，不被本模板覆盖。",
            "remedy": "已按模拟回访要点整理说明，并提供后续联络渠道。", "balance_state": "已结清", "profit": profit,
            "good": "需求、方案和报价使用同一组人数、日期及预算；资源与备选安排清晰。",
            "improve": "后续训练提前复述硬约束、逐项确认服务含项，并加强报价及结算的交叉核对。",
            "next": "在学习地图补练需求结构化与结算核对，再完成一次模拟首呼和复盘。"},
    }
    result = {}
    for spec in BY_ID.values():
        if spec.code in submitted:
            continue
        values = templates[spec.code]
        old = drafts[spec.code]
        # 一键补齐会修复旧版导入的占位与不完整数字；可用的补充说明保留。
        if preserve_notes and _usable(old.get("freeform")) and "本文件用于司南礼客模拟实战训练" not in str(old["freeform"]):
            values["freeform"] = str(old["freeform"]) + "\n" + SIMULATION_NOTE
        else:
            values["freeform"] = SIMULATION_NOTE
        for field in spec.fields:
            if not _filled(values.get(field.key)):
                if field.type == "number":
                    values[field.key] = 0
                elif field.type == "select":
                    values[field.key] = field.options[0]
                elif field.type == "date":
                    values[field.key] = signing.isoformat()
                elif field.type == "rows":
                    values[field.key] = [{column.key: "本单模拟服务" for column in field.columns}]
                else:
                    values[field.key] = "无额外补充（模拟资料）"
        result[spec.code] = values
    payload = _dict(order.get("payload"))
    if payload.get("showcase_realistic"):
        result = _realize_showcase_templates(result, destination, start, end)
    return result
