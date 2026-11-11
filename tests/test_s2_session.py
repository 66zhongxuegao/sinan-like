"""S2 垂直切片离线测试（mock LLM，不联网、不花钱）。"""

from tripcraft.contracts.profile import LearnerProfile
from tripcraft.services.s2_session import S2Session, s2_skill_points


class FakeLLM:
    """按 system prompt 分流的假 LLM。"""

    def chat(self, messages, **kwargs):
        return "嗯，你说吧。"

    def chat_json(self, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        if "需求结构化专家" in system:
            return {
                "items": [
                    {"category": "人数", "content": "一家三口（2 大 1 小）",
                     "attribute": "必须满足", "status": "已确认", "evidence": "我们一家三口"},
                ],
                "missing": ["预算", "日期"],
                "risks": ["预算口径未明确"],
            }
        if "评分专家" in system:
            return {
                "scores": [
                    {"skill_point_id": "C1.1", "level": "M4", "score": 85,
                     "evidence": [{"kind": "message", "quote": "您好，我是XX定制师小李"}],
                     "hit_negative": False, "comment": "开场自报身份完整"},
                    {"skill_point_id": "C2.2", "level": "M2", "score": 65,
                     "evidence": [{"kind": "message", "quote": "性价比高就行"}],
                     "hit_negative": True, "comment": "未量化预算口径"},
                ],
            }
        return {}


def test_s2_skill_points_domestic():
    ids = s2_skill_points(False)
    assert "C1.1" in ids and "C2.2" in ids
    assert not any(i.startswith("C8") for i in ids)


def test_s2_skill_points_inbound():
    ids = s2_skill_points(True)
    assert "C8.1" in ids and "C8.2" in ids and "C8.4" in ids


def test_s2_full_slice():
    sess = S2Session(user_id="u1", llm=FakeLLM(), instance_id="s2-t1")
    opening = sess.start()
    assert opening
    reply = sess.send("您好，我是XX定制师小李，请问怎么称呼您？")
    assert reply

    prof = LearnerProfile(user_id="u1")
    report = sess.finish(profile=prof)

    assert report["requirement_sheet"]["items"], "应有需求单条目"
    assert report["requirement_sheet"]["missing"], "应识别缺失项"
    assert report["scores"], "应有评分"
    assert all(s["evidence"] for s in report["scores"]), "每分必须有证据"
    assert report["average"] > 0

    # 画像写回
    assert prof.values()["C2.2"] == 65.0
    assert "C2.2" in prof.weak_points()


def test_s2_score_without_evidence_is_rejected():
    from tripcraft.agents.scorer import ScoreResult

    bad = ScoreResult(skill_point_id="C2.2", level="M2", score=65, evidence=[])
    try:
        bad.validate()
        raise AssertionError("缺证据应报错")
    except ValueError:
        pass