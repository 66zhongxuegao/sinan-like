"""M0 API 冒烟测试（已迁移到 v2 认证：真实会话 + 对象归属）。

迁移说明（2026-10，认证收紧后）：
- 不再有 `X-User-Id` 直通，`TRIPCRAFT_AUTH=off` 旁路已被删除；受保护路径一律要带
  真实 Bearer token，统一用 conftest 的 `auth_client` fixture（真实注册 + 登录取得）。
- 原始状态机控制（flags / rollback）与手工写能力分是**内部调试面**，必须显式开
  TRIPCRAFT_DEBUG_RUNS / TRIPCRAFT_DEBUG_PROFILE，且只能操作自己的资源；
  这不是「为了迎合旧测试而禁用安全控制」，而是改为按新的调试面门禁调用。
- 声明式 fixture 在 tests/conftest.py（Lead 单写者），本文件不重复定义 client()。
"""

import pytest

from tripcraft.api.routers.growth import PROFILE_DEBUG_ENV
from tripcraft.api.routers.runs import RUNS_DEBUG_ENV


def test_health_and_contracts(client):
    assert client.get("/").json()["service"] == "TripCraft"
    assert len(client.get("/contracts/steps").json()) == 13
    assert len(client.get("/contracts/dimensions").json()) == 8
    assert len(client.get("/contracts/skill-points").json()) == 61
    assert len(client.get("/contracts/skill-points", params={"dimension": "C6"}).json()) == 7


def test_rubric_example_and_missing(client):
    r = client.get("/contracts/rubric/C2.2")
    assert r.status_code == 200
    assert len(r.json()["anchors"]) == 5
    # C1.1 已入库；不存在的技能点应 404
    assert client.get("/contracts/rubric/C1.1").status_code == 200
    assert client.get("/contracts/rubric/C9.9").status_code == 404


def test_protected_paths_require_session(client):
    """未登录必须 401（前端路由守卫不等于安全隔离，边界必须由服务端守）。"""
    for path in ("/practice/orders", "/learn/map", "/auth/profile"):
        assert client.get(path).status_code == 401, path


def test_run_gate_then_advance(auth_client, monkeypatch):
    c, headers = auth_client
    monkeypatch.setenv(RUNS_DEBUG_ENV, "1")

    run = c.post("/runs", json={}, headers=headers).json()
    assert run["current_step"] == "S0"
    assert run["gate"]["passed"] is False
    run_id = run["instance_id"]

    # 旗标入口属调试面：上面已显式开启，且只能操作自己的演练
    assert c.post(f"/runs/{run_id}/flags", json={"name": "hard_rules_recited"},
                  headers=headers).status_code == 200
    adv = c.post(f"/runs/{run_id}/advance", headers=headers).json()
    assert adv["ok"] is True
    assert adv["to"] == "S1"


def test_run_debug_surface_closed_by_default(auth_client):
    """未开调试开关时，原始状态机控制面按「路由不存在」处理。"""
    c, headers = auth_client
    run = c.post("/runs", json={}, headers=headers).json()
    run_id = run["instance_id"]
    r = c.post(f"/runs/{run_id}/flags", json={"name": "hard_rules_recited"}, headers=headers)
    assert r.status_code == 404


def test_profile_ability_write_is_debug_gated_and_self_only(auth_client, monkeypatch):
    """手工写能力分：默认关闭 → 404；开启后只能写自己 → 别人 403。"""
    c, headers = auth_client
    me = c.get("/auth/session", headers=headers).json()["user_id"]
    body = {"skill_point_id": "C2.2", "value": 45}

    assert c.post(f"/profiles/{me}/abilities", json=body, headers=headers).status_code == 404

    monkeypatch.setenv(PROFILE_DEBUG_ENV, "1")
    assert c.post(f"/profiles/{me}/abilities", json=body, headers=headers).status_code == 200

    prof = c.get(f"/profiles/{me}", headers=headers).json()
    assert "C2.2" in prof["weak_points"]
    assert prof["mastery"]["C2.2"]["level"] == "M1"
    assert "C2" in prof["dimensions"]

    # 冒用他人路径 → 403
    assert c.post("/profiles/u-someone-else/abilities", json=body,
                  headers=headers).status_code == 403
    # 读他人画像 → 403
    assert c.get("/profiles/u-someone-else", headers=headers).status_code == 403


def test_auth_session_roundtrip(client):
    """注册 → 登录 → 会话恢复 → 登出后失效（R11 的服务端闭环）。"""
    from tests.conftest import auth_headers, new_username, register_and_login

    username, user_id, token = register_and_login(client, new_username("api_"))
    assert user_id

    me = client.get("/auth/session", headers=auth_headers(token))
    assert me.status_code == 200 and me.json()["user_id"] == user_id

    assert client.post("/auth/logout", headers=auth_headers(token)).status_code == 200
    assert client.get("/auth/session", headers=auth_headers(token)).status_code == 401
    # 登出后受保护接口同样失效
    assert client.get("/learn/map", headers=auth_headers(token)).status_code == 401


def test_duplicate_username_conflicts(client):
    from tests.conftest import DEFAULT_PASSWORD, new_username

    username = new_username("dup_")
    first = client.post("/auth/register", json={"username": username, "password": DEFAULT_PASSWORD})
    assert first.status_code == 200
    second = client.post("/auth/register", json={"username": username, "password": DEFAULT_PASSWORD})
    assert second.status_code == 409
