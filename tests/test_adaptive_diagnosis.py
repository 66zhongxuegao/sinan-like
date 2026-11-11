"""主动诊断：BKT、信息增益与技能图前置约束。"""

from tripcraft.services.adaptive_diagnosis import (
    bkt_update, candidate_probes, constrained_route, prerequisite_ready,
)
from tripcraft.services.experience_compiler import get_skill_graph


def test_bkt_updates_in_expected_direction():
    assert bkt_update(0.5, True) > 0.5
    assert bkt_update(0.5, False) < 0.5


def test_unknown_skill_is_uncertain_not_assumed_mastered():
    probes = candidate_probes({}, limit=1)
    assert probes[0]["observed"] is False
    assert probes[0]["mastery"] == 0.5
    assert probes[0]["expected_information_gain"] > 0


def test_prerequisite_gate_and_constrained_route():
    graph = get_skill_graph()
    assert prerequisite_ready("C2.2", {"C2.1": {"teach": 20}}, graph) is False
    assert prerequisite_ready("C2.2", {"C2.1": {"teach": 80}}, graph) is True
    plan = constrained_route(
        {"C2.1": {"teach": 20}, "C2.2": {"teach": 30}}, graph, size=4, demand_dims=("C2",))
    ids = [row["skill_point_id"] for row in plan]
    assert ids[0] == "C2.1"
    assert "C2.2" not in ids, "前置未达标时，路线不能跳过 C2.1 直接安排 C2.2"
