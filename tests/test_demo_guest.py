"""演示账号多人同时登录互不影响：每次用模板账号登录都拿到独立的访客账号。"""

from tripcraft.services import demo_blank_state, demo_guest

from conftest import auth_headers


def _login(client, username=demo_blank_state.USERNAME, password=demo_blank_state.PASSWORD):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _ensure_template(client):
    # 登录列表接口会补建 demo-blank 模板账号
    assert client.get("/auth/login-accounts").status_code == 200


def test_two_people_on_same_demo_account_get_separate_users(client):
    _ensure_template(client)
    a = _login(client)
    b = _login(client)
    assert a["user_id"] != b["user_id"], "两个人不能共用同一个 user_id"
    assert demo_guest.template_of(a["username"]) == demo_blank_state.USERNAME
    ha, hb = auth_headers(a["token"]), auth_headers(b["token"])
    assert client.get("/auth/session", headers=ha).json()["user_id"] == a["user_id"]

    # A 改了资料（代表 A 的任何数据），B 登录/退出都不能影响 A
    client.patch("/auth/profile", headers=ha, json={"bio": "A 的学习记录"})
    c = _login(client)
    client.post("/auth/logout", headers=hb)
    assert client.get("/auth/session", headers=ha).status_code == 200, "别人登录/退出不能踢掉 A"
    assert client.get("/auth/session", headers=ha).json().get("bio") == "A 的学习记录"
    assert c["user_id"] not in (a["user_id"], b["user_id"])


def test_guest_is_deleted_on_logout_and_hidden_from_login_list(client):
    _ensure_template(client)
    g = _login(client)
    names = [x["username"] for x in client.get("/auth/login-accounts").json()["accounts"]]
    assert demo_blank_state.USERNAME in names
    assert g["username"] not in names, "访客账号不出现在登录列表"
    client.post("/auth/logout", headers=auth_headers(g["token"]))
    assert client.get("/auth/session", headers=auth_headers(g["token"])).status_code == 401
    assert client.post("/auth/login", json={"username": g["username"], "password": "x" * 12}).status_code == 401


def test_stale_guests_are_purged(client):
    _ensure_template(client)
    g = _login(client)
    ctx = client.app.state.ctx
    ctx.store._exec("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00', created_at='2000-01-01T00:00:00' "
                    "WHERE user_id=?", (g["user_id"],))
    assert demo_guest.purge_stale(ctx) >= 1
    assert ctx.store.user_by_id(g["user_id"]) is None


def test_real_accounts_are_never_treated_as_guests():
    assert not demo_guest.is_guest("demo-blank")
    assert not demo_guest.is_guest("alice-g12345678")
    assert demo_guest.is_guest("demo-blank-g0a1b2c3d")
    assert demo_guest.is_blank_like("demo-blank-g0a1b2c3d")
