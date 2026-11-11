"""TripCraft · 司南礼客 —— API 组合根。

重构后本文件只做四件事：构造 AppContext、挂中间件、注册各域路由、托管前端产物。
**不要再往本文件加路由**：业务路由写进 `tripcraft/api/routers/<domain>.py`
（各域 owner 各自的写范围，见 routers/__init__.py）。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from tripcraft.api.context import AppContext
from tripcraft.api.routers import register_routers
from tripcraft.api.security import install_auth
from tripcraft.services.visit_monitor import VisitMonitorMiddleware

ROOT = Path(__file__).resolve().parents[2]


def create_app() -> FastAPI:
    app = FastAPI(title="TripCraft · 司南礼客", version="0.2.0")
    app.add_middleware(VisitMonitorMiddleware)

    ctx = AppContext()
    app.state.ctx = ctx
    register_routers(app, ctx)

    # 专用演示实例：**启动期**就激活确定性 provider（TRIPCRAFT_SCENARIO_MODE=offline）。
    # 不能等第一次访问 /scenario/* 才激活——否则冷启动后「首页 → 12 题测评 → 学习」
    # 会先打到真实模型，直到有人访问 /demo 才切换（监督者发现的冷启动漏洞）。
    # 常规实例（未设该环境变量）不受影响，仍走真实模型。
    try:
        from tripcraft.api.routers.scenario import _service as _scenario_service
        _scenario_service(ctx)
    except Exception as exc:  # noqa: BLE001  装配失败不阻断启动，但留痕以备验收
        app.state.scenario_startup_error = f"{type(exc).__name__}: {exc}"

    install_auth(app, ctx)

    # 托管前端构建（单容器部署用；本地开发仍走 vite 代理）
    dist = ROOT / "frontend" / "dist"
    if os.environ.get("SERVE_WEB", "").strip() not in ("", "0") and dist.exists():
        try:
            from fastapi.staticfiles import StaticFiles
            app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
        except Exception:
            pass

    return app
