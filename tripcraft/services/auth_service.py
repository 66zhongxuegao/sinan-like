"""认证服务（owner: identity）—— 口令哈希 / 会话签发 / token 解析 / 公开资料。

`tripcraft/api/security.py` 冻结的 AuthService 契约（v1）的唯一实现：

    register(username, password, display_name="", kind="") -> dict   # {user_id, username, ...}
    login(username, password) -> dict                                # {token, expires_at, user_id, ...}
    logout(token) -> None
    resolve(token) -> str | None                                     # token → user_id
    user(user_id) -> dict | None                                     # 公开资料（不含口令哈希）

路由层只做 HTTP 映射，凭据校验与口令一律经过本服务。错误由异常携带 `status`：
重复用户名 409（`AuthConflictError`）、用户名或口令错误 401（`AuthCredentialError`）。

安全口径（技术约束，不得放宽）：
- 口令哈希：PBKDF2-HMAC-SHA256，每用户 16 字节随机盐，200_000 轮；
  比对用 `hmac.compare_digest`（常量时间），且未知用户也走一次同代价比对以防计时枚举。
- token：`secrets.token_urlsafe(32)`，只在签发时返回给调用方；库内只存
  `hashlib.sha256(token.encode()).hexdigest()` 摘要，明文 token 不落库。
- 会话：默认 30 天有效；`expires_at` 用 ISO8601（与 `tripcraft.storage.db.now()` 同格式）。
- 解析：未知 / 已登出 / 已过期的 token 一律返回 None，绝不回退到可伪造的身份。

账号规则（owner 定，路由层不得绕开）：
- username：去首尾空白后 3–32 字符，只允许 `[A-Za-z0-9_.-]`；重复（同名）一律冲突 409。
- password：至少 8 个字符。
- kind：只允许 `real` / `demo`；不传时按用户名推断 —— 以 `demo-` 或 `u-show` 开头记 `demo`，
  其余记 `real`；显式传入时以传入为准。
- user_id 由服务端生成，不接受调用方传入。

依赖：仅标准库（hashlib / hmac / secrets / re / datetime / sqlite3）+ Store v1 的
users/sessions 接口；不 import FastAPI，不自行扩表。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

# ---------------- 口令与 token 参数（冻结口径） ----------------

PBKDF2_ITERATIONS = 200_000
PBKDF2_ALGORITHM = "sha256"
SALT_BYTES = 16
SESSION_TTL_DAYS = 30
TOKEN_BYTES = 32
USER_ID_BYTES = 6

# ---------------- 账号规则（冻结口径） ----------------

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-]{%d,%d}" % (MIN_USERNAME_LENGTH, MAX_USERNAME_LENGTH))
MIN_PASSWORD_LENGTH = 8
USER_KINDS = ("real", "demo")
DEMO_USERNAME_PREFIXES = ("demo-", "u-show")

# 未知用户走的假比对：盐/摘要都固定，只为让失败路径的耗时不泄露「用户名是否存在」。
_DUMMY_SALT = hashlib.sha256(b"tripcraft-auth-dummy-salt").hexdigest()[: SALT_BYTES * 2]

# user() 允许暴露的公开列；口令列（password_hash / password_salt）永远不在白名单里。
PUBLIC_USER_FIELDS = (
    "user_id", "username", "display_name", "kind",
    "company", "phone", "email", "bio",
    "created_at", "updated_at", "last_login_at",
)


# ---------------- 异常 ----------------

class AuthError(ValueError):
    """认证域错误基类：既可按自定义类型捕获，也可按 ValueError 捕获。

    `status` 是路由层应当映射的 HTTP 状态码（默认 400）。
    """

    status = 400


class AuthConflictError(AuthError):
    """用户名已被占用（HTTP 409）。"""

    status = 409


class AuthCredentialError(AuthError):
    """用户名不存在或口令不正确（HTTP 401）；两种失败不区分，避免枚举账号。"""

    status = 401


# ---------------- 纯函数工具（便于测试与复用） ----------------

def new_salt() -> str:
    """每用户一个的随机盐（16 字节，十六进制表示）。"""
    return secrets.token_hex(SALT_BYTES)


def hash_password(password: str, salt_hex: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 → 十六进制摘要。同样的口令配不同的盐必然得到不同摘要。"""
    if not isinstance(password, str) or not password:
        raise ValueError("口令不能为空")
    salt = bytes.fromhex(salt_hex or "")
    if not salt:
        raise ValueError("口令盐不能为空")
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations)
    return dk.hex()


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    """常量时间比对；任何异常都按「不匹配」处理，不向上抛。"""
    if not isinstance(password, str) or not password or not expected_hash or not salt_hex:
        return False
    try:
        actual = hash_password(password, salt_hex)
    except Exception:
        return False
    return hmac.compare_digest(actual, expected_hash)


def token_digest(token: str) -> str:
    """token 的落库形态：sha256 十六进制摘要（明文 token 不落库）。"""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def public_user(row: dict | None) -> dict | None:
    """users 行 → 公开资料 dict；没有行返回 None。

    白名单复制，口令列在结构上不可能泄漏（即使以后 users 表加列也不会自动外泄）。
    """
    if not row:
        return None
    return {k: row[k] for k in PUBLIC_USER_FIELDS if k in row}


def _now_iso() -> str:
    """与 db.now() 完全同格式：本地时间、秒级 ISO8601。"""
    return datetime.now().isoformat(timespec="seconds")


def _expires_at(days: int = SESSION_TTL_DAYS) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def normalize_username(username) -> str:
    """用户名规范化 + 校验：去首尾空白、3–32 字符、仅 [A-Za-z0-9_.-]。"""
    if not isinstance(username, str):
        raise ValueError("用户名必须是字符串")
    text = username.strip()
    if not USERNAME_PATTERN.fullmatch(text):
        raise ValueError(
            f"用户名不合法（需 {MIN_USERNAME_LENGTH}-{MAX_USERNAME_LENGTH} 位，"
            f"只允许字母数字与 _ . -）：{username!r}")
    return text


def validate_password(password) -> str:
    """口令校验：必须是非空字符串且不少于 8 个字符。"""
    if not isinstance(password, str) or not password:
        raise ValueError("口令不能为空")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"口令至少 {MIN_PASSWORD_LENGTH} 位")
    return password


def resolve_kind(username: str, kind: str = "") -> str:
    """kind 口径：显式传入优先且只允许 real/demo（不做宽松裁剪）；不传时按用户名前缀推断。"""
    if kind is None or (isinstance(kind, str) and kind.strip() == ""):
        return "demo" if (username or "").startswith(DEMO_USERNAME_PREFIXES) else "real"
    if not isinstance(kind, str) or kind not in USER_KINDS:
        raise ValueError(f"kind 只允许 {'/'.join(USER_KINDS)}，收到: {kind!r}")
    return kind


# ---------------- 服务 ----------------

class AuthService:
    """注册 / 登录 / 登出 / 会话解析 / 公开资料。

    只依赖 `tripcraft.storage.db.Store` 的 v1 接口：
    create_user / user_by_name / user_by_id / create_session / session_by_hash /
    touch_session / revoke_session / touch_login。
    """

    def __init__(self, store) -> None:
        self.store = store

    # ---- 注册 ----

    def register(self, username: str, password: str, display_name: str = "",
                 kind: str = "") -> dict:
        """建新账号。用户名重复抛 `AuthConflictError`（409）；用户名/口令不合规抛 ValueError。

        账号规则：username 去首尾空白后 3–32 位 `[A-Za-z0-9_.-]`；password ≥ 8 位；
        kind 只允许 real/demo，不传时按用户名前缀（demo- / u-show）推断。
        """
        username = normalize_username(username)
        validate_password(password)
        resolved_kind = resolve_kind(username, kind)

        if self.store.user_by_name(username):
            raise AuthConflictError(f"用户名已被占用: {username}")

        salt = new_salt()
        password_hash = hash_password(password, salt)
        user_id = f"u-{secrets.token_hex(USER_ID_BYTES)}"
        try:
            row = self.store.create_user(user_id, username, password_hash, salt,
                                         display_name=display_name or "", kind=resolved_kind)
        except sqlite3.IntegrityError as exc:      # 并发下唯一约束兜底
            raise AuthConflictError(f"用户名已被占用: {username}") from exc
        if not row:
            row = self.store.user_by_id(user_id) or {}
        return public_user(row) or {}

    def login_accounts(self) -> list[dict]:
        """登录页账户列表；真实账号不回填口令，数据库不保存明文口令。"""
        rows = self.store._all(
            "SELECT user_id, username, display_name, kind FROM users ORDER BY "
            "CASE WHEN username='demo-flow' THEN 0 WHEN username='demo-blank' THEN 1 ELSE 2 END, username")
        demo_hints = {"demo-flow": "Demo2026!", "demo-blank": "Demo2026!"}
        out = []
        for row in rows:
            username = row.get("username") or ""
            label = (row.get("display_name") or username or "").strip()
            suffix = "" if row.get("kind") == "demo" else " · 训练账户"
            out.append({"username": username,
                        "password": demo_hints.get(username, "") if row.get("kind") == "demo" else "",
                        "display_name": row.get("display_name") or username,
                        "kind": row.get("kind") or "real", "label": f"{label}{suffix}"})
        return out

    # ---- 登录 ----

    def login(self, username: str, password: str) -> dict:
        """校验口令并签发会话。失败一律抛 `AuthCredentialError`（401）。"""
        name = username.strip() if isinstance(username, str) else ""
        row = self.store.user_by_name(name) if name else None

        if row is None:
            # 计时对齐：未知用户也做一次同轮数的假比对。
            verify_password(password if isinstance(password, str) else "", _DUMMY_SALT,
                            hash_password("tripcraft-dummy-password", _DUMMY_SALT))
            raise AuthCredentialError("用户名或口令不正确")
        if not verify_password(password, row.get("password_salt") or "",
                               row.get("password_hash") or ""):
            raise AuthCredentialError("用户名或口令不正确")

        token = secrets.token_urlsafe(TOKEN_BYTES)
        expires_at = _expires_at()
        self.store.create_session(token_digest(token), row["user_id"], expires_at)
        self.store.touch_login(row["user_id"])

        return {
            "token": token,
            "expires_at": expires_at,
            "user_id": row["user_id"],
            "username": row.get("username") or "",
            "display_name": row.get("display_name") or "",
            "kind": row.get("kind") or "",
        }

    # ---- 登出 ----

    def logout(self, token: str) -> None:
        """吊销会话（幂等）：未知 token、空 token、重复登出都不报错。"""
        if not token or not isinstance(token, str):
            return None
        digest = token_digest(token.strip())
        row = self.store.session_by_hash(digest)
        if row and not (row.get("revoked_at") or ""):
            self.store.revoke_session(digest)
        return None

    # ---- 会话解析 ----

    def resolve(self, token: str) -> str | None:
        """token → user_id。未知 / 已登出 / 已过期 / 用户已被删除一律返回 None。"""
        if not token or not isinstance(token, str):
            return None
        digest = token_digest(token.strip())
        row = self.store.session_by_hash(digest)
        if not row:
            return None
        if row.get("revoked_at"):
            return None
        expires_at = row.get("expires_at") or ""
        if not expires_at or expires_at < _now_iso():
            return None
        user_id = row.get("user_id") or ""
        if not user_id:
            return None
        self.store.touch_session(digest)
        return user_id

    # ---- 公开资料 ----

    def user(self, user_id: str) -> dict | None:
        """公开资料；不存在返回 None。返回值不含 password_hash / password_salt。"""
        if not user_id or not isinstance(user_id, str):
            return None
        return public_user(self.store.user_by_id(user_id.strip()))


__all__ = [
    "AuthService",
    "AuthError",
    "AuthConflictError",
    "AuthCredentialError",
    "PBKDF2_ITERATIONS",
    "SESSION_TTL_DAYS",
    "TOKEN_BYTES",
    "USER_ID_BYTES",
    "MIN_USERNAME_LENGTH",
    "MAX_USERNAME_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "USER_KINDS",
    "DEMO_USERNAME_PREFIXES",
    "PUBLIC_USER_FIELDS",
    "hash_password",
    "verify_password",
    "new_salt",
    "token_digest",
    "public_user",
    "normalize_username",
    "validate_password",
    "resolve_kind",
]
