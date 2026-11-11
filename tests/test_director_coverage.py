"""覆盖校验 / 低置信度升级 / 导演总线 离线测试（mock LLM，不联网）。"""

import os
import re
import tempfile
from uuid import uuid4

from tripcraft.contracts.skill_points import SKILL_POINTS_BY_ID
from tripcraft.services.director_service import INCIDENT_RULES, DirectorService
from tripcraft.services.practice_service import PracticeService
from tripcraft.storage import Store

ORDER = "9000000000000001"


class ScoreFakeLLM:
    """按 system prompt 里出现的 Rubric ID 回分，可控制分数与置信度。"""

    def __init__(self, score: float = 82.0, confidence: float = 0.9) -> None:
        self.score = score
        self.confidence = confidence

    def chat(self, messages, **kwargs):
        return "收到，我马上处理。"

    def chat_json(self, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        ids = re.findall(r"\u3010([A-Z0-9.]+)\u3011", system)
        return {"scores": [{"skill_point_id": i, "level": "M4", "score": self.score,
                            "evidence": [{"kind": "message", "quote": "\u5b66\u5458\u539f\u8bdd"}],
                            "hit_negative": False, "comment": "\u6d4b\u8bd5\u5224\u5b9a",
                            "confidence": self.confidence} for i in ids]}


def seed_baseline(store, passed: bool = True, agreement: float = 0.94,
                  conf: float = 0.9, delta: int = 3) -> None:
    """写入一条校准基线——评分主链的准入门槛（PRD 25.7）。"""
    store.add_calibration_run("cal-test", 17, 17, agreement, 1.0, 1.0, conf, delta, passed, {})


def unlock(store, practice, order_id, *kinds):
    """事件只落在真实存在的会话里；城市资源先由地接确认本单资源池。"""
    from tripcraft.services.supplier_service import SupplierService, destination_city
    svc = SupplierService(store, practice=practice)
    resource_kinds = [k for k in kinds if k in ("酒店", "车队", "导游", "司机")]
    if "地接社" in kinds or resource_kinds:
        try:
            svc.add_contact(order_id, "地接社")
        except ValueError:
            pass
    if resource_kinds:
        DirectorService(store=store, practice=practice).materialize_resource_pool(
            order_id, "测试资源需求", resource_kinds, destination_city(store.order(order_id)), "")
    for kind in kinds:
        try:
            svc.add_contact(order_id, kind)
        except ValueError:
            pass
    return svc


def make(baseline: bool = True, baseline_passed: bool = True):
    p = os.path.join(tempfile.gettempdir(), f"dc_{uuid4().hex}.sqlite")
    store = Store(p)
    practice = PracticeService(store)
    practice.seed("u-demo")
    if baseline:
        seed_baseline(store, passed=baseline_passed)
    director = DirectorService(store=store, practice=practice, llm=None)
    return store, practice, director


def cover_everything(store, practice, order_id: str) -> list[str]:
    """把本单目标技能点全部覆盖：A 型补交付物证据，B 型补触发+反应。"""
    ids = practice.build_plan(order_id)
    for sp_id in ids:
        t = store.target(order_id, sp_id)
        if not t:
            continue
        if t["checkpoint"] == "B":
            practice.mark_trigger(order_id, sp_id, t["step"])
            practice.mark_reacted(order_id, sp_id)
        else:
            practice.record_evidence(order_id, "\u884c\u7a0b\u65b9\u6848",
                                     f"\u8986\u76d6\u7528\u4ea4\u4ed8\u7269 {sp_id}", step=t["step"], ref=f"ev-{sp_id}")
    return ids


# ---------------- 目标清单 / 覆盖校验 ----------------

def test_plan_is_stable_across_calls():
    store, practice, _ = make()
    a = practice.build_plan(ORDER)
    practice.record_evidence(ORDER, "\u884c\u7a0b\u65b9\u6848", "\u65b9\u6848\u6b63\u6587")
    b = practice.build_plan(ORDER)
    assert a == b, "\u76ee\u6807\u6e05\u5355\u5df2\u751f\u6210\u540e\u4e0d\u5e94\u56e0\u8bc1\u636e\u53d8\u5316\u800c\u6f02\u79fb"


def test_coverage_zero_without_material():
    store, practice, _ = make()
    cov = practice.coverage(ORDER)
    assert cov["targets"] > 0
    assert cov["covered"] == 0
    assert cov["passed"] is False


def test_coverage_passes_when_everything_covered():
    store, practice, _ = make()
    cover_everything(store, practice, ORDER)
    cov = practice.coverage(ORDER)
    assert cov["covered"] == cov["targets"]
    assert cov["ratio"] == 1.0 and cov["passed"] is True


def test_without_calibration_baseline_profile_is_not_written():
    """PRD 25.7 红线：未经校准集验证的评分 Agent 不得影响画像。"""
    store, practice, _ = make(baseline=False)
    cover_everything(store, practice, ORDER)
    report = practice.score_order(ORDER, ScoreFakeLLM(score=85, confidence=0.9))
    assert report["calibration"]["baseline"] is False
    assert report["calibration"]["weight"] == 0.0
    assert report["deferred"] is True and "校准" in report["deferred_reason"]
    assert report["written"] == 0
    assert not any((r.get("real_v") or 0) > 0 for r in store.abilities("u-demo").values())


def test_failed_baseline_only_allows_downgrade_writes():
    """有基线但未达标 → 降权：只允许暴露薄弱，不允许抬高画像。"""
    store, practice, _ = make(baseline=True, baseline_passed=False)
    cover_everything(store, practice, ORDER)
    ids = practice.build_plan(ORDER)

    high = practice.score_order(ORDER, ScoreFakeLLM(score=95, confidence=0.99))
    assert high["calibration"]["weight"] == 0.5
    assert high["written"] == 0, "未达标记准下不允许把画像抬高"

    low = practice.score_order(ORDER, ScoreFakeLLM(score=25, confidence=0.99))
    assert low["written"] > 0, "未达标记准下仍应允许暴露薄弱点"
    ab = store.abilities("u-demo")
    assert ab[ids[0]]["real_v"] == 25


def test_thresholds_come_from_calibration_when_available():
    store, practice, _ = make()
    th = practice.thresholds()
    assert th["source"] == "校准集标定" and th["confidence"] == 0.9 and th["boundary_delta"] == 3
    store2, practice2, _ = make(baseline=False)
    th2 = practice2.thresholds()
    assert "经验" in th2["source"]


def test_low_coverage_still_writes_assessed_profile_points():
    store, practice, _ = make()
    practice.record_evidence(ORDER, "\u884c\u7a0b\u65b9\u6848", "\u65b9\u6848\u6b63\u6587")
    report = practice.score_order(ORDER, ScoreFakeLLM(score=85, confidence=0.99))
    assert report["ok"] and report["scored"] > 0, "\u5df2\u8986\u76d6\u7684\u70b9\u5e94\u8be5\u80fd\u8bc4\u51fa\u5206"
    assert report["coverage"]["passed"] is False
    assert report["deferred"] is False
    assert report["written"] == report["scored"] > 0
    assert not report["deferred_reason"]
    written = {item["skill_point_id"] for item in report["skill_points"]}
    covered = {item["skill_point_id"] for item in practice.coverage(ORDER)["items"] if item["covered"]}
    assert written <= covered
    abilities = store.abilities("u-demo")
    assert all(abilities[sp]["real_v"] == 85 for sp in written)
    assert all(not row["real_v"] for sp, row in abilities.items() if sp not in written)


def test_full_coverage_writes_profile():
    store, practice, _ = make()
    cover_everything(store, practice, ORDER)
    report = practice.score_order(ORDER, ScoreFakeLLM(score=85, confidence=0.9))
    assert report["coverage"]["passed"] is True
    assert report["deferred"] is False
    assert report["escalated"] == []
    assert report["written"] == report["scored"] > 0
    ab = store.abilities("u-demo")
    assert all(ab[i["skill_point_id"]]["real_v"] == 85 for i in report["skill_points"])


# ---------------- 低置信度升级 ----------------

def test_low_confidence_escalates_without_writing():
    store, practice, _ = make()
    cover_everything(store, practice, ORDER)
    report = practice.score_order(ORDER, ScoreFakeLLM(score=82, confidence=0.4))
    assert report["escalated"], "\u4f4e\u7f6e\u4fe1\u5ea6\u5e94\u8f6c\u4eba\u5de5"
    assert report["written"] == 0
    pending = practice.pending_reviews(ORDER)
    assert pending and pending[0]["confidence"] == 0.4
    assert not any((r.get("real_v") or 0) > 0 for r in store.abilities("u-demo").values())


def test_boundary_score_escalates():
    store, practice, _ = make()
    cover_everything(store, practice, ORDER)
    report = practice.score_order(ORDER, ScoreFakeLLM(score=70, confidence=0.95))
    assert report["escalated"]
    assert "\u8fb9\u754c" in report["escalated"][0]["review_reason"]


def test_review_accept_and_override_write_profile():
    store, practice, _ = make()
    cover_everything(store, practice, ORDER)
    report = practice.score_order(ORDER, ScoreFakeLLM(score=70, confidence=0.95))
    sp = report["escalated"][0]["skill_point_id"]

    out = practice.review_score(ORDER, sp, "accept")
    assert out["written"] is True
    assert store.abilities("u-demo")[sp]["real_v"] == 70

    sp2 = report["escalated"][1]["skill_point_id"]
    out2 = practice.review_score(ORDER, sp2, "override", score=88)
    assert out2["written"] is True and out2["level"] == "M4"
    assert store.abilities("u-demo")[sp2]["real_v"] == 88


def test_review_reject_does_not_write():
    store, practice, _ = make()
    cover_everything(store, practice, ORDER)
    report = practice.score_order(ORDER, ScoreFakeLLM(score=70, confidence=0.95))
    sp = report["escalated"][0]["skill_point_id"]
    out = practice.review_score(ORDER, sp, "reject")
    assert out["written"] is False
    row = store.abilities("u-demo").get(sp)
    assert (row or {}).get("real_v", 0) == 0, "驳回不应写画像"


# ---------------- 导演总线 ----------------

def test_director_injects_rule_once_then_next_rule():
    store, practice, director = make()
    unlock(store, practice, ORDER, "地接社", "酒店")   # 事件要落在真实会话里
    order = dict(store.order(ORDER))
    order["stage_index"] = 2
    store.upsert_order(ORDER, "u-demo", order["customer"], order["destination"],
                       order["status"], 2, payload={"source_market": "\u9999\u6e2f"})

    first = director.emit(ORDER, "plan_sent")["injected"]
    assert first and first["skill_points"], "事件应关联到要考的技能点"
    assert first["skill_points"], "\u4e8b\u4ef6\u5e94\u5173\u8054\u5230\u8981\u8003\u7684\u6280\u80fd\u70b9"
    # 同一动作再次发生 -> 不重复注入同一条规则，而是轮到下一条
    second = director.emit(ORDER, "plan_sent")["injected"]
    assert second and second["code"] != first["code"]
    codes = [i["code"] for i in director.timeline(ORDER)["incidents"]]
    assert len(codes) == len(set(codes)), "\u540c\u4e00\u4e8b\u4ef6\u4e0d\u5e94\u91cd\u590d\u6ce8\u5165"


def test_director_stage_gate_blocks_early_injection():
    store, practice, director = make()
    store.upsert_order(ORDER, "u-demo", "\u5ba2\u6237 A", "\u6c5f\u82cf", "\u6b63\u5e38", 1,
                       payload={"source_market": "\u9999\u6e2f"})
    out = director.emit(ORDER, "resource_locked")   # 规则要求阶段 >= 5
    assert out["injected"] is None


def test_director_reaction_covers_b_skill_points():
    store, practice, director = make()
    store.upsert_order(ORDER, "u-demo", "\u5ba2\u6237 A", "\u6c5f\u82cf", "\u6b63\u5e38", 2,
                       payload={"source_market": "\u67e5\u770b"})
    inc = director.emit(ORDER, "plan_sent")["injected"]
    for sp in inc["skill_points"]:
        t = store.target(ORDER, sp)
        assert t and t["trigger_state"] == "triggered"

    marked = director.react(inc["session_id"])
    assert set(marked) == set(inc["skill_points"])
    assert len(marked) == len(set(marked)), "\u91cd\u590d\u6280\u80fd\u70b9\u53ea\u5e94\u8ba1\u4e00\u6b21"
    for sp in inc["skill_points"]:
        t = store.target(ORDER, sp)
        assert t["trigger_state"] == "reacted" and t["covered"] == 1


def test_director_unknown_event_and_order():
    store, practice, director = make()
    try:
        director.emit(ORDER, "no_such_event")
        raise AssertionError("\u5e94\u62a5\u9519")
    except ValueError:
        pass
    try:
        director.emit("no-such-order", "plan_sent")
        raise AssertionError("\u5e94\u62a5\u9519")
    except ValueError:
        pass


def test_incident_rules_reference_real_skill_points_and_steps():
    for r in INCIDENT_RULES:
        assert r["skill_points"], f"{r['code']} \u672a\u5173\u8054\u6280\u80fd\u70b9"
        for sp in r["skill_points"]:
            assert sp in SKILL_POINTS_BY_ID, f"{r['code']} \u5f15\u7528\u4e86\u4e0d\u5b58\u5728\u7684 {sp}"
        assert r["step"].startswith("S"), r["code"]
        assert 0 <= r["stage_min"] <= 7, r["code"]

# ---------------- 自动注入（学员动作触发，D-047） ----------------

def test_actions_auto_inject_without_manual_button():
    """学员动作自动进总线并注入事件——不需要在界面上手动点「事件注入」。"""
    store, practice, director = make()
    practice.attach_director(director)
    oid = "auto-incident-order"
    store.upsert_order(oid, "u-demo", "客户 Z", "江苏", "正常", 0, payload={"brief": {}})
    practice.record_action(oid, "grab")
    practice.record_action(oid, "first_call")
    out = practice.record_action(oid, "deliverable:需求确认单")
    inc = out["incident"]
    assert inc, "投递需求确认单应触发注入"
    assert inc["skill_points"]
    events = [e["type"] for e in store.events(oid)]
    assert "requirement_confirmed" in events


def test_quota_comes_from_brief_and_is_at_least_one():
    store, practice, director = make()
    # 补救档（资源冲突=0）也要注入 1 起
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 1,
                       payload={"brief": {"level": 0, "knobs": {"resource_conflict": 0}}})
    # 配额改成「上限保护」：数量由可注入且已解锁的事件决定，不再把一单压成 1-2 起
    assert director.quota(practice._payload(ORDER)) >= 3
    # 加压四档 → 3 起
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 1,
                       payload={"brief": {"level": 4, "knobs": {"resource_conflict": 4}}})
    assert director.quota(practice._payload(ORDER)) == 5      # 加压四档 → 上限 5 起
    # 无简报（种子单）→ 按默认旋钮 2 算上限
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 1, payload={})
    assert director.quota(practice._payload(ORDER)) == 4


def test_strength_follows_brief_level():
    store, practice, director = make()
    for level, want in ((0, "explicit"), (1, "explicit"), (2, "normal"), (3, "normal"), (4, "implicit")):
        store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 1,
                           payload={"brief": {"level": level, "knobs": {}}})
        assert director.strength(practice._payload(ORDER)) == want, level


def test_explicit_strength_appends_hint_implicit_uses_vague_body():
    store, practice, director = make()
    unlock(store, practice, ORDER, "客户")      # 客户事件要落到客户单聊里
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 2,
                       payload={"brief": {"level": 0, "knobs": {"resource_conflict": 0}}})
    # 事件难度逐事件按该点掌握度算：把规则里一个点压到 60 以下 → 走补救（给线索）
    store.set_ability("u-demo", "C2.5", teach=35, real_v=0)
    explicit = director.emit(ORDER, "call_done")["injected"]
    assert "提醒" in explicit["body"], "补救档要给出方向线索"

    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 2,
                       payload={"brief": {"level": 4, "knobs": {"resource_conflict": 4}}})
    implicit = director.emit(ORDER, "call_done")["injected"]
    assert "提醒" not in implicit["body"], "加压档不给线索"


def test_quota_caps_injection_count():
    store, practice, director = make()
    practice.attach_director(director)
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 2,
                       payload={"brief": {"level": 4, "knobs": {"resource_conflict": 4}}})
    for act in ("plan_sent", "quote_sent", "customer_confirmed", "resource_locked"):
        director.emit(ORDER, act)
    assert len(store.incidents(ORDER)) <= 3, "不得超过画像配额"


def test_depart_is_recorded_when_entering_on_trip_stage():
    store, practice, director = make()
    practice.attach_director(director)
    oid = "9000000000000006"
    for act in ("grab", "first_call"):
        practice.record_action(oid, act)
    for a in ("deliverable:需求确认单", "deliverable:行程方案", "deliverable:分项报价",
              "guard_pass:分项报价", "customer_confirmed_plan",
              "contract_signed", "insurance_bought",
              "customer_signed_contract", "deposit_paid",
              "resources_locked", "pre_trip_notice"):
        practice.record_action(oid, a)
    assert practice.get_order(oid)["stage_index"] == 5
    assert store.has_action(oid, "depart"), "进入「客户出团」应自动登记出团"


def test_rule_table_covers_the_expected_steps():
    from tripcraft.services.director_service import INCIDENT_RULES
    steps = {r["step"] for r in INCIDENT_RULES}
    assert {"S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"} <= steps
    triggers = {t for r in INCIDENT_RULES for t in r["trigger"]}
    assert {"call_done", "plan_sent", "quote_sent", "resource_locked", "depart"} <= triggers


def test_plan_skips_untriggerable_event_points():
    """没有事件规则覆盖的 B 型点，不该占考核名额（抽了也考不到）。"""
    from tripcraft.contracts.enums import CheckpointType
    from tripcraft.services.practice_service import injectable_points

    store = Store(os.path.join(tempfile.gettempdir(), f"tc_{uuid4().hex}.sqlite"))
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 1)
    practice = PracticeService(store)
    plan = practice.build_plan(ORDER)

    dead = [sp for sp in plan
            if SKILL_POINTS_BY_ID[sp].checkpoint is CheckpointType.B_EVENT
            and sp not in injectable_points()]
    assert not dead, f"目标里混进了触发不了的 B 型点: {dead}"
    assert plan, "清单不该是空的"


def test_incident_only_tests_learned_skill_points():
    """一条规则覆盖多个点时，只把教学掌握度 >= 60 的点纳入考核，其余留在 pending。"""
    store, practice, director = make()
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 2,
                       payload={"source_market": "香港"})
    practice.record_action(ORDER, "first_call")      # 客户联系方式要首呼后才给
    unlock(store, practice, ORDER, "客户")            # 事件要有地方发生（客户服务群）
    # INC-BAD-REVIEW(S11) 覆盖 C1.5 / C1.8 / C8.7：只让 C1.5 学过
    store.set_ability("u-demo", "C1.5", teach=80)
    store.set_ability("u-demo", "C1.8", teach=0)
    store.set_ability("u-demo", "C8.7", teach=0)
    store.upsert_order(ORDER, "u-demo", "客户 A", "江苏", "正常", 6,
                       payload={"source_market": "香港"})

    inc = director.emit(ORDER, "balance_paid")["injected"]
    assert inc and inc["code"] == "INC-BAD-REVIEW"
    assert inc["skill_points"] == ["C1.5"], f"只该考学过的点，实际 {inc['skill_points']}"

    # 没学过的点：没被这条事件拉进目标表（或即便在清单里也仍是 pending，不计入分母）
    assert store.target(ORDER, "C1.8") is None, "没学过的点不该被事件拉进目标清单"
    assert store.target(ORDER, "C8.7") is None
    cov = practice.coverage(ORDER)
    idle = [i for i in cov["items"] if i["skill_point_id"] in ("C1.8", "C8.7")]
    assert all(i["counted"] is False for i in idle), "没学过的点不该计入覆盖率分母"
