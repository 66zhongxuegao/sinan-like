"""官方来源快照：服务端抓取、完整性回查与证据片段定位。"""

from __future__ import annotations

import os
import tempfile
from uuid import uuid4

import pytest

from tripcraft.services.evidence_verifier import EvidenceVerifier
from tripcraft.services.source_registry import (
    FetchedOfficialSource, OfficialSourceRegistry, SourceRegistryError,
)
from tripcraft.storage import Store


def _store() -> Store:
    return Store(os.path.join(tempfile.gettempdir(), f"source-{uuid4().hex}.sqlite"))


def _fetcher(text: str):
    def fetch(url: str) -> FetchedOfficialSource:
        return FetchedOfficialSource(
            url=url, content=text, title="国家移民管理局政策说明",
            content_type="text/plain", raw_size=len(text.encode("utf-8")),
        )
    return fetch


def test_server_snapshot_is_immutable_and_evidence_must_be_locatable():
    store = _store()
    text = "国家移民管理局政策说明：签证需要提供邀请函。申请人应按官方要求准备材料。"
    registry = OfficialSourceRegistry(store, fetcher=_fetcher(text))
    captured = registry.capture("https://www.gov.cn/policy", "u1")

    assert captured["snapshot_id"].startswith("snap_")
    assert captured["host"] == "www.gov.cn"
    assert registry.resolve(captured["snapshot_id"])
    assert registry.verify_excerpt(captured["snapshot_id"], "签证需要提供邀请函")
    assert registry.verify_excerpt(captured["snapshot_id"], "任意编造的高风险结论") is None

    audit = EvidenceVerifier().audit(
        "签证需要提供邀请函。",
        [{"id": "E1", "source": "https://www.gov.cn/policy",
          "snapshot_id": captured["snapshot_id"], "text": "签证需要提供邀请函。"}],
        strict_provenance=True,
        snapshot_resolver=registry.resolve,
    )
    assert audit["decision"] == "allow"
    assert audit["claims"][0]["source_verified"] is True


def test_snapshot_integrity_check_detects_tampering():
    store = _store()
    text = "国务院政策原文：入境旅游服务消费场景应持续优化。地方部门按职责推进落实。"
    registry = OfficialSourceRegistry(store, fetcher=_fetcher(text))
    captured = registry.capture("https://www.gov.cn/policy", "u1")
    row = store.source_snapshot(captured["snapshot_id"])
    assert row

    store.save_source_snapshot(
        snapshot_id=row["snapshot_id"], url=row["url"], canonical_url=row["canonical_url"],
        host=row["host"], title=row["title"], content=row["content"] + "被篡改",
        content_hash=row["content_hash"], content_type=row["content_type"],
        raw_size=row["raw_size"], created_by=row["created_by"], fetched_at=row["fetched_at"],
    )
    assert registry.resolve(captured["snapshot_id"]) is None


def test_registry_rejects_non_official_url_before_fetch():
    store = _store()
    calls = []
    registry = OfficialSourceRegistry(store, fetcher=lambda url: calls.append(url))
    with pytest.raises(SourceRegistryError):
        registry.capture("https://example.com/policy", "u1")
    assert calls == []
