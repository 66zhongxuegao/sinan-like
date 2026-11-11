"""客户报价输出泄露内部成本/毛利 + PDF 表格可读性 —— 针对性回归（可重跑）。

复现的缺陷（来源：output/acceptance/evidence/standard-case/27-S26.json + pdf/quotation.pdf）：
  1. 《分项报价单》渲染把 `成本 10850 元`、`报价毛利 1840 元（14.5%）` 与「分项汇总（供核对）」
     一起给了客户（预览 / PDF / 客户聊天卡片 / 客户 Agent 反馈上下文）；
  2. PDF 里管道表格被当普通段落，输出成 `| 项目 | 说明 | … |` 原始文本。

本脚本用真实 app（真路由 + 真认证 + 独立库）走真实 HTTP，逐条断言「客户输出无内部信息」与
「内部核算仍然有效」，并落盘证据到 output/acceptance/output-audit-20261017/journey/。
模型客户端在脚本内显式摘除（离线确定性），客户 Agent 反馈上下文用包装器直接捕获。

用法：python scripts/journey_quotation_leak_check.py
退出码 0 = 全通过。
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = ROOT / "output" / "acceptance" / "output-audit-20261017" / "journey"
OUT.mkdir(parents=True, exist_ok=True)
_TMP = ROOT / "output" / "journey" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_DB = _TMP / "journey-leak-check.sqlite"
for _stale in (_DB, Path(str(_DB) + "-wal"), Path(str(_DB) + "-shm")):
    try:
        _stale.unlink(missing_ok=True)
    except OSError:
        pass
os.environ["TRIPCRAFT_DB"] = str(_DB)
os.environ["TRIPCRAFT_VISIT_LOG_DIR"] = str(_TMP / "logs-leak")

from fastapi.testclient import TestClient          # noqa: E402
from tripcraft.api.app import create_app           # noqa: E402

RESULTS: list[dict] = []
INTERNAL_TERMS = ("成本", "毛利", "利润", "采购价", "底价", "返点", "净赚")

# 与标准案例 27-S26.json 完全一致的报价内容（freeform 里那句内部毛利就是审计发现的问题原文）
QUOTE = {
    "people": "3 大 1 小",
    "dates": "2026-11-16 至 2026-11-20，5 天 4 晚",
    "items": [
        {"name": "用车", "desc": "7 座商务含司机与油费 5 天", "qty": 5, "price": 950, "amount": 4750},
        {"name": "住宿", "desc": "四星双床 2 间 × 4 晚（含早）", "qty": 8, "price": 540, "amount": 4320},
        {"name": "导游", "desc": "普通话导游 5 天（慢节奏）", "qty": 5, "price": 560, "amount": 2800},
        {"name": "门票", "desc": "首道门票 4 人", "qty": 4, "price": 145, "amount": 580},
        {"name": "保险", "desc": "旅游意外险 30 万 4 人", "qty": 4, "price": 60, "amount": 240},
    ],
    "total": 12690, "per_person": 3173, "cost": 10850,
    "insurance": "旅游意外险 30 万，60 元/人，共 4 人",
    "pending": "动车票需 48 小时内锁定；旺季酒店涨价需按实结算（预留 5% 空间）",
    "fx": "港币 1:0.92 参考；客户刷卡用卡，按出行前一日汇率结算，手续费我方承担",
    "note": "报价有效 48 小时；不含昆明往返大交通与个人消费",
    "freeform": "报价毛利 1840 元（14.5%），已为旺季房差与动车一等座差价留出空间。",
}
ITIN = {
    "title": "云南 5 日亲子行程（长辈同行版）", "dates": "2026-11-16 至 2026-11-20",
    "people": "3 大 1 小",
    "days": [
        {"day": "D1", "time": "14:00", "transport": "专车 50 分", "spot": "滇池·海埂大坝",
         "meal": "晚 云南菜（不辣）", "hotel": "昆明滇池四星·电梯双床", "guide": "导游·周"},
        {"day": "D2", "time": "09:30", "transport": "动车 2 小时 + 专车 30 分", "spot": "大理古城·洱海生态廊道",
         "meal": "午 白族菜", "hotel": "大理洱海边四星", "guide": "导游·周"},
    ],
}


def check(cid: str, name: str, ok: bool, detail: object = "") -> bool:
    RESULTS.append({"id": cid, "name": name, "ok": bool(ok), "detail": str(detail)})
    print(f"{'PASS' if ok else 'FAIL'}  {cid}  {name}" + (f"  ·  {detail}" if detail else ""))
    return bool(ok)


def pdf_text(blob: bytes) -> tuple[int, str]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob))
    return len(reader.pages), "\n".join((p.extract_text() or "") for p in reader.pages)


def hits(text: str, terms=INTERNAL_TERMS) -> list[str]:
    return [t for t in terms if t in text]


def main() -> int:
    app = create_app()
    ctx = app.state.ctx
    # 离线确定性：本脚本不验收模型层，只验收「什么内容可以进客户上下文」
    from tripcraft.agents.llm import LLMError
    for attr in ("guard", "tools", "director", "call_svc", "supplier_svc"):
        svc = getattr(ctx, attr, None)
        if svc is not None:
            try:
                svc._llm = None
            except Exception:
                pass

    def _offline_llm():
        raise LLMError("journey-leak-check offline")

    ctx.get_llm = _offline_llm
    ctx.llm_holder["client"] = None
    # 捕获客户 Agent 拿到的上下文（不改行为，只记录实参）
    captured: list[str] = []
    if ctx.tools is not None:
        original = ctx.tools.deliverable_feedback

        def spy(*args, **kwargs):
            captured.append(str(args[1] if len(args) > 1 else kwargs.get("content", "")))
            try:
                return original(*args, **kwargs)
            except Exception:
                return {"reply": "", "sentiment": "", "asks": []}

        ctx.tools.deliverable_feedback = spy

    client = TestClient(app)
    username = f"jleak_{int(time.time()) % 1000000}"
    client.post("/auth/register", json={"username": username, "password": "Test1234!",
                                       "display_name": username})
    lr = client.post("/auth/login", json={"username": username, "password": "Test1234!"})
    hdr = {"Authorization": "Bearer " + (lr.json() or {}).get("token", "")}
    uid = (lr.json() or {}).get("user_id", "")

    oid = "9400000000000001"
    ctx.store.upsert_order(oid, uid, "黄先生", "云南", "正常", 1,
                           payload={"source_market": "香港", "language": "中文",
                                    "created_at": "2026-10-17 00:00:00"})
    # 一个客户单聊会话：让交付物真的投进「客户」这个对象（否则不会走客户卡片/反馈分支）
    cust_sid = f"im-{oid}-cust"
    ctx.store.upsert_session(cust_sid, uid, "客户 黄先生", "客户", ["我", "黄先生"],
                             order_id=oid, code="dm")

    # ---------------- 1. 预览＝客户输出 ----------------
    prev = client.post(f"/practice/orders/{oid}/deliverables/quotation/preview",
                       headers=hdr, json={"values": QUOTE})
    pv = prev.json() if prev.status_code == 200 else {}
    pv_text = pv.get("rendered", "")
    internal_text = pv.get("internal_rendered", "")
    check("PREVIEW-1", "预览返回客户版与内部版两份", bool(pv_text) and bool(internal_text),
          f"customer_len={len(pv_text)} internal_len={len(internal_text)}")
    check("PREVIEW-2", "客户预览不含 成本/毛利 等内部口径", not hits(pv_text), str(hits(pv_text)))
    check("PREVIEW-3", "客户预览不含「分项汇总（供核对）」内部核算块",
          "分项汇总" not in pv_text, "分项汇总" in pv_text)
    check("PREVIEW-4", "客户预览不含「（内部）」字样的内部字段标签",
          "（内部）" not in pv_text and "成本" not in pv_text)
    check("PREVIEW-5", "客户预览仍含客户该看到的分项与合计",
          all(k in pv_text for k in ("用车", "住宿", "门票", "12690")),
          "items/total present")
    check("PREVIEW-6", "内部档案仍保留成本与核算汇总（内部校验/评分素材未丢）",
          "成本" in internal_text and "分项汇总" in internal_text and "10850" in internal_text,
          f"internal_has_cost={'成本' in internal_text}")
    check("PREVIEW-7", "被剔除的内部口径词回传（学员知情）",
          "毛利" in (pv.get("customer_withheld") or []),
          f"withheld={pv.get('customer_withheld')}（成本是内部字段，结构上整段不下发）")

    # ---------------- 2. 提交：客户卡片 + 客户 Agent 上下文 ----------------
    sub = client.post(f"/practice/orders/{oid}/deliverables/quotation",
                      headers=hdr, json={"values": QUOTE, "file_ids": [], "targets": [cust_sid]})
    sb = sub.json() if sub.status_code == 200 else {}
    check("SUBMIT-1", "真实提交成功并给出回执", sub.status_code == 200 and sb.get("delivered") is True,
          f"status={sub.status_code} delivered={sb.get('delivered')}")
    check("SUBMIT-2", "回执标注了被客户版剔除的内部口径",
          bool(sb.get("customer_withheld")), str(sb.get("customer_withheld")))
    card = [m for m in ctx.store.im_messages(cust_sid) if m.get("kind") == "card"]
    excerpt = ""
    if card:
        raw_payload = card[-1].get("payload")
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
        excerpt = payload.get("excerpt", "") if isinstance(payload, dict) else ""
    check("CARD-1", "客户会话里落下交付物卡片", bool(card), f"cards={len(card)}")
    check("CARD-2", "客户卡片摘要不含内部成本/毛利", not hits(excerpt), str(hits(excerpt)))
    captured_text = captured[-1] if captured else ""
    check("CTX-1", "客户 Agent 反馈上下文被真实捕获", bool(captured_text),
          f"captured={len(captured)}")
    check("CTX-2", "客户 Agent 上下文不含内部成本/毛利", not hits(captured_text),
          str(hits(captured_text)))
    check("CTX-3", "客户 Agent 上下文含客户该看到的合计", "12690" in captured_text)

    # ---------------- 3. 内部核算仍然有效 ----------------
    row = ctx.store.deliverable(oid, "分项报价") or {}
    stored = row.get("rendered", "")
    check("INTERNAL-1", "落库的内部档案仍含成本与核算汇总（评分/财务可用）",
          "成本" in stored and "10850" in stored and "分项汇总" in stored,
          f"len={len(stored)}")
    ev = [e for e in ctx.store.evidence(oid) if (e.get("ref") or "") == "doc:分项报价"]
    check("INTERNAL-2", "评分证据链仍引用内部档案（含成本）",
          bool(ev) and "成本" in (ev[-1].get("text") or ""), f"evidence={len(ev)}")
    bad = dict(QUOTE)
    bad["total"] = 9999
    blk = client.post(f"/practice/orders/{oid}/deliverables/quotation",
                      headers=hdr, json={"values": bad, "file_ids": [], "targets": []})
    bb = blk.json() if blk.status_code == 200 else {}
    check("INTERNAL-3", "算术拦截仍然生效（内部校验未因脱敏而失效）",
          blk.status_code == 200 and bb.get("blocked") is True,
          f"blocked={bb.get('blocked')}")

    # ---------------- 4. PDF：客户版内容 + 真实表格 ----------------
    pdf = client.post(f"/practice/orders/{oid}/deliverables/quotation/export.pdf",
                      headers=hdr, json={"values": QUOTE})
    blob = pdf.content if pdf.status_code == 200 else b""
    pages, text = pdf_text(blob) if blob.startswith(b"%PDF") else (0, "")
    (OUT / "quotation-customer.pdf").write_bytes(blob)
    check("PDF-1", "报价 PDF 导出成功且可解析", pdf.status_code == 200 and pages >= 1,
          f"status={pdf.status_code} bytes={len(blob)} pages={pages}")
    check("PDF-2", "报价 PDF 不含内部成本/毛利", not hits(text), str(hits(text)))
    check("PDF-3", "报价 PDF 不含「分项汇总（供核对）」", "分项汇总" not in text)
    check("PDF-4", "报价 PDF 不再出现 Markdown 管道文本（| … |）",
          "|" not in text, f"pipes={text.count('|')}")
    check("PDF-5", "报价 PDF 表格内容完整（分项名与金额都在）",
          all(k in text for k in ("用车", "住宿", "导游", "门票", "保险", "4750", "12690")),
          "rows present")
    ipdf = client.post(f"/practice/orders/{oid}/deliverables/itinerary/export.pdf",
                       headers=hdr, json={"values": ITIN})
    ib = ipdf.content if ipdf.status_code == 200 else b""
    ipages, itext = pdf_text(ib) if ib.startswith(b"%PDF") else (0, "")
    (OUT / "itinerary-customer.pdf").write_bytes(ib)
    check("PDF-6", "行程方案 PDF 同样不再出现管道文本",
          ipdf.status_code == 200 and "|" not in itext, f"pipes={itext.count('|')}")
    check("PDF-7", "行程方案 PDF 逐日表格内容完整",
          all(k in itext for k in ("D1", "D2", "滇池", "大理")), "day rows present")

    # ---------------- 5. 其他交付物：客户版与内部版一致性 ----------------
    req = client.post(f"/practice/orders/{oid}/deliverables/requirement_sheet/preview", headers=hdr,
                      json={"values": {"guest": "黄先生", "people": "3 大 1 小", "dates": "11-16 至 11-20",
                                       "must": "预算上限 18000", "budget": "人均 4500",
                                       "freeform": "内部成本 12000，毛利 800（不要外发）"}})
    rq = req.json() if req.status_code == 200 else {}
    check("OTHER-1", "需求确认单客户版同样剔除内部口径句子",
          rq.get("rendered") and not hits(rq.get("rendered", "")),
          str(hits(rq.get("rendered", ""))))
    check("OTHER-1b", "内部版仍保留该句（内部档案完整）",
          "毛利" in (rq.get("internal_rendered") or ""),
          "internal keeps it")

    # ---------------- 6. 内部/地接专用文档：保留自身核算内容（不得被通用客户化抹掉） ----------------
    settle = {
        "settle_no": "JS-20261024-03",
        "items": [{"item": "酒店", "supplier": "4320", "ours": "4320", "diff": "0", "note": "一致"},
                  {"item": "用车", "supplier": "4850", "ours": "4750", "diff": "-100",
                   "note": "地接多算 100，要求核减"},
                  {"item": "导游", "supplier": "2800", "ours": "2800", "diff": "0", "note": "一致"},
                  {"item": "门票", "supplier": "580", "ours": "580", "diff": "0", "note": "一致"},
                  {"item": "保险", "supplier": "240", "ours": "240", "diff": "0", "note": "一致"}],
        "total_settle": "12790", "total_ours": "12690", "diff": "-100",
        "actual_cost": "10850", "actual_margin": "1840",
        "reason": "地接把油费算成两天，实际只有一天；另外旺季房差 100 由我方承担",
        "decision": "据实结算，要求核减 100",
        "freeform": "本单毛利 1840 元，比目标低 3 个点，下次报价要把旺季房差算进去。",
    }
    sprev = client.post(f"/practice/orders/{oid}/deliverables/settlement/preview",
                        headers=hdr, json={"values": settle})
    sp = sprev.json() if sprev.status_code == 200 else {}
    stext = sp.get("rendered", "")
    check("INTERNAL-DOC-1", "地接结算核对单预览标注为内部文档（不假装是客户版）",
          sp.get("customer_facing") is False, f"customer_facing={sp.get('customer_facing')}")
    check("INTERNAL-DOC-2", "内部结算文档预览保留实际成本/实际毛利与差异原因",
          all(k in stext for k in ("实际成本", "10850", "实际毛利", "1840", "核减")),
          f"len={len(stext)}")
    check("INTERNAL-DOC-3", "内部结算文档不做客户脱敏（withheld 为空）",
          not (sp.get("customer_withheld") or []), str(sp.get("customer_withheld")))
    spdf = client.post(f"/practice/orders/{oid}/deliverables/settlement/export.pdf",
                       headers=hdr, json={"values": settle})
    sb2 = spdf.content if spdf.status_code == 200 else b""
    _, stext_pdf = pdf_text(sb2) if sb2.startswith(b"%PDF") else (0, "")
    (OUT / "settlement-internal.pdf").write_bytes(sb2)
    check("INTERNAL-DOC-4", "内部结算 PDF 保留自身核算内容",
          all(k in stext_pdf for k in ("实际成本", "10850", "实际毛利")),
          f"bytes={len(sb2)}")
    hub = ctx.supplier_svc.ensure_hub(uid)["session_id"]
    # 捕获实际投递内容（卡片正文用的是完整渲染文本，展示时才截断）
    posted: list[tuple[str, str]] = []
    deliv = ctx.get_deliverables()
    original_post = deliv._post_card

    def spy_post(sid, spec, rendered, files, target):
        posted.append((sid, rendered))
        return original_post(sid, spec, rendered, files, target)

    deliv._post_card = spy_post
    ssub = client.post(f"/practice/orders/{oid}/deliverables/settlement",
                       headers=hdr, json={"values": settle, "file_ids": [], "targets": [hub]})
    hub_text = next((t for sid, t in reversed(posted) if sid == hub), "")
    check("INTERNAL-DOC-5", "投给地接的结算文档正文保留核算内容（实际投递内容）",
          ssub.status_code == 200 and "实际成本" in hub_text and "10850" in hub_text,
          f"status={ssub.status_code} routed_len={len(hub_text)} "
          f"has_cost={'实际成本' in hub_text}")
    # 同文档显式发给客户：保守起见客户那一侧仍必须拿到安全版
    s2 = client.post(f"/practice/orders/{oid}/deliverables/settlement",
                     headers=hdr, json={"values": settle, "file_ids": [], "targets": [cust_sid]})
    cust_text = next((t for sid, t in reversed(posted) if sid == cust_sid), "")
    check("INTERNAL-DOC-6", "同一文档显式发给客户时，客户拿到的是安全版",
          s2.status_code == 200 and cust_text and not hits(cust_text),
          f"status={s2.status_code} routed_len={len(cust_text)} hits={hits(cust_text)}")

    # ---------------- 7. 正式 PDF 不留「已隐藏」这类开发痕迹 ----------------
    trace_terms = ("已从客户版本中隐藏", "本段涉及内部核算", "（略）", "[hidden]")
    all_pdfs = list(OUT.glob("*.pdf"))
    bad_trace: list[str] = []
    for p in all_pdfs:
        try:
            _, t = pdf_text(p.read_bytes())
        except Exception:
            continue
        bad_trace += [f"{p.name}:{k}" for k in trace_terms if k in t]
    check("TRACE-1", "客户版 PDF 中无「已隐藏」等开发痕迹",
          not bad_trace, str(bad_trace))
    check("TRACE-2", "学员仍能从接口拿到被剔除的词（知情不丢）",
          "毛利" in (pv.get("customer_withheld") or []) and "毛利" in (sb.get("customer_withheld") or []),
          f"preview={pv.get('customer_withheld')} submit={sb.get('customer_withheld')}")

    # ---------------- 8. 真实标准案例数据（scenario 的 standard_case.json，只读） ----------------
    std_path = ROOT / "data" / "scenario" / "standard_case.json"
    if std_path.exists():
        try:
            std = json.loads(std_path.read_text(encoding="utf-8"))
            docs = (std.get("cases") or [{}])[0].get("documents") or {}
            from tripcraft.contracts.deliverables_spec import (is_customer_facing, render,
                                                               render_for_customer, resolve)
            std_ctx = {"order_id": oid, "customer": "黄先生", "destination": "云南",
                       "source_market": "香港", "language": "中文"}
            q = docs.get("quotation") or {}
            if q:
                qc, qw = render_for_customer(resolve("quotation"), q, std_ctx)
                qi = render(resolve("quotation"), q, std_ctx)
                check("STD-1", "标准案例报价：客户版无内部成本/毛利（即使模板把内部口径写在 freeform）",
                      not hits(qc), str(hits(qc)))
                check("STD-2", "标准案例报价：客户版仍含分项与合计",
                      all(k in qc for k in ("用车", "住宿", "12690")), "items/total present")
                check("STD-3", "标准案例报价：内部档案保留成本与核算（评分/拦截可用）",
                      "成本" in qi and "10850" in qi, f"internal_len={len(qi)}")
            for code in ("settlement", "review"):
                v = docs.get(code) or {}
                if not v:
                    continue
                spec = resolve(code)
                own = render(spec, v, std_ctx)
                check(f"STD-{code}", f"标准案例 {spec.title}：内部/地接文档自身内容保留成本/毛利",
                      ("成本" in own or "实际成本" in own) and is_customer_facing(spec) is False,
                      f"customer_facing={is_customer_facing(spec)} len={len(own)}")
        except Exception as exc:
            check("STD-ERR", "标准案例数据读取", False, f"{type(exc).__name__}: {exc}")

    failed = [r for r in RESULTS if not r["ok"]]
    summary = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db": str(_DB), "total": len(RESULTS), "passed": len(RESULTS) - len(failed),
        "failed": len(failed), "results": RESULTS,
        "source_defect": "output/acceptance/evidence/standard-case/27-S26.json"
                         + " + pdf/quotation.pdf（审计证据，未改动）",
        "note": "客户输出＝预览/PDF/客户卡片/客户 Agent 上下文；内部档案＝落库 rendered+证据链，"
                "两者由 render(audience) 分离。",
    }
    (OUT / "quotation-leak-check.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "quotation-leak-check.log").write_text(
        "\n".join(f"{'PASS' if r['ok'] else 'FAIL'}\t{r['id']}\t{r['name']}\t{r['detail']}"
                  for r in RESULTS) + f"\n\n{summary['passed']}/{summary['total']} passed\n",
        encoding="utf-8")
    print(f"\n=== 客户输出/内部核算分离检查: {summary['passed']}/{summary['total']} passed ===")
    for f in failed:
        print(f"FAILED: {f['id']} {f['name']} · {f['detail']}")
    print(f"evidence -> {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
