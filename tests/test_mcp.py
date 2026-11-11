"""MCP 封装测试（离线）。"""

from tripcraft.mcp.server import PROTOCOL_VERSION, TOOLS, MCPServer

SERVICES = {
    "weather": lambda a: {"city": a["city"], "temp": 21},
    "order": lambda a: {"order_id": a["order_id"], "stage": "客户确认合同"},
}


def server() -> MCPServer:
    return MCPServer(SERVICES)


def test_initialize_returns_protocol_and_capabilities():
    r = server().handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["jsonrpc"] == "2.0" and r["id"] == 1
    res = r["result"]
    assert res["protocolVersion"] == PROTOCOL_VERSION
    assert res["capabilities"]["tools"]["listChanged"] is False
    assert res["serverInfo"]["name"] == "tripcraft"


def test_notifications_get_no_response():
    assert server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_exposes_json_schema():
    r = server().handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = r["result"]["tools"]
    assert len(tools) == len(TOOLS)
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert "_handler" not in t, "内部字段不应暴露给客户端"


def test_tools_call_returns_text_content():
    r = server().handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                         "params": {"name": "weather.get", "arguments": {"city": "杭州"}}})
    assert r["result"]["isError"] is False
    assert '"city": "杭州"' in r["result"]["content"][0]["text"]


def test_unknown_tool_and_missing_args_are_jsonrpc_errors():
    s = server()
    r = s.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                  "params": {"name": "nope", "arguments": {}}})
    assert r["error"]["code"] == -32602
    r = s.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                  "params": {"name": "route.plan", "arguments": {"origin": "杭州"}}})
    assert r["error"]["code"] == -32602 and "destination" in r["error"]["message"]


def test_unknown_method_returns_method_not_found():
    r = server().handle({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    assert r["error"]["code"] == -32601


def test_handler_exception_is_reported_not_raised():
    s = MCPServer({"weather": lambda a: 1 / 0})
    r = s.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                  "params": {"name": "weather.get", "arguments": {"city": "x"}}})
    assert r["error"]["code"] == -32603 and "ZeroDivisionError" in r["error"]["message"]


def test_catalog_lists_every_tool_name():
    cat = MCPServer.catalog()
    assert cat["protocolVersion"] == PROTOCOL_VERSION
    assert {t["name"] for t in cat["tools"]} == {t["name"] for t in TOOLS}