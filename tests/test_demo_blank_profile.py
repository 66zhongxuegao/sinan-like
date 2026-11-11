"""空白演示账号：全选同一档时仍生成有高低差的演示画像。"""

from tripcraft.services.demo_blank_state import DEMO_ASSESSMENT_SCORES, normalize_assessment_scores


def test_blank_demo_uniform_answers_get_varied_profile():
    scores = {f"C{i}": 95.0 for i in range(1, 9)}
    out = normalize_assessment_scores(scores)
    assert out == DEMO_ASSESSMENT_SCORES
    assert len(set(out.values())) > 3


def test_blank_demo_varied_answers_are_preserved():
    scores = {"C1": 70, "C2": 40, "C3": 60, "C4": 50,
              "C5": 45, "C6": 55, "C7": 65, "C8": 35}
    assert normalize_assessment_scores(scores) == scores
