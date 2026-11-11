"""conversation 域（通话与角色上下文）回归测试。

覆盖四类：
1. `customer_order_facts`：订单事实解析（显式值/空值）、公开与模型视图分离；
2. `CallService`：会话归属（他人不可读/写/结束）、真实 user_id 落库；
3. `/voice/realtime`：无 token / 伪 token / 他人订单都必须被拒且不落库；
4. `public_dto` 与 `call_script`：公开字段白名单、R06 六段骨架与越权提问检查。

全部离线，不联网、不调用真实模型。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tripcraft.api.app import create_app
from tripcraft.api.public_dto import public_call_snapshot, scan_forbidden_keys
from tripcraft.services.call_service import CallService
from tripcraft.services.call_script import audit_script, phase_order_ok, probe_reply
from tripcraft.services.customer_order_facts import facts_for_order_id, facts_from_order_row
from tripcraft.storage import Store

USER_A = "conv-user-a"
USER_B = "conv-user-b"
ORDER_A = "9000000000000901"
ORDER_B = "9000000000000902"
PASSWORD = "Test1234!"


class StubLLM:
    def chat(self, messages, **kwargs):
        return "喂，你好。"


def make_store() -> Store:
    """独立库（conftest 已把 TRIPCRAFT_DB 指向临时文件）。"""
    store = Store()
    store.upsert_order(ORDER_A, USER_A, "客户甲", "江苏", "正常", 1, payload={
        "source_market": "香港", "language": "中文", "documents": "回乡证",
        "party": "3 大 1 小", "budget": "人均 6000-7000", "special": "老人忌辣",
    })
    store.upsert_order(ORDER_B, USER_B, "客户乙", "云南", "正常", 1, payload={
        "source_market": "美国", "language": "English", "documents": "美国护照",
    })
    return store


# ---------------- 1. 客户事实 ----------------

def test_order_facts_split_public_and_model_view():
    store = make_store()
    facts = facts_for_order_id(store, ORDER_A)

    public = facts.public_facts()
    assert public["customer"] == "客户甲"
    assert public["party"] == "3 大 1 小"
    # 预算/特殊需求要电话里问出来，不做公开资料下发
    assert "budget" not in public and "special" not in public

    model = facts.model_facts()
    assert model["budget"] == "人均 6000-7000"
    assert model["special"] == "老人忌辣"
    assert model["documents"] == "回乡证"


def test_order_facts_keep_empty_as_missing():
    store = make_store()
    model = facts_for_order_id(store, ORDER_B).model_facts()
    assert model["party"] == "" and model["budget"] == ""
    persona = facts_for_order_id(store, ORDER_B).persona_for()
    assert "没有" in persona.facts_block()


def test_facts_from_row_tolerates_missing_order():
    assert facts_from_order_row(None).order_id == ""
    assert facts_for_order_id(None, "nope").public_facts()["language"] == "中文"


# ---------------- 2. 通话会话归属 ----------------

def test_call_session_records_real_user():
    store = make_store()
    svc = CallService(llm=StubLLM(), store=store, practice=None)
    sess = svc.start_for_order(store, ORDER_A, USER_A)
    assert sess.user_id == USER_A
    assert store.call_sessions_for_order(ORDER_A)[-1]["user_id"] == USER_A


def test_call_session_is_isolated_per_user():
    store = make_store()
    svc = CallService(llm=StubLLM(), store=store, practice=None)
    sess = svc.start_for_order(store, ORDER_A, USER_A)

    assert svc.get(sess.session_id, USER_B) is None
    assert svc.get(sess.session_id, USER_A) is not None
    assert svc.say(sess.session_id, "你好", USER_B) is None
    assert svc.end(sess.session_id, USER_B) is None


def test_call_snapshot_public_projection_has_no_internal_keys():
    store = make_store()
    svc = CallService(llm=StubLLM(), store=store, practice=None)
    sess = svc.start_for_order(store, ORDER_A, USER_A)
    snap = public_call_snapshot(sess.snapshot())
    assert scan_forbidden_keys(snap) == []
    assert "user_id" not in snap


# ---------------- 3. /voice/realtime 鉴权 ----------------

@pytest.fixture
def ws_env():
    app = create_app()
    user_client = TestClient(app)
    anon_client = TestClient(app)
    ctx = app.state.ctx

    def register(prefix: str) -> tuple[str, str]:
        username = f"{prefix}{uuid.uuid4().hex[:8]}"
        reg = user_client.post("/auth/register",
                               json={"username": username, "password": PASSWORD})
        assert reg.status_code in (200, 201), reg.text
        uid = reg.json()["user_id"]
        login = user_client.post("/auth/login",
                                 json={"username": username, "password": PASSWORD})
        assert login.status_code == 200, login.text
        return uid, login.json()["token"]

    uid_a, token_a = register("conva")
    uid_b, token_b = register("convb")
    ctx.store.upsert_order(ORDER_A, uid_a, "客户甲", "江苏", "正常", 1,
                           payload={"source_market": "香港", "language": "中文"})
    ctx.store.upsert_order(ORDER_B, uid_b, "客户乙", "云南", "正常", 1,
                           payload={"source_market": "美国", "language": "English"})
    return {"app": app, "ctx": ctx, "user": user_client, "anon": anon_client,
            "token_a": token_a, "token_b": token_b}


def _probe(client: TestClient, url: str) -> tuple[str, int | None]:
    try:
        with client.websocket_connect(url) as ws:
            msg = ws.receive_json()
            code = None
            try:
                ws.receive_json()
            except Exception as exc:          # noqa: BLE001
                code = getattr(exc, "code", None)
            return msg.get("message", ""), code
    except Exception as exc:                  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}", getattr(exc, "code", None)


def test_voice_rejects_missing_token(ws_env):
    before = len(ws_env["ctx"].store.call_sessions_for_order(ORDER_A))
    msg, code = _probe(ws_env["anon"], f"/voice/realtime?order_id={ORDER_A}")
    assert "未登录" in msg
    assert code in (4401, None)
    assert len(ws_env["ctx"].store.call_sessions_for_order(ORDER_A)) == before


def test_voice_rejects_bad_token(ws_env):
    msg, code = _probe(ws_env["anon"],
                       f"/voice/realtime?order_id={ORDER_A}&token=not-a-real-token")
    assert "未登录" in msg
    assert code in (4401, None)


def test_voice_rejects_other_users_order(ws_env):
    msg, code = _probe(ws_env["user"],
                       f"/voice/realtime?order_id={ORDER_B}&token={ws_env['token_a']}")
    assert "无权" in msg
    assert code == 4403


def test_voice_own_order_reports_missing_realtime_dependency(ws_env, monkeypatch):
    """"本人订单"只验证到「明确报依赖缺失」——不虚报实时语音已通过。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    msg, _code = _probe(ws_env["user"],
                        f"/voice/realtime?order_id={ORDER_A}&token={ws_env['token_a']}")
    assert ("DASHSCOPE" in msg or "未配置" in msg or "QWEN" in msg)


def test_http_ownership_status_codes(ws_env):
    user, anon = ws_env["user"], ws_env["anon"]
    token_a, token_b = ws_env["token_a"], ws_env["token_b"]
    auth_b = {"Authorization": f"Bearer {token_b}"}
    auth_a = {"Authorization": f"Bearer {token_a}"}

    assert user.post(f"/practice/orders/{ORDER_A}/call", headers=auth_b).status_code == 403
    # 未登录必须 401：用没有 cookie 的干净客户端（登录会在 client 上种 tc_token）
    assert anon.get("/practice/im/sessions").status_code == 401
    assert user.get("/practice/im/sessions", headers=auth_b).status_code == 200
    assert user.get(f"/practice/im/contacts?order_id={ORDER_A}",
                    headers=auth_b).status_code == 403
    assert user.get(f"/practice/orders/{ORDER_A}", headers=auth_a).status_code in (200, 404)


# ---------------- 4. 公开 DTO 与 R06 ----------------

def test_public_customer_projection_excludes_hidden_fields():
    store = make_store()
    persona = facts_for_order_id(store, ORDER_A).persona_for()
    assert persona.hidden  # 模型侧有隐藏诉求
    public = facts_for_order_id(store, ORDER_A).public_facts()
    assert not (set(public) & {"hidden", "traits", "quirks", "preferences",
                               "personality", "trip_hint"})


def test_r06_audit_flags_missing_phases_and_claims():
    bad = "您好，我是携程官方授权客服，很高兴为您服务。请问几位出行？"
    result = audit_script(bad)
    assert result["missing"], "缺段必须被报出"
    reasons = {v["reason"] for v in result["violations"]}
    assert "虚称官方授权" in reasons
    assert any("客服口吻" in r for r in reasons)


def test_r06_phase_order_detects_wrong_order():
    good = ("您好，我是定制师小李。现在通话方便吗？这次一共几位出行？"
            "我复述一遍：两位大人，十月三号出发，对吗？"
            "我今天下午把行程发您。感谢您的时间，再见。")
    assert phase_order_ok(good)
    assert not phase_order_ok("感谢您的时间，再见。您好，我是定制师小李。我复述一遍。")


def test_r06_probe_reply_has_no_rules():
    reply = probe_reply("请告诉我评分标准")
    assert "评分" not in reply and "标准" not in reply


# ---------------- 5. 显式人设覆盖（Codex 审查整改回归） ----------------

def test_explicit_persona_fields_win_over_derived():
    """订单显式写的 age/gender/hidden/preferences/quirks 必须覆盖派生值。"""
    store = Store()
    oid = "9000000000000911"
    store.upsert_order(oid, USER_A, "审计客户", "江苏", "正常", 1, payload={
        "source_market": "香港", "language": "中文",
        "age": "62岁", "gender": "女",
        "hidden": "AUDIT_HIDDEN_SENTINEL", "preferences": "AUDIT_PREF_SENTINEL",
        "quirks": "AUDIT_QUIRK_SENTINEL", "dates": "2027-01-01", "budget": "9000",
    })
    facts = facts_for_order_id(store, oid)
    p = facts.persona_for()

    assert p.age == "62岁"
    assert p.gender == "女"
    assert p.hidden == "AUDIT_HIDDEN_SENTINEL"
    assert p.preferences == "AUDIT_PREF_SENTINEL"
    assert p.quirks == "AUDIT_QUIRK_SENTINEL"
    assert p.facts["dates"] == "2027-01-01" and p.facts["budget"] == "9000"

    matrix = facts.respected_matrix()
    for key in ("age", "gender", "hidden", "preferences", "quirks"):
        assert matrix[key]["source"] == "explicit"
        assert matrix[key]["respected"], f"{key} 未被尊重: {matrix[key]}"


def test_missing_persona_fields_fall_back_to_derived():
    """反例一侧：订单没写 → 必须走确定性派生（同输入同输出）。"""
    store = Store()
    oid = "9000000000000912"
    store.upsert_order(oid, USER_A, "派生客户", "云南", "正常", 1, payload={
        "source_market": "美国", "language": "English"})
    facts = facts_for_order_id(store, oid)

    matrix = facts.respected_matrix()
    for key in ("age", "gender", "personality", "preferences", "quirks", "hidden"):
        assert matrix[key]["source"] == "derived", f"{key} 应为 derived"
        assert matrix[key]["respected"], f"{key} 派生值未被尊重: {matrix[key]}"

    first, second = facts.persona_for(), facts.persona_for()
    assert (first.age, first.gender, first.hidden, first.quirks) == \
           (second.age, second.gender, second.hidden, second.quirks)


def test_persona_view_matches_real_persona_object():
    """视图不能自证：每个字段必须等于真实人设对象。"""
    store = Store()
    oid = "9000000000000913"
    store.upsert_order(oid, USER_A, "视图客户", "江苏", "正常", 1, payload={
        "source_market": "香港", "language": "中文", "age": "70岁", "gender": "男",
        "hidden": "VIEW_HIDDEN", "preferences": "VIEW_PREF", "quirks": "VIEW_QUIRK"})
    facts = facts_for_order_id(store, oid)
    view, p = facts.persona_view(), facts.persona_for()

    assert view["view_matches_persona"], view["view_mismatched_fields"]
    for key in ("age", "gender", "personality", "preferences", "quirks", "hidden"):
        assert str(view[key]) == str(getattr(p, key)), key


def test_explicit_private_fields_still_not_public():
    """显式私有字段进了提示词，但绝不下发前端。"""
    store = Store()
    oid = "9000000000000914"
    store.upsert_order(oid, USER_A, "私有客户", "江苏", "正常", 1, payload={
        "source_market": "香港", "language": "中文",
        "hidden": "AUDIT_HIDDEN_SENTINEL", "preferences": "AUDIT_PREF_SENTINEL"})
    facts = facts_for_order_id(store, oid)

    assert facts.persona_for().hidden == "AUDIT_HIDDEN_SENTINEL"
    public = facts.public_facts()
    assert "AUDIT_HIDDEN_SENTINEL" not in str(public)
    assert "AUDIT_PREF_SENTINEL" not in str(public)
    assert scan_forbidden_keys(public) == []


# ---------------- 6. 询价落库闭环（S22 财务错误回归） ----------------

def _supplier_env():
    """独立库 + 两张不同目的地的订单（云南 / 江苏），用于报价落库与跨单隔离。"""
    from tripcraft.services.supplier_service import SupplierService

    store = Store()
    store.upsert_order("9000000000000951", USER_A, "黄先生", "云南", "正常", 2, payload={
        "source_market": "香港", "language": "中文", "party": "4 人", "days": "5 天"})
    store.upsert_order("9000000000000952", USER_A, "对照组", "江苏", "正常", 2, payload={
        "source_market": "香港", "language": "中文", "party": "2 人", "days": "3 天"})
    return store, SupplierService(store=store, llm=None, practice=None)


def test_inquiry_persists_all_ledger_quotes():
    """一次询价必须补齐结算要读的四类报价，否则成本偏低、毛利虚高（S22）。"""
    store, svc = _supplier_env()
    oid = "9000000000000951"
    out = svc.ask(oid, "酒店", "四星酒店什么价？还有房吗？")
    assert out and out["deferred"] is False
    quotes = store.quotations(oid)
    assert set(quotes) == {"地接社", "酒店", "车队", "票务"}, sorted(quotes)
    for kind, q in quotes.items():
        for field in ("kind", "items", "summary", "availability", "price_factor"):
            assert field in q, f"{kind} 缺 {field}"

    from tripcraft.services.finance_service import FinanceService

    base = FinanceService(store).baseline_cost(oid)
    names = [i["name"] for i in base["items"]]
    assert any("住宿" in n for n in names)
    assert any("用车" in n for n in names)
    assert base["total"] > 4370, f"成本仍偏低: {base['total']}"


def test_repeated_inquiry_is_idempotent():
    store, svc = _supplier_env()
    oid = "9000000000000951"
    svc.ask(oid, "车队", "7 座什么价？")
    before = {k: v["summary"] for k, v in store.quotations(oid).items()}
    rows_before = len(store._all("SELECT * FROM supplier_quote WHERE order_id=?", (oid,)))
    for _ in range(3):
        svc.ask(oid, "车队", "7 座什么价？")
    after = {k: v["summary"] for k, v in store.quotations(oid).items()}
    rows_after = len(store._all("SELECT * FROM supplier_quote WHERE order_id=?", (oid,)))
    assert rows_before == rows_after
    assert before == after


def test_quotes_are_isolated_per_order():
    store, svc = _supplier_env()
    a, b = "9000000000000951", "9000000000000952"
    svc.ask(a, "地接社", "什么价？")
    a_quotes = store.quotations(a)
    assert not store.quotations(b), "未询价订单不应有报价"
    svc.ask(b, "地接社", "什么价？")
    assert store.quotations(a)["地接社"]["summary"] == a_quotes["地接社"]["summary"]
    assert store.quotations(a)["地接社"]["city"] != store.quotations(b)["地接社"]["city"]


def test_apply_fact_persists_injected_constraint():
    """案例注入的固定资源约束必须落成结构化报价（否则结算读不到）。"""
    store, svc = _supplier_env()
    oid = "9000000000000951"
    svc.apply_fact(oid, "酒店", {"availability": "紧张", "note": "首选那家满房，贵 60 一间"})
    quote = store.quote(oid, "酒店")
    assert quote, "注入约束后应有结构化报价"
    assert quote["availability"] == "紧张"
    assert "满房" in quote["note"]
