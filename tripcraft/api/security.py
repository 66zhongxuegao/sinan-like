"""认证与会话（API 边界层，Lead 冻结 v2）。

v2 变更（监督者静态审查后收紧）：
  1. **删除 TRIPCRAFT_AUTH=off 身份直通旁路**。认证永远强制，生产、标准案例、
     旧测试迁移统一使用真实会话；测试通过注册临时账号取得会话，不允许关认证。
  2. `own_order` 不再接受任何「公共池」式放行。核对结论：`PracticeService.available_orders()`
     返回的本来就是**该 user_id 自己**的、stage_index=0 且未 grab 的订单，
     因此抢单场景无需跨用户放行，归属校验可以严格到底。
  3. 公开路径用**精确/段边界**匹配，不再用可误匹配的松散前缀；
     静态资源白名单与 API 白名单分开（仅 SERVE_WEB 托管时生效）。

职责：把「请求 → 可信 user_id」集中到一处，路由层只消费 `current_user`。
凭据校验、口令哈希、会话签发在 `tripcraft.services.auth_service.AuthService`（owner: identity）。

AuthService 契约（v1，不变）：
    register(username, password, display_name="") -> dict   # {user_id, username, ...}
    login(username, password) -> dict                       # {token, expires_at, user_id, ...}
    logout(token) -> None
    resolve(token) -> str | None                            # token → user_id
    user(user_id) -> dict | None                            # 公开资料（不得含口令哈希）

HTTP 契约：POST /auth/register、POST /auth/login、POST /auth/logout、GET /auth/session。

变更此文件必须升版并通知全部 owner。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse

COOKIE_NAME = "tc_token"

# ---------------- 公开 API（精确 + 段边界；不写松散前缀） ----------------

PUBLIC_API_EXACT = frozenset({
    "/",                     # 健康检查 / SERVE_WEB 时给前端页面
    "/auth/register",
    "/auth/login",
    "/auth/login-accounts",
    "/auth/logout",
    "/auth/session",
    "/deliverables/specs",   # 交付物契约（静态定义）
    "/profile/quiz",         # 初始测评题库（静态题目，不含答案）
    "/contracts/markets",    # 客源市场清单（静态参考数据）
    "/openapi.json",
    "/redoc",
})

PUBLIC_API_PREFIX = (
    "/contracts",            # /contracts/steps|dimensions|skill-points|rubric|...
    "/learn/culture-bridges",
    "/docs",                 # FastAPI 自带文档页
)

# ---------------- 静态资源（仅 SERVE_WEB 托管前端时生效） ----------------
#
# 只放行**真实存在于 frontend/dist 构建产物中**的文件，不使用「任意扩展名」规则：
# 否则 /private/notes.txt、/x.js、/y.map 都会绕过认证中间件（监督者静态审查项3）。
# 前端用 hash 路由（createWebHashHistory），服务端只需分发 "/" 与构建产物，
# 因此不需要 SPA 深链兜底，也就无需给任意路径开口子。

ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = ROOT / "frontend" / "dist"

_STATIC_CACHE: dict[str, object] = {"key": None, "paths": frozenset()}


def static_paths() -> frozenset[str]:
    """枚举构建产物里的可公开静态路径；按构建产物 mtime 轻量缓存。"""
    if not DIST_DIR.is_dir():
        return frozenset()
    try:
        stamps = [DIST_DIR.stat().st_mtime_ns]
        for probe in ("index.html", "assets"):
            p = DIST_DIR / probe
            if p.exists():
                stamps.append(p.stat().st_mtime_ns)
        key = (str(DIST_DIR), tuple(stamps))
    except OSError:
        return frozenset()
    if _STATIC_CACHE.get("key") == key:
        return _STATIC_CACHE["paths"]        # type: ignore[return-value]
    found = {"/"}
    try:
        for p in DIST_DIR.rglob("*"):
            if p.is_file():
                found.add("/" + p.relative_to(DIST_DIR).as_posix())
    except OSError:
        return frozenset()
    paths = frozenset(found)
    _STATIC_CACHE["key"] = key
    _STATIC_CACHE["paths"] = paths
    return paths


def serve_web() -> bool:
    return os.environ.get("SERVE_WEB", "").strip() not in ("", "0")


def _under(path: str, prefix: str) -> bool:
    """段边界前缀匹配：/docs 命中 /docs 与 /docs/x，但**不**命中 /docsx。"""
    p = prefix.rstrip("/")
    if not p:
        return path == "/"
    return path == p or path.startswith(p + "/")


def is_public_api(path: str) -> bool:
    if path in PUBLIC_API_EXACT:
        return True
    return any(_under(path, p) for p in PUBLIC_API_PREFIX)


def is_public_static(path: str) -> bool:
    """只放行真实构建产物（精确路径命中），不再用扩展名规则（监督者审查项3）。"""
    if not serve_web():
        return False
    if is_public_api(path):
        return True
    return path in static_paths()


def is_public(path: str) -> bool:
    return is_public_api(path) or is_public_static(path)


# ---------------- 会话解析 ----------------

def extract_token(request: Request) -> str:
    """Bearer 头优先，其次 cookie `tc_token`。"""
    head = request.headers.get("authorization") or ""
    if head.lower().startswith("bearer "):
        return head[7:].strip()
    return (request.cookies.get(COOKIE_NAME) or "").strip()


def resolve_user(ctx, request: Request) -> str | None:
    """把请求解析成可信 user_id；解析不了返回 None（绝不回退到可伪造的身份）。"""
    token = extract_token(request)
    if not token:
        return None
    try:
        return ctx.get_auth().resolve(token)
    except ModuleNotFoundError:
        # 认证模块尚未就绪：拒绝而不是放行（fail-closed）
        raise HTTPException(503, "认证服务未就绪")
    except Exception:
        return None


def install_auth(app, ctx) -> None:
    """HTTP 认证中间件：设定 request.state.user_id，并对非公开路径 fail-closed。"""

    @app.middleware("http")
    async def _auth_mw(request: Request, call_next):
        request.state.user_id = None
        try:
            uid = resolve_user(ctx, request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        request.state.user_id = uid
        if uid is None and not is_public(request.url.path):
            return JSONResponse({"detail": "未登录或会话已失效，请重新登录"}, status_code=401)
        return await call_next(request)


def current_user(request: Request) -> str:
    """FastAPI 依赖：取当前登录用户（受保护路由必须声明它）。"""
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "未登录或会话已失效")
    return uid


def require_self(requested_user_id: str, actual_user_id: str, what: str = "该用户的资源") -> str:
    """请求体/查询串里带来的 user_id 不得冒用他人。

    路由层拿到 current_user 后，凡请求里出现 user_id，一律用它校验；
    尤其是 POST/PUT 请求体里的 user_id 字段。
    """
    if requested_user_id and requested_user_id != actual_user_id:
        raise HTTPException(403, f"无权访问{what}")
    return actual_user_id


# ---------------- WebSocket ----------------

def websocket_user(ctx, ws: WebSocket) -> str | None:
    """WebSocket 无中间件覆盖，自行取 token（query `token` 或 cookie）。

    没有 token 就返回 None —— 调用方必须拒绝连接，不得匿名进入。
    """
    token = (ws.query_params.get("token") or "").strip() or (ws.cookies.get(COOKIE_NAME) or "").strip()
    if not token:
        return None
    try:
        return ctx.get_auth().resolve(token)
    except Exception:
        return None


# ---------------- 调试/系统面门禁 ----------------

def debug_enabled(env_var: str) -> bool:
    """内部调试/系统开关：默认关闭，必须显式置 1/on/true。"""
    return os.environ.get(env_var, "").strip().lower() in ("1", "on", "true")


def require_debug(env_var: str, label: str) -> None:
    """未开开关时按「路由不存在」处理，不暴露内部面（fail-closed）。

    用于：原始状态机控制（flags / rollback）、校准写、MCP 调试面等
    ——这些不是普通学员可任意调用的入口。
    """
    if not debug_enabled(env_var):
        raise HTTPException(404, "未找到")


# ---------------- 对象归属 ----------------

def own_order(ctx, user_id: str, order_id: str) -> dict:
    """订单归属校验：不存在 404，不属于当前用户 403。

    严格归属，无公共池放行：`available_orders()` 返回的本就是该用户自己的
    stage_index=0 未抢订单，抢单走的是同一 user_id，不需要跨用户例外。
    """
    row = ctx.store.order(order_id)
    if not row:
        raise HTTPException(404, f"未找到订单: {order_id}")
    if (row.get("user_id") or "") != user_id:
        raise HTTPException(403, "无权访问该订单")
    return row
