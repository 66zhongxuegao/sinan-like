"""派单竞争与时限测试（离线，时间可控）。"""

import os
import tempfile
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from tripcraft.services import dispatch_service as dispatch
from tripcraft.services.practice_service import PracticeService
from tripcraft.storage import Store

ORDER = "9000000000000006"


def make():
    store = Store(os.path.join(tempfile.gettempdir(), f"dp_{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    practice.seed("u-demo")
    return store, practice


def _payload(order_id: str) -> dict:
    import json
    return json.loads(Store.__dict__ and "" or "{}")


# ---------------- 纯函数：派单状态 ----------------

def test_status_within_window_is_not_lost():
    base = datetime(2026, 10, 8, 9, 0, 0)
    info = dispatch.status(ORDER, base.isoformat(), {"dispatch_at": base.isoformat()},
                           grabbed=False, now=base + timedelta(minutes=1))
    assert info["lost"] is False and info["expired"] is False
    assert info["seconds_left"] > 0
    assert info["rivals"] >= 2
    assert 0 < info["rival_eta_min"] <= info["window_min"]


def test_status_after_rival_claim_is_lost():
    base = datetime(2026, 10, 8, 9, 0, 0)
    rival = dispatch.rival_claim_at(ORDER, base)
    info = dispatch.status(ORDER, base.isoformat(), {"dispatch_at": base.isoformat()},
                           grabbed=False, now=rival + timedelta(seconds=1))
    assert info["lost"] is True and info["expired"] is True
    assert "接走" in info["lost_reason"]


def test_rival_eta_is_deterministic_and_near_window_end():
    base = datetime(2026, 10, 8, 9, 0, 0)
    a = dispatch.rival_claim_at(ORDER, base)
    b = dispatch.rival_claim_at(ORDER, base)
    assert a == b, "同一订单的竞争者时点必须稳定"
    cfg = dispatch._env()
    assert 0.75 <= (a - base).total_seconds() / 60 / cfg["DISPATCH_WINDOW_MIN"] <= 0.95


def test_claimed_status_exposes_first_call_and_plan_deadlines():
    base = datetime(2026, 10, 8, 9, 0, 0)
    grab = base + timedelta(minutes=3)
    info = dispatch.status(ORDER, base.isoformat(),
                           {"dispatch_at": base.isoformat(), "grabbed_at": grab.isoformat()},
                           grabbed=True, first_call_at=None, now=grab)
    assert info["seconds_left"] == 0, "已认领后抢单窗口不再是关注点"
    assert info["first_call"]["limit_min"] == 60
    assert info["first_call"]["done"] is False and info["first_call"]["missed"] is False
    assert info["plan"]["limit_min"] == 240


def test_first_call_after_limit_is_marked_missed():
    base = datetime(2026, 10, 8, 9, 0, 0)
    grab = base + timedelta(minutes=1)
    info = dispatch.status(ORDER, base.isoformat(),
                           {"dispatch_at": base.isoformat(), "grabbed_at": grab.isoformat()},
                           grabbed=True, now=grab + timedelta(minutes=90))
    assert info["first_call"]["missed"] is True


@pytest.mark.parametrize("call_minutes,missed", [(30, False), (60, False), (90, True)])
def test_completed_first_call_preserves_actual_timeliness(call_minutes, missed):
    grab = datetime(2026, 10, 8, 9, 0, 0)
    info = dispatch.status(
        ORDER, grab.isoformat(), {"grabbed_at": grab.isoformat()}, grabbed=True,
        first_call_at=(grab + timedelta(minutes=call_minutes)).isoformat(),
        now=grab + timedelta(hours=5),
    )
    assert info["first_call"]["done"] is True
    assert info["first_call"]["missed"] is missed


# ---------------- 服务层：惰性判负与抢单守卫 ----------------

def test_dispatch_is_armed_on_first_read():
    store, practice = make()
    assert not practice._payload(ORDER).get("dispatch_at")
    info = practice.dispatch_info(ORDER)
    assert info["dispatch_at"] and practice._payload(ORDER).get("dispatch_at")
    assert practice.get_order(ORDER)["status"] == "正常"


def test_lost_order_is_marked_and_cannot_be_grabbed():
    store, practice = make()
    practice._set_payload(ORDER, dispatch_at=(datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"))
    info = practice.dispatch_info(ORDER)
    assert info["lost"] is True
    assert practice.get_order(ORDER)["status"] == "已派他人"
    assert [e["type"] for e in store.events(ORDER)] == ["dispatch_lost"]
    try:
        practice.record_action(ORDER, "grab")
        raise AssertionError("丢单后不应允许抢单")
    except ValueError as exc:
        assert "接走" in str(exc)


def test_grab_records_grabbed_at_and_blocks_double_grab():
    store, practice = make()
    out = practice.record_action(ORDER, "grab")
    assert out["recorded"] is True
    assert practice._payload(ORDER).get("grabbed_at")
    again = practice.record_action(ORDER, "grab")
    assert again["recorded"] is False
    assert practice.dispatch_info(ORDER)["claimed"] is True


def test_missed_first_call_writes_deadline_event_once():
    store, practice = make()
    practice.record_action(ORDER, "grab")
    practice._set_payload(ORDER, grabbed_at=(datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds"))
    practice.dispatch_info(ORDER)
    assert store.has_action(ORDER, "deadline_miss:first_call")
    events = [e["type"] for e in store.events(ORDER)]
    assert events.count("deadline_miss") == 1
    practice.dispatch_info(ORDER)
    assert [e["type"] for e in store.events(ORDER)].count("deadline_miss") == 1, "不应重复记账"


def test_available_orders_are_the_unclaimed_dispatches():
    store, practice = make()
    avail = practice.available_orders("u-demo")
    ids = {o["order_id"] for o in avail}
    assert ORDER in ids, "未抢的阶段 0 派单应出现在可抢列表"
    assert not any(o["stage_index"] for o in avail), "可抢列表只放阶段 0 的单"
    for o in avail:
        assert o["dispatch"] and o["dispatch"]["claimed"] is False
        assert o["missing_fields"], "派单信息应列出缺失字段供首呼补问"

    # 抢了之后：从可抢列表消失、进入我的订单
    practice.record_action(ORDER, "grab")
    assert ORDER not in {o["order_id"] for o in practice.available_orders("u-demo")}
    assert ORDER in {o["order_id"] for o in practice.list_orders("u-demo")}


def test_unpublished_candidates_stay_hidden_until_due():
    store, practice = make()
    later = [oid for oid in ("9000000000000007", "9000000000000008",
                             "9000000000000009", "9000000000000010")]
    avail = {o["order_id"] for o in practice.available_orders("u-demo")}
    assert not (set(later) & avail), "未到放出时间的候选单不应出现在消息中心"

    practice._set_payload(later[0], publish_at=(datetime.now() - timedelta(seconds=1))
                          .isoformat(timespec="seconds"))
    avail = {o["order_id"] for o in practice.available_orders("u-demo")}
    assert later[0] in avail, "到点后应放出"
    assert [e["type"] for e in store.events(later[0])] == ["dispatch_published"]
    assert practice._payload(later[0]).get("dispatch_at"), "放出即开始抢单窗口"

# ---------------- 客源语言：语言与难度解耦（D-064） ----------------

def test_markets_for_language():
    """指定语言只给说这门语言的客源；随机给全部 23 个市场。"""
    from tripcraft.agents.scenario import LANGUAGES, SOURCE_MARKETS, markets_for
    assert "English" in LANGUAGES and "中文" in LANGUAGES
    assert set(markets_for("English")) == {"美国", "英国", "澳大利亚", "印度"}
    assert {"香港", "澳门", "台湾"} <= set(markets_for("中文"))
    allm = markets_for("")
    assert len(allm) == len(SOURCE_MARKETS) and "美国" in allm and "香港" in allm
    assert markets_for("Klingon") == allm          # 不存在的语言退回全部，不炸


def test_every_language_has_a_voice_profile():
    """下拉里的每门语言都必须能落到语音链路的语言码 + 音色，否则外语单没法打电话。"""
    from tripcraft.agents.scenario import LANGUAGES
    from tripcraft.voice.bridge import lang_code
    from tripcraft.voice.language_profiles import VOICE_LANG, pick_voice
    assert len(LANGUAGES) == 15
    for lang in LANGUAGES:
        code = lang_code(lang)
        assert code != "zh" or lang == "中文", lang       # 不能静默退回中文
        assert code in VOICE_LANG, lang
        for gender in ("男", "女"):
            assert pick_voice(code, gender), (lang, gender)


def test_fallback_respects_language():
    """确定性兜底也遵守语言筛选：补救档不再只剩港澳台。"""
    from tripcraft.agents.scenario import DispatchGenerator, SOURCE_MARKETS
    from tripcraft.services.learner_brief import LearnerBrief
    brief = LearnerBrief(user_id="u1", level=0, branch="补救", label="补救 · L0",
                         target_skill_points=(), target_names=(), target_dimensions=(), mastery={},
                         knobs={"source_complexity": 0, "demand_vagueness": 0, "dispatch_gap": 0,
                                "time_pressure": 0, "budget_tightness": 0,
                                "resource_conflict": 0, "emotion_intensity": 0},
                         rationale="测试", carried_over=())
    gen = DispatchGenerator(None)
    for seq, want in enumerate(("English", "日本語", "한국어")):
        spec = gen._fallback(brief, set(), set(), seq, language=want)
        assert SOURCE_MARKETS[spec.source_market][0] == want, spec.source_market
        assert spec.language == want
    picked = {gen._fallback(brief, set(), set(), i, language="").source_market for i in range(8)}
    assert len(picked) > 1 and picked - {"香港", "澳门", "台湾"}

