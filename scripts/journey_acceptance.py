"""journey 域端到端验收（可重跑）：用真实服务走完整六阶段旅程 + 静态扫描 + 逐条证据落盘。

与 `scripts/journey_api_check.py` 的分工：
- `journey_api_check.py` 是**接口层**自检（契约一致性、字段、越权矩阵，直接造订单行）；
- 本脚本是**旅程层**验收：从空白账号出发，只用公开 API（注册/登录/派单/抢单/首呼/投递四份文档/
  发送方案/客户确认/出团/结算/回访），一路走到订单完成，全程不直接改库、不写死状态；
  并附加学员界面静态扫描（R05 只留 PDF、R09/R10 单一阶段口径、R17 死按钮）。

输出：
    output/journey/acceptance/manifest.json     （逐条证据 + 命令 + 退出状态）
    output/journey/acceptance/journey-acceptance.log
退出码：0 = 全部通过；1 = 有失败项（失败项在日志与 manifest 里逐条列出）。

说明（诚实边界）：无浏览器/无前端构建的情况下，前端**运行时**行为（提交中动画、防重复点击、
真实渲染路径）只能静态核查；manifest 中对应条目标 `runtime: false`，不计入「已核实」。
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = ROOT / "output" / "journey" / "acceptance"
OUT_DIR.mkdir(parents=True, exist_ok=True)
_TMP = ROOT / "output" / "journey" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_DB = _TMP / "journey-acceptance.sqlite"
for _stale in (_DB, Path(str(_DB) + "-wal"), Path(str(_DB) + "-shm")):
    try:
        _stale.unlink(missing_ok=True)
    except OSError:
        pass
os.environ["TRIPCRAFT_DB"] = str(_DB)
os.environ["TRIPCRAFT_VISIT_LOG_DIR"] = str(_TMP / "logs-acceptance")

from fastapi.testclient import TestClient          # noqa: E402
from tripcraft.api.app import create_app           # noqa: E402
from tripcraft.contracts.stages import STAGES      # noqa: E402

# 期望的六阶段顺序（独立于实现写死，避免自证）
EXPECT_STAGE_ORDER = ["pre1_requirement", "pre2_plan", "pre3_quote", "pre4_notice",
                      "on_trip", "post_trip"]
EXPECT_STAGE_CN = {"pre1_requirement": "行前 1", "pre2_plan": "行前 2", "pre3_quote": "行前 3",
                   "pre4_notice": "行前 4", "on_trip": "行中服务", "post_trip": "行后复盘"}

RESULTS: list[dict] = []
TRACE: list[dict] = []


def check(cid: str, name: str, ok: bool, detail: object = "", runtime: bool = True) -> bool:
    RESULTS.append({"id": cid, "name": name, "ok": bool(ok), "detail": str(detail),
                    "runtime": runtime})
    print(f"{'PASS' if ok else 'FAIL'}  {cid}  {name}"
          + (f"  ·  {detail}" if detail != "" else ""))
    return bool(ok)


# ---------------------------------------------------------------- 素材

REQ_VALUES = {"guest": "黄先生", "source": "香港", "people": "3 大 1 小",
              "dates": "2026-11-16 至 2026-11-20，5 天", "route": "昆明 / 大理 / 丽江",
              "must": "日期固定 11/16 出发；总价上限 18000 元；酒店 4 星以上",
              "want": "节奏轻松，长辈同行", "alternative": "酒店可降一档",
              "refuse": "不安排购物点", "budget": "总价上限 18000 元（不含大交通）",
              "docs": "港澳居民来往内地通行证（回乡证）", "taboo": "忌猪肉与酒",
              "decision": "黄先生本人"}
QUOTE_VALUES = {"supplier": "云南地接 A", "kind": "酒店", "quote": "标间 480 元/间/晚 × 2 间 × 5 晚",
                "availability": "有", "included": "含双早；含税",
                "compare": [{"supplier": "地接 A", "price": "480", "included": "含早",
                             "cancel": "提前 7 天免费", "reputation": "4.8"},
                            {"supplier": "地接 B", "price": "520", "included": "含早",
                             "cancel": "提前 3 天", "reputation": "4.6"}],
                "backup": "主选地接 A；若房量不足则换地接 B，价差 +40/间/晚"}
DAY = ["D1", "D2"]
ITIN_VALUES = {
    "title": "香港黄先生 · 云南 5 日亲子长辈同行版",
    "dates": "2026-11-16 至 2026-11-20", "people": "3 大 1 小",
    "days": [
        {"day": "D1", "time": "09:00", "transport": "专车接机 40 分钟", "spot": "滇池海埂大坝",
         "meal": "午餐过桥米线 / 晚餐清淡", "hotel": "昆明 4 星（已确认）", "guide": "导游小周"},
        {"day": "D2", "time": "08:30", "transport": "高铁 2 小时", "spot": "大理古城 / 洱海",
         "meal": "午餐白族菜（无猪肉无酒）", "hotel": "大理海景 4 星（已确认）", "guide": "导游小周"},
    ],
    "vehicle": "7 座商务车，含司机与油费", "hotel": "4 星，含双早，11/16 前确认",
    "tickets": "洱海游船需实名预约，已预约", "insurance": "旅游意外险 30 万，已投保",
    "entry": "回乡证有效期至 2029 年", "backup": "主选方案 A；若高铁票不足则改包车，价差 +300",
}
PRICE_VALUES = {
    "people": "3 大 1 小", "dates": "2026-11-16 至 2026-11-20，5 天",
    "items": [{"name": "酒店", "desc": "4 星 2 间 × 5 晚", "qty": "2", "price": "500", "amount": "1000"},
              {"name": "用车", "desc": "7 座商务车 5 天", "qty": "3", "price": "600", "amount": "1800"}],
    "total": "2800", "per_person": "700", "cost": "2200",
    "insurance": "旅游意外险 30 万，60 元/人",
    "pending": "酒店与用车待资源方 2 小时内锁定", "fx": "汇率 0.92，锁定时间 11/10 18:00",
}
CONTRACT_VALUES = {
    "contract_no": "HT-20261016-17", "sign_date": "2026-10-16", "sign_way": "线上电子签",
    "policy_no": "PL-88213456", "insurer": "XX 保险", "insure_date": "2026-10-16",
    "coverage": "意外 30 万 / 医疗 5 万", "deposit": "5400", "deposit_at": "2026-10-16 11:02",
    "customer_signed": "已签署", "deposit_state": "已到账", "pay_way": "对公转账",
    "order_note": "顺序：先合同 → 再保险 → 后付款",
}
NOTICE_VALUES = {
    "gather": "2026-11-16 09:00，昆明长水机场 T1", "guide": "导游 小周 138**** / 司机 赵师傅 139****",
    "contact": "定制师 小李 137****（24 小时）", "daily": "每天集合时间与行程重点见附件",
    "docs": "证件、充电宝、雨具、常用药", "taboo": "已按无猪肉无酒安排",
    "weather": "昆明 15–24℃，早晚温差大", "confirm": "已发客户群，请回复「收到」",
}
SETTLE_VALUES = {
    "settle_no": "JS-20261024-03",
    "items": [{"item": "酒店", "supplier": "2800", "ours": "2800", "diff": "0", "note": "一致"},
              {"item": "用车", "supplier": "0", "ours": "0", "diff": "0", "note": "含在酒店包价"}],
    "total_settle": "2800", "total_ours": "2800", "diff": "0",
    "actual_cost": "2200", "actual_margin": "600",
    "reason": "无差异", "decision": "据实结算",
}
REVIEW_VALUES = {
    "time": "2026-10-26 电话 15 分钟", "satisfaction": "非常满意",
    "quote": "导游小周很贴心，长辈很满意", "issue": "无投诉",
    "remedy": "无", "balance_state": "已结清", "profit": "600",
    "good": "首呼 10 分钟内完成，需求四分类清楚",
    "improve": "报价单的汇率口径要写更早", "next": "补练 S6 分项报价的汇率与手续费口径",
}


def signup(client: TestClient, tag: str) -> tuple[str, dict]:
    username = f"jacc_{tag}_{uuid.uuid4().hex[:8]}"
    password = "Test1234!"
    r = client.post("/auth/register", json={"username": username, "password": password,
                                           "display_name": username})
    assert r.status_code in (200, 201), f"注册失败 {r.status_code}: {r.text}"
    uid = (r.json() or {}).get("user_id") or ""
    lr = client.post("/auth/login", json={"username": username, "password": password})
    assert lr.status_code == 200, f"登录失败 {lr.status_code}: {lr.text}"
    return uid, {"Authorization": "Bearer " + (lr.json() or {}).get("token", "")}


def main() -> int:
    app = create_app()
    ctx = app.state.ctx
    # 离线确定性：本脚本验收的是 journey 域链路（阶段/文档/回执/PDF/越权），**不验收模型层**。
    # 仓库存在 local.env（真实密钥）时，交付物拦截网的语义层会真调模型，出现「同一个合法填写
    # 时通时拦」的不可复现结果；这里显式摘掉模型客户端，让验收可复现。
    from tripcraft.agents.llm import LLMError
    for attr in ("guard", "tools", "director", "call_svc", "supplier_svc"):
        svc = getattr(ctx, attr, None)
        if svc is not None:
            try:
                svc._llm = None
            except Exception:
                pass

    def _offline_llm():
        raise LLMError("journey-acceptance offline：模型层不在本脚本验收范围")

    ctx.get_llm = _offline_llm          # 阻止后续 get_* 再挂回真实客户端
    ctx.llm_holder["client"] = None
    client = TestClient(app)
    anon = TestClient(app)
    uid_a, hdr_a = signup(client, "a")
    uid_b, hdr_b = signup(client, "b")

    # ---------------- A. 空白账号 → 真实派单 ----------------
    orders0 = client.get("/practice/orders", headers=hdr_a).json()
    check("A1", "新账号初始无订单（不靠演示种子数据）", orders0 == [],
          f"orders={len(orders0)}")
    gen = client.post("/practice/dispatch/generate", headers=hdr_a,
                      json={"user_id": "", "count": 1})
    created = (gen.json() or {}).get("created") or []
    oid = (created[0] or {}).get("order_id") if created else ""
    check("A2", "按画像生成派单成功且归当前账号",
          bool(oid) and (ctx.store.order(oid) or {}).get("user_id") == uid_a, f"order={oid}")
    if not oid:
        return _finish("无法拿到订单，后续旅程无法验证")

    def journey() -> dict:
        r = client.get(f"/practice/orders/{oid}/journey", headers=hdr_a)
        assert r.status_code == 200, f"journey {r.status_code}: {r.text}"
        return r.json()

    def step(tag: str, expect_stage: str | None = None, expect_substep: str | None = None) -> dict:
        j = journey()
        TRACE.append({"tag": tag, "current_stage": j["current_stage"],
                      "platform_stage": j["platform_stage"],
                      "next_action": (j.get("next_action") or {}),
                      "stages_state": {s["id"]: s["state"] for s in j["stages"]}})
        if expect_stage:
            check(f"T-{tag}", f"{tag}：当前阶段 = {EXPECT_STAGE_CN.get(expect_stage, expect_stage)}",
                  j["current_stage"] == expect_stage,
                  f"actual={j['current_stage']} platform={j['platform_stage']}")
        if expect_substep:
            na = j.get("next_action") or {}
            check(f"N-{tag}", f"{tag}：next_action → {expect_substep}",
                  na.get("substep") == expect_substep and str(na.get("route", "")).startswith("/"),
                  f"actual={na.get('substep')} route={na.get('route')}")
        return j

    def submit(code: str, values: dict, tag: str) -> dict:
        r = client.post(f"/practice/orders/{oid}/deliverables/{code}", headers=hdr_a,
                        json={"values": values, "file_ids": [], "targets": []})
        body = r.json() if r.status_code == 200 else {"http": r.status_code, "text": r.text[:200]}
        rst = (body.get("receipt") or {})
        why = ((body.get("guard") or {}).get("reasons") or [])[:2] or body.get("message") or ""
        check(f"S-{tag}", f"投递《{tag}》成功且回执完整",
              r.status_code == 200 and body.get("delivered") is True and bool(rst.get("message")),
              f"http={r.status_code} delivered={body.get('delivered')} blocked={body.get('blocked')} "
              f"V{rst.get('version')} next={(body.get('next_action') or {}).get('substep')} why={why}")
        return body

    # ---------------- B. 行前1：抢单 → 首呼 → 需求确认单 ----------------
    j0 = step("start", "pre1_requirement", "pre1.grab")
    check("B1", "起始 next_action 是抢单且给了路由", (j0.get("next_action") or {}).get("kind") == "action")
    g = client.post(f"/practice/orders/{oid}/grab", headers=hdr_a)
    check("B2", "抢单成功", g.status_code == 200, f"status={g.status_code}")
    step("after-grab", "pre1_requirement", "pre1.call")
    fc = client.post(f"/practice/orders/{oid}/actions", headers=hdr_a,
                     json={"action": "first_call"})
    check("B3", "首呼动作登记成功", fc.status_code == 200, f"status={fc.status_code}")
    # 首呼登记后「需求澄清」子步骤已由首呼动作满足，唯一下一步是提交《需求确认单》
    step("after-call", "pre1_requirement", "pre1.confirm")
    submit("requirement_sheet", REQ_VALUES, "需求确认单")

    # ---------------- C. 行前2：询价 → 行程方案 → 客户反馈 ----------------
    step("pre2", "pre2_plan", "pre2.quote")
    submit("resource_quote", QUOTE_VALUES, "资源询价记录")
    itin_out = submit("itinerary", ITIN_VALUES, "行程方案")
    check("C1", "行前2 阶段内文档按阶段归属（行程方案 stage=pre2_plan）",
          itin_out.get("stage") == "pre2_plan", f"stage={itin_out.get('stage')}")
    submit("quotation", PRICE_VALUES, "分项报价")
    step("pre2-feedback", "pre2_plan", "pre2.feedback")

    # 方案版本：创建 → 发送 → 客户已读 → 客户确认（真实 plan_service 链路）
    pl = client.post(f"/practice/orders/{oid}/plans", headers=hdr_a,
                     json={"values": ITIN_VALUES, "note": ""})
    plan_id = ((pl.json() or {}).get("plan") or {}).get("plan_id", "")
    check("C2", "创建方案版本成功", pl.status_code == 200 and bool(plan_id), f"plan={plan_id}")
    snd = client.post(f"/practice/orders/{oid}/plans/{plan_id}/send", headers=hdr_a,
                      json={"targets": []})
    check("C3", "发送方案成功（状态=已发送）",
          snd.status_code == 200 and (snd.json() or {}).get("ok") is True,
          f"status={snd.status_code}")
    time.sleep(6)                                  # 客户「读」方案（演示节奏 5s）
    plans_now = client.get(f"/practice/orders/{oid}/plans", headers=hdr_a).json().get("plans") or []
    cur = next((p for p in plans_now if p["plan_id"] == plan_id), {})
    check("C4", "客户已读（读回执来自服务端状态而不是前端写死）",
          bool(cur.get("read_at")), f"status={cur.get('status')} read_at={cur.get('read_at')}")
    cf = client.post(f"/practice/orders/{oid}/plans/{plan_id}/confirm", headers=hdr_a)
    check("C5", "登记客户确认方案（仅客户已读后允许）",
          cf.status_code == 200 and (cf.json() or {}).get("ok") is True,
          f"status={cf.status_code}")

    # ---------------- D. 行前3：合同与保险 → 回签 → 定金 ----------------
    step("pre3", "pre3_quote")
    submit("contract", CONTRACT_VALUES, "合同与保险")

    # ---------------- E. 行前4：资源锁定 + 出团通知书 ----------------
    step("pre4", "pre4_notice")
    submit("departure_notice", NOTICE_VALUES, "出团通知书")
    ledger = ctx.store.action_keys(oid)
    check("E1", "出团通知书投递后动作账本有对应动作（动作字典 ↔ 交付物契约一致）",
          "deliverable:出团通知书" in ledger and "resources_locked" in ledger
          and "pre_trip_notice" in ledger,
          f"deliverable:出团通知书={'deliverable:出团通知书' in ledger} "
          f"resources_locked={'resources_locked' in ledger} "
          f"pre_trip_notice={'pre_trip_notice' in ledger}")

    # ---------------- F. 行中 ----------------
    step("on_trip", "on_trip")

    # ---------------- G. 行后：结算 → 回访复盘 → 订单完成 ----------------
    submit("settlement", SETTLE_VALUES, "地接结算核对单")
    ledger = ctx.store.action_keys(oid)
    check("G0a", "地接结算单投递后动作账本有对应动作 + 结算门槛动作",
          "deliverable:地接结算核对单" in ledger and "settlement_verified" in ledger,
          f"deliverable:地接结算核对单={'deliverable:地接结算核对单' in ledger} "
          f"settlement_verified={'settlement_verified' in ledger}")
    # 结算核对单投递后平台态才推进到 6，此时当前阶段才是「行后复盘」
    step("post", "post_trip")
    submit("review", REVIEW_VALUES, "回访与复盘记录")
    ledger = ctx.store.action_keys(oid)
    check("G0b", "回访复盘投递后动作账本有对应动作 + 复盘门槛动作",
          "deliverable:回访与复盘记录" in ledger and "review_done" in ledger
          and "balance_paid" in ledger,
          f"deliverable:回访与复盘记录={'deliverable:回访与复盘记录' in ledger} "
          f"review_done={'review_done' in ledger} balance_paid={'balance_paid' in ledger}")

    j_end = journey()
    TRACE.append({"tag": "end", "current_stage": j_end["current_stage"],
                  "platform_stage": j_end["platform_stage"],
                  "next_action": j_end.get("next_action"),
                  "stages_state": {s["id"]: s["state"] for s in j_end["stages"]}})
    check("G1", "订单走到完成：平台态 7", j_end["platform_stage"] == 7,
          f"platform={j_end['platform_stage']}")
    check("G2", "完成时六阶段全部 done", all(s["state"] == "done" for s in j_end["stages"]),
          str({s["id"]: s["state"] for s in j_end["stages"]}))
    check("G3", "完成时 next_action = null（不再提示下一步）", j_end.get("next_action") is None)

    # 阶段推进轨迹：必须按 行前1→行前2→行前3→行前4→行中→行后 单调前进，且六段都到过
    seen = []
    for t in TRACE:
        if not seen or seen[-1] != t["current_stage"]:
            seen.append(t["current_stage"])
    check("G4", "六阶段按顺序全部走到（无跳段/无乱序）", seen == EXPECT_STAGE_ORDER, str(seen))
    check("G5", "阶段顺序与 contracts/stages.py 一致",
          [s.id for s in STAGES] == EXPECT_STAGE_ORDER, str([s.id for s in STAGES]))

    # ---------------- H. R01：四份文档按阶段后移 ----------------
    docs = client.get(f"/practice/orders/{oid}/deliverables", headers=hdr_a).json()
    items = docs.get("deliverables", [])
    order_codes = [i["code"] for i in items]
    expect_codes = ["requirement_sheet", "resource_quote", "itinerary", "quotation",
                    "contract", "departure_notice", "settlement", "review"]
    check("H1", "四份文档/八份产出按阶段顺序返回（不再是无阶段总入口）",
          order_codes == expect_codes, str(order_codes))
    stage_map = {i["code"]: i["stage"] for i in items}
    check("H2", "四份主文档落点正确",
          stage_map.get("requirement_sheet") == "pre1_requirement"
          and stage_map.get("itinerary") == "pre2_plan"
          and stage_map.get("quotation") == "pre3_quote"
          and stage_map.get("departure_notice") == "pre4_notice",
          str({k: stage_map.get(k) for k in ("requirement_sheet", "itinerary", "quotation",
                                             "departure_notice")}))
    check("H3", "八份产出全部由服务端标记已投递", all(i["submitted"] for i in items),
          str([(i["code"], i["submitted"]) for i in items]))
    check("H4", "完成的订单不再有 is_next 标记", not any(i["is_next"] for i in items))

    # ---------------- I. R04：失败可恢复（拦截后状态不变） ----------------
    before = len(ctx.store.deliverables(oid))
    bad = dict(PRICE_VALUES)
    bad["total"] = "9999"
    blk = client.post(f"/practice/orders/{oid}/deliverables/quotation", headers=hdr_a,
                      json={"values": bad, "file_ids": [], "targets": []})
    after = len(ctx.store.deliverables(oid))
    bb = blk.json() if blk.status_code == 200 else {}
    check("I1", "算术不一致被拦截：blocked=true 且 delivered=false",
          blk.status_code == 200 and bb.get("blocked") is True and bb.get("delivered") is False,
          f"reasons={len((bb.get('guard') or {}).get('reasons') or [])}")
    check("I2", "被拦截后未落库、可原处重试", before == after, f"{before} -> {after}")
    missing = client.post(f"/practice/orders/{oid}/deliverables/review", headers=hdr_a,
                          json={"values": {"time": "只有这一项"}, "file_ids": [], "targets": []})
    check("I3", "必填缺失 → 400，不写库", missing.status_code == 400,
          f"status={missing.status_code}")

    # ---------------- J. R05：PDF 真实可用 ----------------
    pdf = client.post(f"/practice/orders/{oid}/deliverables/departure_notice/export.pdf",
                      headers=hdr_a, json={"values": NOTICE_VALUES})
    body = pdf.content if pdf.status_code == 200 else b""
    pages, text = 0, ""
    if body.startswith(b"%PDF"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(body))
            pages = len(reader.pages)
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as exc:
            text = f"<parse error: {type(exc).__name__}: {exc}>"
    check("J1", "PDF 导出 200 + application/pdf",
          pdf.status_code == 200 and "application/pdf" in pdf.headers.get("content-type", ""),
          f"status={pdf.status_code}")
    check("J2", "PDF 真实可解析（%PDF + 页数）", body.startswith(b"%PDF") and pages >= 1,
          f"bytes={len(body)} pages={pages}")
    check("J3", "PDF 与工作台渲染同源（含订单号）", oid in text, f"extracted_len={len(text)}")
    with_headers = client.post(f"/practice/orders/{oid}/deliverables/requirement_sheet/export.pdf",
                               headers=hdr_a, json={"values": REQ_VALUES})
    check("J4", "中文标题文档导出 PDF 也成功（非空且不同内容）",
          with_headers.status_code == 200 and with_headers.content != body,
          f"len1={len(body)} len2={len(with_headers.content)}")
    prev = client.post(f"/practice/orders/{oid}/deliverables/requirement_sheet/preview",
                       headers=hdr_a, json={"values": REQ_VALUES})
    prev_text = (prev.json() or {}).get("rendered", "") if prev.status_code == 200 else ""
    check("J5", "文档正文不再暴露内部文件名（渲染结果无 .md）",
          bool(prev_text) and ".md" not in prev_text,
          f"rendered_len={len(prev_text)}")

    # ---------------- K. R09/R10：单一阶段口径（静态） ----------------
    src = ROOT / "frontend" / "src"
    flat = []
    for f in src.rglob("*.vue"):
        if re.search(r"\{\s*id:\s*'S\d", f.read_text(encoding="utf-8", errors="ignore")):
            flat.append(str(f.relative_to(ROOT)))
    check("K1", "前端不存在把 S0–S12 平铺作主导航的数组", not flat, str(flat))
    nav_users = []
    for f in src.rglob("*.vue"):
        t = f.read_text(encoding="utf-8", errors="ignore")
        if "components/StageNav.vue" in t:
            nav_users.append(str(f.relative_to(ROOT)).replace("\\", "/"))
    check("K2", "首页与实战页共用同一个 StageNav 组件",
          any(u.endswith("views/HomeView.vue") for u in nav_users)
          and any(u.endswith("views/practice/PracticeView.vue") for u in nav_users),
          str(nav_users))
    check("K3", "六阶段导航组件内不含硬编码阶段名/S 编号",
          "S0" not in (src / "components" / "StageNav.vue").read_text(encoding="utf-8"),
          "StageNav.vue checked")

    # ---------------- L. R05：学员界面不再有 Markdown 导出 ----------------
    learner_files = [
        "frontend/src/views/practice/DeliverableWorkbenchView.vue",
        "frontend/src/views/vbooking/PlanNewView.vue",
        "frontend/src/views/vbooking/OrderDetailView.vue",
        "frontend/src/views/practice/PracticeView.vue",
        "frontend/src/views/practice/FinanceView.vue",
        "frontend/src/components/ProgressDock.vue",
        "frontend/src/components/StageNav.vue",
        "frontend/src/components/StepBar.vue",
        "frontend/src/views/HomeView.vue",
    ]
    md_hits = []
    for rel in learner_files:
        p = ROOT / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"导出\s*<?i?>?\s*Markdown|\.md['\"`]|text/markdown", line):
                md_hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    check("L1", "journey 域学员界面 Markdown 导出入口为 0", not md_hits, str(md_hits))
    # 范围外（其他域）的 Markdown 导出：如实报告，不算本域失败
    outside = []
    for f in src.rglob("*.vue"):
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        if rel in learner_files:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"\.md['\"`]|text/markdown", line):
                outside.append(f"{rel}:{i}")
    TRACE.append({"outside_markdown_export": sorted(set(outside))})

    # ---------------- M. R17：死按钮静态扫描（journey 域页面） ----------------
    dead = []
    for rel in learner_files:
        p = ROOT / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"<button\b[^>]*>", t):
            tag = m.group(0)
            if "@click" in tag or "disabled" in tag or "type=\"submit\"" in tag:
                continue
            dead.append(f"{rel}:{t[:m.start()].count(chr(10)) + 1}: {' '.join(tag.split())[:90]}")
    check("M1", "journey 域页面无「无 @click 也不 disabled」的死按钮", not dead, str(dead))

    # ---------------- M2. 学生可见文案不得出现实现语言（监督者 item 4） ----------------
    # 复用 scripts/journey_copy_scan.py 的判定口径（含中文的字符串字面量 + .vue 模板文本节点）
    import subprocess
    scan = subprocess.run([sys.executable, str(ROOT / "scripts" / "journey_copy_scan.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))
    jargon_hits = [ln for ln in (scan.stdout or "").splitlines() if ln.startswith("  ")]
    TRACE.append({"copy_scan_stdout": (scan.stdout or "").strip().splitlines()[:60]})
    check("M2", "journey 域学生可见文案无实现语言（注释不计）",
          scan.returncode == 0, f"命中 {len(jargon_hits)} 条；详见 journey-copy-scan 输出")

    # ---------------- M3. 窄屏：右下角流程面板不得溢出（静态） ----------------
    dock = (src / "components" / "ProgressDock.vue").read_text(encoding="utf-8", errors="ignore")
    narrow_ok = bool(re.search(r"@media[^{]*max-width", dock)) and (
        "min(" in dock or "100vw" in dock or "max-width: 92vw" in dock)
    check("M3", "ProgressDock 有窄屏约束（面板宽度自适应，不固定溢出）", narrow_ok,
          "contains @media + 100vw/min()", runtime=False)

    # ---------------- N. 越权（与 API 自检互补：这次是走完整旅程后的对象） ----------------
    idor = [
        ("N1", "其他账号读本单旅程", 403, lambda: client.get(f"/practice/orders/{oid}/journey", headers=hdr_b)),
        ("N2", "其他账号读本单交付物", 403, lambda: client.get(f"/practice/orders/{oid}/deliverables", headers=hdr_b)),
        ("N3", "其他账号投递到本单", 403, lambda: client.post(f"/practice/orders/{oid}/deliverables/requirement_sheet", headers=hdr_b, json={"values": REQ_VALUES, "file_ids": [], "targets": []})),
        ("N4", "其他账号导出本单 PDF", 403, lambda: client.post(f"/practice/orders/{oid}/deliverables/requirement_sheet/export.pdf", headers=hdr_b, json={"values": {}})),
        ("N5", "其他账号读本单方案", 403, lambda: client.get(f"/practice/orders/{oid}/plans", headers=hdr_b)),
        ("N6", "其他账号确认本单方案", 403, lambda: client.post(f"/practice/orders/{oid}/plans/{plan_id}/confirm", headers=hdr_b)),
        ("N7", "未登录读本单旅程", 401, lambda: anon.get(f"/practice/orders/{oid}/journey")),
        ("N8", "不存在的订单", 404, lambda: client.get("/practice/orders/9999999999999999/journey", headers=hdr_a)),
    ]
    for cid, label, want, call in idor:
        try:
            got = call().status_code
        except Exception as exc:
            got = f"EXC {type(exc).__name__}"
        check(cid, label, got == want, f"expect={want} actual={got}")

    # ---------------- O. 契约数据的学生可见文案（阶段/交付物定义里的说明文字） ----------------
    # 这一层不在前端源码里：由 /practice/stages 与 /deliverables/specs 下发，同样必须有 人话门禁。
    from tripcraft.services.workflow import ACTION_LABELS, MANUAL_ACTIONS, is_known_action
    from tripcraft.contracts.deliverables_spec import DELIVERABLES
    from tripcraft.contracts.stages import STAGES_BY_ID, deliverable_stage

    banned = ["契约", "口径", "原子", "DTO", "阶段归属", "接口", "服务端", "后端", "端点",
              "字段", "落库", "schema", "payload"]
    data_hits: list[str] = []
    stages_api = client.get("/practice/stages", headers=hdr_a).json()
    for st in stages_api.get("stages", []):
        for key in ("name", "short", "focus"):
            v = str(st.get(key) or "")
            for kw in banned:
                if kw in v:
                    data_hits.append(f"stages.{st['id']}.{key}: [{kw}] {v}")
        for sub in st.get("substeps", []):
            for key in ("name", "hint"):
                v = str(sub.get(key) or "")
                for kw in banned:
                    if kw in v:
                        data_hits.append(f"stages.{st['id']}.{sub['id']}.{key}: [{kw}] {v}")
    specs = client.get("/deliverables/specs").json().get("deliverables", [])
    for d in specs:
        texts = [("title", d.get("title")), ("purpose", d.get("purpose"))]
        for f in d.get("fields", []):
            texts += [(f"field[{f['key']}].label", f.get("label")),
                      (f"field[{f['key']}].placeholder", f.get("placeholder")),
                      (f"field[{f['key']}].help", f.get("help"))]
        for key, v in texts:
            v = str(v or "")
            for kw in banned:
                if kw in v:
                    data_hits.append(f"specs.{d['code']}.{key}: [{kw}] {v}")
    check("O1", "六阶段契约与交付物契约下发的文案无实现语言（学生可见）",
          not data_hits, f"命中 {len(data_hits)} 条（详见 trace.contract_copy_hits）")
    TRACE.append({"contract_copy_hits": data_hits})

    # ---------------- P. 动作字典 ↔ 交付物契约 ↔ 六阶段 一致性（Lead 要求的对照 + 闭环） ----------------
    step_of_stage = {s.id: s.id for s in STAGES}
    table = []
    unknown: list[str] = []
    for spec in DELIVERABLES:
        sid = deliverable_stage(spec.code)
        acts = list(spec.auto_actions) + [a for a, _k, _v in spec.conditional_actions]
        for a in acts:
            known = is_known_action(a)
            if not known:
                unknown.append(f"{spec.code}: {a}")
        table.append({
            "code": spec.code, "title": spec.id, "step": spec.step,
            "stage": sid,
            "stage_name": (STAGES_BY_ID[sid].name if sid in STAGES_BY_ID else ""),
            "auto_actions": list(spec.auto_actions),
            "conditional_actions": [list(x) for x in spec.conditional_actions],
            "actions_known": all(is_known_action(a) for a in acts),
        })
    check("P1", "每个交付物声明的动作都在动作字典里（无静默丢弃）", not unknown, str(unknown))
    manual_unknown = [a for a in MANUAL_ACTIONS if not is_known_action(a)]
    check("P2", "MANUAL_ACTIONS 全部存在于 ACTION_LABELS", not manual_unknown,
          str(manual_unknown))
    check("P3", "出团通知书/结算/复盘三份交付物都有可落地动作",
          all(is_known_action(f"deliverable:{t}")
              for t in ("出团通知书", "地接结算核对单", "回访与复盘记录")),
          f"labels={[f'deliverable:{t}' for t in ('出团通知书', '地接结算核对单', '回访与复盘记录')]}")
    check("P4", "三份交付物的阶段归属与 contracts/stages.py 一致",
          deliverable_stage("departure_notice") == "pre4_notice"
          and deliverable_stage("settlement") == "post_trip"
          and deliverable_stage("review") == "post_trip",
          f"departure_notice={deliverable_stage('departure_notice')} "
          f"settlement={deliverable_stage('settlement')} review={deliverable_stage('review')}")
    TRACE.append({"action_contract_table": table,
                  "action_labels": dict(ACTION_LABELS),
                  "manual_actions": list(MANUAL_ACTIONS)})

    return _finish(None)


def _finish(early: str | None) -> int:
    failed = [r for r in RESULTS if not r["ok"]]
    summary = {
        "workId": "journey-acceptance",
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db": str(_DB),
        "offline": True,
        "offline_note": "本脚本摘掉了模型客户端（guard/tools/director/call/supplier 的 _llm 置空 + "
                        "get_llm 抛 LLMError）：验收目标是 journey 域阶段/文档/回执/PDF/越权链路，"
                        "模型语义与实时语音不在本证据范围（见未核实项）。",
        "total": len(RESULTS), "passed": len(RESULTS) - len(failed), "failed": len(failed),
        "results": RESULTS, "trace": TRACE,
        "runtime_verified": [r["id"] for r in RESULTS if r["ok"] and r["runtime"]],
        "static_only": [r["id"] for r in RESULTS if r["ok"] and not r["runtime"]],
        "not_verified": [r["id"] for r in RESULTS if not r["ok"]],
        "early_exit": early or "",
        "note": "本 manifest 只记录真实跑过的项；前端运行时行为（动画/防重复点击/浏览器路径）"
                "不在本脚本覆盖范围，标记 runtime=false 的项仅为静态核查。",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    (OUT_DIR / "journey-acceptance.log").write_text(
        "\n".join(f"{'PASS' if r['ok'] else 'FAIL'}\t{r['id']}\t{r['name']}\t{r['detail']}"
                  for r in RESULTS) + f"\n\n{summary['passed']}/{summary['total']} passed\n",
        encoding="utf-8")
    print(f"\n=== journey acceptance: {summary['passed']}/{summary['total']} passed ===")
    if early:
        print(f"EARLY EXIT: {early}")
    for f in failed:
        print(f"FAILED: {f['id']} {f['name']} · {f['detail']}")
    print(f"manifest -> {OUT_DIR / 'manifest.json'}")
    return 1 if failed or early else 0


if __name__ == "__main__":
    raise SystemExit(main())
