"""流程通关驱动冒烟：用一个订单从「定制师接单」一路推到「订单完成」。

每一步都做真动作（抢单/首呼/交付物/确认…），门槛全部达成后平台状态自动推进。

用法：python -X utf8 scripts/smoke_workflow.py [order_id]
前置：后端已启动。不传订单号时自动挑一个「阶段 0 且正常」的单。
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18020"


def call(method: str, path: str, body: dict | None = None, timeout: float = 240.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


REQUIREMENT_SHEET = """必须满足：3 大 1 小、10 月 20 日出发 5 天、住四星、人均预算 5000-6000 含大交通
希望满足：节奏不太赶、有一天自由活动
可替代：酒店可降一档、用车可从 7 座换 5 座
明确不要：石林
预算口径：人均 5000-6000，不含机票，含高铁"""

PLAN = """D1 09:00 抵达昆明，10:30 商务车接机（约 40 分钟），12:00 午餐，14:00 石林（车程 1.5 小时，游览 3 小时），
19:00 晚餐，20:30 入住昆明四星酒店（入住 14:00 / 退房 12:00）。导游服务时段 09:00-18:00。
D2 08:30 出发，高铁赴大理（2 小时），12:30 午餐，14:00 洱海环湖，18:30 晚餐，20:00 入住大理四星酒店。
D3 大理古城一日，09:00-17:00，导游服务时段 09:00-17:00。
D4 丽江古城自由活动（无导游），住丽江四星酒店。
D5 09:00 送机返程。
备选：A 酒店已确认；若入住前 3 天确认满房，换 B 酒店（已确认，价差 40/间，我方承担）。
报价为待确认区间价，资源方确认后锁定。"""

QUOTE = """3大1小，10月20日出发，5天
导游服务费 800 元
用车（7座商务含司机） 2400 元
酒店 4晚 1920 元
门票 600 元
餐饮 500 元
保险 60 元
合计 6280 元
成本 5600 元
说明：酒店与用车为待确认价，资源方确认后 2 小时内锁定最终报价。"""


def main() -> int:
    order_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not order_id:
        rows = call("GET", "/practice/orders")
        pick = [o for o in rows if o["stage_index"] == 0 and o["status"] == "正常"]
        if not pick:
            print("没有处于阶段 0 的正常订单可用")
            return 2
        order_id = pick[0]["order_id"]

    def show(tag: str):
        d = call("GET", f"/practice/orders/{order_id}")
        g = call("GET", f"/practice/orders/{order_id}/gates")
        print(f"  [{tag}] 阶段 {d['stage_index']} {d['stage_name']}"
              f"（门槛 {g['done']}/{g['total']}）")
        return d, g

    d, g = show("起始")
    print(f"订单 {order_id} {d['customer']} · {d['source_market']} · {d['destination']}")
    print(f"目标：{g['stage_hint']}")
    for c in g["checks"]:
        print(f"   [{'x' if c['ok'] else ' '}] {c['label']}")

    print("\n== 0→1：抢单 → 首呼 → 需求确认单 ==")
    print("   抢单:", call("POST", f"/practice/orders/{order_id}/grab")["recorded"])
    sess = call("POST", f"/practice/orders/{order_id}/call")
    sid = sess["session_id"]
    for line in ["您好，我是司南礼客定制游的定制师小李，请问怎么称呼您？",
                 "王女士您好。想确认下：3 大 1 小、10 月 20 日出发 5 天，对吗？",
                 "预算按人均还是总价？大概区间？含不含机票高铁？",
                 "好的我复述一遍：人均 5000-6000，不含机票，含高铁。对吗？"]:
        call("POST", f"/practice/call/{sid}/messages", {"text": line})
    call("POST", f"/practice/call/{sid}/end")
    call("POST", "/tools/deliverable", {"kind": "需求确认单", "content": REQUIREMENT_SHEET,
                                        "customer": "客户", "order_id": order_id})
    show("阶段推进")

    print("\n== 1→2：行程方案 + 分项报价 + 通过拦截网 + 客户确认 ==")
    for kind, content in (("行程方案", PLAN), ("分项报价", QUOTE)):
        out = call("POST", "/tools/deliverable", {"kind": kind, "content": content,
                                                  "customer": "客户", "order_id": order_id})
        print(f"   投递「{kind}」-> 拦截网 {out['guard']['verdict']}，客户：{out['reply'][:34]}…")
    call("POST", f"/practice/orders/{order_id}/actions", {"action": "customer_confirmed_plan"})
    show("阶段推进")

    print("\n== 2→3：合同 + 保险 ==")
    for a in ("contract_signed", "insurance_bought"):
        call("POST", f"/practice/orders/{order_id}/actions", {"action": a})
    show("阶段推进")

    print("\n== 3→4：客户签合同 + 定金 ==")
    for a in ("customer_signed_contract", "deposit_paid"):
        call("POST", f"/practice/orders/{order_id}/actions", {"action": a})
    show("阶段推进")

    print("\n== 4→5：资源锁定 + 出团通知 ==")
    for a in ("resources_locked", "pre_trip_notice"):
        r = call("POST", f"/practice/orders/{order_id}/actions", {"action": a})
        if r["advance"]["advanced"]:
            print(f"   {a} -> 推进到 {r['advance']['stage_name']}")
    show("阶段推进")

    print("\n== 5→6：结算核对 ==")
    call("POST", f"/practice/orders/{order_id}/actions", {"action": "settlement_verified"})
    show("阶段推进")

    print("\n== 6→7：尾款 + 回访复盘 ==")
    for a in ("balance_paid", "review_done"):
        r = call("POST", f"/practice/orders/{order_id}/actions", {"action": a})
        if r["advance"]["advanced"]:
            print(f"   {a} -> 推进到 {r['advance']['stage_name']}")

    d, g = show("最终")
    print("\n== 动作账本 ==")
    acts = call("GET", f"/practice/orders/{order_id}/actions")["actions"]
    for a in acts:
        print(f"   {a['at']}  {a['label']}")
    print("\n== 导演时间线（阶段推进事件）==")
    tl = call("GET", f"/practice/orders/{order_id}/timeline")
    for e in tl["events"]:
        if e["type"] == "stage_advanced":
            print(f"   阶段 {e['payload'].get('from')} -> {e['payload'].get('to')}  {e['payload'].get('stage_name')}")
    ok = d["stage_index"] == 7
    print("\n结果:", "全流程跑通（订单完成）" if ok else f"未走完（停在阶段 {d['stage_index']}）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())