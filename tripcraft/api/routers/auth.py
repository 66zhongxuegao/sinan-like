"""身份域 HTTP 入口（owner: identity）：注册 / 登录 / 登出 / 会话恢复 / 个人资料。

对外契约（Lead 冻结 v1，tests/conftest.py 与前端都按此编写）：
    POST  /auth/register  {"username","password","display_name"?}
                          -> 200 {"user_id","username","display_name","token","expires_at"}
    POST  /auth/login     {"username","password"}
                          -> 200 {"token","user_id","expires_at","username"}
    POST  /auth/logout    -> 200 {"ok": true, "revoked": bool}
    GET   /auth/session   -> 200 {"user_id","username",...} / 401
    GET   /auth/profile   -> 200 公开个人资料
    PATCH /auth/profile   -> 200 公开个人资料（display_name/company/phone/email/bio）

安全要点（R08/R11）：
- 口令只经 AuthService 做加盐哈希落库，本模块永远不接触明文口令的存储形态。
- 返回给前端的任何个人资料都来自 `AuthService.user()`，绝不含 password_hash / password_salt。
- 注册成功后直接签发会话（等价于「注册即登录」），口令同时写入 HttpOnly cookie `tc_token`，
  供新窗口打开 PDF/文件下载时仍能通过 security.extract_token 的 cookie 分支。
- 本模块只消费 `ctx.get_auth()`，不 import 具体服务实现之外的任何 HTTP 细节。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from tripcraft.api.context import AppContext
from tripcraft.api.security import COOKIE_NAME, extract_token

# 服务层异常：优先用 AuthService 真实实现里的类；服务层缺失时用同名兜底，
# 保证「模块没就绪」表现为 503 而不是把注册/登录路由一起带崩。
# 真实实现（tripcraft/services/auth_service.py）用 AuthError 基类 + `.status` 属性：
# AuthConflictError.status=409、AuthCredentialError.status=401。
try:  # pragma: no cover - 正常路径下一定 import 成功
    from tripcraft.services.auth_service import AuthConflictError, AuthError
except ImportError:  # pragma: no cover
    class AuthConflictError(ValueError):  # type: ignore[no-redef]
        """用户名冲突（兜底定义，仅当服务层缺失时存在）。"""

    class AuthError(ValueError):  # type: ignore[no-redef]
        """认证失败（兜底定义，仅当服务层缺失时存在）。"""


USERNAME_MIN = 3
USERNAME_MAX = 32
PASSWORD_MIN = 8
PROFILE_FIELDS = ("display_name", "company", "phone", "email", "bio")

# 新账号初始化：注册后发 1 条隔离的初始派单，避免消息中心/订单管理一片空白。
BOOTSTRAP_ORDERS_ENV = "TRIPCRAFT_BOOTSTRAP_ORDERS"
_OFF = ("0", "false", "off", "no")

# demo/示例身份约定（R14「区分示例与真实数据」、R13 演示模式隔离身份）：
# username 前缀决定 users.kind，Standard Case 域与前端演示入口都按这个前缀建号。
DEMO_USERNAME_PREFIXES = ("demo-", "u-show")


# ---------------- 请求 DTO（本域自有；schemas.py 为 Lead 所有，不在此新增） ----------------

class RegisterBody(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


class ProfileBody(BaseModel):
    display_name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    bio: str | None = None


# ---------------- 内部工具 ----------------

def _fail(exc: Exception, default_status: int = 401, default_detail: str = "认证失败") -> HTTPException:
    """把服务层异常映射成 HTTP 状态。

    主路径：AuthService 的异常自带 `.status`（AuthConflictError=409 / AuthCredentialError=401），
    直接用；类名与 ValueError 分支只是兜底，避免服务层换名字后状态码悄悄退化成 400。
    """
    detail = str(exc) or default_detail
    status = getattr(exc, "status", None)
    if isinstance(status, int) and 400 <= status <= 599:
        return HTTPException(status, detail)
    name = type(exc).__name__
    if isinstance(exc, AuthConflictError) or name in (
            "AuthConflict", "AuthConflictError", "UsernameTaken", "Conflict"):
        return HTTPException(409, detail)
    if name in ("AuthError", "AuthCredentialError", "AuthFailed", "InvalidCredentials"):
        return HTTPException(401, detail)
    if isinstance(exc, ValueError):
        # 入参校验类错误（用户名/口令规则）由服务层抛出，按 400 处理
        return HTTPException(400, detail)
    return HTTPException(default_status, detail)


def _public(user: dict | None) -> dict:
    """公开个人资料视图：显式白名单，杜绝口令哈希等内部列被带出去。"""
    row = dict(user or {})
    return {
        "user_id": row.get("user_id", ""),
        "username": row.get("username", ""),
        "display_name": row.get("display_name", ""),
        "company": row.get("company", ""),
        "phone": row.get("phone", ""),
        "email": row.get("email", ""),
        "bio": row.get("bio", ""),
        "kind": row.get("kind", "real"),
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
        "last_login_at": row.get("last_login_at", ""),
    }


def _validate_credentials(username: str, password: str) -> str:
    name = (username or "").strip()
    if not (USERNAME_MIN <= len(name) <= USERNAME_MAX):
        raise HTTPException(400, f"用户名需为 {USERNAME_MIN}–{USERNAME_MAX} 个字符")
    if not all(ch.isalnum() or ch in "_.-" for ch in name):
        raise HTTPException(400, "用户名只能包含字母、数字、下划线、点与短横线")
    if len(password or "") < PASSWORD_MIN:
        raise HTTPException(400, f"口令至少 {PASSWORD_MIN} 位")
    return name


def _expires_in_seconds(expires_at: str) -> int | None:
    try:
        delta = datetime.fromisoformat(str(expires_at)) - datetime.now()
    except (TypeError, ValueError):
        return None
    secs = int(delta.total_seconds())
    return secs if secs > 0 else 1


def _set_session_cookie(response: Response, token: str, expires_at: str) -> None:
    if not token:
        return
    max_age = _expires_in_seconds(expires_at) or 30 * 24 * 3600
    response.set_cookie(
        COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="lax", path="/",
    )


def _bootstrap_new_account(ctx: AppContext, user_id: str, kind: str) -> dict:
    """新注册账号的隔离初始数据。

    **不用** `PracticeService.seed(user_id)` 给每个新用户铺单：
    seed 写的是固定 SEED_ORDERS 的 order_id，而 `store.upsert_order` 是
    INSERT OR REPLACE —— 同一个 order_id 会整行改写，归属随之易主。
    identity 在调查期实测过这个后果：seed("u-demo") 后 10 条演示单全归 u-demo，
    再 seed("u-new") 后 10/10 全部变成 u-new 的，u-demo 一张不剩。
    journey 随后在 `practice_service.seed()` 里加了归属保护（跳过已被他人持有的
    order_id），当前版本已不可复现；机制层面仍由本文件的证据脚本持续验证
    （output/acceptance/identity/bootstrap-seed-contamination.txt 第 2 节）。

    因此新用户的初始单走 `generate_dispatch(user_id, llm=None, count=1)`：
    `spawn_order` 生成全局唯一 order_id 并直接落在目标 user_id 名下，用户之间不共享
    order_id，也不需要模型（llm=None 走确定性生成）。这是 Lead 已采纳的全队口径，
    也与 practice_service.seed() 自己的 docstring 一致。要更多单走既有入口
    `POST /practice/dispatch/generate`（owner: journey）。

    demo 账号（标准的「标准案例」身份，username 前缀 demo- / u-show → kind=demo）
    不在这里初始化，交由 scenario 域按固定案例注入。
    """
    # 演示实例：注册初始单也走「固定案例替换随机游客」（服务端开关，不看账号名）。
    # 幂等：同名账号第二次注册会被 409 拒绝；本函数只在注册成功时执行一次，不会重复建单。
    # 演示实例里注册初始单**必须**是固定案例：
    #   - 替换成功 → 固定黄先生那单；
    #   - 替换失败 → **可读失败**（seeded=false + 原因），**绝不静默退回随机游客**
    #     （否则现场会跑错客人且难排查）；账号本身已建好，注册数据保留。
    from tripcraft.services.scenario_service import demo_instance, demo_replacement
    if demo_instance()["enabled"]:
        try:
            replaced = demo_replacement(ctx, user_id, count=1)
        except Exception as exc:  # noqa: BLE001 - 注册不失败，但如实报错、绝不倒随机
            return {"seeded": False,
                    "reason": f"演示实例固定案例注入失败（未退回随机游客）：{type(exc).__name__}: {exc}",
                    "replaced_random_tourist": False,
                    "how": "scenario.demo_replacement（失败，已如实上报）"}
        return {"seeded": True,
                "orders": replaced.get("orders") or [],
                "replaced_random_tourist": True,
                "case_id": replaced.get("case_id", ""),
                "how": replaced.get("how", "scenario.demo_replacement")}
    if kind == "demo":
        return {"seeded": False, "reason": "demo 账号由标准案例域初始化"}
    if os.environ.get(BOOTSTRAP_ORDERS_ENV, "1").strip().lower() in _OFF:
        return {"seeded": False, "reason": f"{BOOTSTRAP_ORDERS_ENV}=off"}
    try:
        res = ctx.practice.generate_dispatch(user_id, llm=None, count=1)
    except Exception as exc:  # noqa: BLE001 - 初始化失败不得让注册失败
        return {"seeded": False, "reason": f"生成初始派单失败: {exc}"}
    created = res.get("created") or []
    return {"seeded": bool(created),
            "orders": [c.get("order_id") for c in created],
            "how": "practice.generate_dispatch(user, llm=None, count=1)"}


def build(ctx: AppContext) -> APIRouter:
    """装配身份域路由。每个 app 实例调用一次。"""
    router = APIRouter()

    def _auth():
        try:
            return ctx.get_auth()
        except ModuleNotFoundError as exc:
            raise HTTPException(503, f"认证服务未就绪: {exc}")

    def _current(request: Request) -> str:
        uid = getattr(request.state, "user_id", None)
        if not uid:
            raise HTTPException(401, "未登录或会话已失效")
        return uid

    # ---------------- 注册 / 登录 / 登出 / 会话 ----------------

    @router.post("/auth/register")
    def auth_register(body: RegisterBody, request: Request, response: Response):
        username = _validate_credentials(body.username, body.password)
        kind = "demo" if username.lower().startswith(DEMO_USERNAME_PREFIXES) else "real"
        # 内部演示实例里，**任何用户名**注册出来的账号都是示例来源（不按用户名判定）：
        # 否则现场用普通用户名注册的账号会被算进真实训练统计口径，混掉示例/真实的分界。
        from tripcraft.services.scenario_service import demo_instance
        demo_flag = demo_instance()
        if demo_flag["enabled"]:
            kind = "demo"
        svc = _auth()
        try:
            user = svc.register(username, body.password,
                                (body.display_name or "").strip() or username, kind=kind)
        except TypeError:
            # 服务层若未接受 kind 关键字，退回 v1 两参数调用（公开契约只有三个位置参数）
            try:
                user = svc.register(username, body.password,
                                    (body.display_name or "").strip() or username)
            except Exception as exc:  # noqa: BLE001
                raise _fail(exc, 400, "注册失败")
        except Exception as exc:  # noqa: BLE001 - 统一映射为 HTTP 状态
            raise _fail(exc, 400, "注册失败")
        try:
            sess = svc.login(username, body.password)
        except Exception as exc:  # noqa: BLE001
            # 注册已成功；签发失败时仍返回公开资料，由前端走登录页重试
            return {"user_id": user.get("user_id", ""), "username": username,
                    "display_name": user.get("display_name", ""), "token": "",
                    "expires_at": "", "login_error": str(exc)}
        payload = _public(svc.user(user.get("user_id", "")) or user)
        payload.update({"token": sess.get("token", ""), "expires_at": sess.get("expires_at", "")})
        if not payload.get("display_name"):
            payload["display_name"] = user.get("display_name", "")
        # 新账号初始化：注册即得到 1 条只属于自己的初始派单（走 generate_dispatch，不 seed）
        payload["bootstrap"] = _bootstrap_new_account(ctx, payload["user_id"], payload.get("kind", "real"))
        _set_session_cookie(response, payload["token"], payload["expires_at"])
        return payload

    @router.get("/auth/login-accounts")
    def auth_login_accounts():
        """本地登录助手：列出全部已注册账号和可回填密码，不返回密码哈希。"""
        # 空白演示账号是产品内置账号：即使库被替换/清理，也要保证它出现在登录列表。
        try:
            from tripcraft.services import demo_blank_state
            demo_blank_state.ensure_account(ctx, reset=False)
        except Exception:  # noqa: BLE001 - 账号补建失败不阻断登录列表
            pass
        return {"accounts": _auth().login_accounts()}

    @router.post("/auth/login")
    def auth_login(body: LoginBody, response: Response):
        username = (body.username or "").strip()
        if not username or not body.password:
            raise HTTPException(400, "请输入用户名与口令")
        svc = _auth()
        try:
            sess = svc.login(username, body.password)
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc, 401, "用户名或密码不正确")
        payload = {
            "token": sess.get("token", ""),
            "user_id": sess.get("user_id", ""),
            "username": sess.get("username", username),
            "expires_at": sess.get("expires_at", ""),
        }
        try:
            payload["user"] = _public(svc.user(payload["user_id"]))
        except Exception:  # noqa: BLE001 - 资料读取失败不应影响登录本身
            payload["user"] = None
        # 空白演示账号：每次登录都清空旧的订单/学习/画像，保证从「未测画像」开始。
        try:
            from tripcraft.services import demo_blank_state
            if (sess.get("username") or username) == demo_blank_state.USERNAME:
                demo_blank_state.reset_blank(ctx, payload["user_id"])
        except Exception:  # noqa: BLE001 - 演示复位失败不阻断登录
            pass
        _set_session_cookie(response, payload["token"], payload["expires_at"])
        return payload

    @router.post("/auth/logout")
    def auth_logout(request: Request, response: Response):
        token = extract_token(request)
        revoked = False
        if token:
            try:
                from tripcraft.services import demo_blank_state, demo_stage_state, demo_standard_state
                uid = ctx.get_auth().resolve(token)
                user = ctx.get_auth().user(uid) if uid else None
                if user and user.get("username") == demo_stage_state.USERNAME:
                    demo_stage_state.reset_initial(ctx, uid)
                elif user and user.get("username") == demo_blank_state.USERNAME:
                    demo_blank_state.reset_blank(ctx, uid)
                elif user and user.get("username") == demo_standard_state.USERNAME:
                    demo_standard_state.reset_standard(ctx, uid)
            except Exception:  # noqa: BLE001 - 演示复位失败不阻断退出
                pass
            try:
                ctx.get_auth().logout(token)
                revoked = True
            except ModuleNotFoundError as exc:
                raise HTTPException(503, f"认证服务未就绪: {exc}")
            except Exception:  # noqa: BLE001 - 登出幂等：未知 token 也算已登出
                revoked = False
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True, "revoked": revoked}

    @router.get("/auth/session")
    def auth_session(request: Request):
        uid = getattr(request.state, "user_id", None)
        if not uid:
            raise HTTPException(401, "未登录或会话已失效")
        svc = _auth()
        try:
            user = svc.user(uid)
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc, 401, "会话无效")
        if not user:
            raise HTTPException(401, "会话对应的账号不存在")
        return _public(user)

    # ---------------- 个人资料（R12 右上角用户菜单） ----------------

    @router.get("/auth/profile")
    def auth_profile_get(request: Request):
        uid = _current(request)
        svc = _auth()
        try:
            user = svc.user(uid)
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc, 401)
        if not user:
            raise HTTPException(404, "账号不存在")
        return _public(user)

    @router.patch("/auth/profile")
    def auth_profile_patch(body: ProfileBody, request: Request):
        uid = _current(request)
        svc = _auth()
        fields = {k: getattr(body, k) for k in PROFILE_FIELDS if getattr(body, k) is not None}
        if not fields:
            raise HTTPException(400, "没有需要更新的字段")
        try:
            updated = svc.update_profile(uid, fields)
        except AttributeError:
            # 服务层未暴露 update_profile 时的兜底：直接经 Store 白名单更新
            updated = ctx.store.update_user_profile(uid, fields)
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc, 400, "资料更新失败")
        if not updated:
            raise HTTPException(404, "账号不存在")
        return _public(updated)

    return router
