"""成本 · 损失 · 结算台账 离线测试（不联网）。

对应 PRD 6.2 / 28.24：C5（成本核算、毛利测算、结算对账）与 C6.7（成本记录闭环）
必须在系统里有真实的账可核对，而不是学员在交付物里填多少就是多少。
"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.director_service import DirectorService
from tripcraft.services.finance_service import (INSURANCE_PER_PERSON, RECOURSE_RATIO,
                                                FinanceService)
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.storage import Store

O4 = "9000000000000004"      # 浙江 · 阶段 4（含 5 天 / 2 人默认口径）
O2 = "9000000000000002"      # 云南 · 阶段 2


def make():
    path = os.path.join(tempfile.gettempdir(), f"fin_{uuid4().hex}.sqlite")
    store = Store(path)
    practice = PracticeService(store)
    practice.seed("u-demo")
    sup = SupplierService(store, practice=practice)
    # D-059：事件只落在真实存在的会话里——先把这一单要用的联系人加上
    for kind in ("地接社", "酒店", "车队", "导游", "司机"):
        try:
            sup.add_contact(O4, kind)
        except ValueError:
            pass
    try:
        sup.add_contact(O2, "客户")
    except ValueError:
        pass
    return store, practice, FinanceService(store, practice=practice), sup


def test_baseline_cost_prefers_supplier_package():
    store, _, fin, sup = make()
    sup.ask(O4, "地接社", "什么价？")
    sup.ask(O4, "酒店", "什么价？")
    base = fin.baseline_cost(O4)
    assert base["source"] == "地接社组合报价"          # 酒店报价不重复计入
    names = [i["name"] for i in base["items"]]
    assert not any(n == "住宿" for n in names)
    assert any("保险" in n for n in names)             # 保险必选
    ins = [i for i in base["items"] if "保险" in i["name"]][0]
    assert ins["amount"] == INSURANCE_PER_PERSON * base["people"]


def test_incident_writes_cost_entry():
    store, practice, fin, sup = make()
    director = DirectorService(store, practice=practice, llm=None)
    fired = director.emit(O4, "pre_trip")              # 车辆故障 → 换车费 400（写死）
    assert fired["injected"]["code"] == "INC-VEHICLE-BREAKDOWN"
    entries = fin.entries(O4)
    assert len(entries) == 1
    e = entries[0]
    assert e["label"] == "临时换车费" and e["amount"] == 400
    assert e["supplier_kind"] == "车队" and e["status"] == "待处理"


def test_unhandled_loss_defaults_to_us():
    store, practice, fin, _ = make()
    store.save_deliverable(O4, "分项报价", {"total": 12000, "cost": 9000}, "rendered",
                           ["客户"], {}, [])
    DirectorService(store, practice=practice, llm=None).emit(O4, "pre_trip")
    s = fin.summary(O4)
    assert s["loss"] == 400                            # 没定责 = 自己吃下
    assert s["profit"] == round(12000 - s["cost"] - 400, 2)
    assert s["pending"] == 1


def test_recourse_ratio_is_hardcoded():
    store, practice, fin, _ = make()
    director = DirectorService(store, practice=practice, llm=None)
    director.emit(O4, "pre_trip")                      # 车队 400
    e = fin.entries(O4)[0]
    out = fin.decide(O4, e["entry_id"], "资源方")
    assert out["entry"]["ours"] == 0                   # 车队 100% 承担
    assert "我们认" in out["message"]
    assert RECOURSE_RATIO["车队"] == 1.0
    s = fin.summary(O4)
    assert s["loss"] == 0 and s["pending"] == 0


def test_decide_leaves_evidence_for_review():
    """定责动作必须留痕：复盘/评分要能看到学员把损失谈给了谁。"""
    store, practice, fin, _ = make()
    DirectorService(store, practice=practice, llm=None).emit(O4, "pre_trip")   # 车队 400
    e = fin.entries(O4)[0]
    fin.decide(O4, e["entry_id"], "资源方")
    ev = [x for x in store.evidence(O4) if x["kind"] == "定责"]
    assert ev and "临时换车费" in ev[-1]["text"] and "资源方" in ev[-1]["text"]
    # 定责证据不落 13 步的某一步（不制造覆盖率），但必须进评分材料
    assert ev[-1]["step"] == ""
    assert "临时换车费" in practice._render_evidence(O4)


def test_customer_transfer_rejected_after_contract():
    store, practice, fin, _ = make()
    # 手工记一笔可转嫁的涨价（模拟机票涨价，发生在合同确认之后）
    e = fin.add_entry(O4, "COST-TICKET-HIKE", "机票涨价差额", 660, category="loss",
                      supplier_kind="票务", transferable=True)
    out = fin.decide(O4, e["entry_id"], "客户")
    assert out["entry"]["ours"] == 660                 # 阶段 4 > 3：客户不认
    assert "客户不认" in out["message"]


def test_customer_transfer_allowed_before_contract():
    store, practice, fin, _ = make()
    e = fin.add_entry(O2, "COST-TICKET-HIKE", "机票涨价差额", 440, category="loss",
                      supplier_kind="票务", transferable=True)
    out = fin.decide(O2, e["entry_id"], "客户")
    assert out["entry"]["ours"] == 0                   # 阶段 2，可转嫁
    assert "客户接受" in out["message"]


def test_ticket_price_hike_cannot_be_recoursed():
    store, practice, fin, _ = make()
    e = fin.add_entry(O4, "COST-TICKET-HIKE", "机票涨价差额", 440, category="loss",
                      supplier_kind="票务", transferable=True)
    out = fin.decide(O4, e["entry_id"], "资源方")
    assert out["entry"]["ours"] == 440                 # 票务 0%：航司调价不可追偿
    assert RECOURSE_RATIO["票务"] == 0.0


def test_chat_attribution_and_settlement_evidence():
    store, practice, fin, _ = make()
    store.save_deliverable(O4, "分项报价", {"total": 12000, "cost": 9000}, "rendered",
                           ["客户"], {}, [])
    DirectorService(store, practice=practice, llm=None).emit(O4, "pre_trip")
    out = fin.maybe_attribute_from_chat(O4, "车队", "这次换车 400 你们承担一下吧")
    assert out and out["entry"]["bearer"] == "资源方"
    # 学员自己在群里说「我们自己承担」→ 记我方
    e = fin.add_entry(O4, "COST-EXTRA", "临时加点费用", 200, category="loss",
                      supplier_kind="地接社", transferable=True)
    out2 = fin.maybe_attribute_from_chat(O4, "地接社", "这笔我们自己承担")
    assert out2["entry"]["bearer"] == "我方" and out2["entry"]["ours"] == 200

    res = fin.settle(O4)
    assert res["evidence_id"]
    assert store.settlement(O4)["grade"] in ("优秀", "达标", "偏低", "亏损")
    ev = [x for x in store.evidence(O4) if x["kind"] == "结算"]
    assert ev and ev[-1]["step"] == "S11" and "实际毛利" in ev[-1]["text"]
    # 评分参照里必须能看到账目（否则 C5.7/C5.8 只能靠猜）
    ref = practice.scoring_reference(O4)
    assert "资源口径成本" in ref and "实际毛利" in ref


def test_declared_profit_gap_is_visible():
    store, practice, fin, _ = make()
    store.save_deliverable(O4, "分项报价", {"total": 12000, "cost": 5000}, "rendered",
                           ["客户"], {}, [])
    store.save_deliverable(O4, "回访与复盘记录", {"profit": 5000}, "rendered",
                           ["内部"], {}, [])
    s = fin.summary(O4)
    gaps = {g["name"]: g for g in s["gaps"]}
    assert "自报成本 vs 资源口径" in gaps and "自报利润 vs 实际毛利" in gaps
    assert gaps["自报利润 vs 实际毛利"]["declared"] == 5000
    assert gaps["自报利润 vs 实际毛利"]["actual"] == s["profit"]


def test_grade_before_quotation_is_not_loss():
    store, practice, fin, _ = make()
    s = fin.summary(O4)
    assert s["revenue"] == 0 and s["grade"] == "未报价"
