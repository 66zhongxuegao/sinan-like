"""conversation 域自检：/voice/realtime 令牌鉴权与订单归属（R08）+ 公开 DTO 边界。

用法（在仓库根目录）：
    python scripts/verify_public_dto.py

在线测试面（不联网、不调用真实模型）：
1. WebSocket 四种情形：无 token / 伪 token / 他人订单 / 本人订单（未配置实时依赖）；
2. HTTP 越权：他人订单发起通话、他人会话读写、IM 会话与联系人越权，打印真实状态码；
3. 响应字段级扫描：对订单详情、通话快照、IM 会话列表递归查找隐藏/答案/系统提示/密钥字段。

退出码 0 = 全部通过，1 = 有失败项。
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 独立临时库（工作区内，见 verify_conversation_facts.py 的说明）
_DB_DIR = ROOT / ".dsh-run" / "conv-verify"
_DB_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TRIPCRAFT_DB"] = str(_DB_DIR / f"dto-{uuid.uuid4().hex[:8]}.sqlite")
os.environ.pop("DASHSCOPE_API_KEY", None)   # 明确：本机无实时语音依赖

from fastapi.testclient import TestClient  # noqa: E402

from tripcraft.api.app import create_app  # noqa: E402
from tripcraft.api.public_dto import FORBIDDEN_KEYS, scan_forbidden_keys  # noqa: E402

PASSWORD = "Test1234!"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def banner(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def register(client: TestClient, prefix: str) -> tuple[str, str, str]:
    """注册 + 登录，返回 (user_id, token, username)。"""
    username = f"{prefix}{uuid.uuid4().hex[:8]}"
    r = client.post("/auth/register", json={"username": username, "password": PASSWORD})
    assert r.status_code in (200, 201), f"注册失败 {r.status_code} {r.text}"
    uid = r.json()["user_id"]
    r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, f"登录失败 {r.status_code} {r.text}"
    return uid, r.json()["token"], username


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_order(ctx, user_id: str, order_id: str, customer: str, destination: str,
                source_market: str, language: str) -> str:
    """在自检库里显式建一条只属于该用户的订单（不依赖 practice.seed）。"""
    ctx.store.upsert_order(order_id, user_id, customer, destination, "正常", 1, payload={
        "source_market": source_market, "language": language,
        "documents": "自检用证件口径", "created_at": "2026-10-16 10:00:00",
    })
    row = ctx.store.order(order_id) or {}
    assert row.get("user_id") == user_id, f"建单归属失败: {row}"
    return order_id


def main() -> int:
    app = create_app()
    client = TestClient(app)
    ctx = app.state.ctx

    uid_a, token_a, _ = register(client, "conv-a")
    uid_b, token_b, _ = register(client, "conv-b")

    # 自检库明确各建一单，**不调 practice.seed**：
    # seed 用固定 order_id + INSERT OR REPLACE，会给后一个用户把前一个用户的单抢走
    # （这正是 lead 全队规则里的已知污染），自检不能依赖它。
    order_a = _make_order(ctx, uid_a, "9000000000000101", "验证客户甲", "江苏", "香港", "中文")
    order_b = _make_order(ctx, uid_b, "9000000000000102", "验证客户乙", "云南", "美国", "English")
    print(f"用户 A={uid_a} 订单 {order_a} / 用户 B={uid_b} 订单 {order_b}")

    # ---------------------------------------------------------------- ① WebSocket

    banner("① /voice/realtime 鉴权（无 token / 伪 token / 他人订单 / 本人订单）")

    # 干净客户端：不继承已登录用户的 cookie（login 会种 tc_token，
    # 否则「无 token」用例其实带着有效 cookie，测不出拒绝路径）。
    anon = TestClient(app)

    def ws_probe(name: str, url: str, use_anon: bool = False) -> tuple[str, int | None]:
        """返回 (收到的消息或异常文本, close code)。"""
        browser = anon if use_anon else client
        try:
            with browser.websocket_connect(url) as ws:
                msg = ws.receive_json()
                code = None
                try:
                    ws.receive_json()      # 期待服务端关闭
                except Exception as exc:   # noqa: BLE001
                    code = getattr(exc, "code", None)
                return msg.get("message", ""), code
        except Exception as exc:           # noqa: BLE001
            return f"{type(exc).__name__}: {exc}", getattr(exc, "code", None)

    msg, code = ws_probe("无 token", f"/voice/realtime?order_id={order_a}", use_anon=True)
    check("无 token（无 cookie 的干净连接）：收到 error 帧",
          "未登录" in msg, f"msg={msg!r}")
    check("无 token：拒绝进入（close code 4401 或无 ready）", code == 4401 or code is None,
          f"code={code}")

    sessions_before = len(ctx.store.call_sessions_for_order(order_a))
    msg, code = ws_probe("伪 token", f"/voice/realtime?order_id={order_a}&token=not-a-real-token")
    check("伪 token：收到 error 帧", "未登录" in msg, f"msg={msg!r}")

    msg, code = ws_probe("他人订单", f"/voice/realtime?order_id={order_b}&token={token_a}")
    check("他人订单：收到 error 帧", "无权" in msg, f"msg={msg!r}")
    check("他人订单：close code 4403", code == 4403, f"code={code}")

    msg, code = ws_probe("本人订单", f"/voice/realtime?order_id={order_a}&token={token_a}")
    check("本人订单（无实时依赖）：明确报实时依赖缺失而不是匿名放行",
          ("DASHSCOPE" in msg or "未配置" in msg or "QWEN" in msg), f"msg={msg!r}")

    sessions_after = len(ctx.store.call_sessions_for_order(order_a))
    check("被拒的握手没有落任何 call_session",
          sessions_after == sessions_before,
          f"before={sessions_before} after={sessions_after}")

    # ---------------------------------------------------------------- ② HTTP 越权

    banner("② HTTP 对象归属（打印真实状态码）")

    r = client.post(f"/practice/orders/{order_a}/call", headers=headers(token_b))
    check("B 对 A 的订单发起通话 → 403", r.status_code == 403, f"HTTP {r.status_code}")

    r = client.get(f"/practice/orders/{order_a}", headers=headers(token_b))
    print(f"    （参考）B 读 A 的订单详情 → HTTP {r.status_code}（journey 域，归属由其 owner 收口）")

    r = client.post(f"/practice/orders/{order_a}/call", headers=headers(token_a))
    call_status = r.status_code
    print(f"    （参考）A 对自己的订单发起文本通话 → HTTP {call_status}")
    if call_status == 200:
        sid = r.json()["session_id"]
    elif call_status == 503:
        sid = None
        print("    （本机无 DEEPSEEK_API_KEY：文本通话走 503，改用会话归属直测）")
    else:
        sid = None

    if sid is None:
        from tripcraft.services.call_service import CallService

        class StubLLM:
            def chat(self, messages, **kwargs):
                return "喂，你好。"

        svc = ctx.get_call()
        svc._llm = StubLLM()
        s = svc.start_for_order(ctx.store, order_a, uid_a)
        sid = s.session_id
        print(f"    （用 StubLLM 建会话 {sid} 直测归属）")

    r = client.get(f"/practice/call/{sid}", headers=headers(token_b))
    check("B 读 A 的通话会话 → 404（不暴露他人会话存在）", r.status_code == 404,
          f"HTTP {r.status_code}")
    r = client.post(f"/practice/call/{sid}/messages", headers=headers(token_b),
                    json={"text": "你好"})
    check("B 向 A 的会话发言 → 404", r.status_code == 404, f"HTTP {r.status_code}")
    r = client.post(f"/practice/call/{sid}/end", headers=headers(token_b))
    check("B 结束 A 的会话 → 404", r.status_code == 404, f"HTTP {r.status_code}")
    r = client.get(f"/practice/call/{sid}", headers=headers(token_a))
    check("A 读自己的会话 → 200", r.status_code == 200, f"HTTP {r.status_code}")

    r = client.get(f"/practice/im/contacts?order_id={order_a}", headers=headers(token_b))
    check("B 查 A 订单的联系人 → 403", r.status_code == 403, f"HTTP {r.status_code}")
    r = client.post("/practice/im/contacts", headers=headers(token_b),
                    json={"order_id": order_a, "kind": "客户"})
    check("B 往 A 的订单加联系人 → 403", r.status_code == 403, f"HTTP {r.status_code}")

    r = client.get("/practice/im/sessions", headers=headers(token_b))
    check("未带 token 访问 IM 会话列表 → 401（认证中间件）",
          anon.get("/practice/im/sessions").status_code == 401,
          f"HTTP {anon.get('/practice/im/sessions').status_code}")
    check("B 的 IM 会话列表可读", r.status_code == 200, f"HTTP {r.status_code}")
    b_sessions = {s["session_id"] for s in (r.json() or [])}
    r2 = client.get("/practice/im/sessions", headers=headers(token_a))
    a_sessions = {s["session_id"] for s in (r2.json() or [])}
    check("A/B 的 IM 会话列表不重叠（按登录用户隔离）",
          not (a_sessions & b_sessions), f"交集={a_sessions & b_sessions}")

    # 他人会话改名 / 拉人
    other_sid = next(iter(b_sessions), "")
    if other_sid:
        r = client.post(f"/practice/im/sessions/{other_sid}/rename", headers=headers(token_a),
                        json={"name": "越权改名"})
        check("A 改 B 的会话名 → 403", r.status_code == 403, f"HTTP {r.status_code}")
        r = client.post(f"/practice/im/sessions/{other_sid}/members", headers=headers(token_a),
                        json={"names": ["某人"]})
        check("A 往 B 的会话拉人 → 403", r.status_code == 403, f"HTTP {r.status_code}")
        r = client.post(f"/practice/im/sessions/{other_sid}/messages", headers=headers(token_a),
                        json={"sender": "我", "role": "me", "content": "越权发言"})
        check("A 往 B 的会话发言 → 403", r.status_code == 403, f"HTTP {r.status_code}")

    # ---------------------------------------------------------------- ③ 字段级边界

    banner("③ 响应字段级扫描（隐藏人设 / 答案 / 系统提示 / 密钥）")
    print(f"    禁止 key 清单（{len(FORBIDDEN_KEYS)} 个）: {sorted(FORBIDDEN_KEYS)}")

    r = client.get(f"/practice/orders/{order_a}", headers=headers(token_a))
    found = scan_forbidden_keys(r.json() if r.status_code == 200 else {})
    check("订单详情无禁止字段", not found, f"命中: {found}")

    r = client.get(f"/practice/call/{sid}", headers=headers(token_a))
    body = r.json() if r.status_code == 200 else {}
    found = scan_forbidden_keys(body)
    check("通话快照无禁止字段", not found, f"命中: {found}")
    check("通话快照含公开客户字段", "customer" in body and "language" in body,
          f"keys={sorted(body)}")

    r = client.get("/practice/im/sessions", headers=headers(token_a))
    found = scan_forbidden_keys(r.json() if r.status_code == 200 else [])
    check("IM 会话列表无禁止字段", not found, f"命中: {found}")

    r = client.get("/threads/C2.2", headers=headers(token_a))
    if r.status_code == 200:
        found = scan_forbidden_keys(r.json())
        print(f"    （参考）技能点线程响应禁止字段命中: {found or '无'}"
              f"（thread 归属 identity 域，答案剥离由该 owner 收口）")

    banner("结果")
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} 项未通过 → {FAILURES}")
        return 1
    print("PASS: 全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
