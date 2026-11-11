"""MCP 封装 —— 把外部数据与资源能力按 Model Context Protocol 暴露（PRD 23 / DECISIONS D-011）。

定位：**框架先行、数据可换**。今天后面接的是高德/Open-Meteo/汇率 + 角色扮演的模拟资源方；
复赛如果拿到携程或真实供应商接口，只替换 handler 实现，工具契约（名字 / 入参 / 出参）不变。

不引入重框架：这里实现 MCP 的核心 JSON-RPC 方法（initialize / tools/list / tools/call / ping），
由 FastAPI 暴露在 `POST /mcp`。stdio 传输可复用同一份 `handle()`。
"""

from __future__ import annotations

import json
from typing import Any, Callable

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "tripcraft", "version": "0.1.0"}

# JSON Schema 片段
STR = {"type": "string"}
ORDER = {"type": "string", "description": "本地订单号，如 9000000000000004"}


def tool(name: str, description: str, properties: dict, required: list[str],
         handler: str) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
        "_handler": handler,
    }


TOOLS: tuple[dict, ...] = (
    tool("weather.get", "查询某城市当前天气（Open-Meteo + 高德地理编码）",
         {"city": STR}, ["city"], "weather"),
    tool("route.plan", "规划两点驾车路线，返回距离与耗时（高德）",
         {"origin": STR, "destination": STR}, ["origin", "destination"], "route"),
    tool("itinerary.check", "核验行程点顺序：折返检测 + 累计驾车耗时",
         {"stops": {"type": "array", "items": STR}}, ["stops"], "itinerary"),
    tool("fx.rates", "实时汇率（open.er-api.com）",
         {"base": STR, "quotes": {"type": "array", "items": STR}}, [], "fx"),
    tool("supplier.inquire", "向资源方（地接社/酒店/车队/票务）询价，返回报价与可用性",
         {"kind": STR, "request": STR}, ["kind", "request"], "supplier"),
    tool("deliverable.push", "把交付物投递给客户，返回客户反馈（会先过双层拦截网）",
         {"kind": STR, "content": STR, "customer": STR, "order_id": ORDER},
         ["kind", "content", "order_id"], "deliverable"),
    tool("guard.check", "对交付物跑双层拦截网：确定性校验 + 语义合规校验",
         {"kind": STR, "content": STR, "order_id": ORDER, "geo": {"type": "boolean"}},
         ["kind", "content"], "guard"),
    tool("director.emit", "把学员动作作为事件送入导演总线，可能注入突发事件",
         {"order_id": ORDER, "type": STR}, ["order_id", "type"], "director"),
    tool("order.status", "查询订单详情（平台阶段 / 客源地 / 完成条件）",
         {"order_id": ORDER}, ["order_id"], "order"),
    tool("practice.coverage", "查询某订单的覆盖校验结果",
         {"order_id": ORDER}, ["order_id"], "coverage"),
    tool("knowledge.lookup", "按技能点取教学知识点基座（讲解 / 资源 / 题目）",
         {"skill_point_id": STR}, ["skill_point_id"], "knowledge"),
)

TOOL_NAMES = tuple(t["name"] for t in TOOLS)


class MCPServer:
    """极简 MCP 服务端：只依赖传入的 service 门面。"""

    def __init__(self, services: dict[str, Callable[[dict], Any]]) -> None:
        self._handlers = services

    # ---------- JSON-RPC ----------

    def handle(self, request: dict) -> dict | None:
        method = request.get("method", "")
        rid = request.get("id")
        params = request.get("params") or {}
        try:
            if method == "initialize":
                return self._ok(rid, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                })
            if method in ("notifications/initialized", "notifications/cancelled"):
                return None                      # 通知不应答
            if method == "ping":
                return self._ok(rid, {})
            if method == "tools/list":
                return self._ok(rid, {"tools": [self._public(t) for t in TOOLS]})
            if method == "tools/call":
                return self._call(rid, params)
            return self._err(rid, -32601, f"未实现的方法: {method}")
        except Exception as exc:
            return self._err(rid, -32603, f"{type(exc).__name__}: {exc}")

    def _call(self, rid, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        spec = next((t for t in TOOLS if t["name"] == name), None)
        if spec is None:
            return self._err(rid, -32602, f"未知工具: {name}")
        missing = [k for k in spec["inputSchema"]["required"] if k not in args or args[k] in ("", None)]
        if missing:
            return self._err(rid, -32602, f"缺少必填参数: {', '.join(missing)}")
        handler = self._handlers.get(spec["_handler"])
        if handler is None:
            return self._err(rid, -32603, f"工具 {name} 未绑定实现")
        result = handler(args)
        return self._ok(rid, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": False,
        })

    @staticmethod
    def _public(spec: dict) -> dict:
        return {k: v for k, v in spec.items() if not k.startswith("_")}

    @staticmethod
    def _ok(rid, result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def _err(rid, code, message):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    # ---------- 给前端看的清单 ----------

    @staticmethod
    def catalog() -> dict:
        return {"protocolVersion": PROTOCOL_VERSION, "serverInfo": SERVER_INFO,
                "transport": "http-jsonrpc（POST /mcp）",
                "tools": [{"name": t["name"], "description": t["description"],
                           "required": t["inputSchema"]["required"]} for t in TOOLS]}
