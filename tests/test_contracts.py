"""数据契约 v0 的回归测试。"""

from tripcraft.contracts import skill_points as sp
from tripcraft.contracts.enums import (
    Dimension,
    MasteryLevel,
    StepId,
    mastery_of,
)
from tripcraft.contracts.evidence import Evidence, ScoreTrace
from tripcraft.contracts.profile import LearnerProfile, dimension_value, overall_value
from tripcraft.contracts.rubric import get_rubric

EXPECTED_PER_DIM = {
    Dimension.C1_COMMUNICATION: 8,
    Dimension.C2_REQUIREMENT: 7,
    Dimension.C3_ITINERARY: 9,
    Dimension.C4_RESOURCE: 8,
    Dimension.C5_QUOTATION: 8,
    Dimension.C6_EMERGENCY: 7,
    Dimension.C7_COMPLIANCE: 7,
    Dimension.C8_CROSS_CULTURE: 7,
}


def test_skill_point_totals():
    assert len(sp.SKILL_POINTS) == 61
    assert len({s.id for s in sp.SKILL_POINTS}) == 61


def test_skill_points_per_dimension():
    for dim, expected in EXPECTED_PER_DIM.items():
        assert len(sp.by_dimension(dim)) == expected, dim


def test_all_scoring_steps_have_skill_points():
    """除 S12（复盘，按 PRD 不单独打分）外，每一步都应有技能点。"""
    for step in StepId:
        if step is StepId.S12_REVIEW:
            assert sp.by_step(step) == ()
            continue
        assert sp.by_step(step), f"{step} 无技能点"


def test_mastery_bands():
    assert mastery_of(0) is MasteryLevel.M1
    assert mastery_of(59.9) is MasteryLevel.M1
    assert mastery_of(60) is MasteryLevel.M2
    assert mastery_of(75) is MasteryLevel.M3
    assert mastery_of(85) is MasteryLevel.M4
    assert mastery_of(95) is MasteryLevel.M5
    assert mastery_of(999) is MasteryLevel.M5


def test_dimension_and_overall_value():
    params = {s.id: 80.0 for s in sp.SKILL_POINTS}
    for dim in Dimension:
        assert dimension_value(params, dim) == 80.0
    assert overall_value(params, frozenset(Dimension)) == 80.0
    # 国内单：排除 C8 后仍为 80
    domestic = frozenset(d for d in Dimension if d is not Dimension.C8_CROSS_CULTURE)
    assert overall_value(params, domestic) == 80.0


def test_rubric_c22_complete():
    r = get_rubric("C2.2")
    assert r is not None
    r.validate()  # B 型必须有触发条件；锚点覆盖 M1-M5
    assert r.trigger
    assert len(r.anchors) == 5
    assert r.positive and r.negative and r.evidence_required and r.knowledge


def test_score_trace_requires_evidence():
    trace = ScoreTrace("C2.2", "M2", 65.0, evidence_ids=(), hit_negative=False)
    try:
        trace.validate()
        raise AssertionError("缺证据应报错")
    except AssertionError:
        pass
    ok = ScoreTrace("C2.2", "M2", 65.0, evidence_ids=("msg-1",), hit_negative=False)
    ok.validate()


def test_profile_abilities_and_weak_points():
    prof = LearnerProfile(user_id="u1")
    prof.set_ability("C2.2", 45.0)
    prof.set_ability("C1.1", 88.0)
    assert prof.values()["C2.2"] == 45.0
    weak = prof.weak_points(threshold=60.0)
    assert "C2.2" in weak
    assert "C1.1" not in weak