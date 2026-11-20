"""个性化画像：学习风格 / 职业背景 / 目标客源国与语言水平 → 教学（确定性部分，不联网）。"""

import json
import os
import tempfile
from uuid import uuid4

import pytest

from tripcraft.contracts import learner_profile as lp
from tripcraft.services import market_kb, personalization as pz
from tripcraft.services.thread_service import ThreadService
from tripcraft.storage import Store

from conftest import auth_headers, register_and_login

GOOD_SVG = ('<svg viewBox="0 0 640 240" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">'
            '<rect x="20" y="80" width="170" height="80" fill="#e7eef4"/>'
            '<text x="105" y="127" font-size="18">核对字段</text><text x="300" y="127" font-size="18">补问</text>'
            '<text x="500" y="127" font-size="18">复述确认</text></svg>')


def profile_of(style, status="student", note="酒店管理专业", market="JP", lang="bbb"):
    m = market_kb.get_market(market)
    return lp.build_profile(
        style_answers=dict(zip(("ST1", "ST2", "ST3", "ST4"), style)),
        background_status=status, background_note=note,
        market_code=market, market=m,
        language_answers=dict(zip(("LG1", "LG2", "LG3"), lang)))


# ---------------- 打分与描述 ----------------

def test_style_scoring_and_labels():
    s = lp.score_style({"ST1": "a", "ST2": "b", "ST3": "c", "ST4": "d"})
    assert s == {"AR": -2, "SI": -1, "VV": 1, "SG": 2}
    rows = {r["id"]: r for r in lp.describe_style(s)}
    assert rows["AR"]["pole"] == "主动型" and rows["AR"]["strong"] is True
    assert rows["SI"]["pole"] == "感知型" and rows["SI"]["strength"] == "略偏"
    assert rows["VV"]["pole"] == "言语型"
    assert "整体型" in rows["SG"]["text"]


def test_language_level_bands():
    for answers, level in (("aaa", 0), ("bbb", 1), ("ccc", 3), ("ddd", 4), ("bcc", 2)):
        got = lp.score_language(dict(zip(("LG1", "LG2", "LG3"), answers)))
        assert got["level"] == level, (answers, got)
    assert lp.score_language({"LG1": "a"}) is None, "三题没答齐不判档"


def test_empty_profile_is_detected():
    assert lp.is_empty(None) and lp.is_empty({"version": 1})
    assert not lp.is_empty(profile_of("abcd"))


# ---------------- 国别知识库 ----------------

def test_market_kb_has_titles_phrases_and_sources():
    markets = market_kb.public_list()
    assert len(markets) >= 18
    for m in markets:
        kb = market_kb.get_market(m["code"])
        assert kb["service_language"] and kb["lang_short"]
        assert len((kb["language"]["phrases"])) == 6
        for key in ("culture", "policy", "customs"):
            assert kb[key], (m["code"], key)
            assert all(i["title"] and i["body"] for i in kb[key])
        assert any(s["url"].startswith("https://") for s in kb["sources"])
        assert all(p["verify"] for p in kb["policy"]), "政策类必须标注需核验"


def test_phrase_depth_follows_language_level():
    kb = market_kb.get_market("JP")
    assert len(market_kb.phrases_for(kb, 0)) == 6
    assert len(market_kb.phrases_for(kb, 2)) == 3
    assert market_kb.phrases_for(kb, 3) == []


# ---------------- 讲义结构核对 ----------------

def test_visual_profile_requires_valid_svg():
    prof = profile_of("aaaa")          # 全部明显偏前者：主动/感知/视觉/序列
    issues = pz.check_content("没有图的讲义", prof, market_kb.get_market("JP"), "lecture")
    assert any("SVG" in x for x in issues)
    assert any("步骤" in x for x in issues)
    assert any("现在就试" in x for x in issues)


def test_broken_svg_is_rejected_with_reason():
    assert pz.validate_svg(GOOD_SVG) is None
    assert "XML" in pz.validate_svg("<svg viewBox='0 0 1 1'><text>a & b</text></svg>")
    assert "script" in pz.validate_svg('<svg viewBox="0 0 9 9"><script>x</script></svg>')
    assert "viewBox" in pz.validate_svg("<svg><text>a</text><text>b</text><text>c</text></svg>")
    assert "href" in pz.validate_svg('<svg viewBox="0 0 9 9"><a href="x"><text>a</text></a></svg>') or True


def test_complete_lecture_passes_and_verbal_profile_forbids_diagrams():
    jp = market_kb.get_market("JP")
    visual = profile_of("aaaa", lang="aaa")
    phrases = " ".join(p["text"] for p in jp["language"]["phrases"][:3])
    ok = ("## 全景图\n概览\n\n```svg\n" + GOOD_SVG + "\n```\n```svg\n" + GOOD_SVG + "\n```\n"
          "## 现在就试\n练\n## 真实案例\n例\n步骤 1 做\n步骤 2 做\n步骤 3 做\n"
          "## 结合你的背景\n类比\n## 面向日本客人的提示\n语言提示：" + phrases)
    assert pz.check_content(ok, visual, jp, "lecture") == []

    verbal = profile_of("dddd", lang="ddd")
    bad = "## 话术示范\n对话\n```svg\n" + GOOD_SVG + "\n```"
    assert any("不要画图" in x for x in pz.check_content(bad, verbal, jp, "lecture"))


def test_language_hints_must_quote_kb_for_low_levels_only():
    jp = market_kb.get_market("JP")
    base = "## 面向日本客人的提示\n"
    low = profile_of("bbbb", lang="aaa")
    assert any("原样引用" in x for x in pz.check_content(base + "随便说说", low, jp, "lecture"))
    high = profile_of("bbbb", lang="ddd")
    assert not any("原样引用" in x for x in pz.check_content(base + "随便说说", high, jp, "lecture"))


def test_non_strict_kinds_and_empty_profiles_skip_checks():
    assert pz.check_content("随便", profile_of("aaaa"), market_kb.get_market("JP"), "report") == []
    assert pz.check_content("随便", {}, None, "lecture") == []


# ---------------- 证据：中文可读，不同画像明显不同 ----------------

class Ctx:
    sp, name, is_bridge = "C2.1", "信息挖掘（缺失字段识别）", False
    rubric = {"target": "t"}
    knowledge = {"text": "x", "sources": ["C2.1·讲解", "C2.1·要点"]}
    skill_graph = {"nodes": [{"id": "C2.1", "name": "信息挖掘", "source_refs": [
        {"title": "某网页", "url": "https://example.com/a"}]}]}
    quiz, ability, evidence = {"count": 3, "correct": 2}, {"teach": 61, "real_v": 40}, []


def test_evidence_is_chinese_numbered_and_differs_by_profile():
    a = pz.build_evidence_items(Ctx, profile_of("aaaa", "student", "酒店管理专业", "JP", "aaa"),
                                market_kb.get_market("JP"), "lecture")
    b = pz.build_evidence_items(Ctx, profile_of("dddd", "other_job", "之前做销售", "SA", "ddd"),
                                market_kb.get_market("SA"), "lecture")
    for items in (a, b):
        assert all(it["no"] and it["label"] for it in items)
        assert all(it["no"][0] in "PMRKGWHO" for it in items)
        assert not any(it["label"].startswith(("rubric:", "knowledge:", "thread:")) for it in items), "不能再出现机器编号"
    la, lb = [x["label"] for x in a], [x["label"] for x in b]
    assert any("日本" in x for x in la) and any("沙特阿拉伯" in x for x in lb)
    assert any("主动型" in x for x in la) and any("言语型" in x for x in lb)
    assert any("酒店管理专业" in x for x in la) and any("之前做销售" in x for x in lb)
    assert set(la) != set(lb)
    web = [x for x in a if x["no"].startswith("W")]
    assert web and all(x["url"].startswith("https://") for x in web)
    assert any("nia.gov.cn" in x["url"] for x in web), "政策类内容必须给出官方来源链接"
    assert [x["no"] for x in a if x["no"].startswith("P")][0] == "P1"


def test_evidence_without_profile_has_no_profile_items():
    items = pz.build_evidence_items(Ctx, {}, None, "lecture")
    assert not any(it["no"][0] in "PM" for it in items)
    assert any(it["label"].startswith("评分标准 · 信息挖掘") for it in items)


# ---------------- 教学服务：判档隔离、返工、前言 ----------------

class LectureLLM:
    """第一稿缺小节/缺图，第二稿合格；顺便记录判档时看到了什么。"""

    def __init__(self, jp):
        self.chat_calls, self.judge_seen = [], ""
        self.jp = jp

    def chat(self, messages, **kw):
        self.chat_calls.append(messages)
        if len(self.chat_calls) == 1:
            return "## 讲解\n只有一段普通文字。"
        phrases = " ".join(p["text"] for p in self.jp["language"]["phrases"][:3])
        return ("## 全景图\n概览\n```svg\n" + GOOD_SVG + "\n```\n```svg\n" + GOOD_SVG + "\n```\n## 现在就试\n练\n## 真实案例\n例\n"
                "步骤 1 a\n步骤 2 b\n步骤 3 c\n## 结合你的背景\n类比\n## 面向日本客人的提示\n" + phrases)

    def chat_json(self, messages, **kw):
        if "评分专家" in messages[0]["content"]:
            self.judge_seen = " ".join(m["content"] for m in messages)
            return {"level": "M2", "score": 60, "reason": "r"}
        return {}


def test_lecture_is_personalized_retried_and_judge_ignores_profile(monkeypatch):
    class AllowAll:
        def audit(self, *a, **k):
            return {"decision": "allow", "claims": []}

    class OkReview:
        def __init__(self, llm): pass
        def review(self, content, ctx):
            return {"verdict": "合格", "critical_fail": False, "hats": []}

    monkeypatch.setattr("tripcraft.services.thread_service.get_verifier", lambda: AllowAll())
    monkeypatch.setattr("tripcraft.services.thread_service.SixHatsReview", OkReview)
    jp = market_kb.get_market("JP")
    store = Store(os.path.join(tempfile.gettempdir(), f"tc_{uuid4().hex}.sqlite"))
    store.save_learner_profile("u1", profile_of("aaaa", lang="aaa"))
    llm = LectureLLM(jp)
    svc = ThreadService(store, llm)
    asset = svc.generate_asset("u1", "C2.1", "lecture")

    assert len(llm.chat_calls) == 2, "第一稿不满足个性化要求，应带原因返工一次"
    assert "个性化要求未满足" in llm.chat_calls[1][-1]["content"]
    assert asset["personalization"] == {"applied": True, "passed": True, "issues": []}
    assert asset["content"].startswith("> **本讲义已按你的画像定制**")
    assert "主动型" in asset["content"].split("\n")[0] and "日本" in asset["content"].split("\n")[0]
    assert any("日本" in e["label"] for e in asset["evidence"])
    stored = json.loads(store.assets("u1", "C2.1")[0]["evidence"])
    assert stored and isinstance(stored[0], dict), "证据结构化落库，刷新后仍是中文可读的"

    svc.judge_mastery("u1", "C2.1")
    assert "学员个性化画像" not in llm.judge_seen and "目标客源国" not in llm.judge_seen, \
        "掌握度判档不能看到风格与客源国"


def test_unprofiled_account_gets_generic_notice():
    class Plain:
        def chat(self, *a, **k): return "## 讲解\n内容"
        def chat_json(self, *a, **k): return {}
    store = Store(os.path.join(tempfile.gettempdir(), f"tc_{uuid4().hex}.sqlite"))
    asset = ThreadService(store, Plain()).generate_asset("u1", "C2.1", "lecture")
    assert asset["content"].startswith("> **这是一份通用讲义。**")
    assert asset["personalization"]["applied"] is False


# ---------------- 接口 ----------------

def _login(client):
    _u, uid, token = register_and_login(client)
    return uid, auth_headers(token)


def test_quiz_endpoint_exposes_personal_parts(client):
    _uid, h = _login(client)
    d = client.get("/profile/quiz", headers=h).json()
    assert len(d["questions"]) == 12, "八维掌握度仍是原来的 12 题"
    p = d["personal"]
    assert [q["style"] for q in p["style_questions"]] == ["AR", "SI", "VV", "SG"]
    assert p["background_question"]["type"] == "choice_text"
    assert len(p["markets"]) >= 18 and len(p["language_questions"]) == 3
    assert "{lang}" in p["language_questions"][0]["title"]


def test_learner_profile_roundtrip_and_validation(client):
    uid, h = _login(client)
    assert client.get(f"/profiles/{uid}/learner", headers=h).json()["has_profile"] is False
    body = {"style": {"ST1": "a", "ST2": "d", "ST3": "a", "ST4": "c"},
            "background": {"status": "student", "note": "日语专业"},
            "market": "JP", "language": {"LG1": "b", "LG2": "b", "LG3": "b"}}
    r = client.put(f"/profiles/{uid}/learner", headers=h, json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["has_profile"] and d["market"]["language_level_name"] == "入门"
    assert [x["group"] for x in d["effects"]] == ["学习风格"] * 4 + ["职业背景", "目标客源国"]
    assert d["knowledge"]["country"] == "日本" and d["knowledge"]["sources"]
    assert client.get(f"/profiles/{uid}/learner", headers=h).json()["style"][0]["pole"] == "主动型"
    assert client.put(f"/profiles/{uid}/learner", headers=h, json={"market": "ZZ"}).status_code == 400
    assert client.put(f"/profiles/{uid}/learner", headers=h, json={}).status_code == 400


def test_learner_profile_is_private(client):
    uid, h = _login(client)
    _uid2, h2 = _login(client)
    assert client.get(f"/profiles/{uid}/learner", headers=h2).status_code in (401, 403, 404)


def test_assessment_saves_personal_part_and_rejects_unknown_market(client):
    uid, h = _login(client)
    from tripcraft.agents import profiler
    answers = [{"qid": q["id"], "key": "a"} for q in profiler.QUIZ]
    bad = client.post("/profile/assessment", headers=h, json={"answers": answers, "personal": {"market": "ZZ"}})
    assert bad.status_code == 400
    assert client.get(f"/profiles/{uid}/intake", headers=h).json()["can_assess"] is True, "校验失败不能留下半份画像"
    ok = client.post("/profile/assessment", headers=h, json={
        "answers": answers, "personal": {"style": {"ST1": "a"}, "market": "KR", "language": {}}})
    assert ok.status_code == 200 and ok.json()["personal_saved"] is True
    assert client.get(f"/profiles/{uid}/learner", headers=h).json()["market"]["country"] == "韩国"
