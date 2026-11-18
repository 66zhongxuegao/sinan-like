"""线程服务测试（mock LLM，不联网、不花钱）。"""

import os

import pytest
import tempfile
from uuid import uuid4

from tripcraft.services.thread_service import ThreadService
from tripcraft.storage import Store


class FakeLLM:
    def chat(self, messages, **kwargs):
        return "## 讲解\n\n预算是硬约束，要问清**人均/总价**和区间。\n\n<div class=\"refs\">参考来源：Rubric C2.2</div>"

    def chat_json(self, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        if "评分专家" in system:
            return {"level": "M3", "score": 75, "reason": "问到人均但没核区间"}
        if "实战出题老师" in system or "出题" in system:
            return {"type": "choice", "stem": "客户说性价比高，你应该？",
                    "options": ["直接做方案", "追问人均/总价与区间", "报最低价", "先加微信"],
                    "answer": "B", "explain": "预算属硬约束"}
        if "实战评判老师" in system or "评判" in system:
            return {"correct": True, "reason": "覆盖了预算三问"}
        return {}


def make():
    p = os.path.join(tempfile.gettempdir(), f"tc_{uuid4().hex}.sqlite")
    store = Store(p)
    store.set_ability("u1", "C2.2", teach=60, real_v=40)
    store.upsert_order("9000000000000001", "u1", "客户 A", "江苏", "正常", 1)
    return ThreadService(store, FakeLLM()), store


def tid(store, user_id: str, sp: str) -> str:
    """线程 ID 现在按「用户 + 技能点」唯一（旧写法 `thread:<技能点>` 会跨账号串数据）。"""
    return store.get_or_create_thread(user_id, sp)["thread_id"]


def test_context_has_six_sources():
    svc, _ = make()
    ctx = svc.build_context("u1", "C2.2")
    text = ctx.render()
    assert "Rubric" in text
    assert "知识点基座" in text or ctx.knowledge == {}
    assert "画像掌握度" in text
    assert "实战证据" in text
    src = ctx.sources()
    assert any(s.startswith("rubric:") for s in src)
    assert any(s.startswith("thread:") for s in src)
    assert any(s.startswith("quiz:") for s in src)


def test_reply_saves_message_and_evidence():
    svc, store = make()
    r = svc.reply("u1", "C2.2", "预算这块怎么问？")
    assert "预算" in r["content"]
    assert r["evidence"], "回复必须带来源"
    msgs = store.messages(tid(store, "u1", "C2.2"))
    assert [m["role"] for m in msgs] == ["user", "ai"]


def test_generate_asset_and_list():
    svc, store = make()
    a = svc.generate_asset("u1", "C2.2", "lecture")
    assert a["type"] == "lecture" and a["content"]
    assert store.assets("u1", "C2.2"), "资产应已入库"


def test_pick_question_follows_judged_level():
    svc, _ = make()
    q = svc.pick_question("u1", "C2.2")
    assert q["type"] == "choice"
    assert q["judged_level"] == "M3"
    assert q["difficulty"] == "L3", "M3 应对应 L3 难度（L1–L5 五档）"


def right_answer(store, q) -> str:
    """正确答案位置由服务端随机指定，测试从服务端题库读取，而不是假设固定是 B。"""
    return store.quiz_question(q["question_id"])["answer"]


def wrong_answer(store, q) -> str:
    return next(x for x in "ABCD" if x != right_answer(store, q))


def test_submit_answer_updates_mastery():
    svc, store = make()
    q = svc.pick_question("u1", "C2.2")
    r = svc.submit_answer("u1", "C2.2", q, right_answer(store, q))
    assert r["correct"] is True
    assert r["teach"] > 60, "答对应提升教学掌握度"
    assert len(store.attempts("u1", "C2.2")) == 1


def test_submit_wrong_triggers_reteach():
    svc, store = make()
    q = svc.pick_question("u1", "C2.2")
    r = svc.submit_answer("u1", "C2.2", q, wrong_answer(store, q))
    assert r["correct"] is False
    assert r["reteach"] is True
    assert store.memories("u1"), "答错应写入记忆"

# ---------------- 文化桥：教师必须知道这是什么技能 ----------------

def test_bridge_context_carries_name_and_content():
    svc, _ = make()
    ctx = svc.build_context("u1", "US", query="跨文化沟通")
    text = ctx.render()
    assert ctx.is_bridge is True
    assert ctx.name == "中美文化桥"
    assert "【本次技能点】中美文化桥（US）" in text, "教师必须知道技能点叫什么"
    assert "共通点" in text, "文化桥底座要进上下文，否则教师没有资料可讲"
    assert any(s.startswith("bridge:") for s in ctx.sources())
    assert not any(s.startswith("rubric:") for s in ctx.sources()), "文化桥没有 M1–M5 锚点"


def test_skill_context_still_reports_rubric():
    svc, _ = make()
    ctx = svc.build_context("u1", "C2.2")
    assert ctx.is_bridge is False
    assert "【本次技能点】" in ctx.render()
    assert any(s.startswith("rubric:") for s in ctx.sources())


def test_route_intent():
    assert ThreadService.route_intent("给我生成一份讲义。") == ("asset", "lecture")
    assert ThreadService.route_intent("把我这个技能点的错题整理成错题本。") == ("asset", "wrong_book")
    assert ThreadService.route_intent("出一道这个技能点的题给我练。") == ("quiz", "")
    assert ThreadService.route_intent("预算怎么问才不冒犯？") == ("chat", "")


def test_chat_routes_asset_and_saves_it():
    svc, store = make()
    r = svc.chat("u1", "C2.2", "给我生成一份讲义。")
    assert r["kind"] == "asset"
    assert r["asset"]["type"] == "lecture"
    assert store.assets("u1", "C2.2"), "生成的资源要进个性资源栏"
    roles = [m["role"] for m in store.messages(tid(store, "u1", "C2.2"))]
    assert roles == ["user", "ai"], "学员那句话也要留在会话里"


def test_chat_routes_quiz():
    svc, store = make()
    r = svc.chat("u1", "C2.2", "出一道这个技能点的题给我练。")
    assert r["kind"] == "quiz"
    assert r["quiz"]["type"] == "choice"
    assert [m["role"] for m in store.messages(tid(store, "u1", "C2.2"))] == ["user", "ai"]


def test_chat_plain_question_stays_chat():
    svc, store = make()
    r = svc.chat("u1", "C2.2", "预算这块怎么问？")
    assert r["kind"] == "chat"
    assert "预算" in r["content"]


# ---------------- 题卡进聊天记录：每道题各一张，答过的可回看 ----------------

def test_quiz_is_stored_as_structured_message():
    svc, store = make()
    r = svc.chat("u1", "C2.2", "出一道题给我练。")
    assert r["kind"] == "quiz"
    rows = store.messages(tid(store, "u1", "C2.2"))
    kinds = [m["kind"] for m in rows]
    assert "quiz" in kinds, "题目要作为 kind=quiz 的消息落库"
    card = [m for m in rows if m["kind"] == "quiz"][-1]
    assert r["quiz"]["question_id"] in card["payload"], "题目本体要存在 payload 里"


def test_answer_result_is_attached_by_question_id():
    svc, store = make()
    q = svc.pick_question("u1", "C2.2")
    svc.submit_answer("u1", "C2.2", q, "B")
    rows = store.messages(tid(store, "u1", "C2.2"))
    res = [m for m in rows if m["kind"] == "quiz_result"]
    assert res, "判分结果要落库，否则刷新后题卡变回未作答"
    assert q["question_id"] in res[-1]["payload"]


def test_snapshot_exposes_kind_and_payload():
    svc, _ = make()
    svc.chat("u1", "C2.2", "出一道题给我练。")
    snap = svc.snapshot("u1", "C2.2")
    quizes = [m for m in snap["messages"] if m.get("kind") == "quiz"]
    assert quizes and quizes[-1]["payload"], "快照要带 kind/payload，前端才能重建题卡"


# ---------------- 竞赛技术闭环：技能图 / 证据治理 / BKT / 反馈回流 ----------------

def test_context_carries_skill_graph_and_source_trust_levels():
    svc, _ = make()
    ctx = svc.build_context("u1", "C2.2", knowledge={"text": "预算要确认人均与总价。", "sources": []})
    node_ids = {n["id"] for n in ctx.skill_graph.get("nodes", [])}
    assert {"C2.1", "C2.2"} <= node_ids
    assert "技能图约束" in ctx.render()
    rows = ctx.evidence_payload()
    assert any(r["trust"] == "curated" and r["source"].startswith("rubric:") for r in rows)
    assert any(r["trust"] == "teaching" and r["source"].startswith("knowledge:") for r in rows)
    assert any(r["trust"] == "observed" and r["source"].startswith("order:") for r in rows)


def test_generate_asset_exposes_claim_audit_and_attempt_count():
    svc, store = make()
    asset = svc.generate_asset("u1", "C2.2", "lecture")
    assert asset["evidence_audit"]["method"] == "deterministic_lexical_numeric_gate_v2"
    assert asset["evidence_audit"]["source_policy"] == "high_risk_requires_official_curated_or_observed"
    assert asset["review"]["attempts"] >= 1


def test_answer_writes_one_learning_signal_and_rejects_duplicate_submission():
    from tripcraft.services.thread_service import QuizQuestionAnswered

    svc, store = make()
    q = svc.pick_question("u1", "C2.2")
    first = svc.submit_answer("u1", "C2.2", q, "B")
    assert first["diagnosis"]["method"].startswith("BKT")
    assert first["learning_signal"]["skill_point_id"] == "C2.2"
    signals = [m for m in store.memories("u1", limit=50) if m["type"] == "learning_signal"]
    assert len(signals) == 1

    with pytest.raises(QuizQuestionAnswered):
        svc.submit_answer("u1", "C2.2", q, "B")
    signals = [m for m in store.memories("u1", limit=50) if m["type"] == "learning_signal"]
    assert len(signals) == 1


def test_asset_audit_is_recomputed_on_final_draft_not_first_draft():
    class RejectFirstDraftLLM:
        def __init__(self):
            self.chat_calls = []

        def chat(self, messages, **kwargs):
            self.chat_calls.append(messages)
            content = "签证需要提供邀请函。"
            if len(self.chat_calls) > 1:
                content = "预算是硬约束，要问清人均/总价和区间。"
            return content

        def chat_json(self, messages, **kwargs):
            return {"verdict": "通过", "note": "按材料审查"}

    p = os.path.join(tempfile.gettempdir(), f"tc_audit_{uuid4().hex}.sqlite")
    store = Store(p)
    store.set_ability("u1", "C2.2", teach=60, real_v=40)
    store.upsert_order("9000000000000011", "u1", "客户 B", "江苏", "正常", 1)
    svc = ThreadService(store, RejectFirstDraftLLM())
    asset = svc.generate_asset("u1", "C2.2", "lecture")
    assert asset["review"]["attempts"] == 2
    assert "人均" in asset["content"]
    assert asset["evidence_audit"]["decision"] == "allow"
    assert all("签证" not in c["claim"] for c in asset["evidence_audit"]["claims"])


# ---------------- 出题难度规格：干扰条件 / 约束 / 题干长度 / 选项近似度 ----------------

from tripcraft.contracts.quiz_difficulty import (  # noqa: E402
    QUIZ_DIFFICULTY, place_answer, spec_for, text_len, validate_question,
)


def _good_question(level: str) -> dict:
    """按规格拼一道合格题（用于校验器正向用例）。"""
    spec = spec_for(level)
    distractors = [f"客户顺口提到第{i}件和本次决策无关的小事情" for i in range(spec.distractors)]
    body = "客户张女士一家四口计划十月去云南，预算人均八千元，老人行动不便需要少走路。" + "".join(distractors)
    while text_len(body) < spec.stem_min:
        body += "她在电话里反复确认出发日期和住宿位置。"
    stem = body + "此时你最应该先做什么？"
    opt = "先电话确认预算口径与老人身体情况，再据此推荐{}"
    return {"type": "choice", "stem": stem,
            "options": [opt.format(x) for x in ("一号方案", "二号方案", "三号方案", "四号方案")],
            "answer": "C", "explain": "选C，因为先确认约束。",
            "design": {"distractor_conditions": distractors,
                       "key_constraints": [f"约束{i}" for i in range(spec.constraints)],
                       "option_traps": {"A": "a", "B": "b", "C": "", "D": "d"},
                       "answer_basis": "约束0 决定先确认再推荐；B 违反约束1"}}


def test_difficulty_spec_is_strictly_increasing():
    levels = [QUIZ_DIFFICULTY[f"L{i}"] for i in range(1, 6)]
    for lo, hi in zip(levels, levels[1:]):
        assert hi.stem_min > lo.stem_min, "题干长度要随难度递增"
        assert hi.distractors >= lo.distractors and hi.constraints >= lo.constraints
        assert hi.option_ratio < lo.option_ratio, "选项近似度要随难度收紧"
    assert levels[-1].distractors > levels[0].distractors


def test_validator_accepts_spec_compliant_question():
    for lv in ("L1", "L3", "L5"):
        assert validate_question(_good_question(lv), spec_for(lv)) == [], lv


def test_validator_catches_three_short_one_long():
    q = _good_question("L3")
    q["options"] = ["直接报价给客户确认一下", "先加微信再说吧好不好", "马上发送行程方案过去",
                    "先电话确认预算口径、老人身体情况和出发日期，再按约束筛选两套方案推荐并说明取舍理由"]
    q["answer"] = "D"
    issues = validate_question(q, spec_for("L3"))
    assert any("长短差距" in x for x in issues)
    assert any("可以靠长度猜对" in x for x in issues)


def test_validator_requires_distractors_written_into_stem():
    q = _good_question("L4")
    q["design"]["distractor_conditions"] = ["这句话根本没有出现在题干里面"] * 3
    assert any("干扰条件" in x for x in validate_question(q, spec_for("L4")))


def test_validator_rejects_short_stem_and_internal_words():
    q = _good_question("L5")
    q["stem"] = "客户要去云南，按 M3 档位你怎么做？"
    issues = validate_question(q, spec_for("L5"))
    assert any("题干只有" in x for x in issues)
    assert any("内部评分词" in x for x in issues)


def test_place_answer_moves_correct_option_and_rewrites_explain():
    q = _good_question("L2")
    q["options"][2] = "正确做法"
    out = place_answer(q, "A")
    assert out["answer"] == "A" and out["options"][0] == "正确做法"
    assert "选A" in out["explain"]
    assert out["design"]["option_traps"]["C"] == "a", "错项陷阱说明要跟着选项一起换位"


def test_pick_question_retries_with_issue_list_and_hides_design():
    class StrictLLM(FakeLLM):
        def __init__(self):
            self.question_calls = []

        def chat_json(self, messages, **kwargs):
            system = messages[0]["content"] if messages else ""
            if "实战出题老师" in system:
                self.question_calls.append(messages)
                if len(self.question_calls) == 1:
                    return {"type": "choice", "stem": "太短", "options": ["a", "b", "c", "很长很长很长很长的选项"],
                            "answer": "D", "explain": ""}
                return _good_question("L3")
            return super().chat_json(messages, **kwargs)

    import random
    store = Store(os.path.join(tempfile.gettempdir(), f"tc_{uuid4().hex}.sqlite"))
    llm = StrictLLM()
    svc = ThreadService(store, llm, rng=random.Random(7))
    q = svc.pick_question("u1", "C2.2")
    assert len(llm.question_calls) == 2, "第一稿不合格应带问题清单重出一次"
    assert "上一稿不符合难度规格" in llm.question_calls[1][-1]["content"]
    assert "design" not in q and "quality" not in q and "answer" not in q, "出题留档不能下发"
    stored = __import__("json").loads(store.quiz_question(q["question_id"])["payload"])
    assert stored["quality"]["passed"] is True and stored["quality"]["attempts"] == 2
    assert stored["design"]["distractor_conditions"], "服务端保留干扰条件清单以便抽查"
    assert stored["answer"] == store.quiz_question(q["question_id"])["answer"]


def test_answer_position_is_spread_across_letters():
    import random
    svc, store = make()
    svc._rng = random.Random(3)
    letters = {right_answer(store, svc.pick_question("u1", "C2.2")) for _ in range(12)}
    assert len(letters) >= 3, "正确答案不能总在同一个位置"


def test_validator_requires_answer_basis_for_near_identical_options():
    q = _good_question("L4")
    q["design"].pop("answer_basis")
    assert any("answer_basis" in x for x in validate_question(q, spec_for("L4")))
