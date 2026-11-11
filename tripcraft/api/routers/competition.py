"""竞赛技术闭环入口：技能图、证据闸门、主动诊断与反馈候选。

这些接口把实验室里的四个模块接到真实产品边界，均使用当前登录用户身份；
不把技能图或证据校验做成绕过认证的“演示接口”。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from tripcraft.api.context import AppContext
from tripcraft.api.security import current_user
from tripcraft.services.adaptive_diagnosis import candidate_probes
from tripcraft.services.capability_compounding import (
    capability_candidates, load_learning_signals, mine_error_patterns,
)
from tripcraft.services.evidence_verifier import get_verifier
from tripcraft.services.experience_compiler import get_skill_graph
from tripcraft.services.source_registry import OfficialSourceRegistry, SourceRegistryError


class EvidenceVerifyBody(BaseModel):
    content: str = ""
    evidence: list[Any] = Field(default_factory=list)


class SourceSnapshotBody(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/competition")

    @router.get("/skill-graph/summary")
    def skill_graph_summary(uid: str = Depends(current_user)):
        graph = get_skill_graph()
        return {"summary": graph.summary(), "note": "61 个技能点由契约、Rubric 与知识文件编译"}

    @router.get("/skill-graph/{skill_point_id}")
    def skill_graph_node(skill_point_id: str, uid: str = Depends(current_user)):
        graph = get_skill_graph()
        node = graph.node(skill_point_id)
        if node is None:
            raise HTTPException(404, f"未知技能点: {skill_point_id}")
        return {"node": node.as_dict(), "subgraph": graph.subgraph(skill_point_id, depth=1)}

    @router.post("/evidence/snapshots")
    def evidence_snapshot(body: SourceSnapshotBody, uid: str = Depends(current_user)):
        """服务端抓取官方页面并落快照；这是官方证据的信任根。"""
        registry = OfficialSourceRegistry(ctx.store)
        try:
            return registry.capture(body.url, created_by=uid)
        except SourceRegistryError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/evidence/snapshots/{snapshot_id}")
    def evidence_snapshot_detail(snapshot_id: str, uid: str = Depends(current_user)):
        registry = OfficialSourceRegistry(ctx.store)
        row = registry.resolve(snapshot_id)
        if row is None:
            raise HTTPException(404, "官方快照不存在或完整性校验失败")
        return registry.public_snapshot(row)

    @router.post("/evidence/verify")
    def evidence_verify(body: EvidenceVerifyBody, uid: str = Depends(current_user)):
        if not str(body.content or "").strip():
            raise HTTPException(400, "content 不能为空")
        registry = OfficialSourceRegistry(ctx.store)
        return get_verifier().audit(
            body.content, body.evidence, strict_provenance=True,
            snapshot_resolver=registry.resolve,
        )

    @router.get("/diagnosis/next")
    def diagnosis_next(uid: str = Depends(current_user)):
        abilities = ctx.store.abilities(uid)
        probes = candidate_probes(abilities, limit=10)
        return {
            "method": "BKT + expected_information_gain",
            "next_best_probe": probes[0] if probes else None,
            "probes": probes,
            "observed_skills": len(abilities),
        }

    @router.get("/feedback/candidates")
    def feedback_candidates(uid: str = Depends(current_user)):
        signals = load_learning_signals(ctx.store, uid)
        patterns = mine_error_patterns(signals)
        candidates = capability_candidates(signals, min_count=1)
        return {
            "signal_count": len(signals),
            "patterns": patterns,
            "candidates": candidates,
            "gate": "pending_expert_review",
        }

    @router.get("/overview")
    def competition_overview(uid: str = Depends(current_user)):
        graph = get_skill_graph()
        signals = load_learning_signals(ctx.store, uid)
        return {
            "skill_graph": graph.summary(),
            "evidence_verifier": {
                "version": "deterministic_lexical_numeric_gate_v2",
                "claim_level": True,
                "human_review_on_high_risk": True,
                "source_policy": "high_risk_requires_official_curated_or_observed",
                "source_verification_policy": "official_requires_server_snapshot_and_evidence_span",
                "strict_provenance": True,
                "source_snapshot_count": ctx.store.source_snapshot_count(),
            },
            "diagnosis": {"method": "BKT", "slip": 0.10, "guess": 0.20, "learn": 0.15},
            "feedback": {"signals": len(signals), "pending_expert_review": len(capability_candidates(signals))},
            "next_best_probe": (candidate_probes(ctx.store.abilities(uid), limit=1) or [None])[0],
        }

    return router
