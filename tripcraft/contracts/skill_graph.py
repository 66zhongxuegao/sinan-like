"""可执行技能图的最小共享契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    source: str
    requirement: str
    risk_level: str = "medium"
    locator: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "requirement": self.requirement,
                "risk_level": self.risk_level, "locator": self.locator}


@dataclass(frozen=True)
class SkillGraphEdge:
    source: str
    target: str
    kind: str
    evidence_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "kind": self.kind,
                "evidence_id": self.evidence_id, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class SkillGraphNode:
    id: str
    name: str
    dimension: str
    steps: tuple[str, ...]
    checkpoint: str
    target: str
    prerequisites: tuple[str, ...]
    methods: tuple[str, ...]
    knowledge: tuple[str, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    positive: str
    negative: str
    risk_level: str
    source_refs: tuple[dict[str, Any], ...]
    version: str = "1"

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "dimension": self.dimension,
                "steps": list(self.steps), "checkpoint": self.checkpoint, "target": self.target,
                "prerequisites": list(self.prerequisites), "methods": list(self.methods),
                "knowledge": list(self.knowledge),
                "evidence_requirements": [e.as_dict() for e in self.evidence_requirements],
                "positive": self.positive, "negative": self.negative,
                "risk_level": self.risk_level, "source_refs": [dict(s) for s in self.source_refs],
                "version": self.version}


@dataclass
class SkillGraph:
    nodes: dict[str, SkillGraphNode]
    edges: tuple[SkillGraphEdge, ...] = ()
    schema_version: str = "1"

    def node(self, skill_point_id: str) -> SkillGraphNode | None:
        return self.nodes.get(skill_point_id)

    def prerequisites_of(self, skill_point_id: str) -> list[str]:
        node = self.node(skill_point_id)
        return list(node.prerequisites) if node else []

    def subgraph(self, skill_point_id: str, depth: int = 1) -> dict[str, Any]:
        seen: set[str] = set()
        frontier = [skill_point_id]
        # depth=1 应包含根节点 + 一跳前置；旧的 range(depth) 只保留了根节点。
        for _ in range(max(0, int(depth)) + 1):
            if not frontier:
                break
            nxt: list[str] = []
            for sid in frontier:
                if sid in seen:
                    continue
                seen.add(sid)
                nxt.extend(self.prerequisites_of(sid))
            frontier = nxt
        nodes = [self.nodes[s].as_dict() for s in sorted(seen) if s in self.nodes]
        ids = set(seen)
        edges = [e.as_dict() for e in self.edges if e.source in ids and e.target in ids]
        return {"root": skill_point_id, "depth": depth, "nodes": nodes, "edges": edges}

    def summary(self) -> dict[str, Any]:
        by_dimension: dict[str, int] = {}
        for node in self.nodes.values():
            by_dimension[node.dimension] = by_dimension.get(node.dimension, 0) + 1
        return {"schema_version": self.schema_version, "nodes": len(self.nodes),
                "edges": len(self.edges), "by_dimension": by_dimension,
                "evidence_requirements": sum(len(n.evidence_requirements) for n in self.nodes.values()),
                "high_risk_nodes": sum(1 for n in self.nodes.values() if n.risk_level == "high")}

    def as_dict(self) -> dict[str, Any]:
        return {**self.summary(), "nodes": [n.as_dict() for n in self.nodes.values()],
                "edges": [e.as_dict() for e in self.edges]}
