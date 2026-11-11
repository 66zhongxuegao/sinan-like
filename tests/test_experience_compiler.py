"""经验编译器：技能图契约、前置边与经验卡校验。"""

from tripcraft.services.experience_compiler import get_skill_graph, validate_experience_card


def test_skill_graph_compiles_all_skill_points_and_edges():
    graph = get_skill_graph()
    summary = graph.summary()
    assert summary["nodes"] == 61
    assert summary["edges"] > 61
    assert summary["evidence_requirements"] > 61
    assert graph.prerequisites_of("C2.2") == ["C2.1"]
    kinds = {e.kind for e in graph.edges}
    assert {"prerequisite", "requires_evidence", "belongs_to_step"} <= kinds


def test_subgraph_keeps_root_and_prerequisite_context():
    sub = get_skill_graph().subgraph("C2.2", depth=1)
    ids = {node["id"] for node in sub["nodes"]}
    assert {"C2.1", "C2.2"} <= ids
    assert any(edge["kind"] == "prerequisite" for edge in sub["edges"])


def test_experience_card_requires_all_six_fields():
    card = {k: "x" for k in ("context", "cue", "judgment", "action", "boundary", "outcome")}
    assert validate_experience_card(card)["judgment"] == "x"
    del card["boundary"]
    try:
        validate_experience_card(card)
    except ValueError as exc:
        assert "boundary" in str(exc)
    else:
        raise AssertionError("缺字段的经验卡必须被拒绝")
