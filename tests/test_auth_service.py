"""AuthService 自检（owner: identity）—— 独立临时库，不碰开发库/演示库。

覆盖验收条件（与 workId identity-auth-service 的 acceptance 一致）：
  1. 五个方法签名与 tripcraft/api/security.py 冻结契约一致；
  2. 直查 DB 证明 password_hash 非明文、不含可逆编码（PBKDF2-HMAC-SHA256 / 200k 轮）；
  3. 同口令两次注册（两个用户）得到不同 hash —— 随机盐生效；
  4. resolve 对未知 / 过期 / 已登出 token 返回 None，对有效 token 返回正确 user_id；
  5. user(user_id) 不含 password_hash / password_salt；不存在返回 None；
  6. 重复用户名 409、口令错误 401；token 只存 sha256 摘要；会话有效期 30 天；
  7. owner 定的账号规则：username 3–32 位 [A-Za-z0-9_.-]、password ≥8 位、
     kind 推断（demo-/u-show → demo，显式优先，仅 real/demo）、user_id 服务端生成。

库隔离：每个测试用 monkeypatch 把 TRIPCRAFT_DB 指向本用例独占的临时库，
再由 `Store()` 自己按环境变量建档（与生产装配路径一致）。

注意：临时目录刻意不用 `tempfile.mkdtemp` / pytest `tmp_path`（两者都用 0o700 建目录），
在 DSH Windows 沙箱下那样的目录无法写入（PermissionError）；改用 `Path.mkdir()`
在 `tests/.auth-tmp/` 下建每用例目录，用完即删。
"""

from __future__ import annotations

import hashlib
import inspect
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tripcraft.services.auth_service import (
    PBKDF2_ITERATIONS,
    SESSION_TTL_DAYS,
    AuthConflictError,
    AuthCredentialError,
    AuthError,
    AuthService,
    hash_password,
    token_digest,
)
from tripcraft.storage.db import Store, now

PASSWORD = "Test1234!"


# ---------------- fixtures ----------------

# 临时库根目录：默认在本测试文件同级放 tests/.auth-tmp/（点目录，pytest 不收集）；
# 需要换位置时设 TRIPCRAFT_AUTH_TEST_TMP。
_TMP_ROOT = Path(os.environ.get("TRIPCRAFT_AUTH_TEST_TMP")
                 or Path(__file__).resolve().parent / ".auth-tmp")


def _fresh_dir() -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    for _ in range(64):
        candidate = _TMP_ROOT / f"case-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            candidate.mkdir()          # 默认权限；0o700 的目录在沙箱下写不进
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"无法在 {_TMP_ROOT} 下创建临时目录")


@pytest.fixture
def scratch():
    """每用例一个独占临时目录，结束后删除。"""
    root = _fresh_dir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            _TMP_ROOT.rmdir()          # 根目录空了就一起收掉，不留测试垃圾
        except OSError:
            pass


@pytest.fixture
def store(scratch, monkeypatch):
    """TRIPCRAFT_DB → 每测试一个临时库；Store() 从环境变量取路径。"""
    db_path = scratch / "auth-test.sqlite"
    monkeypatch.setenv("TRIPCRAFT_DB", str(db_path))
    s = Store()
    assert Path(s.path) == db_path, "Store 必须使用 TRIPCRAFT_DB 指定的临时库"
    assert db_path.exists(), "库文件必须真的落在临时目录里"
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def auth(store):
    return AuthService(store)


@pytest.fixture
def db_path(store):
    return store.path


def _rows(db_path, sql, args=()):
    """旁路连接直查库文件：验证的是落盘结果，不是服务层内存态。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _users(db_path):
    return _rows(db_path, "SELECT * FROM users")


def _sessions(db_path):
    return _rows(db_path, "SELECT * FROM sessions")


def _register(auth, username="alice", password=PASSWORD, **kw):
    return auth.register(username, password, **kw)


def _login(auth, username="alice", password=PASSWORD):
    return auth.login(username, password)


# ---------------- 1. 契约签名 ----------------

def test_signatures_match_frozen_contract(auth):
    """security.py docstring 的 register/login/logout/resolve/user 参数逐字一致。"""
    expected = {
        "register": [("username", inspect.Parameter.empty), ("password", inspect.Parameter.empty),
                     ("display_name", ""), ("kind", "")],
        "login": [("username", inspect.Parameter.empty), ("password", inspect.Parameter.empty)],
        "logout": [("token", inspect.Parameter.empty)],
        "resolve": [("token", inspect.Parameter.empty)],
        "user": [("user_id", inspect.Parameter.empty)],
    }
    for name, params in expected.items():
        sig = inspect.signature(getattr(auth, name))      # 绑定方法：不含 self
        actual = [(p.name, p.default) for p in sig.parameters.values()]
        assert actual == params, f"signature mismatch for {name}: {actual} != {params}"


def test_context_construction_path_works(store):
    """context.py:140 的构造方式 AuthService(self.store) 可用。"""
    assert isinstance(AuthService(store), AuthService)
    assert isinstance(AuthService(store).resolve("no-such-token"), type(None))


def test_docstring_call_forms_are_accepted(auth):
    """security.py docstring 的调用形态（含位置/关键字）必须原样可用。"""
    a = auth.register("pos_alice", PASSWORD, "爱丽丝")
    b = auth.register(username="kw_bob", password=PASSWORD, display_name="鲍勃")
    c = auth.register("plain_carol", PASSWORD)
    assert {a["username"], b["username"], c["username"]} == {"pos_alice", "kw_bob", "plain_carol"}
    assert b["display_name"] == "鲍勃"
    assert auth.login("kw_bob", PASSWORD)["token"]
    assert auth.login(username="kw_bob", password=PASSWORD)["token"]


# ---------------- 2/3. 口令哈希 ----------------

def test_password_hash_is_not_plaintext_and_not_reversible_encoding(auth, db_path):
    reg = _register(auth, "alice", PASSWORD)
    assert reg["user_id"] and reg["username"] == "alice"

    rows = _users(db_path)
    assert len(rows) == 1
    row = rows[0]
    stored_hash, salt = row["password_hash"], row["password_salt"]

    # 非明文：任何列都不出现口令原文
    for key, value in row.items():
        assert PASSWORD not in str(value or ""), f"{key} 里出现口令明文"
    # 非可逆编码：不是 hex/base64 直接编码后的口令
    assert stored_hash != PASSWORD.encode("utf-8").hex()
    assert stored_hash != hashlib.sha256(PASSWORD.encode()).hexdigest()   # 也不是裸 sha256
    assert len(stored_hash) == 64 and all(c in "0123456789abcdef" for c in stored_hash)
    assert len(salt) == 32 and all(c in "0123456789abcdef" for c in salt)
    # 不可从库内数据重算出摘要：确实需要口令 + 盐 + 轮数
    assert stored_hash != salt
    assert hash_password(PASSWORD, salt) == stored_hash


def test_pbkdf2_rounds_are_exactly_200k(store, auth, db_path):
    """200_000 轮：用同盐同轮数重算必须命中，换轮数必须不命中。"""
    _register(auth, "alice", PASSWORD)
    row = _users(db_path)[0]
    assert PBKDF2_ITERATIONS == 200_000
    assert hash_password(PASSWORD, row["password_salt"]) == row["password_hash"]
    assert hash_password(PASSWORD, row["password_salt"], iterations=199_999) != row["password_hash"]
    assert hash_password(PASSWORD, row["password_salt"], iterations=200_001) != row["password_hash"]


def test_same_password_two_users_get_different_salt_and_hash(auth, db_path):
    """随机盐生效：同一口令的两个账号盐与摘要都不同。"""
    a = _register(auth, "alice", PASSWORD)
    b = _register(auth, "bob", PASSWORD)
    rows = {r["username"]: r for r in _users(db_path)}
    assert rows["alice"]["password_salt"] != rows["bob"]["password_salt"]
    assert rows["alice"]["password_hash"] != rows["bob"]["password_hash"]
    assert a["user_id"] != b["user_id"]
    assert hash_password(PASSWORD, rows["bob"]["password_salt"]) == rows["bob"]["password_hash"]


# ---------------- 4. 会话签发与解析 ----------------

def test_login_issues_session_and_stores_only_sha256_digest(auth, db_path):
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)

    assert out["user_id"] == _users(db_path)[0]["user_id"]
    assert out["username"] == "alice"
    assert isinstance(out["token"], str) and len(out["token"]) >= 32
    # 有效期口径：ISO8601 秒级，与 db.now() 同格式
    assert datetime.fromisoformat(out["expires_at"]) > datetime.now()
    assert out["expires_at"] == datetime.fromisoformat(out["expires_at"]).isoformat(timespec="seconds")

    sessions = _sessions(db_path)
    assert len(sessions) == 1
    sess = sessions[0]
    assert out["token"] != sess["token_hash"]                      # 明文 token 不落库
    assert sess["token_hash"] == token_digest(out["token"])
    assert sess["token_hash"] == hashlib.sha256(out["token"].encode()).hexdigest()
    assert out["token"] not in str(dict(sess))                      # 整行也搜不到明文
    assert sess["user_id"] == out["user_id"]
    assert sess["revoked_at"] == ""
    # 登录写入 last_login_at
    assert _users(db_path)[0]["last_login_at"]


def test_session_ttl_is_30_days(auth, db_path):
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)
    sess = _sessions(db_path)[0]
    delta = datetime.fromisoformat(sess["expires_at"]) - datetime.fromisoformat(sess["created_at"])
    assert SESSION_TTL_DAYS == 30
    assert timedelta(days=30) - timedelta(seconds=2) <= delta <= timedelta(days=30) + timedelta(seconds=2)


def test_resolve_returns_user_id_for_valid_token(auth, db_path):
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)
    uid = out["user_id"]
    assert auth.resolve(out["token"]) == uid
    assert auth.resolve(out["token"]) == uid           # 可重复解析，无一次性副作用
    assert _sessions(db_path)[0]["last_seen_at"]       # 解析顺带刷新 last_seen_at


def test_resolve_returns_none_for_unknown_malformed_and_empty_tokens(auth, db_path):
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)
    token = out["token"]

    assert auth.resolve(token) == out["user_id"]
    assert auth.resolve("") is None
    assert auth.resolve(None) is None
    assert auth.resolve("x" * 43) is None
    # 篡改一个字符即失效
    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    assert auth.resolve(tampered) is None
    # token 摘要在库中不存在时不得回退
    assert auth.resolve(hashlib.sha256(b"nope").hexdigest()) is None


def test_resolve_returns_none_for_expired_session(auth, db_path):
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)
    assert auth.resolve(out["token"]) == out["user_id"]

    past = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?", (past, token_digest(out["token"])))
        conn.commit()
    finally:
        conn.close()

    assert auth.resolve(out["token"]) is None, "过期会话必须判为无效"
    assert _sessions(db_path)[0]["expires_at"] == past   # 过期判定来自库内事实，不是内存缓存


def test_logout_invalidates_token_and_is_idempotent(auth, db_path):
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)

    assert auth.logout(out["token"]) is None
    assert auth.resolve(out["token"]) is None
    assert _sessions(db_path)[0]["revoked_at"]           # 落库为已吊销，不是只改内存

    auth.logout(out["token"])                            # 重复登出不报错
    assert auth.resolve(out["token"]) is None
    auth.logout("never-issued-token")                    # 未知 token 不报错
    auth.logout("")                                      # 空 token 不报错
    auth.logout(None)                                    # None 不报错
    # 仍能在库里直查验证：会话有效期为 30 天口径
    assert auth.resolve("") is None


def test_two_logins_are_independent_sessions(auth, db_path):
    _register(auth, "alice", PASSWORD)
    a = _login(auth, "alice", PASSWORD)
    b = _login(auth, "alice", PASSWORD)
    assert a["token"] != b["token"]
    assert len(_sessions(db_path)) == 2
    auth.logout(a["token"])
    assert auth.resolve(a["token"]) is None
    assert auth.resolve(b["token"]) == b["user_id"]


# ---------------- 5. 公开资料 ----------------

def test_user_returns_public_profile_without_password_columns(auth):
    reg = _register(auth, "alice", PASSWORD, display_name="爱丽丝", kind="real")
    info = auth.user(reg["user_id"])

    assert isinstance(info, dict)
    assert info["user_id"] == reg["user_id"]
    assert info["username"] == "alice"
    assert info["display_name"] == "爱丽丝"
    assert info["kind"] == "real"
    assert set(info) & {"password_hash", "password_salt"} == set()
    assert not any("password" in k for k in info)
    assert PASSWORD not in repr(info)
    assert auth.user("u-does-not-exist") is None
    assert auth.user("") is None


def test_register_honours_display_name_and_kind_defaults(auth, db_path):
    a = _register(auth, "alice", PASSWORD)
    b = _register(auth, "bob", PASSWORD, display_name="鲍勃", kind="demo")
    assert a["display_name"] == "alice"       # db.create_user 的空 display_name 回退为用户名
    assert a["kind"] == "real"                # kind 省略、用户名无 demo 前缀 → real
    assert b["display_name"] == "鲍勃"
    assert b["kind"] == "demo"
    rows = {r["username"]: r for r in _users(db_path)}
    assert rows["bob"]["kind"] == "demo" and rows["alice"]["kind"] == "real"


# ---------------- 7. 账号规则（owner 定） ----------------

def test_username_rules_3_to_32_chars_charset(auth, db_path):
    """username：去空白后 3–32 位，只允许 [A-Za-z0-9_.-]。"""
    ok = auth.register("  Alice_01.x-y  ", PASSWORD)
    assert ok["username"] == "Alice_01.x-y"          # 首尾空白被去掉后才落库
    assert auth.user(ok["user_id"])["username"] == "Alice_01.x-y"

    for bad in ("ab", "a", "a" * 33, "has space", "中文名字", "bad!name", "semi;colon", "", "  "):
        with pytest.raises(ValueError):
            auth.register(bad, PASSWORD)
    assert len(_users(db_path)) == 1


def test_password_min_length_8(auth, db_path):
    with pytest.raises(ValueError):
        auth.register("shortpwd", "1234567")
    assert _users(db_path) == []
    u = auth.register("minpwd", "12345678")
    assert _login(auth, "minpwd", "12345678")["user_id"] == u["user_id"]
    with pytest.raises(AuthCredentialError):
        _login(auth, "minpwd", "1234567")


def test_kind_inference_and_explicit_override(auth, db_path):
    """demo- / u-show 前缀 → demo；显式传入优先；只允许 real/demo。"""
    assert _register(auth, "demo-zhang", PASSWORD)["kind"] == "demo"
    assert _register(auth, "u-show1", PASSWORD)["kind"] == "demo"
    assert _register(auth, "carol", PASSWORD)["kind"] == "real"
    assert _register(auth, "demo-li", PASSWORD, kind="real")["kind"] == "real"
    assert _register(auth, "dave", PASSWORD, kind="demo")["kind"] == "demo"
    assert _register(auth, "erin", PASSWORD, kind=None)["kind"] == "real"      # None == 未指定
    for bad_kind in ("admin", "REAL", "real ", "super", 1):
        with pytest.raises(ValueError):
            auth.register("kind" + str(bad_kind).strip().lower(), PASSWORD, kind=bad_kind)
    rows = {r["username"]: r["kind"] for r in _users(db_path)}
    assert rows == {
        "demo-zhang": "demo", "u-show1": "demo", "carol": "real",
        "demo-li": "real", "dave": "demo", "erin": "real",
    }


def test_user_id_is_server_generated(auth):
    reg = _register(auth, "alice", PASSWORD)
    assert reg["user_id"].startswith("u-")
    assert len(reg["user_id"]) == len("u-") + 12      # secrets.token_hex(6)
    assert reg["user_id"] != _register(auth, "bob", PASSWORD)["user_id"]


# ---------------- 6. 错误口径 ----------------

def test_duplicate_username_raises_409_conflict(auth, db_path):
    _register(auth, "alice", PASSWORD)
    with pytest.raises(AuthConflictError) as exc:
        _register(auth, "alice", "AnotherPass1!")
    assert exc.value.status == 409
    assert isinstance(exc.value, AuthError) and isinstance(exc.value, ValueError)
    assert len(_users(db_path)) == 1
    # 重复注册不得悄悄改掉原账号口令：另开一个 Store 从同一库文件复核
    other = Store(db_path)
    try:
        assert AuthService(other).login("alice", PASSWORD)["token"]
    finally:
        other.close()


def test_wrong_password_and_unknown_user_raise_401(auth):
    _register(auth, "alice", PASSWORD)
    with pytest.raises(AuthCredentialError) as exc:
        _login(auth, "alice", "WrongPass1!")
    assert exc.value.status == 401
    with pytest.raises(AuthCredentialError) as exc2:
        _login(auth, "nobody", PASSWORD)
    assert exc2.value.status == 401
    assert str(exc.value) == str(exc2.value)      # 两种失败同文案，不泄露账号是否存在


def test_blank_username_or_password_rejected(auth, db_path):
    for bad_user in ("", "   ", None, 123):
        with pytest.raises(ValueError):
            auth.register(bad_user, PASSWORD)
    for bad_pwd in ("", None):
        with pytest.raises(ValueError):
            auth.register("alice", bad_pwd)
    assert _users(db_path) == []
    # 登录时的空口令/空用户名按凭据错误处理（不建号、不崩）
    with pytest.raises(AuthCredentialError):
        auth.login("alice", "")


def test_store_v1_only_no_extra_tables_or_columns(auth, db_path):
    """不扩表：只有 users / sessions 参与认证，且列名与 db.py v1 一致。"""
    _register(auth, "alice", PASSWORD)
    out = _login(auth, "alice", PASSWORD)
    auth.resolve(out["token"])
    user_cols = {r["name"] for r in _rows(db_path, "PRAGMA table_info(users)")}
    sess_cols = {r["name"] for r in _rows(db_path, "PRAGMA table_info(sessions)")}
    assert user_cols == {
        "user_id", "username", "display_name", "password_hash", "password_salt", "kind",
        "company", "phone", "email", "bio", "created_at", "updated_at", "last_login_at",
    }
    assert sess_cols == {"token_hash", "user_id", "created_at", "expires_at", "revoked_at",
                         "last_seen_at", "ua"}
    # now() 与落库时间同格式
    assert datetime.fromisoformat(_users(db_path)[0]["created_at"])
    assert datetime.fromisoformat(now())
