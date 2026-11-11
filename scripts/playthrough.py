"""以学员身份把一单从抢单走到复盘（真实接口 + 真实模型，落临时库）。

用法：python -X utf8 scripts/playthrough.py
每一步都会打印：动作 / 门槛进度 / 后端吃到的数据（证据、群消息、台账、评分）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("TRIPCRAFT_DB", os.path.join(tempfile.gettempdir(), "playthrough.sqlite"))
if os.path.exists(os.environ["TRIPCRAFT_DB"]):
    os.remove(os.environ["TRIPCRAFT_DB"])

from fastapi.testclient import TestClient          # noqa: E402
from tripcraft.api.app import create_app           # noqa: E402
from tripcraft.storage import Store                # noqa: E402

c = TestClient(create_app())
store = Store(os.environ["TRIPCRAFT_DB"])
# 评分写回画像的前提是「有校准基线」（calibration_gate 权重 > 0），演示库本来就有，
# 临时库这里补一条，否则会出现"评了分但画像不更新"，看起来像 bug。
store.add_calibration_run("cal-playthrough", 50, 50, 0.92, 0.98, 1.0, 0.9, 3, True,
                          {"note": "playthrough 用基线"})
USER = "u-demo"
step_no = 0


def title(text: str) -> None:
    global step_no
    step_no += 1
    print("\n" + "=" * 78)
    print(f"【{step_no}】{text}")
    print("=" * 78)


def show(label: str, ok: bool, extra: str = "") -> None:
    print(f"  {'OK ' if ok else 'NG '}| {label}{('：' + extra) if extra else ''}")


def gates(oid: str) -> dict:
    return c.get(f"/practice/orders/{oid}/gates").json()


def gate_line(oid: str) -> str:
    g = gates(oid)
    return (f"{g.get('stage_name')} {g['done']}/{g['total']}｜"
            + "、".join(("%s%s" % (ch['label'], "✓" if ch['ok'] else "✗")) for ch in g["checks"]))


def post(path: str, body: dict | None = None):
    r = c.post(path, json=body) if body is not None else c.post(path)
    if r.status_code >= 400:
        return {"__status": r.status_code, "__detail": r.text[:300]}
    return r.json()


def submit(oid: str, did: str, values: dict, targets=None) -> dict:
    return post(f"/practice/orders/{oid}/deliverables/{did}",
                {"values": values, "file_ids": [], "targets": targets or []})


# ---------------------------------------------------------------- 0 生成派单

title("0 消息中心：刷新拿新派单（按画像生成）")
created = post("/practice/dispatch/generate", {"count": 1})["created"][0]
available = c.get("/practice/orders/available").json()
OID = available[0]["order_id"] if available else created["order_id"]
o = c.get(f"/practice/orders/{OID}").json()
show("拿到可抢派单", bool(available), f"{OID} {o['customer']} {o['destination']} "
     f"{o.get('source_market','')} 缺失字段{len(o.get('missing_fields', []) or [])}项")
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 1 抢单

title("1 抢单（消息中心 › 待接单）")
post(f"/practice/orders/{OID}/grab", {"by": USER})
show("抢单成功", store.has_action(OID, "grab"), "动作 grab 已登记（抢单窗口由服务端判定）")
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 2 首呼

title("2 首呼（订单 › 拨打电话，真实模型扮演客户）")
call = post(f"/practice/orders/{OID}/call")
sid = call.get("session_id") or call.get("sid")
show("通话会话建立", bool(sid), str(sid))
for line in ("您好，我是携程定制师小李，客户是黄先生吗？现在方便说两句吗？",
             "想先确认下：几位出行、大概哪几天、预算大概什么口径？",
             "好的，我按您说的先出一版方案，今天 18 点前发您微信。"):
    out = post(f"/practice/call/{sid}/messages", {"text": line})
    reply = (out.get("reply") or out.get("customer") or "")
    print(f"  我：{line[:28]}…  → 客户：{str(reply)[:40]}")
ended = post(f"/practice/call/{sid}/end")
turns = (ended.get("turns") or ended.get("snapshot", {}).get("turns") or 0)
show("通话结束并登记 first_call", store.has_action(OID, "first_call"), f"学员 {turns} 轮")
ev = store.evidence(OID)
show("通话转写进证据链", any(e["kind"] == "call" for e in ev),
     f"证据 {len(ev)} 条：{[e['kind'] for e in ev]}")
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 3 加联系人

title("3 加联系方式 → 拉群（聊天界面）")
cat0 = {x["kind"]: x for x in c.get("/practice/im/contacts", params={"order_id": OID}).json()["contacts"]}
show("地接还没加时，酒店/车队拿不到", not cat0["酒店"]["available"], cat0["酒店"]["source"])
for kind in ("客户", "地接社"):
    r = post("/practice/im/contacts", {"order_id": OID, "kind": kind})
    show(f"加{kind}", r.get("ok") is True, (r.get("contact") or {}).get("name", str(r)[:60]))
cat = {x["kind"]: x for x in c.get("/practice/im/contacts", params={"order_id": OID}).json()["contacts"]}
show("加完地接后酒店/车队才可加", cat["酒店"]["available"] and cat["车队"]["available"],
     "来源：" + cat["酒店"]["source"])
sessions = {g["code"]: g for g in c.get(f"/practice/im/sessions?order_id={OID}").json()}
sessions.setdefault("customer", sessions.get("dm-客户", {}))
show("客户单聊已建立", bool(sessions.get("dm-客户")))
group = post("/practice/im/sessions", {"order_id": OID, "name": "浙江 5 天 · 客户小群",
                                       "kind": "群聊", "members": [cat["客户"]["name"]]})
show("拉旅行小群", group.get("ok") is not False and bool(group.get("session_id")), group.get("name", ""))

# ---------------------------------------------------------------- 4 需求确认单

title("4 需求结构化确认（产出与投递 › 需求确认单 → 客户群）")
cus_sid = (sessions.get("dm-客户") or sessions.get("customer") or {})["session_id"]
r = submit(OID, "需求确认单", {
    "guest": o["customer"], "people": "3 大 1 小", "dates": "2026-11-12 至 11-16",
    "must": "四星含早、要电梯房", "want": "亲子体验", "budget": "人均 5000-6000（不含机票）",
    "refuse": "不要早班机", "taboo": "一位老人不吃辣",
    "freeform": "老人膝盖不好，每天步行控制在 2 小时内。"}, targets=[cus_sid])
show("需求确认单投递", r.get("blocked") is False, f"送达 {[t['name'] for t in r.get('routing', {}).get('targets', [])]}")
show("客户群出现卡片", any(m["kind"] == "card" for m in store.im_messages(cus_sid)))
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 5 询价

title("5 资源询价（聊天界面 › 地接群 / 酒店群；学员工具询价）")
sup_sid = c.get(f"/practice/im/sessions?order_id={OID}").json()
sup = next(g for g in sup_sid if g["code"] == "hub")
r = post(f"/practice/im/sessions/{sup['session_id']}/messages",
         {"sender": "我", "role": "me", "content": "11 月 12-16 号，3 大 1 小，四星两间 + 7 座车 + 导游，什么价？"})
show("地接群里报价", bool(r.get("reply")), (r.get("reply") or {}).get("content", "")[:56])
tool = post("/tools/supplier", {"kind": "酒店", "request": "四星两间四晚什么价？", "order_id": OID})
show("学员工具询价同口径", bool(tool.get("reply")), str(tool.get("price", ""))[:46])
show("群聊与询价都进证据", sum(1 for e in store.evidence(OID) if e["kind"] in ("im", "供应商询价")) >= 2)
for kind in ("酒店", "车队"):
    rr = post("/practice/im/contacts", {"order_id": OID, "kind": kind})
    show(f"地接给了{kind}联系方式，加上", rr.get("ok") is True, (rr.get("contact") or {}).get("name", ""))

# ---------------------------------------------------------------- 6 方案

title("6 创建方案 → 发送方案 → 客户已读（vbooking 主链）")
plan = post(f"/practice/orders/{OID}/plans", {"values": {
    "title": f"{o['destination']} 5 天亲子行程（长辈同行版）", "dates": "2026-11-12 至 11-16",
    "people": "3 大 1 小",
    "days": [
        {"day": "D1", "time": "14:00", "transport": "专车 50 分", "spot": "西湖·断桥",
         "meal": "晚 杭帮菜", "hotel": "西湖四星电梯房", "guide": "导游·王"},
        {"day": "D2", "time": "09:30", "transport": "专车 1 时", "spot": "灵隐寺·龙井村",
         "meal": "午 素斋", "hotel": "西湖四星电梯房", "guide": "导游·王"},
        {"day": "D3", "time": "08:30", "transport": "专车 2 时", "spot": "乌镇西栅",
         "meal": "晚 民宿餐", "hotel": "乌镇民宿", "guide": "导游·王"},
        {"day": "D4", "time": "09:00", "transport": "专车 1.5 时", "spot": "宋城",
         "meal": "午 团餐", "hotel": "西湖四星电梯房", "guide": "导游·王"},
        {"day": "D5", "time": "10:00", "transport": "专车 40 分", "spot": "西溪湿地",
         "meal": "午 简餐", "hotel": "返程", "guide": "导游·王"}],
    "sections": [{"title": "交通与用车", "body": "7 座商务，含司机与油费"},
                 {"title": "给长辈的安排", "body": "每天步行不超过 2 小时，酒店要电梯房"}]}, "note": ""})
pid = plan["plan"]["plan_id"]
show("创建方案（草稿）", plan["plan"]["status"] == "草稿", f"V{plan['plan']['version']}")
sent = post(f"/practice/orders/{OID}/plans/{pid}/send", {"targets": [cus_sid]})
show("发送方案（客户未读）", sent.get("ok") is True, sent["plan"]["status"] + f"，送达 {[t['name'] for t in sent['plan']['routing']['targets']]}")
time.sleep(6)
cur = [p for p in c.get(f"/practice/orders/{OID}/plans").json()["plans"] if p["plan_id"] == pid][0]
show("客户已读并反馈", cur["read"], f"{cur['read_at'][11:16]}｜{cur['feedback'][:52]}")
conf = post(f"/practice/orders/{OID}/plans/{pid}/confirm")
show("登记客户确认方案", conf.get("ok") is True, (conf.get("plan") or {}).get("status", ""))
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 7 报价

title("7 分项报价与利润测算（过双层拦截网）")
quote = submit(OID, "分项报价", {
    "people": "3 大 1 小", "dates": "2026-11-12 至 11-16",
    "items": [{"name": "导游服务费", "desc": "全程 5 天", "qty": 5, "price": 560, "amount": 2800},
              {"name": "用车", "desc": "7 座商务含油费司机", "qty": 5, "price": 950, "amount": 4750},
              {"name": "住宿", "desc": "四星电梯房 2 间 × 4 晚", "qty": 8, "price": 540, "amount": 4320},
              {"name": "门票", "desc": "首道门票 4 人", "qty": 4, "price": 145, "amount": 580}],
    "total": 12450, "per_person": 3112, "cost": 10850, "insurance": "旅游意外保险 30 万，60 元/人",
    "pending": "机票价格待确认，锁位需 80% 预留", "fx": "港元 1:0.92，锁定 48 小时",
    "freeform": "报价有效 48 小时；机票与酒店旺季涨价需按实结算。"}, targets=[cus_sid])
show("报价提交", quote.get("blocked") is False,
     "拦截网通过" if quote.get("blocked") is False else str(quote.get("guard", {}).get("reasons"))[:80])
show("门槛登记 guard_pass", store.has_action(OID, "guard_pass:分项报价"))
fin0 = c.get(f"/practice/orders/{OID}/finance").json()
show("平台能算出资源口径成本（评分参照）", fin0["cost"] > 0,
     f"{fin0['cost']} 元（{fin0['cost_source']}）")
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 8 合同保险

title("8 合同与保险（平台表单 + 客户签署 + 定金）")
contract = submit(OID, "合同与保险", {
    "contract_no": "HT-20261112-031", "sign_date": "2026-10-20", "sign_way": "电子签",
    "policy_no": "PL-8842-2026", "insurer": "中国平安", "insure_date": "2026-10-20",
    "coverage": "意外 30 万 / 医疗 5 万", "deposit": 3000, "deposit_at": "2026-10-20 15:20",
    "customer_signed": "已签署", "deposit_state": "已到账", "pay_way": "对公转账",
    "freeform": "特殊约定：老人同行，行程节奏以舒适为先，酒店须电梯房。"}, targets=[cus_sid])
show("合同与保险提交", contract.get("blocked") is False)
for act in ("contract_signed", "insurance_bought", "customer_signed_contract", "deposit_paid"):
    show(f"动作 {act}", store.has_action(OID, act))
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 9 行前

title("9 资源锁定与出团通知书（客户群 + 司导群）")
for kind in ("导游", "司机"):
    rr = post("/practice/im/contacts", {"order_id": OID, "kind": kind})
    show(f"行前地接给{kind}电话，加上", rr.get("ok") is True, (rr.get("contact") or {}).get("name", ""))
guide = next(g for g in c.get(f"/practice/im/sessions?order_id={OID}").json() if g["code"] == "dm-导游")
notice = submit(OID, "出团通知书", {
    "gather": "11 月 12 日 10:30 杭州东站北出口", "guide": f"{guide['members'][1]} 138xxxx",
    "contact": "定制师 小李 137xxxx", "daily": "每天 8:30 出发，晚间自由活动",
    "docs": "港澳回乡证、常备药", "taboo": "老人不吃辣，餐食需清淡",
    "weather": "11 月 10-20℃，早晚偏凉", "confirm": "群里请客户回复「收到」",
    "freeform": "导游提前一天核对房间与电梯房。"}, targets=[cus_sid, guide["session_id"]])
show("出团通知书投递", notice.get("blocked") is False,
     f"送达 {[t['name'] for t in notice.get('routing', {}).get('targets', [])]}")
for act in ("resources_locked", "pre_trip_notice"):
    show(f"动作 {act}", store.has_action(OID, act))
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 10 行中

title("10 行中突发事件（司导群协商解决）")
mcp = post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "director.emit",
                               "arguments": {"order_id": OID, "type": "pre_trip"}}})
inc = ((mcp or {}).get("result") or {}).get("injected") or {}
injected = store.incidents(OID)
show("本单已注入突发事件", bool(injected),
     "、".join(f"{i['title']}（{i['channel']}）" for i in injected) or "（配额内没有新事件）")
r = post(f"/practice/im/sessions/{guide['session_id']}/messages",
         {"sender": "我", "role": "me",
          "content": "赵师傅你先联系备用车，客人那边我来解释；更换车的差额由车队承担，你恢复后给我时间点。"})
show("司导群里回应事件", bool(r.get("reply")), (r.get("reply") or {}).get("content", "")[:52])
cov_b = [t for t in store.targets(OID) if t["checkpoint"] == "B" and t["trigger_state"] == "reacted"]
show("B 型考点转变为「已回应」", bool(cov_b), f"{len(cov_b)} 个")
fin = c.get(f"/practice/orders/{OID}/finance").json()
print(f"  · 成本台账 {len(fin['entries'])} 笔，我方承担 {fin['loss']} 元"
      + (f"（{fin['entries'][0]['label']} {fin['entries'][0]['amount']}）" if fin["entries"] else
         "（本单注入的事件不含成本项）"))

# ---------------------------------------------------------------- 11 结算

title("11 行后结算与回访（结算单核对 + 结账留档）")
settle = submit(OID, "地接结算核对单", {
    "settle_no": "JS-20261116-07",
    "items": [{"item": "用车", "settle": 4750, "ours": 4750, "diff": 0, "note": "一致"},
              {"item": "住宿", "settle": 4320, "ours": 4320, "diff": 0, "note": "一致"},
              {"item": "导游", "settle": 2800, "ours": 2800, "diff": 0, "note": "一致"},
              {"item": "门票", "settle": 580, "ours": 580, "diff": 0, "note": "一致"},
              {"item": "临时换车", "settle": 400, "ours": 0, "diff": -400, "note": "由车队承担"}],
    "total_settle": 12850, "total_ours": 12450, "diff": 400, "actual_cost": 10850,
    "actual_margin": 1600, "reason": "临时换车由车队承担，我方不承担",
    "decision": "结算单扣减 400 元后付尾款", "freeform": "结算单与报价逐项核对，差异一项已谈定。"})
show("结算核对单", settle.get("blocked") is False, f"门槛 settlement_verified={store.has_action(OID, 'settlement_verified')}")
book = post(f"/practice/orders/{OID}/finance/settle")
show("结账留档（写 S11 证据）", bool(book.get("evidence_id")),
     f"收入 {book.get('revenue')} 成本 {book.get('cost')} 损失 {book.get('loss')} 毛利 {book.get('profit')}（{book.get('grade')}）")

# ---------------------------------------------------------------- 12 复盘

title("12 回访与复盘（内部记录）")
review = submit(OID, "回访与复盘记录", {
    "time": "2026-11-17 20:00 微信语音", "satisfaction": "满意",
    "quote": "整体挺顺，导游照顾老人，换车处理得也快。",
    "issue": "乌镇那天午饭偏晚", "remedy": "下次把午餐时间写进导游执行单",
    "balance_state": "已结清", "profit": 1600, "good": "需求挖掘细，长辈节奏控制到位",
    "improve": "行程单里要写清每餐时间；报价的机票涨价空间留得偏小",
    "next": "下一单练习：把机票波动写进报价说明", "freeform": ""})
show("回访与复盘提交", review.get("blocked") is False, f"门槛 review_done={store.has_action(OID, 'review_done')}")
print("  门槛：", gate_line(OID))

# ---------------------------------------------------------------- 13 评分

title("13 实战评分：证据 → 覆盖校验 → 评分 → 写回画像")
score = post(f"/practice/orders/{OID}/score", {})
cov = score.get("coverage") or {}
show("可评分", score.get("ok") is not False, f"错误 {score.get('error', '')}" if score.get("ok") is False else f"评了 {score.get('scored')} 个技能点")
show("覆盖校验", bool(cov), f"{cov.get('covered')}/{cov.get('targets')} = {cov.get('ratio')}（门槛 {cov.get('threshold')}，通过 {cov.get('passed')}）")
items = score.get("items") or score.get("scores") or []
for it in items[:12]:
    sp = it.get("skill_point_id")
    print(f"   · {sp:6} {it.get('level')} {it.get('score')} 分｜{it.get('status')}｜{str(it.get('comment'))[:30]}")
# 以数据库为准核对"评分 → 画像"：order_score 是评分结果，ability.real_v 是写回后的画像
graded = store._all("SELECT skill_point_id, score, level, status FROM order_score WHERE order_id=?",
                    (OID,))
stored = [g for g in graded if str(g["status"]).startswith("已入库")]
ab = store.abilities(USER)
written = [g["skill_point_id"] for g in stored if (ab.get(g["skill_point_id"]) or {}).get("real_v")]
escalated = [g["skill_point_id"] for g in graded if g["status"] == "待复核"]
show("评分结果入库", bool(graded), f"{len(graded)} 条（已入库 {len(stored)}、待复核 {len(escalated)}）")
show("写回画像 ability.real_v", bool(written), f"{len(written)} 条：{written[:6]}")
row = ab.get(written[0]) if written else None
show("画像数据可查", row is not None,
     f"{written[0]} real_v={row['real_v']}" if row else "（本条没有写回，检查校准基线）")

# ---------------------------------------------------------------- 14 右下角进度条

title("14 右下角进度条：13 步 + 完成条件 + 「去哪做」提示")
flow = c.get(f"/practice/orders/{OID}/flow").json()
g = gates(OID)
show("流程接口返回 13 步", len(flow["steps"]) == 13,
     f"当前 {flow['step_evidence']}")
with_ev = [x for x in flow["steps"] if x.get("evidence")]
show("每一步都带「产出在哪里」", len(with_ev) == 13, f"{len(with_ev)}/13 步有提示")
show("完成条件带 step_evidence", bool(g.get("step_evidence")), g.get("step_evidence", ""))
missing_where = [ch["label"] for ch in g["checks"] if not ch.get("where")]
show("每条未完成条件带「去哪做」", not missing_where,
     "全部有" if not missing_where else "缺：" + "、".join(missing_where))
print("  当前进度：", gate_line(OID))
print("  本步提示：", g.get("step_evidence", ""))

print("\n" + "=" * 78)
ev = store.evidence(OID)
kinds = {}
for e in ev:
    kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
print("后端最终吃到的数据：")
print("  证据", len(ev), "条 →", kinds)
print("  群消息", sum(len(store.im_messages(g["session_id"]))
                    for g in c.get(f"/practice/im/sessions?order_id={OID}").json()), "条")
print("  方案版本", len(c.get(f"/practice/orders/{OID}/plans").json()["plans"]), "个")
print("  成本台账", len(c.get(f"/practice/orders/{OID}/finance").json()["entries"]), "笔")
print("  订单终态", c.get(f"/practice/orders/{OID}").json()["stage_name"])
print("=" * 78)
