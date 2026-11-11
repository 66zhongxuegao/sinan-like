"""journey 域接口自检（可重跑，独立数据库，不碰演示库）。

覆盖 R01 / R03 / R04 / R09 / R10 的服务端判据，以及 security.py v2 的对象归属：
  - `GET /practice/stages` 与 `contracts/stages.py` 的 as_payload() 逐字段一致；
  - `GET /practice/orders/{id}/journey` 的平台态 → 六阶段映射、子步骤状态、唯一 next_action；
  - 交付物列表的 stage/stage_name/in_current_stage/is_next 与阶段排序；
  - 提交回执 delivered/receipt/next_action（只有服务端真实投递才算 delivered）；
  - 拦截网拦截时状态不变（失败可恢复）；
  - PDF 真实字节可被解析成页，且内容含该订单号（与工作台渲染同源）；
  - 越权矩阵：未登录 401 / 他人订单 403 / 不存在 404。

用法：
    python scripts/journey_api_check.py
退出码 0 = 全部通过；1 = 有失败项。原始结果落盘 output/journey/evidence/api-check.json。
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:                                  # 控制台按 UTF-8 输出，避免 Windows 代码页把中文写成乱码
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = ROOT / "output" / "journey" / "evidence"
OUT_DIR.mkdir(parents=True, exist_ok=True)
# 独立库固定放在 output/journey/tmp 下（每次运行先删旧文件重来），仓库根目录不留任何临时产物
_TMP = ROOT / "output" / "journey" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_DB = _TMP / "journey-check.sqlite"
for _stale in (_DB, Path(str(_DB) + "-wal"), Path(str(_DB) + "-shm")):
    try:
        _stale.unlink(missing_ok=True)
    except OSError:
        pass
os.environ["TRIPCRAFT_DB"] = str(_DB)
os.environ["TRIPCRAFT_VISIT_LOG_DIR"] = str(_TMP / "logs")

from fastapi.testclient import TestClient          # noqa: E402
from tripcraft.api.app import create_app           # noqa: E402
from tripcraft.contracts.stages import as_payload  # noqa: E402

# 独立于实现的预期映射（写死在这里，避免「拿被测代码断言被测代码」）
EXPECT_STAGE_OF_PLATFORM = {
    0: "pre1_requirement", 1: "pre2_plan", 2: "pre3_quote",
    4: "pre4_notice", 6: "post_trip", 7: "post_trip",
}
EXPECT_DOC_ORDER = [
    "requirement_sheet", "resource_quote", "itinerary", "quotation",
    "contract", "departure_notice", "settlement", "review",
]
VALID_STATES = {"done", "current", "todo"}

RESULTS: list[dict] = []
EXTRA: dict = {}


def check(cid: str, name: str, ok: bool, detail: object = "") -> bool:
    RESULTS.append({"id": cid, "name": name, "ok": bool(ok), "detail": str(detail)})
    print(f"{'PASS' if ok else 'FAIL'}  {cid}  {name}"
          + (f"  ·  {detail}" if detail != "" else ""))
    return bool(ok)


def signup(client: TestClient, tag: str) -> tuple[str, dict]:
    username = f"journey_{tag}_{uuid.uuid4().hex[:8]}"
    password = "Test1234!"
    r = client.post("/auth/register", json={"username": username, "password": password,
                                            "display_name": username})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"注册失败 {r.status_code}: {r.text}")
    user_id = (r.json() or {}).get("user_id") or ""
    lr = client.post("/auth/login", json={"username": username, "password": password})
    if lr.status_code != 200:
        raise RuntimeError(f"登录失败 {lr.status_code}: {lr.text}")
    return user_id, {"Authorization": "Bearer " + (lr.json() or {}).get("token", "")}


def make_order(ctx, order_id: str, user_id: str, stage: int, customer: str = "客户 A") -> None:
    ctx.store.upsert_order(order_id, user_id, customer, "云南", "正常", stage,
                           payload={"source_market": "香港", "language": "中文",
                                    "created_at": "2026-10-16 10:00:00"})


def _scan_forbidden(payload, forbidden, path: str = "$") -> list[str]:
    """递归找出响应里出现的隐藏/内部字段（与 api/public_dto.scan_forbidden_keys 同口径）。"""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in forbidden:
                found.append(f"{path}.{key}")
            found.extend(_scan_forbidden(value, forbidden, f"{path}.{key}"))
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            found.extend(_scan_forbidden(item, forbidden, f"{path}[{i}]"))
    return found


def main() -> int:
    app = create_app()
    ctx = app.state.ctx
    client = TestClient(app)
    # 未登录用例必须用不带 cookie 的独立客户端：登录会往 cookie jar 写 tc_token，
    # 复用同一个 TestClient 会让「未登录」请求实际带着上一个用户的会话。
    anon = TestClient(app)

    uid_a, hdr_a = signup(client, "a")
    uid_b, hdr_b = signup(client, "b")

    # 订单：A 覆盖 6 个平台态；B 一单（用于越权）
    a_orders = {}
    for i, stage in enumerate(sorted(EXPECT_STAGE_OF_PLATFORM)):
        oid = f"91000000000001{i:02d}"
        make_order(ctx, oid, uid_a, stage)
        a_orders[stage] = oid
    b_order = "9200000000000001"
    make_order(ctx, b_order, uid_b, 1, customer="客户 B")

    # ---------------- 1. 六阶段契约原样透传 ----------------
    r = client.get("/practice/stages", headers=hdr_a)
    payload = r.json() if r.status_code == 200 else {}
    expect = as_payload()
    check("R09-1", "GET /practice/stages 200", r.status_code == 200, f"status={r.status_code}")
    check("R09-2", "六阶段契约逐字段一致（== contracts.stages.as_payload()）",
          payload == expect, f"stages={len(payload.get('stages', []))}")
    check("R09-3", "阶段数量 = 6", len(payload.get("stages", [])) == 6,
          f"len={len(payload.get('stages', []))}")
    check("R09-4", "只出现阶段名，不含 S0–S12 编号作为主导航",
          all(not s["name"].startswith("S") for s in payload.get("stages", []))
          and all(s["substeps"] for s in payload.get("stages", [])),
          "每阶段子步骤非空")
    EXTRA["stages_payload"] = payload

    # ---------------- 2. journey 投影 ----------------
    journeys = {}
    mapping_ok, substep_ok, action_ok = True, True, True
    map_detail = []
    for stage, oid in a_orders.items():
        jr = client.get(f"/practice/orders/{oid}/journey", headers=hdr_a)
        if jr.status_code != 200:
            mapping_ok = False
            map_detail.append(f"stage{stage}:HTTP{jr.status_code}")
            continue
        j = jr.json()
        journeys[stage] = j
        got = j.get("current_stage")
        want = EXPECT_STAGE_OF_PLATFORM[stage]
        if got != want:
            mapping_ok = False
            map_detail.append(f"stage{stage}:{got}!={want}")
        for st in j.get("stages", []):
            if not st.get("substeps"):
                substep_ok = False
            if st.get("state") not in VALID_STATES:
                substep_ok = False
            for sub in st["substeps"]:
                if sub.get("state") not in VALID_STATES:
                    substep_ok = False
        na = j.get("next_action")
        if stage < 7:
            if not na or not str(na.get("route", "")).startswith("/"):
                action_ok = False
    check("R10-1", "平台态 → 六阶段映射正确（0/1/2/4/6/7）", mapping_ok,
          "、".join(map_detail) or "全部命中")
    check("R10-2", "每阶段子步骤非空且 state ∈ {done,current,todo}", substep_ok)
    check("R03-1", "未完成订单都有唯一 next_action 且带可路由 route", action_ok)
    j1 = journeys.get(1, {})
    check("R03-2", "next_action 指向当前阶段最早未完成子步骤",
          (j1.get("next_action") or {}).get("substep") == "pre2.quote",
          (j1.get("next_action") or {}).get("substep"))
    check("R03-3", "next_action.route 可直接路由",
          (j1.get("next_action") or {}).get("route", "").startswith(
              f"/practice/orders/{a_orders[1]}/deliverables?code="),
          (j1.get("next_action") or {}).get("route"))
    done_order = journeys.get(7, {})
    check("R03-4", "订单完成（平台态 7）时 next_action = null",
          done_order.get("next_action") is None, str(done_order.get("next_action")))
    EXTRA["journey_stage1"] = j1

    # ---------------- 3. 交付物阶段元数据（R01） ----------------
    dl = client.get(f"/practice/orders/{a_orders[1]}/deliverables", headers=hdr_a)
    d = dl.json() if dl.status_code == 200 else {}
    items = d.get("deliverables", [])
    codes = [i.get("code") for i in items]
    check("R01-1", "交付物列表按阶段顺序返回", codes == EXPECT_DOC_ORDER, str(codes))
    check("R01-2", "每条带 stage / stage_name / stage_state / in_current_stage / is_next",
          all(i.get("stage") and i.get("stage_name") and i.get("stage_state")
              and "in_current_stage" in i and "is_next" in i for i in items))
    req = next((i for i in items if i["code"] == "requirement_sheet"), {})
    itin = next((i for i in items if i["code"] == "itinerary"), {})
    check("R01-3", "四份文档归属到各自阶段",
          req.get("stage") == "pre1_requirement" and itin.get("stage") == "pre2_plan",
          f"需求确认单→{req.get('stage')} 行程方案→{itin.get('stage')}")
    check("R01-4", "当前阶段文档被标记（in_current_stage + is_next）",
          any(i.get("in_current_stage") for i in items) and any(i.get("is_next") for i in items))
    check("R01-5", "顶层带 current_stage / next_action",
          d.get("current_stage") == "pre2_plan" and d.get("next_action"))
    EXTRA["deliverable_list"] = {
        "order_id": d.get("order_id"), "current_stage": d.get("current_stage"),
        "deliverables": [{k: i.get(k) for k in
                          ("code", "stage", "stage_name", "stage_state", "in_current_stage",
                           "is_next", "submitted")} for i in items],
    }

    # ---------------- 4. 提交回执（R04） ----------------
    values_ok = {"supplier": "云南地接 A", "kind": "酒店", "quote": "标间 480 元/间/晚",
                 "availability": "有"}
    sub = client.post(f"/practice/orders/{a_orders[1]}/deliverables/resource_quote",
                      headers=hdr_a, json={"values": values_ok, "file_ids": [], "targets": []})
    sub_body = sub.json() if sub.status_code == 200 else {}
    check("R04-1", "提交成功返回 200 + delivered=true",
          sub.status_code == 200 and sub_body.get("delivered") is True,
          f"status={sub.status_code} delivered={sub_body.get('delivered')}")
    check("R04-2", "回执含 receipt（版本/时间/去向/文案）",
          bool((sub_body.get("receipt") or {}).get("message"))
          and (sub_body.get("receipt") or {}).get("version") == 1,
          str(sub_body.get("receipt")))
    check("R04-3", "回执带下一步 next_action",
          bool(sub_body.get("next_action")), str((sub_body.get("next_action") or {}).get("label")))
    after = client.get(f"/practice/orders/{a_orders[1]}/deliverables", headers=hdr_a).json()
    rq = next(i for i in after["deliverables"] if i["code"] == "resource_quote")
    check("R04-4", "只有服务端投递成功后列表才显示已投递", rq["submitted"] is True,
          f"submitted={rq['submitted']} version={rq['version']}")
    EXTRA["submission"] = {k: sub_body.get(k) for k in ("delivered", "receipt", "next_action",
                                                        "blocked", "stage", "version")}

    # ---------------- 5. 拦截网拦截后状态不变（失败可恢复） ----------------
    before_count = len(ctx.store.deliverables(a_orders[1]))
    bad = {"people": "3 大 1 小", "dates": "10月20日-24日",
           "items": [{"name": "酒店", "qty": "2", "price": "500", "amount": "1000"}],
           "total": "5000", "insurance": "旅游意外险 30 万"}
    blk = client.post(f"/practice/orders/{a_orders[1]}/deliverables/quotation",
                      headers=hdr_a, json={"values": bad, "file_ids": [], "targets": []})
    blk_body = blk.json() if blk.status_code == 200 else {}
    after_count = len(ctx.store.deliverables(a_orders[1]))
    check("R04-5", "算术校验不通过 → blocked 且 delivered=false",
          blk.status_code == 200 and blk_body.get("blocked") is True
          and blk_body.get("delivered") is False,
          f"status={blk.status_code} reasons={len((blk_body.get('guard') or {}).get('reasons') or [])}")
    check("R04-6", "被拦截时未落库（状态不变，可在原处重试）",
          before_count == after_count, f"{before_count} -> {after_count}")
    missing = client.post(f"/practice/orders/{a_orders[1]}/deliverables/resource_quote",
                          headers=hdr_a, json={"values": {"supplier": "只有这一项"},
                                               "file_ids": [], "targets": []})
    check("R04-7", "必填项缺失 → 400（不写库）", missing.status_code == 400,
          f"status={missing.status_code}")

    # ---------------- 6. PDF（R05：只留 PDF 且真实可用） ----------------
    order_id_4 = a_orders[1]
    pdf = client.post(f"/practice/orders/{order_id_4}/deliverables/requirement_sheet/export.pdf",
                      headers=hdr_a, json={"values": {"guest": "王女士", "people": "3 大 1 小",
                                                      "dates": "10月20日-24日",
                                                      "must": "预算上限 3 万", "budget": "总价"}})
    body = pdf.content if pdf.status_code == 200 else b""
    pages, text = 0, ""
    if body.startswith(b"%PDF"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(body))
            pages = len(reader.pages)
            text = (reader.pages[0].extract_text() or "")
        except Exception as exc:            # 解析失败也要留下真实原因
            text = f"<parse error: {type(exc).__name__}: {exc}>"
    check("R05-1", "PDF 导出返回 200 + application/pdf",
          pdf.status_code == 200 and "application/pdf" in pdf.headers.get("content-type", ""),
          f"status={pdf.status_code} type={pdf.headers.get('content-type')}")
    check("R05-2", "PDF 是真实可解析文档（%PDF 头 + ≥1 页）",
          body.startswith(b"%PDF") and pages >= 1, f"bytes={len(body)} pages={pages}")
    check("R05-3", "PDF 内容与工作台渲染同源（含订单号）",
          order_id_4 in text, f"extracted_len={len(text)}")
    pdf2 = client.post(f"/practice/orders/{order_id_4}/deliverables/quotation/export.pdf",
                       headers=hdr_a, json={"values": {"people": "3 大 1 小"}})
    check("R05-4", "不同交付物的 PDF 内容不同（不是空壳）",
          pdf2.status_code == 200 and pdf2.content != body,
          f"len1={len(body)} len2={len(pdf2.content)}")
    EXTRA["pdf"] = {"status": pdf.status_code, "bytes": len(body), "pages": pages,
                    "content_type": pdf.headers.get("content-type"),
                    "extracted_head": text[:120]}

    # ---------------- 7. 越权矩阵（security.py v2） ----------------
    a_order = a_orders[1]
    file_up = client.post("/deliverables/files", headers=hdr_a,
                          json={"filename": "evidence.txt", "mime": "text/plain",
                                "data_b64": base64.b64encode(b"journey evidence").decode(),
                                "order_id": a_order, "deliverable_id": ""})
    fid = (file_up.json() or {}).get("file_id", "")

    plan = client.post(f"/practice/orders/{a_order}/plans", headers=hdr_a,
                       json={"values": {"title": "香港客人云南 5 日", "days": [{"day": "D1"}]},
                             "note": ""})
    plan_id = ((plan.json() or {}).get("plan") or {}).get("plan_id", "")
    b_plan = client.post(f"/practice/orders/{b_order}/plans", headers=hdr_b,
                         json={"values": {"title": "B 单方案", "days": [{"day": "D1"}]}, "note": ""})
    b_plan_id = ((b_plan.json() or {}).get("plan") or {}).get("plan_id", "")

    tpl = client.post("/practice/doc-templates", headers=hdr_a,
                      json={"name": "本人模板", "sections": [{"title": "交通"}], "kind": "plan"})
    tpl_id = (tpl.json() or {}).get("template_id", "")

    a_calls = [
        ("IDOR-1  未登录访问 /practice/orders", 401,
         lambda: anon.get("/practice/orders")),
        ("IDOR-2  未登录访问 /practice/stages", 401,
         lambda: anon.get("/practice/stages")),
        ("IDOR-3  B 读 A 单 journey", 403,
         lambda: client.get(f"/practice/orders/{a_order}/journey", headers=hdr_b)),
        ("IDOR-4  B 读 A 单详情", 403,
         lambda: client.get(f"/practice/orders/{a_order}", headers=hdr_b)),
        ("IDOR-5  B 读 A 单 gates", 403,
         lambda: client.get(f"/practice/orders/{a_order}/gates", headers=hdr_b)),
        ("IDOR-6  B 读 A 单交付物列表", 403,
         lambda: client.get(f"/practice/orders/{a_order}/deliverables", headers=hdr_b)),
        ("IDOR-7  B 提交 A 单交付物", 403,
         lambda: client.post(f"/practice/orders/{a_order}/deliverables/resource_quote",
                             headers=hdr_b, json={"values": values_ok, "file_ids": [],
                                                  "targets": []})),
        ("IDOR-8  B 导出 A 单 PDF", 403,
         lambda: client.post(
             f"/practice/orders/{a_order}/deliverables/requirement_sheet/export.pdf",
             headers=hdr_b, json={"values": {}})),
        ("IDOR-9  B 下载 A 单附件", 403,
         lambda: client.get(f"/deliverables/files/{fid}", headers=hdr_b)),
        ("IDOR-10 B 上传到 A 单", 403,
         lambda: client.post("/deliverables/files", headers=hdr_b,
                             json={"filename": "x.txt", "data_b64": "aGk=", "order_id": a_order})),
        ("IDOR-11 B 读 A 单方案", 403,
         lambda: client.get(f"/practice/orders/{a_order}/plans", headers=hdr_b)),
        ("IDOR-12 B 改 A 单方案", 403,
         lambda: client.put(f"/practice/orders/{a_order}/plans/{plan_id}", headers=hdr_b,
                            json={"values": {"title": "x"}, "note": ""})),
        ("IDOR-13 B 发 A 单方案", 403,
         lambda: client.post(f"/practice/orders/{a_order}/plans/{plan_id}/send", headers=hdr_b,
                             json={"targets": []})),
        ("IDOR-14 B 抢 A 单", 403,
         lambda: client.post(f"/practice/orders/{a_order}/grab", headers=hdr_b)),
        ("IDOR-15 B 登记 A 单动作", 403,
         lambda: client.post(f"/practice/orders/{a_order}/actions", headers=hdr_b,
                             json={"action": "resources_locked"})),
        ("IDOR-16 B 删 A 的模板", 403,
         lambda: client.delete(f"/practice/doc-templates/{tpl_id}", headers=hdr_b)),
        ("IDOR-17 B 冒用 A 的 user_id 存模板", 403,
         lambda: client.post("/practice/doc-templates", headers=hdr_b,
                             json={"name": "冒用", "sections": [], "kind": "plan",
                                   "user_id": uid_a})),
        ("IDOR-18 B 冒用 A 的 user_id 生成派单", 403,
         lambda: client.post("/practice/dispatch/generate", headers=hdr_b,
                             json={"user_id": uid_a, "count": 1})),
        ("IDOR-19 不存在的订单 journey → 404", 404,
         lambda: client.get("/practice/orders/9999999999999999/journey", headers=hdr_a)),
        ("IDOR-20 B 的 plan_id 配 A 的 order_id → 404", 404,
         lambda: client.put(f"/practice/orders/{a_order}/plans/{b_plan_id}", headers=hdr_a,
                            json={"values": {"title": "x"}, "note": ""})),
        ("IDOR-21 上传不带 order_id → 400", 400,
         lambda: client.post("/deliverables/files", headers=hdr_a,
                             json={"filename": "y.txt", "data_b64": "aGk="})),
        ("IDOR-22 未登录下载附件 → 401", 401,
         lambda: anon.get(f"/deliverables/files/{fid}")),
    ]
    matrix = []
    for label, want, call in a_calls:
        try:
            resp = call()
            got = resp.status_code
        except Exception as exc:
            got = f"EXC {type(exc).__name__}: {exc}"
        ok = got == want
        matrix.append({"case": label, "expected": want, "actual": got, "ok": ok})
        check(label.split()[0], label, ok, f"expect={want} actual={got}")

    own_ok = client.get(f"/deliverables/files/{fid}", headers=hdr_a)
    check("IDOR-23", "A 下载自己的附件 → 200", own_ok.status_code == 200,
          f"status={own_ok.status_code}")
    extra_tpl = client.post("/practice/doc-templates", headers=hdr_a,
                            json={"name": "未自报模板", "sections": [], "kind": "plan",
                                  "user_id": ""})
    check("IDOR-24", "user_id 为空 = 未自报，不算冒用 → 200",
          extra_tpl.status_code == 200, f"status={extra_tpl.status_code}")

    # 账号隔离：订单列表只返回自己的单
    mine = client.get("/practice/orders", headers=hdr_a).json()
    foreign = [o["order_id"] for o in mine if o.get("user_id") not in (None, uid_a)]
    check("ISO-1", "/practice/orders 只返回当前登录用户的单", not foreign, f"越界={foreign}")

    # seed() 只能给单一 demo 账号：对第二个账号调用不得改走别人的演示单
    ctx.practice.seed("u-demo")                   # 先按 Lead 的启动期约定给 demo 账号播种
    before = {o["order_id"]: o["user_id"] for o in ctx.store.orders()}
    ctx.practice.seed(uid_a)                      # 模拟 identity 侧误用
    after = {o["order_id"]: o["user_id"] for o in ctx.store.orders()}
    stolen = [oid for oid, owner in before.items() if after.get(oid) != owner]
    check("SEED-1", "对第二个账号调 seed() 不改走别人的演示单（多账号隔离）",
          not stolen and any(owner == "u-demo" for owner in before.values()),
          f"被改归属={stolen} seed 前 u-demo 单数="
          f"{sum(1 for v in before.values() if v == 'u-demo')}")
    demo_left = {oid for oid, owner in after.items() if owner == "u-demo"}
    demo_before = {oid for oid, owner in before.items() if owner == "u-demo"}
    check("SEED-2", "u-demo 演示单仍全部属于 u-demo", demo_left == demo_before,
          f"before={len(demo_before)} after={len(demo_left)}")

    gen = client.post("/practice/dispatch/generate", headers=hdr_a,
                      json={"user_id": "", "count": 1})
    gen_body = gen.json() if gen.status_code == 200 else {}
    created = gen_body.get("created") or []
    new_oid = (created[0] or {}).get("order_id") if created else ""
    check("SEED-3", "新用户初始订单走 /practice/dispatch/generate（唯一 order_id）",
          gen.status_code == 200 and bool(new_oid)
          and ctx.store.order(new_oid).get("user_id") == uid_a
          and new_oid not in before,
          f"status={gen.status_code} new_order={new_oid}")

    # ---------------- 8. R08：客户人设公开投影 + 越界字段自检 ----------------
    detail = client.get(f"/practice/orders/{a_order}", headers=hdr_a)
    dbody = detail.json() if detail.status_code == 200 else {}
    persona = dbody.get("persona") or {}
    expect_public = {"name", "nationality", "age", "gender", "language", "docs"}
    check("R08-1", "订单详情 persona 只出公开白名单字段",
          detail.status_code == 200 and set(persona.keys()) == expect_public,
          f"status={detail.status_code} keys={sorted(persona.keys())}")
    from tripcraft.api.public_dto import FORBIDDEN_KEYS, public_customer_from_facts
    from tripcraft.services.customer_order_facts import facts_for_order_id
    leak = _scan_forbidden(dbody, FORBIDDEN_KEYS)
    check("R08-2", "订单详情整份响应无隐藏人设/答案/提示词/成本底牌/密钥字段",
          not leak, f"命中={leak}")
    check("R08-3", "persona 与 conversation 的 public_dto 投影逐字段一致",
          persona == public_customer_from_facts(facts_for_order_id(ctx.store, a_order)),
          "public_customer_from_facts 对比")
    brief = client.get("/practice/dispatch/brief", headers=hdr_a)
    bbody = brief.json() if brief.status_code == 200 else {}
    check("R08-4", "派单简报不再下发内部身份 user_id",
          brief.status_code == 200 and "user_id" not in bbody,
          f"status={brief.status_code} keys_has_user_id={'user_id' in bbody}")
    EXTRA["r08"] = {"persona_keys": sorted(persona.keys()), "forbidden_hits": leak}

    EXTRA["idor_matrix"] = matrix
    EXTRA["orders"] = {"user_a": uid_a, "user_b": uid_b, "a_orders": a_orders,
                       "b_order": b_order}

    # ---------------- 汇总 ----------------
    failed = [r for r in RESULTS if not r["ok"]]
    summary = {"total": len(RESULTS), "passed": len(RESULTS) - len(failed),
               "failed": len(failed), "results": RESULTS, "evidence": EXTRA}
    out = OUT_DIR / "api-check.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log = OUT_DIR / "api-check.log"
    log.write_text("\n".join(
        f"{'PASS' if r['ok'] else 'FAIL'}\t{r['id']}\t{r['name']}\t{r['detail']}"
        for r in RESULTS) + f"\n\n{summary['passed']}/{summary['total']} passed\n",
        encoding="utf-8")
    print(f"\n=== journey API check: {summary['passed']}/{summary['total']} passed ===")
    if failed:
        for f in failed:
            print(f"FAILED: {f['id']} {f['name']} · {f['detail']}")
    print(f"evidence -> {out}")
    print(f"log      -> {log}")
    print(f"db       -> {_DB}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
