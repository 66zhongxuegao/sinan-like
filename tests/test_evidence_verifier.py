"""证据闸门：claim 级支持、数字一致性与高风险阻断。"""

from tripcraft.services.evidence_verifier import EvidenceVerifier


def test_supported_claim_passes_with_traceable_evidence():
    verifier = EvidenceVerifier()
    audit = verifier.audit(
        "预算需确认人均预算与总价区间，并复述确认。",
        [{"id": "E1", "source": "rubric:C2.2", "text": "预算需确认人均预算与总价区间，并复述确认"}],
    )
    assert audit["decision"] == "allow"
    assert audit["supported"] == 1
    assert audit["claims"][0]["evidence_id"] == "E1"


def test_high_risk_claim_without_evidence_is_blocked_for_review():
    audit = EvidenceVerifier().audit("签证需要提供邀请函。", [])
    assert audit["decision"] == "human_review"
    assert audit["blocked"] is True
    assert audit["high_risk_failures"]


def test_numeric_mismatch_cannot_be_supported():
    audit = EvidenceVerifier().audit(
        "客户预算为人均 8000 元。",
        [{"id": "E1", "source": "knowledge:C5", "text": "客户预算为人均 6000 元"}],
    )
    assert audit["claims"][0]["status"] != "supported"
    assert audit["claims"][0]["number_ok"] is False


def test_high_risk_claim_rejects_secondary_source_even_with_high_overlap():
    audit = EvidenceVerifier().audit(
        "签证需要提供邀请函。",
        [{"id": "E1", "source": "百度百科", "text": "签证需要提供邀请函"}],
    )
    assert audit["decision"] == "human_review"
    assert audit["blocked"] is True
    assert audit["source_trust_counts"] == {"secondary": 1}
    assert audit["claims"][0]["status"] == "unsupported"


def test_high_risk_claim_accepts_official_curated_and_observed_sources():
    cases = (
        ("国家移民管理局", "official"),
        ("rubric:C2.2", "curated"),
        ("practice:ORDER-1:result", "observed"),
    )
    for source, expected in cases:
        audit = EvidenceVerifier().audit(
            "签证需要提供邀请函。",
            [{"id": "E1", "source": source, "text": "签证需要提供邀请函。"}],
        )
        assert audit["decision"] == "allow", source
        assert audit["claims"][0]["source_trust"] == expected, source


def test_client_cannot_forge_trust_level_for_a_secondary_source():
    audit = EvidenceVerifier().audit(
        "签证需要提供邀请函。",
        [{"id": "E1", "source": "百度百科", "trust": "official",
          "text": "签证需要提供邀请函。"}],
    )
    assert audit["decision"] == "human_review"
    assert audit["source_trust_counts"] == {"secondary": 1}
    assert audit["claims"][0]["source_trust"] == ""


def test_source_trust_counts_cover_all_supplied_evidence():
    audit = EvidenceVerifier().audit(
        "行程安排需要提前确认。",
        [
            {"id": "E1", "source": "https://www.gov.cn/policy", "text": "行程安排需要提前确认。"},
            {"id": "E2", "source": "rubric:C2.2", "text": "行程安排需要提前确认。"},
            {"id": "E3", "source": "knowledge:C2.2", "text": "行程安排需要提前确认。"},
            {"id": "E4", "source": "百度百科", "text": "行程安排需要提前确认。"},
        ],
    )
    assert audit["source_trust_counts"] == {
        "official": 1, "curated": 1, "teaching": 1, "secondary": 1,
    }


def test_low_risk_claim_can_use_teaching_material():
    audit = EvidenceVerifier().audit(
        "行程安排需要提前确认。",
        [{"id": "E1", "source": "knowledge:C2.2", "text": "行程安排需要提前确认。"}],
    )
    assert audit["decision"] == "allow"
    assert audit["claims"][0]["source_trust"] == "teaching"
