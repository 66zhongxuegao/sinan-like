"""竞赛技术闭环 API：认证、技能图、证据治理和主动诊断。"""

from hashlib import sha256

from tripcraft.api.security import current_user  # noqa: F401  （依赖契约已由路由声明）
from tripcraft.services.source_registry import FetchedOfficialSource


def test_competition_api_requires_authentication(client):
    response = client.get("/competition/overview")
    assert response.status_code == 401


def test_competition_api_exposes_skill_graph_and_source_policy(auth_client):
    client, headers = auth_client
    summary = client.get("/competition/skill-graph/summary", headers=headers)
    assert summary.status_code == 200
    graph = summary.json()["summary"]
    assert graph["nodes"] == 61
    assert graph["evidence_requirements"] == 412
    assert graph["high_risk_nodes"] >= 1

    node = client.get("/competition/skill-graph/C2.2", headers=headers)
    assert node.status_code == 200
    ids = {row["id"] for row in node.json()["subgraph"]["nodes"]}
    assert {"C2.1", "C2.2"} <= ids

    overview = client.get("/competition/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["evidence_verifier"]["source_policy"] == (
        "high_risk_requires_official_curated_or_observed"
    )


def test_evidence_api_blocks_forged_trust_and_accepts_server_snapshot(
        auth_client, monkeypatch):
    client, headers = auth_client
    claim = "签证需要提供邀请函。"
    forged = client.post(
        "/competition/evidence/verify",
        headers=headers,
        json={"content": claim, "evidence": [
            {"id": "E1", "source": "百度百科", "trust": "official", "text": claim},
        ]},
    )
    assert forged.status_code == 200
    assert forged.json()["decision"] == "human_review"

    bare_name = client.post(
        "/competition/evidence/verify",
        headers=headers,
        json={"content": claim, "evidence": [
            {"id": "E1", "source": "国家移民管理局", "text": claim},
        ]},
    )
    assert bare_name.status_code == 200
    assert bare_name.json()["decision"] == "human_review"
    assert bare_name.json()["strict_provenance"] is True

    # 客户端可以给任意伪造正文自算哈希，因此“哈希一致”不再是官方证明。
    digest = sha256(claim.encode("utf-8")).hexdigest()
    client_hash_only = client.post(
        "/competition/evidence/verify",
        headers=headers,
        json={"content": claim, "evidence": [
            {"id": "E1", "source": "https://www.gov.cn/policy",
             "content_hash": digest, "text": claim},
        ]},
    )
    assert client_hash_only.status_code == 200
    assert client_hash_only.json()["decision"] == "human_review"
    assert client_hash_only.json()["claims"][0]["source_verified"] is False

    source_text = "国家移民管理局政策说明：" + claim + "申请人应按官方要求准备材料。"
    def fake_fetch(url: str):
        return FetchedOfficialSource(
            url=url, content=source_text, title="官方政策说明",
            content_type="text/plain", raw_size=len(source_text.encode("utf-8")),
        )

    monkeypatch.setattr("tripcraft.services.source_registry.fetch_official_url", fake_fetch)
    captured = client.post(
        "/competition/evidence/snapshots", headers=headers,
        json={"url": "https://www.gov.cn/policy"},
    )
    assert captured.status_code == 200, captured.text
    snapshot_id = captured.json()["snapshot_id"]
    assert snapshot_id.startswith("snap_")

    official = client.post(
        "/competition/evidence/verify",
        headers=headers,
        json={"content": claim, "evidence": [
            {"id": "E1", "source": "https://www.gov.cn/policy",
             "snapshot_id": snapshot_id, "content_hash": digest, "text": claim},
        ]},
    )
    assert official.status_code == 200
    assert official.json()["decision"] == "allow"
    assert official.json()["claims"][0]["source_trust"] == "official"
    assert official.json()["claims"][0]["source_verified"] is True
    assert official.json()["source_verification_policy"] == (
        "official_requires_server_snapshot_and_evidence_span"
    )
