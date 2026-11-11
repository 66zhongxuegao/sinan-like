"""专家经验编译：把技能点、Rubric 和知识片段编译成可执行技能图。

设计取舍：
- 不把 LLM 的自由文本直接当规则；规则来自现有 contracts + 可追溯知识文件；
- 每个技能节点同时保留任务、方法、知识、证据要求和反例边界；
- 同一维度的前置技能形成 prerequisite 边，供生成约束和路径规划使用；
- 经验卡采用 KUPAS 风格的 Context/Cue/Judgment/Action/Boundary/Outcome 六元结构。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts.rubric import RUBRICS
from ..contracts.skill_graph import EvidenceRequirement, SkillGraph, SkillGraphEdge, SkillGraphNode
from ..contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"

HIGH_RISK_TERMS = (
    "签证", "入境", "海关", "证件", "移民", "法律", "保险", "安全", "宗教", "清真",
    "医疗", "疫苗", "开放时间", "门票", "价格", "赔付", "合同", "政策",
)
MEDIUM_RISK_TERMS = ("预算", "行程", "资源", "酒店", "交通", "时间", "费用", "禁忌")


def _risk_level(text: str) -> str:
    value = str(text or "")
    if any(term in value for term in HIGH_RISK_TERMS):
        return "high"
    if any(term in value for term in MEDIUM_RISK_TERMS):
        return "medium"
    return "low"


def _dedupe(items: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("title") or item.get("text") or ""), str(item.get("url") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return tuple(out)


def validate_experience_card(card: dict[str, Any]) -> dict[str, Any]:
    """校验六元经验卡；返回规范化结果，缺字段直接报错，避免把半成品写进图谱。"""
    required = ("context", "cue", "judgment", "action", "boundary", "outcome")
    missing = [key for key in required if not str(card.get(key) or "").strip()]
    if missing:
        raise ValueError("经验卡缺少字段: " + ", ".join(missing))
    return {
        **{key: str(card[key]).strip() for key in required},
        "skill_point_id": str(card.get("skill_point_id") or ""),
        "source": str(card.get("source") or ""),
        "owner": str(card.get("owner") or ""),
        "confidence": float(card.get("confidence") or 0.0),
        "tags": [str(x) for x in (card.get("tags") or [])],
    }


class ExperienceCompiler:
    def __init__(self, knowledge_dir: str | Path | None = None) -> None:
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else KNOWLEDGE_DIR
        self._compiled: SkillGraph | None = None

    def _load_doc(self, skill_point_id: str) -> dict[str, Any]:
        path = self.knowledge_dir / f"{skill_point_id}.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _prerequisites(skill_point: Any) -> tuple[str, ...]:
        """同一维度内按技能点顺序形成前置关系；这是可解释的保守边，不臆造跨维因果。"""
        same_dim = [p for p in SKILL_POINTS if p.dimension is skill_point.dimension]
        index = next((i for i, p in enumerate(same_dim) if p.id == skill_point.id), -1)
        return (same_dim[index - 1].id,) if index > 0 else ()

    def _requirements(self, sp_id: str, doc: dict[str, Any], rubric: Any) -> tuple[EvidenceRequirement, ...]:
        rows: list[EvidenceRequirement] = []
        for i, point in enumerate(doc.get("key_points") or [], 1):
            rows.append(EvidenceRequirement(
                id=f"EV:{sp_id}:{i}", source=f"knowledge:{sp_id}",
                requirement=str(point), risk_level=_risk_level(str(point)),
                locator=f"data/knowledge/{sp_id}.json#key_points[{i - 1}]",
            ))
        if rubric is not None:
            rows.append(EvidenceRequirement(
                id=f"EV:{sp_id}:rubric", source=f"rubric:{sp_id}",
                requirement=f"{rubric.target}；{rubric.evidence_required}",
                risk_level=_risk_level(f"{rubric.target} {rubric.negative}"),
                locator=f"contracts.rubric.{sp_id}",
            ))
        return tuple(rows)

    def compile(self) -> SkillGraph:
        # 技能图由静态契约与知识文件编译而成，进程内只做一次，避免每次对话重复扫描 61 份资料。
        if self._compiled is not None:
            return self._compiled
        nodes: dict[str, SkillGraphNode] = {}
        edges: list[SkillGraphEdge] = []
        for skill_point in SKILL_POINTS:
            doc = self._load_doc(skill_point.id)
            rubric = RUBRICS.get(skill_point.id)
            prerequisites = self._prerequisites(skill_point)
            methods = tuple(str(x.get("title") or x.get("format") or "方法")
                            for x in (doc.get("resources") or [])[:3] if isinstance(x, dict))
            knowledge = tuple(str(x) for x in (doc.get("key_points") or [])[:8])
            sources = _dedupe(list(doc.get("sources") or []))
            reqs = self._requirements(skill_point.id, doc, rubric)
            node = SkillGraphNode(
                id=skill_point.id, name=skill_point.name,
                dimension=skill_point.dimension.value,
                steps=tuple(s.value for s in skill_point.steps),
                checkpoint=skill_point.checkpoint.value, target=skill_point.target,
                prerequisites=prerequisites, methods=methods or ("按 SOP 执行",),
                knowledge=knowledge, evidence_requirements=reqs,
                positive=(rubric.positive if rubric else ""),
                negative=(rubric.negative if rubric else "未提供反例时，必须标记为待专家补充"),
                risk_level=_risk_level(" ".join([skill_point.target, *knowledge, *(x.requirement for x in reqs)])),
                source_refs=sources,
            )
            nodes[node.id] = node
            for prior in prerequisites:
                edges.append(SkillGraphEdge(prior, node.id, "prerequisite",
                                            evidence_id=f"skill:{node.id}"))
            for req in reqs:
                edges.append(SkillGraphEdge(node.id, req.id, "requires_evidence",
                                            evidence_id=req.id,
                                            metadata={"risk_level": req.risk_level,
                                                      "source": req.source}))
            for step in node.steps:
                edges.append(SkillGraphEdge(node.id, f"step:{step}", "belongs_to_step",
                                            metadata={"step": step}))
        self._compiled = SkillGraph(nodes=nodes, edges=tuple(edges))
        return self._compiled

    def subgraph_for_generation(self, skill_point_id: str, depth: int = 1) -> dict[str, Any]:
        graph = self.compile()
        return graph.subgraph(skill_point_id, depth=depth)


_compiler: ExperienceCompiler | None = None


def get_compiler() -> ExperienceCompiler:
    global _compiler
    if _compiler is None:
        _compiler = ExperienceCompiler()
    return _compiler


def get_skill_graph() -> SkillGraph:
    return get_compiler().compile()
