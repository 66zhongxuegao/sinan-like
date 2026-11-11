"""画像 Agent：初始画像测评 + 动态刷新（D-066）。

迁移说明（2026-10，认证收紧后）：
- 不再自建 `TestClient`，也不再用 `monkeypatch.setattr(app_mod, "DeepSeekClient", ...)`
  （api/app.py 拆分后已不持有 DeepSeekClient）。改用 conftest 的 `auth_client` fixture
  拿真实会话，并在本文件内把 `ctx.get_llm()` 强制离线，让画像 Agent 走确定性模板兜底。
- 请求体里不再传 user_id：身份一律来自服务端会话（security v2 要求）；
  路径里的 user_id 必须是自己的，否则 403（新增越权用例覆盖）。
- 离线可跑：不需要模型、不需要网络、不碰演示库（conftest 已隔离 TRIPCRAFT_DB）。
"""

import pytest

from tripcraft.agents import profiler as P
from tripcraft.agents.llm import LLMError


def _answers(level_by_dim: dict[str, int] | None = None) -> list[dict]:
    """按「每个维度想要几档」构造一份完整作答。"""
    level_by_dim = level_by_dim or {}
    out = []
    for q in P.QUIZ:
        want = level_by_dim.get(q["dim"], 3)
        opt = min(q["options"], key=lambda o: abs(o["level"] - want))   # 没有该档就取最接近的
        out.append({"qid": q["id"], "key": opt["key"]})
    return out


@pytest.fixture
def session(auth_client):
    """(client, headers, user_id)：已注册登录的独立账号，且模型被强制离线。"""
    c, headers = auth_client

    def _no_llm():
        raise LLMError("测试环境故意不接模型")

    c.app.state.ctx.get_llm = _no_llm
    uid = c.get("/auth/session", headers=headers).json()["user_id"]
    return c, headers, uid


# ---------------- 纯函数：题面与打分 ----------------

def test_quiz_public_hides_levels():
    qs = P.questions_public()
    assert len(qs) == len(P.QUIZ) == 12
    assert {q["dim"] for q in qs} == set(P.DIM_ORDER), "8 个维度都要覆盖到"
    for q in qs:
        assert q["options"]
        assert all("level" not in o for o in q["options"]), "权重不能下发到前端"


def test_score_answers_is_deterministic_and_bounded():
    a = _answers({"C1": 4, "C4": 0, "C8": 0})
    s1 = P.score_answers(a)
    assert s1 == P.score_answers(a), "同一份作答必须可复算"
    assert set(s1) == set(P.DIM_ORDER)
    assert s1["C1"] == 95.0, "顶格封顶 95，不给满分"
    assert s1["C4"] == 20.0, "全不会也给 20 保底"
    # 未知题号 / 未知选项一律忽略，不炸
    assert P.score_answers([{"qid": "NOPE", "key": "z"}]) == P.score_answers([])


def test_dim_comments_accepts_both_shapes():
    assert P.dim_comments([{"dim": "C1", "comment": "x"}]) == {"C1": "x"}
    # 模型有时把整句写进 key
    assert P.dim_comments({"C2 需求洞察：教学75 vs 实战0": ""}) == {"C2": "教学75 vs 实战0"}


# ---------------- 边界：认证与归属（R08/R11） ----------------

def test_profile_endpoints_require_session(client):
    """未登录访问画像接口一律 401（前端守卫不算安全隔离）。"""
    for path in ("/profiles/u-any/intake", "/profiles/u-any", "/profiles/u-any/report",
                 "/profiles/u-any/trend", "/profiles/u-any/radar"):
        assert client.get(path).status_code == 401, path


def test_profile_cross_user_is_forbidden(auth_client):
    """A 读别人的画像 / 报告 / 趋势 / 雷达一律 403。"""
    c, headers = auth_client
    for path in ("/profiles/u-other", "/profiles/u-other/report", "/profiles/u-other/trend",
                 "/profiles/u-other/radar", "/profiles/u-other/intake"):
        assert c.get(path, headers=headers).status_code == 403, path
    assert c.post("/profiles/u-other/refresh", headers=headers).status_code == 403
    # 请求体里显式冒用他人身份 → 403（不能靠 body.user_id 换身份）
    spoof = c.post("/profile/assessment", headers=headers,
                   json={"user_id": "u-other", "answers": _answers({})})
    assert spoof.status_code == 403


def test_manual_ability_write_is_debug_gated(auth_client, monkeypatch):
    """手工写能力分默认关闭；开启后也只能写自己。"""
    c, headers = auth_client
    uid = c.get("/auth/session", headers=headers).json()["user_id"]
    body = {"skill_point_id": "C2.2", "value": 45}
    assert c.post(f"/profiles/{uid}/abilities", headers=headers, json=body).status_code == 404
    monkeypatch.setenv("TRIPCRAFT_DEBUG_PROFILE", "1")
    assert c.post(f"/profiles/{uid}/abilities", headers=headers, json=body).status_code == 200
    assert c.post("/profiles/u-other/abilities", headers=headers, json=body).status_code == 403


# ---------------- 接口：初始画像 ----------------

def test_initial_assessment_only_for_new_users(session):
    c, h, uid = session
    assert c.get(f"/profiles/{uid}/intake", headers=h).json()["can_assess"] is True

    r = c.post("/profile/assessment", headers=h, json={"answers": _answers({"C1": 3})})
    assert r.status_code == 200
    body = r.json()
    assert body["scores"]["C1"] == 75.0
    assert body["report"]["summary"], "兜底模板也要有定性描述"
    assert len(body["report"]["suggestions"]) >= 3
    assert body["user_id"] == uid, "画像只能写到自己名下"

    after = c.get(f"/profiles/{uid}/intake", headers=h).json()
    assert after["can_assess"] is False and after["has_report"] is True

    again = c.post("/profile/assessment", headers=h, json={"answers": _answers({})})
    assert again.status_code == 409, "已有画像数据的不再开放初始画像"


def test_assessment_requires_all_questions(session):
    c, h, _uid = session
    r = c.post("/profile/assessment", headers=h, json={"answers": _answers({})[:5]})
    assert r.status_code == 400


def test_assessment_writes_teach_for_every_skill_point(session):
    c, h, uid = session
    c.post("/profile/assessment", headers=h, json={"answers": _answers({"C3": 4})})

    m = c.get("/learn/map", headers=h).json()
    pts = [p for d in m["dimensions"] for p in d["points"]]
    assert len(pts) == 61
    assert all(p["teach"] > 0 for p in pts), "每个技能点都要拿到基线，画像不能有空洞"
    assert all(p["real"] == 0 for p in pts), "初始画像只写教学侧，实战侧留空"
    c3 = next(d for d in m["dimensions"] if d["id"] == "C3")
    assert c3["teach"] == 95.0
    # 查询串里指别人 → 403（不允许拿 user_id 当身份）
    assert c.get("/learn/map", params={"user_id": "u-other"}, headers=h).status_code == 403


def test_suggestions_point_to_a_real_skill_point(session):
    c, h, uid = session
    rep = c.post("/profile/assessment", headers=h,
                 json={"answers": _answers({"C8": 0})}).json()["report"]
    ids = {p["id"] for d in c.get("/learn/map", headers=h).json()["dimensions"]
           for p in d["points"]}
    assert rep["focus"][0] == "C8", "最弱的一维要排在最前"
    for s in rep["suggestions"]:
        assert s["skill_point_id"] in ids
        assert s["why"] and s["how"], "每条建议都要说清为什么、怎么练"


# ---------------- 接口：更新画像 ----------------

def test_refresh_needs_data_then_marks_kind(session):
    c, h, uid = session
    assert c.post(f"/profiles/{uid}/refresh", headers=h).status_code == 409

    c.post("/profile/assessment", headers=h, json={"answers": _answers({"C6": 0})})
    rep = c.post(f"/profiles/{uid}/refresh", headers=h).json()["report"]
    assert rep["kind"] == "refresh"
    assert len(rep["suggestions"]) >= 3
    assert len(rep["dimensions"]) == 8, "8 维都要有点评"


def test_report_endpoint_returns_latest(session):
    c, h, uid = session
    assert c.get(f"/profiles/{uid}/report", headers=h).json()["report"] == {}
    c.post("/profile/assessment", headers=h, json={"answers": _answers({})})
    assert c.get(f"/profiles/{uid}/report", headers=h).json()["report"]["kind"] == "initial"
    c.post(f"/profiles/{uid}/refresh", headers=h)
    assert c.get(f"/profiles/{uid}/report", headers=h).json()["report"]["kind"] == "refresh"


# ---------------- 接口：R12 初始/当前雷达 ----------------

def test_radar_flags_unassessed_without_faking_scores(session):
    """没有画像数据时必须显示「未评估」，不能补 0 分假装有分。"""
    c, h, uid = session
    b = c.get(f"/profiles/{uid}/radar", headers=h).json()
    assert b["assessed"] is False
    assert all(d["value"] is None and d["assessed"] is False for d in b["initial"]["dimensions"])
    assert all(d["value"] is None for d in b["current"]["dimensions"])
    assert all(d["value"] is None for d in b["delta"])
    assert b["note"], "未评估要给出下一步提示"


def test_radar_is_same_scale_and_records_real_time(session):
    c, h, uid = session
    c.post("/profile/assessment", headers=h, json={"answers": _answers({"C1": 4, "C4": 0})})

    b = c.get(f"/profiles/{uid}/radar", headers=h).json()
    assert b["assessed"] is True
    assert b["scale"] == {"min": 0, "max": 100, "unit": "维度值"}
    init = b["initial"]["dimensions"]
    cur = b["current"]["dimensions"]
    assert [d["id"] for d in init] == [d["id"] for d in cur], "初始/当前必须同量纲同维度顺序"
    assert all(0 <= d["value"] <= 100 for d in init)
    assert all(0 <= d["value"] <= 100 for d in cur)
    assert b["initial"]["at"], "初始快照要保存真实时间"
    assert b["initial"]["source"], "初始快照要保存来源"
    # 初始快照来自测评选择：C1 顶格 95、C4 保底 20
    by_id = {d["id"]: d["value"] for d in init}
    assert by_id["C1"] == 95.0 and by_id["C4"] == 20.0


def test_initial_assessment_syncs_to_learning_layer(session):
    """初始测评完成后，学习能力层应沿用初始分数，而不是显示未评估。"""
    c, h, uid = session
    c.post("/profile/assessment", headers=h, json={"answers": _answers({"C1": 4, "C4": 0})})
    b = c.get(f"/profiles/{uid}/radar", headers=h).json()
    initial = {d["id"]: d["value"] for d in b["initial"]["dimensions"]}
    learning = {d["id"]: d for d in b["learning"]["dimensions"]}
    assert all(d["assessed"] for d in learning.values())
    assert {k: v["value"] for k, v in learning.items()} == initial
    assert all(v["source"] in ("initial", "training") for v in learning.values())
    assert b["learning"]["at"] == b["initial"]["at"]


# ---------------- 接口：R14 趋势按真实记录 ----------------

def test_completed_practice_radar_uses_initial_without_coverage_gate(session):
    from tripcraft.contracts.deliverables_spec import PRACTICE_FINAL_CODES, resolve
    c, headers, uid = session
    assert c.post("/profile/assessment", headers=headers, json={"answers": _answers({})}).status_code == 200
    store = c.app.state.ctx.store
    oid = "completion-profile-api"
    store.upsert_order(oid, uid, "模拟客户", "福建", "进行中", 0, {})
    for code in PRACTICE_FINAL_CODES:
        store.save_deliverable(oid, resolve(code).id, {}, "模拟文件", [], {}, [])
    response = c.get(f"/profiles/{uid}/radar", headers=headers)
    assert response.status_code == 200
    radar = response.json()
    assert all(row["assessed"] and row["inherited"] for row in radar["practice"]["dimensions"])
    assert [row["value"] for row in radar["practice"]["dimensions"]] == [row["value"] for row in radar["initial"]["dimensions"]]
    assert radar["practice"]["at"] == store.completed_practice_at(uid)
    assert not any(row["real_v"] for row in store.abilities(uid).values())
    docs = c.get(f"/practice/orders/{oid}/deliverables", headers=headers).json()
    assert docs["training_completion"]["completed"]
    assert docs["training_completion"]["score_route"] == f"/practice/orders/{oid}/score"


def test_recorded_practice_scores_are_visible_without_ability_write_or_intake(session):
    c, headers, uid = session
    store = c.app.state.ctx.store
    oid = "recorded-practice-api"
    store.upsert_order(oid, uid, "模拟客户", "福建", "进行中", 0, {})
    store.upsert_order_score(oid, "C1.1", 85, "M4", False, [{"quote": "真实提交证据"}], "评分报告", "实战", status="已入库")
    store.upsert_order_score(oid, "C2.1", 45, "M1", False, [{"quote": "待复核证据"}], "低置信度", "实战", status="待复核")
    response = c.get(f"/profiles/{uid}/radar", headers=headers)
    assert response.status_code == 200
    radar = response.json()
    assert radar["assessed"]
    by_id = {row["id"]: row for row in radar["practice"]["dimensions"]}
    assert by_id["C1"]["value"] == 85 and not by_id["C1"]["inherited"]
    assert by_id["C2"]["value"] is None
    assert not store.abilities(uid), "雷达读取不改写能力表或采纳待复核分数"
    assert c.post(f"/profiles/{uid}/refresh", headers=headers).status_code == 200

def test_trend_counts_match_real_records(session):
    c, h, uid = session
    store = c.app.state.ctx.store

    orders = c.get("/practice/orders/available", headers=h).json()
    order_id = (orders[0]["order_id"] if orders else "")
    store.add_attempt(uid, "C1.1", "q1", {"title": "t1"}, "a", True, 80.0)
    store.add_attempt(uid, "C1.2", "q2", {"title": "t2"}, "a", False, 40.0)
    if order_id:
        store.upsert_order_score(order_id, "C1.1", 70.0, "M3", False, [], "ok", "test")

    body = c.get(f"/profiles/{uid}/trend", headers=h).json()
    assert body["quiz"]["total_samples"] == 2
    assert body["quiz"]["correct"] == 1
    assert body["quiz"]["avg_score"] == 60.0
    assert body["quiz"]["unit"] == "题目"
    assert body["order"]["unit"] == "订单"
    assert body["data_scope"]["scope"] in ("real", "example")
    if order_id:
        assert body["order"]["total_samples"] == 1
        assert body["order"]["avg_score"] == 70.0
    # 旧实现用固定 30.0 起点模拟；现在没有样本就不该凭空出现 30.0
    for p in body["trend"]:
        assert not (p["teach"] == 30.0 and p["quiz_samples"] == 0)
