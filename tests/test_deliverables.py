"""交付物工作台测试（离线，不调用模型）。"""

import os
import re
import tempfile
from uuid import uuid4

from tripcraft.contracts.deliverables_spec import BY_CODE, DELIVERABLES, resolve, render
from tripcraft.services.deliverable_service import (DeliverableError, DeliverableService,
                                                    check_arithmetic)
from tripcraft.services.guard_service import GuardService
from tripcraft.services.practice_service import PracticeService
from tripcraft.storage import Store

ORDER = "9000000000000006"


def make(with_guard: bool = True):
    store = Store(os.path.join(tempfile.gettempdir(), f"dl_{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    practice.seed("u-demo")
    svc = DeliverableService(store=store, practice=practice,
                             guard=GuardService() if with_guard else None)
    return store, practice, svc


class FakeFeedback:
    """假的客户 Agent：把交付物内容回显一小段，便于断言路由。"""

    def deliverable_feedback(self, kind, content, customer="客户", order_id=""):
        return {"kind": kind, "customer": customer, "reply": f"收到你的{kind}",
                "sentiment": "满意", "asks": ["能不能再确认一下日期？"]}


def quote_values(total=1000, cost=900):
    return {
        "people": "3 大 1 小", "dates": "11 月 12 日–16 日，5 天",
        "items": [{"name": "导游服务费", "desc": "全程", "qty": 1, "price": 400, "amount": 400},
                  {"name": "用车", "desc": "7 座商务", "qty": 1, "price": 600, "amount": 600}],
        "total": total, "cost": cost, "insurance": "旅游意外险 30 万",
        "pending": "酒店待确认", "fx": "港元 1:0.92 锁定 48 小时",
    }


# ---------------- 契约 ----------------

def test_specs_are_well_formed():
    assert len(DELIVERABLES) == 8
    ids = [d.id for d in DELIVERABLES]
    codes = [d.code for d in DELIVERABLES]
    assert len(set(ids)) == len(ids) and len(set(codes)) == len(codes)
    for d in DELIVERABLES:
        assert re.fullmatch(r"[a-z_]+", d.code), d.code
        assert d.step.startswith("S") and d.audience and d.fields
        for f in d.fields:
            assert f.key and f.label
            if f.type == "rows":
                assert f.columns, f"{d.id}.{f.key} 缺少列定义"


def test_resolve_accepts_chinese_id_or_ascii_code():
    assert resolve("行程方案").code == "itinerary"
    assert resolve("itinerary").id == "行程方案"
    assert resolve("nope") is None
    assert set(BY_CODE) == {d.code for d in DELIVERABLES}


def test_render_produces_sections_and_quote_summary():
    spec = resolve("quotation")
    doc = render(spec, quote_values(), {"order_id": ORDER, "customer": "客户 F", "source_market": "香港"})
    assert "# 分项报价单" in doc
    assert "## 分项明细" in doc and "| 项目 |" in doc
    assert "## 分项汇总（供核对）" in doc
    assert "合计 1000 元" in doc and "成本 900 元" in doc
    assert "香港" in doc


def test_rendered_quote_passes_text_guard():
    """渲染出来的报价文档必须能被拦截网的文本校验读懂。"""
    doc = render(resolve("quotation"), quote_values(), {})
    out = GuardService().check("分项报价", doc)
    assert out["deterministic"]["errors"] == []


# ---------------- 字段级算术校验 ----------------

def test_arithmetic_catches_item_total_mismatch():
    assert any("不一致" in e for e in check_arithmetic("quotation", quote_values(total=1500)))


def test_arithmetic_catches_negative_margin_and_thin_margin():
    assert any("毛利" in e for e in check_arithmetic("quotation", quote_values(total=900, cost=900)))
    assert any("毛利率" in e for e in check_arithmetic("quotation", quote_values(total=1000, cost=970)))


def test_arithmetic_accepts_consistent_quote():
    assert check_arithmetic("quotation", quote_values()) == []


def test_arithmetic_checks_settlement_relations():
    bad = {"total_settle": 8180, "total_ours": 7930, "diff": 100, "actual_cost": 10050, "actual_margin": -2120}
    assert any("合计差异" in e for e in check_arithmetic("settlement", bad))
    good = {"total_settle": 8180, "total_ours": 7930, "diff": 250, "actual_cost": 10050, "actual_margin": -2120}
    assert check_arithmetic("settlement", good) == []
    row_bad = {"items": [{"item": "用车", "supplier": 4500, "ours": 4250, "diff": 999}]}
    assert any("逐项" in e for e in check_arithmetic("settlement", row_bad))


# ---------------- 必填校验 ----------------

def test_validate_lists_missing_required_fields():
    assert "出行日期" in DeliverableService.validate("quotation", {"people": "3 大 1 小"})
    rows_missing = DeliverableService.validate("itinerary",
                                               {"title": "x", "dates": "y", "people": "z", "days": [{}]})
    assert "逐日行程" in rows_missing
    # 逐日行程要写全六要素：只填景点不算方案（客户与评分都无从核对）
    partial = DeliverableService.validate("itinerary", {
        "title": "x", "dates": "y", "people": "z",
        "days": [{"day": "D1", "spot": "甲秀楼"}]})
    assert any("缺" in m for m in partial)


def test_unknown_deliverable_is_rejected():
    try:
        DeliverableService.validate("nope", {})
        raise AssertionError("应报错")
    except DeliverableError:
        pass


def test_specs_are_grouped_by_surface_and_allow_freeform():
    """产出分三类：平台提交 / 发给对方 / 内部记录；每份都留一段自由编辑。"""
    surfaces = {d.id: d.surface for d in DELIVERABLES}
    assert surfaces["合同与保险"] == "platform"
    assert surfaces["行程方案"] == "document"
    assert surfaces["地接结算核对单"] == "ledger"
    for d in DELIVERABLES:
        assert any(f.key == "freeform" for f in d.fields), d.id
        assert d.fields[-1].key == "freeform"


def test_targets_can_be_chosen_explicitly():
    """发在给谁由学员选：指定司导群就投到司导群，而不是默认的客户群。"""
    from tripcraft.services.supplier_service import SupplierService
    store, practice, svc = make()
    oid = "9000000000000004"          # 浙江单，已在「客户确认合同」阶段（行前）
    sup = SupplierService(store, practice=practice)
    sup.add_contact(oid, "地接社")
    hub = sup.ensure_hub("u-demo", oid)
    sup.respond(hub["session_id"], "需要导游", target_role="地接社")
    sup.add_contact(oid, "导游")
    guide = sup.group_for(oid, "guide")
    out = svc.submit(oid, "departure_notice", {
        "gather": "11 月 12 日 10:30 贵阳机场", "guide": "导游 小周 138****"},
        targets=[guide["session_id"]])
    assert [t["name"] for t in out["routing"]["targets"]] == [guide["name"]]
    msgs = store.im_messages(guide["session_id"])
    assert msgs and msgs[-1]["kind"] == "card"


# ---------------- 提交与分路 ----------------

def test_submit_blocked_by_arithmetic_does_not_record_anything():
    store, practice, svc = make()
    out = svc.submit(ORDER, "quotation", quote_values(total=1500))
    assert out["blocked"] is True
    assert out["guard"]["reasons"]
    assert store.deliverable(ORDER, "分项报价") is None, "被拦下不应存档"
    assert not store.has_action(ORDER, "deliverable:分项报价")


def test_submit_records_evidence_action_and_advances():
    store, practice, svc = make()
    _unlock_customer(store, practice, ORDER)
    out = svc.submit(ORDER, "requirement_sheet", {
        "guest": "客户 F", "people": "3 大 1 小", "dates": "11 月 12 日–16 日",
        "must": "四星、含大交通", "budget": "人均 5000-6000",
    })
    assert out["blocked"] is False and out["evidence_id"]
    assert store.has_action(ORDER, "deliverable:需求确认单")
    assert practice.get_order(ORDER)["stage_index"] == 1, "三门槛齐了应推进"
    assert store.deliverable(ORDER, "需求确认单")["version"] == 1


def test_routing_sends_to_platform_and_supplier():
    store, practice, svc = make()
    out = svc.submit(ORDER, "departure_notice", {
        "gather": "11 月 12 日 10:30 贵阳机场", "guide": "导游 小周 138****",
        "contact": "定制师 小李 137****",
    })
    # 出团通知书的发送对象是「客户 + 地接社」，平台留痕由合同类交付物负责
    assert out["routing"]["sent_to"] == ["地接社"]
    msgs = store.im_messages(out["routing"]["im_session"])
    assert msgs and "出团通知书" in msgs[-1]["content"]


def _unlock_customer(store, practice, order_id):
    """客户要首呼问到电话并加进通讯录，交付物才会进客户群（D-054）。"""
    from tripcraft.services.supplier_service import SupplierService
    practice.record_action(order_id, "grab")
    practice.record_action(order_id, "first_call")
    SupplierService(store, practice=practice).add_contact(order_id, "客户")


def test_routing_to_customer_uses_customer_agent():
    store, practice, svc = make()
    svc._tools = FakeFeedback()
    _unlock_customer(store, practice, ORDER)
    out = svc.submit(ORDER, "requirement_sheet", {
        "guest": "客户 F", "people": "3 大 1 小", "dates": "11 月 12 日",
        "must": "四星", "budget": "人均 5000-6000",
    })
    assert "客户" in out["routing"]["sent_to"]
    assert out["routing"]["customer_reply"] == "收到你的需求确认单"
    assert out["routing"]["asks"]


def test_conditional_actions_only_fire_on_expected_value():
    store, practice, svc = make()
    base = {"contract_no": "HT-1", "sign_date": "2026-11-01", "policy_no": "PL-1",
            "insure_date": "2026-11-01", "customer_signed": "待签署", "deposit_state": "未到账"}
    svc.submit(ORDER, "contract", base)
    assert store.has_action(ORDER, "contract_signed") and store.has_action(ORDER, "insurance_bought")
    assert not store.has_action(ORDER, "customer_signed_contract"), "未签署不应登记"
    assert not store.has_action(ORDER, "deposit_paid"), "未到账不应登记"

    svc.submit(ORDER, "contract", {**base, "customer_signed": "已签署", "deposit_state": "已到账"})
    assert store.has_action(ORDER, "customer_signed_contract")
    assert store.has_action(ORDER, "deposit_paid")


def test_resubmit_bumps_version():
    store, practice, svc = make()
    _unlock_customer(store, practice, ORDER)
    values = {"guest": "客户 F", "people": "3 大 1 小", "dates": "11 月 12 日",
              "must": "四星", "budget": "人均 5000-6000"}
    svc.submit(ORDER, "requirement_sheet", values)
    out = svc.submit(ORDER, "requirement_sheet", {**values, "note": "补充：有一天自由活动"})
    assert out["version"] == 2


def test_files_are_stored_and_referenced():
    store, practice, svc = make()
    store.save_file("f-1", ORDER, "行程方案", "方案.pdf", "application/pdf", 12, b"hello world!")
    row = store.file("f-1")
    assert row and row["size"] == 12 and store.file_meta(row)["filename"] == "方案.pdf"
    out = svc.submit(ORDER, "itinerary", {
        "title": "贵州 5 日", "dates": "11 月 12–16 日", "people": "3 大 1 小",
        "days": [{"day": "D1", "time": "09:00", "transport": "专车 40 分", "spot": "甲秀楼",
                  "meal": "午 黔菜", "hotel": "贵阳四星", "guide": "导游·周"},
                 {"day": "D2", "time": "08:30", "transport": "专车 2.5 时", "spot": "西江苗寨",
                  "meal": "晚 长桌宴", "hotel": "苗寨民宿", "guide": "导游·周"}],
    }, file_ids=["f-1"])
    assert out["files"] and out["files"][0]["filename"] == "方案.pdf"
    assert "方案.pdf" in out["routing"]["platform_note"] or out["files"]


def test_list_for_order_marks_submitted():
    store, practice, svc = make()
    _unlock_customer(store, practice, ORDER)
    svc.submit(ORDER, "requirement_sheet", {"guest": "客户 F", "people": "3 大 1 小",
                                            "dates": "11 月 12 日", "must": "四星",
                                            "budget": "人均 5000-6000"})
    lst = svc.list_for_order(ORDER)["deliverables"]
    assert len(lst) == 8
    done = [x for x in lst if x["submitted"]]
    assert [x["code"] for x in done] == ["requirement_sheet"]
    assert all("code" in x and "audience" in x for x in lst)

def test_platform_facing_deliverable_records_platform_submission():
    store, practice, svc = make()
    out = svc.submit(ORDER, "contract", {
        "contract_no": "HT-1", "sign_date": "2026-11-01", "policy_no": "PL-1",
        "insure_date": "2026-11-01", "customer_signed": "已签署", "deposit_state": "已到账"})
    assert "平台" in out["routing"]["sent_to"]
    assert out["routing"]["platform_note"]
    events = [e["type"] for e in store.events(ORDER)]
    assert "platform_submission" in events
