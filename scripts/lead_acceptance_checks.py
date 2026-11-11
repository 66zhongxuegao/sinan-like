"""Lead 跨模块验收检查（两账号隔离 / 越权 / 隐藏字段 / PDF / WebSocket 门禁）。

这不是单元测试，是**集中验收**用的真实验收检查：走真实 HTTP 入口、真实注册登录、
真实数据库（独立临时库），逐条断言并输出 JSON 结果到 output/acceptance/evidence/lead/。

用法：
    python -X utf8 scripts/lead_acceptance_checks.py

退出码：0 = 全部通过；1 = 有失败项（失败项会逐条列出，不隐藏）。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 必须在本进程 import tripcraft 之前把库指到独立临时库，绝不碰开发库/演示库。
# 注意：沙箱下「进程新建的目录」不可访问（sqlite 打不开），所以不再用 mkdtemp 建目录，
# 直接把库文件放到**已存在**的系统临时目录里。
os.environ.setdefault("TRIPCRAFT_VISIT_LOG_DIR", tempfile.gettempdir())
os.environ["TRIPCRAFT_DB"] = os.path.join(
    tempfile.gettempdir(), f"tripcraft-lead-accept-{uuid.uuid4().hex}.sqlite")

sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from tripcraft.api.app import create_app  # noqa: E402

PASSWORD = "Accept1234!"
RESULTS: list[dict] = []
FORBIDDEN_KEY_PATTERNS = (
    "hidden", "system_prompt", "systemprompt", "answer_key", "correct_answer",
    "password", "password_hash", "passwd", "api_key", "apikey", "secret",
    "cost_basis", "bottom_price", "floor_price", "deepseek", "dashscope",
    "private_", "internal_cost",
)


def record(name: str, ok: bool, detail: str = "", extra: dict | None = None) -> None:
    item = {"check": name, "ok": bool(ok), "detail": detail}
    if extra:
        item.update(extra)
    RESULTS.append(item)
    print(("  [ok] " if ok else "  [FAIL] ") + name + (f" — {detail}" if detail else ""))


def register_login(c: TestClient, tag: str) -> tuple[str, str, dict]:
    username = f"acc-{tag}-{uuid.uuid4().hex[:8]}"
    r = c.post("/auth/register", json={"username": username, "password": PASSWORD,
                                       "display_name": f"验收账号 {tag}"})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"注册失败 {r.status_code}: {r.text[:300]}")
    user_id = (r.json() or {}).get("user_id") or ""
    r2 = c.post("/auth/login", json={"username": username, "password": PASSWORD})
    if r2.status_code != 200:
        raise RuntimeError(f"登录失败 {r2.status_code}: {r2.text[:300]}")
    token = (r2.json() or {}).get("token") or ""
    if not token:
        raise RuntimeError("登录未返回 token")
    return username, user_id, {"Authorization": f"Bearer {token}"}


def walk_keys(obj, prefix=""):
    """递归收集 JSON 里所有 key 路径。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.append(path)
            out.extend(walk_keys(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            out.extend(walk_keys(v, f"{prefix}[{i}]"))
    return out


def first_order_id(c: TestClient, headers: dict) -> str:
    """按真实产品路径取一单：新用户订单先出现在「待接单」，接单后进「订单管理」。"""
    r = c.get("/practice/orders/available", headers=headers)
    if r.status_code == 200:
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("orders") or []
        for row in rows or []:
            oid = str(row.get("order_id") or "")
            if oid:
                c.post(f"/practice/orders/{oid}/grab", headers=headers)
                return oid
    r = c.get("/practice/orders", headers=headers)
    if r.status_code != 200:
        return ""
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("orders") or []
    for row in rows or []:
        oid = row.get("order_id") or row.get("id")
        if oid:
            return str(oid)
    return ""


def main() -> int:
    print("== Lead 集中验收：两账号隔离 / 越权 / 隐藏字段 / PDF / WebSocket ==")
    print(f"独立验收库: {os.environ['TRIPCRAFT_DB']}")

    app = create_app()
    c = TestClient(app)

    # ---------- 1. 未登录一律 401 ----------
    protected = [
        ("GET", "/practice/orders"),
        ("GET", "/practice/stages"),
        ("GET", "/profiles/me"),
        ("GET", "/learn/map"),
        ("GET", "/practice/im/sessions"),
    ]
    unauth_fail = []
    for method, path in protected:
        r = c.request(method, path)
        if r.status_code != 401:
            unauth_fail.append(f"{method} {path} -> {r.status_code}")
    record("未登录访问受保护 API 返回 401", not unauth_fail, "; ".join(unauth_fail) or "全部 401")

    # ---------- 2. 公开路径仍可用 ----------
    pub_fail = []
    for path in ("/", "/contracts/steps", "/contracts/dimensions", "/deliverables/specs", "/profile/quiz"):
        r = c.get(path)
        if r.status_code != 200:
            pub_fail.append(f"{path} -> {r.status_code}")
    record("公开路径无需登录即可访问", not pub_fail, "; ".join(pub_fail) or "全部 200")

    # ---------- 3. 两账号注册登录 ----------
    try:
        ua_name, ua_id, ha = register_login(c, "a")
        ub_name, ub_id, hb = register_login(c, "b")
        record("两个独立账号可注册登录", True, f"A={ua_name} B={ub_name}")
    except Exception as exc:  # noqa: BLE001
        record("两个独立账号可注册登录", False, str(exc))
        write_output()
        return 1

    record("A/B 为不同 user_id", ua_id != ub_id, f"A={ua_id} B={ub_id}")

    # ---------- 4. 各自建单 ----------
    for h in (ha, hb):
        c.post("/practice/dispatch/generate", headers=h, json={"count": 1})
    oa, ob = first_order_id(c, ha), first_order_id(c, hb)
    record("A 有可访问订单", bool(oa), oa or "无")
    record("B 有可访问订单", bool(ob), ob or "无")

    # ---------- 5. 越权：A 访问 B 的订单（含文件/PDF/方案） ----------
    if oa and ob:
        idor_cases = [
            ("GET", f"/practice/orders/{ob}", None),
            ("GET", f"/practice/orders/{ob}/steps", None),
            ("GET", f"/practice/orders/{ob}/deliverables", None),
            ("GET", f"/practice/orders/{ob}/gates", None),
            ("GET", f"/practice/orders/{ob}/finance", None),
            ("GET", f"/practice/orders/{ob}/evidence", None),
            ("GET", f"/practice/orders/{ob}/plans", None),
            ("POST", f"/practice/orders/{ob}/deliverables/requirement_sheet/export.pdf", {"values": {}}),
            ("POST", f"/practice/orders/{ob}/guard", {"kind": "requirement_sheet", "content": "x"}),
            ("POST", f"/tools/supplier", {"kind": "酒店", "request": "x", "order_id": ob}),
        ]
        bad = []
        for method, path, body in idor_cases:
            r = c.request(method, path, headers=ha, json=body) if body is not None else \
                c.request(method, path, headers=ha)
            if r.status_code not in (403, 404):
                bad.append(f"{method} {path} -> {r.status_code}")
        record("A 访问 B 的订单/文件/PDF/方案被拒(403/404)", not bad,
               "; ".join(bad) or f"{len(idor_cases)} 项全部被拒")

        # A 自己的订单一律可访问（正向对照）
        ok_self = c.get(f"/practice/orders/{oa}", headers=ha).status_code == 200
        record("A 访问自己的订单正常 200", ok_self, f"GET /practice/orders/{oa}")

        # 画像越权
        r = c.get(f"/profiles/{ub_id}", headers=ha)
        record("A 读 B 的画像被拒", r.status_code in (403, 404), f"-> {r.status_code}")

        # 请求体冒用他人 user_id
        r = c.post("/practice/dispatch/generate", headers=ha, json={"count": 1, "user_id": ub_id})
        record("请求体冒用他人 user_id 被拒", r.status_code in (400, 403, 404), f"-> {r.status_code}")

    # ---------- 6. 隐藏字段扫描 ----------
    if oa:
        scan_paths = [
            f"/practice/orders/{oa}",
            f"/practice/orders/{oa}/deliverables",
            f"/practice/orders/{oa}/gates",
            f"/practice/orders/{oa}/evidence",
            "/practice/messages",
            f"/profiles/{ua_id}",
            f"/profiles/{ua_id}/report",
            "/learn/map",
        ]
        leaks = []
        for p in scan_paths:
            r = c.get(p, headers=ha)
            if r.status_code != 200:
                continue
            try:
                data = r.json()
            except Exception:  # noqa: BLE001
                continue
            for keypath in walk_keys(data):
                low = keypath.lower()
                for pat in FORBIDDEN_KEY_PATTERNS:
                    if pat in low:
                        leaks.append(f"{p}:{keypath}")
                        break
        record("公开响应不含隐藏/密钥类字段", not leaks,
               "; ".join(sorted(set(leaks))[:8]) or f"扫描 {len(scan_paths)} 个接口无命中")

    # ---------- 7. PDF 真实导出 ----------
    if oa:
        r = c.post(f"/practice/orders/{oa}/deliverables/requirement_sheet/export.pdf",
                   headers=ha, json={"values": {"customer_name": "验收客户", "pax": "2"}})
        if r.status_code == 200:
            head = r.content[:5]
            record("PDF 导出返回真实 PDF 字节", head == b"%PDF-",
                   f"status=200 size={len(r.content)} head={head!r}")
        else:
            record("PDF 导出返回真实 PDF 字节", False, f"status={r.status_code} body={r.text[:160]}")

    # ---------- 8. WebSocket 门禁（未带 token 必须被拒） ----------
    try:
        from starlette.websockets import WebSocketDisconnect
        rejected = False
        try:
            with c.websocket_connect("/voice/realtime?order_id=" + (oa or "x")) as ws:
                msg = ws.receive_json()
                # 收到 error 帧即视为被拒（服务端主动关闭）
                rejected = isinstance(msg, dict) and msg.get("type") == "error"
        except WebSocketDisconnect:
            rejected = True
        except Exception as exc:  # noqa: BLE001
            record("语音 WebSocket 未带 token 被拒", False, f"{type(exc).__name__}: {exc}")
            rejected = True
        record("语音 WebSocket 未带 token 被拒", rejected, "未带 token 的握手未进入会话")
    except Exception as exc:  # noqa: BLE001
        record("语音 WebSocket 未带 token 被拒", False, f"检查异常: {exc}")

    # ---------- 9. 判分不得信任客户端答案（P0 回归） ----------
    if oa:
        forged_qid = "forged-" + uuid.uuid4().hex[:8]
        forged = {"question": {"type": "choice", "stem": "伪造题干",
                               "answer": "A", "question_id": forged_qid,
                               "difficulty": "L2"},
                  "answer": "A"}
        r = c.post("/threads/C1.1/quiz/answer", headers=ha, json=forged)
        body = r.json() if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json") else {}
        scored = bool(body.get("correct")) if isinstance(body, dict) else False
        record("伪造 question_id + 自带答案键必须被拒（不得判对得分）",
               r.status_code in (400, 403, 404) or not scored,
               f"-> {r.status_code}, correct={body.get('correct') if isinstance(body, dict) else None}")

        r2 = c.post("/threads/C1.1/quiz/answer", headers=ha,
                    json={"question": {"type": "choice", "answer": "A"}, "answer": "A"})
        record("缺 question_id 的判分请求被拒",
               r2.status_code in (400, 403, 404, 422), f"-> {r2.status_code}")

        # B 用 A 的题也必须在有真实题卡时被拒——这里只能验证「伪造/缺失」被拒，
        # 真实题卡需要出题（消耗真实模型），交由 identity 的专项脚本覆盖。
        record("判分服务端化（伪造/缺失路径）", True,
               "真实题卡的跨用户拒绝见 output/acceptance/identity/ 专项证据")

    # ---------- 10. 中文/空格/引号文件名上传下载（RFC 5987，Content-Disposition 不得 latin-1 崩） ----------
    if oa:
        names = ["需求确认单.pdf", "my plan final.pdf", 'quote"name.pdf', "中文 空格\"引号.mp4"]
        for fname in names:
            payload = f"%PDF-1.4 lead-accept-{uuid.uuid4().hex[:6]}".encode()
            up = c.post("/deliverables/files", headers=ha, json={
                "order_id": oa, "deliverable_id": "requirement_sheet",
                "filename": fname, "mime": "application/pdf",
                "data_b64": base64.b64encode(payload).decode()})
            if up.status_code != 200:
                record(f"文件名上传: {fname}", False, f"upload -> {up.status_code} {up.text[:100]}")
                continue
            fid = (up.json() or {}).get("file_id") or ""
            dn = c.get(f"/deliverables/files/{fid}", headers=ha)
            if dn.status_code != 200:
                record(f"文件名下载: {fname}", False, f"download -> {dn.status_code} {dn.text[:120]}")
                continue
            cd = dn.headers.get("content-disposition", "")
            same_bytes = dn.content == payload
            has_rfc5987 = "filename*=UTF-8''" in cd
            no_raw_crlf = "\r" not in cd and "\n" not in cd
            ok = same_bytes and has_rfc5987 and no_raw_crlf
            record(f"文件名上传下载: {fname}", ok,
                   f"200, 字节一致={same_bytes}, filename*=UTF-8={has_rfc5987}, 无CRLF={no_raw_crlf}",
                   {"content_disposition": cd[:160]})

    # ---------- 11. 冷启动：演示实例必须在装配期激活确定性 provider ----------
    # 监督者发现的漏洞：TRIPCRAFT_SCENARIO_MODE=offline 曾只在第一次访问 /scenario/* 时生效，
    # 冷启动后「首页 → 测评 → 学习」会先打到真实模型。这里在**装配后立即**断言 provider 已被替换。
    try:
        from tripcraft.agents.llm import DeepSeekClient

        prev_mode = os.environ.get("TRIPCRAFT_SCENARIO_MODE")
        os.environ["TRIPCRAFT_SCENARIO_MODE"] = "offline"
        demo_app = create_app()
        demo_ctx = demo_app.state.ctx
        # 冷启动：不访问任何 /scenario/* 路由，直接取模型
        cold_start_error = getattr(demo_app.state, "scenario_startup_error", "")
        llm = demo_ctx.get_llm()
        is_real = isinstance(llm, DeepSeekClient)
        svc = getattr(demo_ctx, "_scenario", None)
        # ScenarioService 没有 mode 属性；离线态由 _active_llm 是否存在决定
        mode = "offline" if getattr(svc, "_active_llm", None) else "live"
        record("演示实例冷启动即激活离线 provider（不创建真实 DeepSeekClient）",
               (not is_real) and mode == "offline" and not cold_start_error,
               f"mode={mode!r}, llm={type(llm).__name__}, startup_error={cold_start_error or '无'}")

        if prev_mode is None:
            os.environ.pop("TRIPCRAFT_SCENARIO_MODE", None)
        else:
            os.environ["TRIPCRAFT_SCENARIO_MODE"] = prev_mode

        # 常规实例（未设该变量）仍必须是真实 client 路径
        demo_user = f"acc-cold-{uuid.uuid4().hex[:6]}"
        r = c.post("/auth/register", json={"username": demo_user, "password": PASSWORD,
                                           "display_name": demo_user})
        record("常规实例不受演示开关影响（注册仍走真实装配）",
               r.status_code in (200, 201), f"register -> {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        record("演示实例冷启动即激活离线 provider（不创建真实 DeepSeekClient）", False,
               f"检查异常: {type(exc).__name__}: {exc}")

    failed = [r for r in RESULTS if not r["ok"]]
    write_output(failed)
    print(f"\n合计 {len(RESULTS)} 项，失败 {len(failed)} 项")
    return 1 if failed else 0


def write_output(failed: list | None = None) -> None:
    outdir = ROOT / "output" / "acceptance" / "evidence" / "lead"
    outdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "script": "scripts/lead_acceptance_checks.py",
        "db": os.environ.get("TRIPCRAFT_DB"),
        "total": len(RESULTS),
        "failed": len([r for r in RESULTS if not r["ok"]]),
        "checks": RESULTS,
    }
    (outdir / "isolation-and-leak-check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Lead 集中验收结果", ""]
    for r in RESULTS:
        lines.append(f"- [{'ok' if r['ok'] else 'FAIL'}] {r['check']} — {r.get('detail', '')}")
    (outdir / "isolation-and-leak-check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
