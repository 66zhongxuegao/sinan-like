"""画像 → 难度 → 派单 的闭环测试（离线，确定性）。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.agents.scenario import (DISPATCH_FIELDS, SOURCE_MARKETS, DispatchGenerator,
                                       _first_call_limit, _preset_incidents, missing_fields)
from tripcraft.contracts.skill_points import SKILL_POINTS
from tripcraft.services.learner_brief import KNOBS, build_brief
from tripcraft.services.practice_service import PracticeService
from tripcraft.storage import Store


def abilities_all(value: float) -> dict:
    return {sp.id: {"teach": value, "real_v": 0.0} for sp in SKILL_POINTS}


def abilities_c1(value: float) -> dict:
    return {sp.id: {"teach": value if sp.dimension.value == "C1" else 0.0, "real_v": 0.0}
            for sp in SKILL_POINTS}


# ---------------- 简报：画像 → 难度 ----------------

def test_m1_profile_goes_remedial_on_every_knob():
    """M1 走补救：所有旋钮放松、时限放宽、不埋突发。"""
    b = build_brief(abilities_all(45))
    assert b.level == 0 and b.branch == "补救"
    assert "补救" in b.label
    assert set(b.knobs.values()) == {0}, b.knobs
    assert _first_call_limit(b.knobs["time_pressure"]) == 120
    # 补救 ≠ 不考：事件仍要发生（否则 B 型考点永远考不到），区别是强度更显式
    assert len(_preset_incidents(b.knobs["resource_conflict"])) == 1


def test_m4_profile_goes_pressure_on_every_knob():
    b = build_brief(abilities_all(85))
    assert b.level == 3 and b.branch == "加压"
    assert set(b.knobs.values()) == {3}, b.knobs
    assert _first_call_limit(b.knobs["time_pressure"]) == 30
    assert len(_preset_incidents(b.knobs["resource_conflict"])) == 2


def test_knob_fallback_follows_overall_level_not_neutral():
    """目标技能点只覆盖 C1 时，其它维度的旋钮要跟随整单档位，
    不能取中性值偷偷加压（否则出现「标补救、时限却收紧」）。"""
    b = build_brief(abilities_c1(45))          # 只有 C1 有数据 → 目标点都是 C1
    assert b.level == 0
    assert b.knobs["emotion_intensity"] == 0
    for knob in ("source_complexity", "dispatch_gap", "time_pressure", "budget_tightness"):
        assert b.knobs[knob] == 0, f"{knob} 应跟随整单补救档，实际 {b.knobs[knob]}"


def test_unevaluated_points_are_picked_first():
    ab = abilities_all(88)                     # 全部已评估且不错
    for sp in list(SKILL_POINTS)[:2]:
        ab[sp.id] = {"teach": 0.0, "real_v": 0.0}   # 抽掉两项 → 未评估
    b = build_brief(ab)
    assert set(b.target_skill_points[:2]) == {list(SKILL_POINTS)[0].id, list(SKILL_POINTS)[1].id}


def test_carried_over_points_get_priority_and_are_explained():
    ids = [sp.id for sp in SKILL_POINTS[:2]]
    b = build_brief(abilities_all(80), carried_over=ids)
    assert set(ids) <= set(b.target_skill_points)
    assert all(i in b.rationale for i in ids)
    assert "未覆盖" in b.rationale


def test_brief_is_deterministic():
    ab = abilities_all(72)
    assert build_brief(ab).to_dict() == build_brief(ab).to_dict()


def test_brief_exposes_knob_labels_for_ui():
    d = build_brief(abilities_all(65)).to_dict()
    assert set(d["knob_labels"]) == set(KNOBS)
    assert set(d["knob_words"]) == set(KNOBS)
    assert "rationale" in d and d["rationale"]


# ---------------- 生成器：简报 → 游客 ----------------

def test_generator_output_matches_brief_complexity():
    gen = DispatchGenerator(llm=None)
    brief = build_brief(abilities_all(45))          # 补救 → 客源复杂度 0
    spec = gen.generate(brief, seq=0)
    assert SOURCE_MARKETS[spec.source_market][2] == 0, "补救单应给中文客源"
    assert spec.language == SOURCE_MARKETS[spec.source_market][0]
    assert spec.destination
    assert spec.first_call_limit_min == 120
    assert len(spec.preset_incidents) == 1, "补救单也要埋 1 起，只是给线索"


def test_generator_gives_exactly_the_allowed_field_count():
    gen = DispatchGenerator(llm=None)
    for value, gap in ((45, 0), (65, 1), (85, 3)):
        brief = build_brief(abilities_all(value))
        spec = gen.generate(brief, seq=0)
        missing = missing_fields(spec.to_payload())
        expect_missing = 2 + brief.knobs["dispatch_gap"]
        assert len(missing) == expect_missing, (value, missing)


def test_generator_avoids_duplicate_market_destination_pairs():
    gen = DispatchGenerator(llm=None)
    brief = build_brief(abilities_all(45))
    seen, existing = set(), []
    for i in range(6):
        spec = gen.generate(brief, existing=existing, seq=i)
        key = (spec.source_market, spec.destination)
        assert key not in seen, f"重复派单 {key}"
        seen.add(key)
        existing.append({"source_market": spec.source_market, "destination": spec.destination})


def test_generator_carries_difficulty_and_rationale():
    gen = DispatchGenerator(llm=None)
    brief = build_brief(abilities_all(85))
    spec = gen.generate(brief, seq=0)
    assert spec.difficulty_label == brief.label
    assert spec.rationale == brief.rationale
    assert spec.source_complexity == brief.knobs["source_complexity"]


def test_first_call_limit_and_incidents_scale_with_knobs():
    assert [_first_call_limit(i) for i in range(5)] == [120, 60, 45, 30, 20]
    # 最少 1 起：补救档不是不注入，而是「显式触发 + 给线索」
    assert [len(_preset_incidents(i)) for i in range(5)] == [1, 1, 2, 2, 3]


# ---------------- 服务层：落库为真实派单 ----------------

def make():
    store = Store(os.path.join(tempfile.gettempdir(), f"br_{uuid4().hex}.sqlite"))
    svc = PracticeService(store)
    svc.seed("u-demo")
    return store, svc


def test_generate_dispatch_creates_claimable_order_with_brief():
    store, svc = make()
    before = {o["order_id"] for o in svc.available_orders("u-demo")}
    out = svc.generate_dispatch("u-demo", llm=None, count=1)
    assert out["created"], "应至少生成一条"
    new_id = out["created"][0]["order_id"]
    assert new_id not in before

    rows = {o["order_id"]: o for o in svc.available_orders("u-demo")}
    assert new_id in rows, "生成后应立刻可抢"
    o = rows[new_id]
    assert o["difficulty"] == out["brief"]["label"]
    assert o["target_skill_points"] == list(out["brief"]["target_skill_points"])
    assert o["rationale"]
    payload = svc._payload(new_id)
    assert payload.get("generated") is True and payload.get("brief")
    assert [e["type"] for e in store.events(new_id)] == ["dispatch_generated"]


def test_generated_order_honours_brief_first_call_limit():
    store, svc = make()
    out = svc.generate_dispatch("u-demo", llm=None, count=1)
    oid = out["created"][0]["order_id"]
    svc.record_action(oid, "grab")
    info = svc.dispatch_info(oid)
    assert info["first_call"]["limit_min"] == out["brief"]["plan"]["first_call_limit_min"]


def test_generate_dispatch_can_emit_several_orders():
    store, svc = make()
    out = svc.generate_dispatch("u-demo", llm=None, count=2)
    assert len(out["created"]) == 2
    ids = [c["order_id"] for c in out["created"]]
    assert len(set(ids)) == 2


def test_brief_for_reflects_real_profile():
    store, svc = make()
    assert svc.brief_for("u-demo")["target_skill_points"], "画像为空也应给出摸底目标"
    # 写一个 M4 的能力值 → 简报应变成加压档
    for sp in SKILL_POINTS:
        store.set_ability("u-demo", sp.id, teach=88.0)
    b = svc.brief_for("u-demo")
    assert b["branch"] == "加压" and b["level"] == 3
    assert b["plan"]["first_call_limit_min"] == 30