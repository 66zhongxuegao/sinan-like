"""人工校准集测试（指标与阈值标定，离线）。"""

from tripcraft.calibration import MIN_PER_SKILL_POINT, audit_dataset, load_samples, normalize_text
from tripcraft.calibration.metrics import (MIN_KEPT_RATIO, TARGET_AGREEMENT, evaluate,
                                           sweep_thresholds)
from tripcraft.contracts.rubric import RUBRICS
from tripcraft.contracts.skill_points import SKILL_POINTS_BY_ID

VALID_LEVELS = {"M1", "M2", "M3", "M4", "M5"}


# ---------------- 数据集自检 ----------------

def test_dataset_audit_passes_prd_25_2():
    """PRD 25.2：技能点分层 / M1–M5 分层 / 难例 / 语言与客源覆盖。"""
    a = audit_dataset(load_samples())
    assert a["passed"] is True, a["gaps"]
    assert a["thin_skill_points"] == [], a["thin_skill_points"]
    assert a["missing_levels"] == [], a["missing_levels"]
    assert a["hard_cases"] > 0
    assert len(a["markets"]) >= 2 and len(a["languages"]) >= 2
    assert all(n >= MIN_PER_SKILL_POINT for n in a["per_skill_point"].values())


def test_audit_reports_gaps_for_a_poor_dataset():
    tiny = [{"id": "x", "skill_point_ids": ["C1.1"], "labels": [{"level": "M1"}],
             "source_market": "香港", "language": "中文", "difficulty": "", "note": ""}]
    a = audit_dataset(tiny)
    assert a["passed"] is False
    assert any("档位" in g for g in a["gaps"])


def test_samples_are_well_formed():
    rows = load_samples()
    assert len(rows) >= 40, "校准集样本太少，不足以支撑验收"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "样本 ID 必须唯一"
    for r in rows:
        assert r["transcript"].strip(), f"{r['id']} 缺转写"
        assert r["labels"], f"{r['id']} 缺人工标注"
        for sp in r["skill_point_ids"]:
            assert sp in RUBRICS, f"{r['id']} 引用了没有 Rubric 的技能点 {sp}"
        for lab in r["labels"]:
            assert lab["level"] in VALID_LEVELS, f"{r['id']} 人工作标 {lab['level']} 非法"
            assert lab.get("evidence_quote", "").strip(), f"{r['id']} 标注缺证据坐标"
            assert lab["skill_point_id"] in SKILL_POINTS_BY_ID


def test_samples_cover_markets_levels_and_boundaries():
    rows = load_samples()
    markets = {r["source_market"] for r in rows}
    languages = {r["language"] for r in rows}
    levels = {l["level"] for r in rows for l in r["labels"]}
    assert len(markets) >= 5, "至少覆盖 5 个客源市场（跨境沟通能力需要）"
    assert {"M1", "M2", "M3", "M4", "M5"} <= levels, "M1–M5 五个档位都要有样本"
    assert len(languages) >= 2, "至少覆盖一门入境语言"
    assert any("边界" in r["difficulty"] for r in rows), "必须包含易漂移的边界档样本"


def test_normalize_text_strips_punctuation():
    assert normalize_text("你好，世界！") == normalize_text("你好世界")
    assert normalize_text(" A-B ") == "ab"


# ---------------- 指标 ----------------

def _pred(**kw):
    base = {"run": 0, "sample_id": "s1", "skill_point_id": "C1.1", "level": "M4",
            "score": 85, "confidence": 0.9, "evidence_quote": "我是定制师", "human_level": "M4"}
    base.update(kw)
    return base


SAMPLES = [{"id": "s1", "transcript": "我是定制师小李", "deliverables": {}, "labels": []}]


def test_evaluate_counts_agreement_and_evidence():
    preds = [_pred(), _pred(level="M3", evidence_quote="不存在的句子")]
    m = evaluate(preds, SAMPLES)
    assert m["predictions"] == 2
    assert m["agreement"] == 0.5
    assert m["evidence_accuracy"] == 0.5
    assert len(m["errors"]) == 1 and m["errors"][0]["predicted"] == "M3"


def test_evaluate_measures_stability_across_repeats():
    stable = [_pred(run=0), _pred(run=1)]
    assert evaluate(stable, SAMPLES)["stability"] == 1.0
    unstable = [_pred(run=0), _pred(run=1, level="M3")]
    assert evaluate(unstable, SAMPLES)["stability"] == 0.0


def test_empty_predictions_are_safe():
    m = evaluate([], SAMPLES)
    assert m["predictions"] == 0 and m["agreement"] == 0.0


# ---------------- 阈值标定 ----------------

def test_sweep_prefers_conservative_threshold_within_floor():
    preds = ([_pred(confidence=0.6, score=85)] * 3
             + [_pred(confidence=0.95, score=85)] * 7)
    out = sweep_thresholds(preds, target=TARGET_AGREEMENT)
    assert out["passed"] is True
    assert out["confidence"] >= 0.6
    assert out["kept_ratio"] >= MIN_KEPT_RATIO, "不能把绝大多数判定都推给人工"


def test_sweep_reports_failure_when_target_unreachable():
    # 一半判错且置信度都很高：任何阈值都拦不住，只能标定失败
    preds = [_pred(confidence=0.95, level="M4", human_level="M1")] * 5 + [_pred(confidence=0.95)] * 5
    out = sweep_thresholds(preds, target=TARGET_AGREEMENT)
    assert out["passed"] is False
    assert "达标" in out["note"]


def test_sweep_without_predictions_returns_defaults():
    out = sweep_thresholds([], target=TARGET_AGREEMENT)
    assert out["passed"] is False and out["confidence"] > 0