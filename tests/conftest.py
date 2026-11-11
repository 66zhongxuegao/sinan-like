"""测试期全局约定（Lead 单写者）。

三件事在任何 tripcraft 模块被 import 之前完成：

1. 公网访问监控（tripcraft/services/visit_monitor.py）默认把访客写进项目根 logs/；
   跑测试时会经过 TestClient 产生一堆假访问，所以把日志目录改到临时目录。
2. **数据库隔离**：测试一律使用独立临时库，绝不写开发库/演示库
   （交接文本要求「测试使用独立数据库，不操作真实历史训练记录」）。
   需要自己指定库的测试仍可直接覆盖 TRIPCRAFT_DB 或给 Store(path)。
3. 提供认证工具：新版 API 默认 TRIPCRAFT_AUTH=on，受保护路径必须带有效会话。
   这里给出 `register_and_login` / `auth_client` / `auth_headers`，
   供各域把自己域内的 API 测试迁移到新认证（**不得为迎合旧测试而禁用安全控制**）。

认证 HTTP 契约（与 tripcraft/api/security.py 冻结契约配套，owner: identity）：
    POST /auth/register  {"username","password","display_name"?} -> 200 {"user_id","username",...}
    POST /auth/login     {"username","password"}                -> 200 {"token","user_id","expires_at"}
    POST /auth/logout                                            -> 200（带 token）
    GET  /auth/session                                           -> 200 {"user_id","username"} 或 401
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest

os.environ.setdefault("TRIPCRAFT_VISIT_LOG_DIR", tempfile.gettempdir())
os.environ.setdefault("TRIPCRAFT_COMPETITION_EASY", "0")

# 独立测试库：每个测试会话一个**文件**，互不污染，也不碰 tripcraft.sqlite。
#
# 注意（identity 实测的沙箱限制，证据 output/acceptance/identity/sandbox-tempdir-probe.txt）：
# 在本机沙箱下「进程新建的目录」不可访问——在 tempfile.mkdtemp() 返回的目录里
# sqlite3.connect 打不开文件、os.mkdir 报 WinError 5；而已存在的系统临时目录一切正常。
# 所以这里**不再建目录**，直接把库文件放到已存在的系统临时目录里。
os.environ["TRIPCRAFT_DB"] = os.path.join(
    tempfile.gettempdir(), f"tripcraft-test-{uuid.uuid4().hex}.sqlite"
)

DEFAULT_PASSWORD = "Test1234!"


def new_username(prefix: str = "u") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def register_and_login(client, username: str | None = None, password: str = DEFAULT_PASSWORD):
    """走真实注册 + 登录接口，返回 (username, user_id, token)。

    这是各域迁移 API 测试的标准入口；不要用 header 直通绕过认证。
    """
    username = username or new_username()
    reg = client.post("/auth/register", json={
        "username": username, "password": password, "display_name": username,
    })
    assert reg.status_code in (200, 201), f"注册失败: {reg.status_code} {reg.text}"
    user_id = (reg.json() or {}).get("user_id") or ""
    login = client.post("/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, f"登录失败: {login.status_code} {login.text}"
    token = (login.json() or {}).get("token") or ""
    assert token, f"登录未返回 token: {login.text}"
    return username, user_id, token


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    """未认证客户端（用于公开路径与 401 断言）。"""
    from fastapi.testclient import TestClient

    from tripcraft.api.app import create_app

    return TestClient(create_app())


@pytest.fixture
def auth_client(client):
    """(client, headers)：已注册并登录的独立账号，后续请求带 Bearer token。"""
    _username, _user_id, token = register_and_login(client)
    return client, auth_headers(token)


# ======================================================================
# 测试期默认「禁真实模型 / 禁真实外网」
#
# 背景（监督者审查意见）：本仓库 local.env 里已经有真实 DEEPSEEK_API_KEY。
# 如果测试里任何代码路径不小心构造了 DeepSeekClient，就会真的联网——
# 造成 120s 级超时、真实费用、以及非确定性数据。测试必须默认离线。
#
# 做法：autouse fixture 把模型类的方法替换成**明确失败**（抛 LLMError），
# 效果等同于「未配置模型」，与拆分前的行为一致且完全确定。
# 需要真实链路的验证只能走单独脚本：scripts/acceptance_real_model.py
# （它在 pytest 之外运行，不受这里的拦截影响）。
# 测试要模拟模型时，自己 monkeypatch 覆盖（fixture 先执行，测试内的覆盖生效）。
#
# 注意：这里**不是**为了让测试变绿而屏蔽断言；它把「意外联网」变成显式失败。
# ======================================================================

@pytest.fixture(autouse=True)
def _no_real_model(monkeypatch):
    """测试期禁止真实模型调用：任何 chat/chat_json 直接抛 LLMError。"""
    from tripcraft.agents import llm as llm_mod

    def _blocked(*_args, **_kwargs):
        raise llm_mod.LLMError(
            "测试环境禁用真实模型调用；真实链路验收见 scripts/acceptance_real_model.py"
        )

    monkeypatch.setattr(llm_mod.DeepSeekClient, "chat", _blocked, raising=False)
    monkeypatch.setattr(llm_mod.DeepSeekClient, "chat_json", _blocked, raising=False)
    # 避免测试断言依赖本机 local.env 是否存在真实 key
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_real_external_network(monkeypatch):
    """测试期禁止外部工具真实联网（高德/汇率等）。

    需要外部数据的测试请在自己的用例里 monkeypatch `_get_json` 提供 stub
    （测试内的 monkeypatch 在本 fixture 之后执行，会覆盖它）。
    """
    from tripcraft.tools import external as ext_mod

    def _blocked(*_args, **_kwargs):
        raise RuntimeError(
            "测试环境禁止真实外部网络调用；请在本用例内 monkeypatch stub 数据"
        )

    monkeypatch.setattr(ext_mod, "_get_json", _blocked, raising=False)


@pytest.fixture(autouse=True)
def _isolate_local_env(monkeypatch):
    """测试期**完全不读真实 local.env**。

    必要性（Codex 审查意见）：本仓库 local.env 里有真实 DEEPSEEK_API_KEY。
    只要有任何代码路径读到它，畸形输入下的 traceback 就可能把**整个 env 字典**
    打进 pytest 日志，造成私钥泄漏。所以这里把 tripcraft 内所有 local.env 读取点
    统一替换成测试用固定值——测试既不依赖本机配置，也不把凭据载入内存。

    覆盖的读取点（全仓 grep 结果）：
      tripcraft/agents/llm.py::load_env
      tripcraft/tools/external.py::load_env
      tripcraft/voice/realtime_qwen.py::_local_env
      tripcraft/services/dispatch_service.py::_env
    """
    from tripcraft.agents import llm as llm_mod
    from tripcraft.services import dispatch_service as dispatch_mod
    from tripcraft.tools import external as ext_mod
    from tripcraft.voice import realtime_qwen as voice_mod

    monkeypatch.setattr(llm_mod, "load_env", lambda: {}, raising=False)
    monkeypatch.setattr(ext_mod, "load_env",
                        lambda: {"AMAP_API_KEY": "test-placeholder-key-not-real"}, raising=False)
    monkeypatch.setattr(voice_mod, "_local_env", lambda: {}, raising=False)
    monkeypatch.setattr(dispatch_mod, "_env",
                        lambda: dict(dispatch_mod.DEFAULTS), raising=False)

    # 环境变量侧同样保持干净：只留无网络的占位 key
    monkeypatch.setenv("AMAP_API_KEY", "test-placeholder-key-not-real")
    for _k in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "QWEN_OMNI_API_KEY"):
        monkeypatch.delenv(_k, raising=False)