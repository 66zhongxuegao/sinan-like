"""行后提交完成判定与雷达初始值回退：离线内存库验证。"""
import json

import pytest

from tripcraft.contracts.deliverables_spec import PRACTICE_FINAL_CODES, resolve
from tripcraft.contracts.enums import Dimension
from tripcraft.services.deliverable_service import DeliverableService
from tripcraft.services.guard_service import GuardService
from tripcraft.services.journey_service import annotate_submission, training_completion
from tripcraft.services.profile_radar import build_radar, initial_only, radar_abilities
from tripcraft.storage import Store


@pytest.fixture
def store():
    value = Store(":memory:")
    value.upsert_order("completion-order", "completion-user", "客户甲", "福建", "进行中", 0, {})
    try:
        yield value
    finally:
        value.close()


@pytest.mark.parametrize("codes", [PRACTICE_FINAL_CODES, tuple(reversed(PRACTICE_FINAL_CODES))])
def test_final_documents_complete_in_either_order_without_other_gates(store, codes):
    oid = "completion-order"
    service = DeliverableService(store, guard=GuardService())
    service.import_templates(oid)
    assert not training_completion(store, oid)["completed"]
    assert not store.completed_practice_at("completion-user")
    for index, code in enumerate(codes):
        values = json.loads(store.deliverable_draft(oid, resolve(code).id)["values_json"])
        result = annotate_submission(store, oid, service.submit(oid, code, values, submit_once=True))
        assert result["delivered"]
        assert result["training_completion"]["completed"] == bool(index)
    completion = result["training_completion"]
    assert completion["score_route"] == f"/practice/orders/{oid}/score"
    assert completion["completed_at"] == store.completed_practice_at("completion-user")
    assert not store.completed_practice_at("other-user")
    assert store.order(oid)["stage_index"] == 0, "完成提示独立于旧平台阶段"
    repeated = annotate_submission(store, oid, service.submit(oid, codes[-1], values, submit_once=True))
    assert repeated["already_submitted"] and repeated["training_completion"]["completed"]
    assert len(store.deliverables(oid)) == 2


def test_drafts_other_documents_and_rejected_submission_do_not_complete(store):
    oid = "completion-order"
    service = DeliverableService(store, guard=GuardService())
    service.import_templates(oid)
    code = "departure_notice"
    values = json.loads(store.deliverable_draft(oid, resolve(code).id)["values_json"])
    service.submit(oid, code, values)
    out = annotate_submission(store, oid, {"deliverable_id": resolve("settlement").id, "blocked": True})
    assert not out["delivered"] and not out["training_completion"]["completed"]
    assert not store.completed_practice_at("completion-user")


def baseline():
    return {dim.value: {"value": 40 + index * 5, "created_at": "2026-10-01T09:00:00"}
            for index, dim in enumerate(Dimension)}


def test_partial_training_inherits_initial_axes_and_keeps_zero_score():
    radar = build_radar("u", {"C1.1": {"real_v": 0, "real_source": "practice", "real_updated_at": "2026-10-17T10:00:00"},
                              "C2.1": {"teach": 85, "teach_source": "learning", "teach_updated_at": "2026-10-17T11:00:00"}}, baseline())
    for layer, own_dimension, own_value in (("practice", "C1", 0), ("learning", "C2", 85)):
        for row in radar[layer]["dimensions"]:
            assert row["assessed"]
            if row["id"] == own_dimension:
                assert row["value"] == own_value and not row["inherited"]
                assert row["assessed_points"] == 1
            else:
                assert row["value"] == baseline()[row["id"]]["value"]
                assert row["inherited"] and row["assessed_points"] == 0
                assert row["source"] == "initial"


def test_completed_training_shows_baseline_before_scoring_without_writing_fake_abilities(store):
    for code in PRACTICE_FINAL_CODES:
        store.save_deliverable("completion-order", resolve(code).id, {}, "模拟提交", [], {}, [])
    at = store.completed_practice_at("completion-user")
    radar = build_radar("completion-user", {}, baseline(), practice_completed_at=at)
    assert all(row["inherited"] and row["assessed"] for row in radar["practice"]["dimensions"])
    assert radar["practice"]["at"] == at
    assert not store.abilities("completion-user")
    historical = initial_only(radar)
    assert all(row["value"] is None and not row["inherited"] for row in historical["practice"]["dimensions"])


def test_no_initial_assessment_does_not_generate_scores():
    radar = build_radar("u", {}, {}, practice_completed_at="2026-10-17T10:00:00")
    assert not radar["assessed"]
    assert all(row["value"] is None for row in radar["practice"]["dimensions"])


def test_radar_reads_recorded_scores_without_writing_or_using_pending_results():
    abilities = {"C1.1": {"teach": 50, "teach_source": "initial"}}
    scores = [{"skill_point_id": sp, "score": value, "status": status, "evidence": evidence, "created_at": at}
              for sp, value, status, evidence, at in (
                  ("C1.1", 80, "已入库", '[{"quote":"实际证据"}]', "2026-10-17T10:00:00"),
                  ("C1.1", 30, "待复核", '[{"quote":"待核证据"}]', "2026-10-17T11:00:00"),
                  ("C2.1", 85, "已入库", '[]', "2026-10-17T10:00:00"),
                  ("C3.1", 90, "已驳回", '[{"quote":"驳回"}]', "2026-10-17T10:00:00"),
              )]
    displayed = radar_abilities(abilities, scores)
    assert displayed["C1.1"]["real_v"] == 80
    assert "real_v" not in abilities["C1.1"]
    assert "C2.1" not in displayed and "C3.1" not in displayed
    radar = build_radar("u", displayed, baseline())
    assert radar["practice"]["dimensions"][0]["value"] == 80
    assert all(row["inherited"] for row in radar["practice"]["dimensions"][1:])


def test_older_score_report_does_not_replace_newer_ability():
    displayed = radar_abilities({"C1.1": {"real_v": 90, "real_source": "practice", "real_updated_at": "2026-10-17T11:00:00"}},
                               [{"skill_point_id": "C1.1", "score": 60, "status": "已入库", "evidence": [{"quote": "早先证据"}], "created_at": "2026-10-17T09:00:00"}])
    assert displayed["C1.1"]["real_v"] == 90


def test_initial_assessment_is_learning_ability_not_only_inherited():
    abilities = {}
    from tripcraft.contracts.skill_points import SKILL_POINTS
    for point in SKILL_POINTS:
        abilities[point.id] = {"teach": baseline()[point.dimension.value]["value"],
                               "teach_source": "initial",
                               "teach_updated_at": "2026-10-01T09:00:00"}
    radar = build_radar("u", abilities, baseline())
    for row in radar["learning"]["dimensions"]:
        assert row["assessed"] and not row["inherited"]
        assert row["value"] == baseline()[row["id"]]["value"]
