"""路由模块注册表（Lead 冻结 v1）。

新增业务域 = 在 routers/ 下加一个模块，暴露 `build(ctx) -> APIRouter`，
然后把模块名加进 `ROUTER_MODULES`（本文件由 Lead 单写者维护）。

写范围约定（防并发写冲突）：
  core / runs / platform  → Lead
  auth / growth           → identity 域
  practice / deliverables → journey 域
  calls                   → conversation 域
  scenario（新增）        → scenario 域
"""

from __future__ import annotations

from importlib import import_module

from fastapi import FastAPI

ROUTER_MODULES = (
    "core",
    "auth",
    "runs",
    "practice",
    "deliverables",
    "calls",
    "growth",
    "scenario",
    "platform",
    "competition",
)


def register_routers(app: FastAPI, ctx) -> FastAPI:
    """按固定顺序装配各域路由。"""
    for name in ROUTER_MODULES:
        mod = import_module(f"tripcraft.api.routers.{name}")
        app.include_router(mod.build(ctx))
    return app
