"""交付物工作台冒烟：按契约逐个提交 8 份交付物，观察分路投递与流程推进。

用法：python -X utf8 scripts/smoke_deliverables.py [order_id]
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18020"


def call(method: str, path: str, body: dict | None = None, timeout: float = 300.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    order_id = sys.argv[1] if len(sys.argv) > 1 else "9000000000000006"

    print("== 交付物契约 ==")
    for d in call("GET", "/deliverables/specs")["deliverables"]:
        print(f"   {d['code']:18} {d['id']:8} {d['step']:4} → {'、'.join(d['audience']):12} "
              f"字段 {len(d['fields']):2} 校验 {'、'.join(d['checks']) or '—'}")

    # 先把阶段 0 的门槛补上（抢单 + 首呼）
    call("POST", f"/practice/orders/{order_id}/grab")
    sess = call("POST", f"/practice/orders/{order_id}/call")
    call("POST", f"/practice/call/{sess['session_id']}/messages",
         {"text": "您好，我是司南礼客定制游的定制师小李，请问怎么称呼您？"})
    call("POST", f"/practice/call/{sess['session_id']}/end")

    PLAN = [
        ("requirement_sheet", {
            "guest": "客户 F", "source": "香港", "people": "3 大 1 小", "dates": "11 月 12 日–16 日，5 天",
            "route": "贵州：贵阳 / 黔东南 / 荔波",
            "must": "3 大 1 小、11 月 12 日出发 5 天、住四星、人均 5000-6000 含大交通",
            "want": "节奏不太赶、有一天自由活动", "alternative": "酒店可降一档",
            "refuse": "购物店", "budget": "人均 5000-6000，含高铁，不含机票",
            "docs": "回乡证（港澳居民来往内地通行证）", "taboo": "无特殊禁忌", "decision": "客户 F 本人"}),
        ("resource_quote", {
            "supplier": "黔行地接·张经理", "kind": "组合",
            "quote": "四星 460/间/晚含双早；7 座商务 850/天含司机与油；首道门票 110/人；导游 500/天",
            "availability": "有", "included": "酒店含早；用车含司机油费过路费；门票为首道门票",
            "deadline": "今天 18 点前确认",
            "compare": [
                {"supplier": "黔行地接", "price": "460/间", "included": "含双早", "cancel": "入住前 7 天免费取消", "reputation": "4.6"},
                {"supplier": "山水假期", "price": "430/间", "included": "含双早", "cancel": "入住前 3 天免费取消", "reputation": "4.2"},
            ],
            "backup": "主选黔行（确认状态：已确认）；若满房换山水假期（已确认，价差 -30/间）"}),
        ("itinerary", {
            "title": "香港客人 贵州 5 日定制行程", "dates": "11 月 12 日 – 11 月 16 日", "people": "3 大 1 小",
            "days": [
                {"day": "D1", "time": "10:30-20:00", "transport": "商务车 40 分钟", "spot": "抵达贵阳·甲秀楼",
                 "meal": "午餐/晚餐", "hotel": "贵阳四星（入住 14:00）", "guide": "10:00-18:00"},
                {"day": "D2", "time": "08:30-19:30", "transport": "高铁 1.5 小时", "spot": "西江千户苗寨",
                 "meal": "早餐/午餐/晚餐", "hotel": "西江特色客栈", "guide": "09:00-17:00"},
                {"day": "D3", "time": "09:00-17:00", "transport": "商务车 3 小时", "spot": "镇远古镇",
                 "meal": "早餐/午餐", "hotel": "镇远四星", "guide": "09:00-17:00"},
                {"day": "D4", "time": "全天自由", "transport": "—", "spot": "荔波小七孔（自由活动）",
                 "meal": "早餐", "hotel": "荔波四星", "guide": "—"},
                {"day": "D5", "time": "09:00 送机", "transport": "商务车 30 分钟", "spot": "返程",
                 "meal": "早餐", "hotel": "—", "guide": "—"},
            ],
            "vehicle": "7 座商务，含司机与油费", "hotel": "四星含早，主选黔行（已确认）",
            "tickets": "含首道门票；小七孔需实名预约", "insurance": "旅游意外险 30 万，已投保",
            "entry": "港澳居民来往内地通行证（回乡证），有效期已核",
            "backup": "主选黔行酒店（已确认）；若入住前 7 天内满房换山水假期（已确认，价差 -30/间）"}),
        ("quotation", {
            "people": "3 大 1 小", "dates": "11 月 12 日–16 日，5 天",
            "items": [
                {"name": "导游服务费", "desc": "全程 4 天", "qty": 4, "price": 500, "amount": 2000},
                {"name": "用车", "desc": "7 座商务含司机", "qty": 5, "price": 850, "amount": 4250},
                {"name": "酒店", "desc": "四星 4 晚 2 间", "qty": 8, "price": 460, "amount": 3680},
                {"name": "门票", "desc": "首道门票 4 人", "qty": 4, "price": 110, "amount": 440},
                {"name": "餐饮", "desc": "含早及 3 正餐", "qty": 1, "price": 600, "amount": 600},
                {"name": "保险", "desc": "意外险 30 万", "qty": 4, "price": 50, "amount": 200},
            ],
            "total": 11170, "per_person": 2792, "cost": 9800,
            "insurance": "旅游意外险 30 万，50 元/人，已投保",
            "pending": "酒店与用车为待确认价，资源方 2 小时内回复后锁定最终报价",
            "fx": "港元按 1:0.92 锁定 48 小时；信用卡手续费 1.5% 由我方承担；发票与收据均可提供",
            "note": "报价预留 300 元/人 的票务涨价空间"}),
        ("contract", {
            "contract_no": "HT-20261101-08", "sign_date": "2026-11-01", "sign_way": "线上电子签",
            "policy_no": "PL-88213456", "insurer": "XX 保险", "insure_date": "2026-11-01",
            "coverage": "意外 30 万 / 医疗 5 万", "deposit": 3350, "deposit_at": "2026-11-01 15:20",
            "customer_signed": "已签署", "deposit_state": "已到账",
            "pay_way": "对公转账", "order_note": "顺序：先合同签署 → 再投保 → 后收定金"}),
        ("departure_notice", {
            "gather": "11 月 12 日 10:30，贵阳龙洞堡机场 T2", "guide": "导游 小周 138**** / 司机 赵师傅 139****",
            "contact": "定制师 小李 137****（24 小时）",
            "daily": "D1 甲秀楼；D2 西江千户苗寨；D3 镇远古镇；D4 荔波小七孔自由活动；D5 送机",
            "docs": "回乡证、充电宝、雨具、常用药", "taboo": "已按无猪肉无酒需求安排，餐厅名单见群文件",
            "weather": "贵阳 12–20℃，早晚温差大，建议外套", "confirm": "已发微信群，请回复「收到」"}),
        ("settlement", {
            "settle_no": "JS-20261116-03",
            "items": [
                {"item": "用车", "supplier": "4500", "ours": "4250", "diff": "250", "说明": "超时 2 小时"},
                {"item": "酒店", "supplier": "3680", "ours": "3680", "diff": "0", "说明": "一致"},
            ],
            "total_settle": "8180", "total_ours": "7930", "diff": "250",
            "actual_cost": "10050", "actual_margin": "-2120",
            "reason": "用车超时 2 小时加收 250；且报价时漏算了景区二次消费与餐饮超支",
            "decision": "据实结算 250，并把本单亏损写进复盘；下次报价必须预留二次消费与餐饮上浮空间"}),
        ("review", {
            "time": "2026-11-20 电话 12 分钟", "satisfaction": "满意",
            "quote": "整体还不错，就是荔波那天没导游，我们自己摸索有点费劲。",
            "issue": "自由活动日无导游支持", "remedy": "电话致歉，补寄当地特产礼盒",
            "balance_state": "已结清",
            "profit": -2120, "good": "首呼需求问得全，客户确认没有反复",
            "improve": "自由活动日应提供图文版自助攻略或半日导游选项",
            "next": "补练 C3.5 特殊人群与自由活动安排"}),
    ]

    for code, values in PLAN:
        r = call("POST", f"/practice/orders/{order_id}/deliverables/{code}", {"values": values})
        # 客户确认方案是人工动作（真实平台也是定制师点确认）
        if code == "quotation" and not r.get("blocked"):
            call("POST", f"/practice/orders/{order_id}/actions", {"action": "customer_confirmed_plan"})
        tag = "拦截" if r.get("blocked") else "已投递"
        sent = "、".join(r.get("routing", {}).get("sent_to", []))
        stage = (r.get("gates") or {}).get("stage_name", "")
        print(f"\n[{tag}] {code:18} → {sent:14} | 阶段：{stage}")
        if r.get("blocked"):
            for reason in r["guard"]["reasons"]:
                print("    ×", reason)
            continue
        reply = r["routing"].get("customer_reply")
        if reply:
            print("    客户：", reply[:70])
        if r["routing"].get("platform_note"):
            print("    平台：", r["routing"]["platform_note"])
        if r["routing"].get("im_session"):
            print("    地接群：已同步（会话", r["routing"]["im_session"], "）")
        print("    拦截网：", r["guard"]["verdict"],
              "| 校验项", len(r["guard"]["deterministic"]["checks"]),
              "| 语义问题", len(r["guard"]["semantic"].get("issues", [])))

    d = call("GET", f"/practice/orders/{order_id}")
    print(f"\n最终：阶段 {d['stage_index']} {d['stage_name']}")
    acts = call("GET", f"/practice/orders/{order_id}/actions")["actions"]
    print(f"动作账本 {len(acts)} 条；已提交交付物 "
          f"{sum(1 for x in call('GET', f'/practice/orders/{order_id}/deliverables')['deliverables'] if x['submitted'])}/8")
    return 0 if d["stage_index"] == 7 else 1


if __name__ == "__main__":
    raise SystemExit(main())