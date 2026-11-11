"""DemoCaseView ↔ /scenario/* 真实接口契约核对（证据脚本）。

做法：在**同一个进程**里用 uvicorn 起真实 app（随机端口，真实 HTTP/真实 store/真实 services），
再用 httpx 按 DemoCaseView.vue 里实际发出的请求逐条核对：
  - 请求路径/查询串/方法（与 frontend/src/demo/scenarioApi.ts 一一对应）
  - 响应字段是否真的存在（组件渲染依赖的字段缺失就是渲染缺陷）
  - 未登录 401、导入回执、订单状态、重置回执、重置后计数归零
  - 演示账号的导入/重置只影响本账号

为什么在进程内起服务：本沙箱禁止子进程用管道 stdio（esbuild/vite 起不来），
但同一进程内起 uvicorn + httpx 出网是可行的；这样仍然是真实 HTTP 往返。

用法：python -X utf8 scripts/acceptance_demo_case_ui.py
产物：output/acceptance/evidence/scenario-demo-ui/api-contract.json
      output/acceptance/logs/scenario-demo-ui-api.log
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_ID = "hk-huang-yunnan-5d"
USERNAME = "demo-lvyuan"
PASSWORD = "LvyuanDemo#2026"
EVID = ROOT / "output" / "acceptance" / "evidence" / "scenario-demo-ui"
LOGS = ROOT / "output" / "acceptance" / "logs"

checks: list[dict] = []
log_lines: list[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    log_lines.append(line)


def check(name: str, ok: bool, detail: object = "") -> bool:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    log(("OK   " if ok else "FAIL ") + name + (f" :: {detail}" if detail != "" else ""))
    return bool(ok)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # noqa: D102 - 线程内不能装信号处理
        return


def boot() -> tuple[str, Server]:
    from tripcraft.api.app import create_app

    port = free_port()
    app = create_app()
    server = Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            r = httpx.get(base + "/", timeout=1.0)
            if r.status_code == 200:
                log(f"app ready at {base}（进程内真实 uvicorn）")
                return base, server
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("app 未起来")


def login_or_register(c: httpx.Client, base: str) -> str:
    r = c.post(base + "/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if r.status_code == 401 or r.status_code == 400:
        log("演示账号不存在 → 按 demo- 前缀真实注册")
        r = c.post(
            base + "/auth/register",
            json={"username": USERNAME, "password": PASSWORD, "display_name": "标准案例演示账号"},
        )
        check("auth/register 200 且返回 token", r.status_code == 200 and bool(r.json().get("token")), r.status_code)
    else:
        check("auth/login 200 且返回 token", r.status_code == 200 and bool(r.json().get("token")), r.status_code)
    token = str(r.json().get("token") or "")
    user = r.json().get("user") or {}
    check("演示账号 kind=demo", user.get("kind") == "demo", user.get("kind"))
    return token


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    base, server = boot()
    c = httpx.Client(timeout=120.0)

    # 未登录必须 401（页面据此显示「未登录」并停住，不做兜底）
    anon = httpx.get(base + "/scenario/cases", timeout=30)
    check("未登录 GET /scenario/cases → 401", anon.status_code == 401, anon.status_code)
    anon2 = httpx.get(base + "/scenario/status", timeout=30)
    check("未登录 GET /scenario/status → 401", anon2.status_code == 401, anon2.status_code)

    token = login_or_register(c, base)
    h = {"Authorization": f"Bearer {token}"}
    check("带 Bearer 的 /auth/session 200", c.get(base + "/auth/session", headers=h).status_code == 200)

    # ① GET /scenario/cases —— 组件读 catalog.cases / digest / stage_plan / status
    r = c.get(base + "/scenario/cases", headers=h)
    check("GET /scenario/cases 200", r.status_code == 200, r.status_code)
    cat = r.json()
    for key in ("cases", "digest", "stage_plan", "demo_label", "status"):
        check(f"catalog.{key} 存在", key in cat, type(cat.get(key)).__name__)
    case0 = (cat.get("cases") or [{}])[0]
    for key in ("case_id", "title", "demo_label", "demo_data", "customer", "dates", "days",
                "party", "budget", "hotel", "transport", "resource_constraints", "demo_account",
                "stage_ids", "realtime_dependencies"):
        check(f"catalog.cases[0].{key} 存在", key in case0)
    check("catalog.cases[0].case_id == 期望案例", case0.get("case_id") == CASE_ID, case0.get("case_id"))
    check("catalog.demo_label == 标准案例/演示数据", cat.get("demo_label") == "标准案例/演示数据", cat.get("demo_label"))
    check("catalog.cases[0].demo_data is True", case0.get("demo_data") is True)
    plan = cat.get("stage_plan") or []
    check("stage_plan 有 6 个阶段", len(plan) == 6, len(plan))
    sub = (plan[0] if plan else {}).get("substeps") or []
    check("stage_plan[0].substeps 非空", bool(sub), len(sub))
    for key in ("id", "name", "hint", "step", "deliverable"):
        check(f"substeps[0].{key} 存在", key in (sub[0] if sub else {}))
    st = cat.get("status") or {}
    check("catalog.status.mode 是 offline/live", st.get("mode") in ("offline", "live"), st.get("mode"))
    deps = st.get("deps") or {}
    for key in ("llm_key_present", "llm_key_source", "llm_connectivity_verified",
                "llm_not_verified_reason", "voice_key_present", "voice_key_source",
                "voice_connectivity_verified", "voice_not_verified_reason",
                "db_path", "auth_mode", "scenario_mode_env"):
        check(f"status.deps.{key} 存在", key in deps)
    check("status.honest_notes 非空", bool(st.get("honest_notes")), len(st.get("honest_notes") or []))
    check("status.confidence_cap 存在", "confidence_cap" in st, st.get("confidence_cap"))
    for key in ("scope", "demo_instance", "switch_policy", "instance_note"):
        check(f"status.{key} 存在", key in st)

    # ①b GET /scenario/status?probe=true —— 页面「真实连通核验」按钮走的接口
    r = c.get(base + "/scenario/status", params={"probe": "true"}, headers=h)
    check("GET /scenario/status?probe=true 200", r.status_code == 200, r.status_code)
    pr = r.json()
    check("probe 返回 llm_connectivity_verified", "llm_connectivity_verified" in (pr.get("deps") or {}),
          (pr.get("deps") or {}).get("llm_connectivity_verified"))
    check("probe 未核验时给出原因", bool((pr.get("deps") or {}).get("llm_connectivity_verified"))
          or bool((pr.get("deps") or {}).get("llm_not_verified_reason")),
          (pr.get("deps") or {}).get("llm_not_verified_reason"))

    # ①c 运行期 provider 开关：非演示实例必须 409（页面据此显示真实错误，不做本地切换假象）
    r = c.post(base + "/scenario/provider/offline", headers=h)
    check("非演示实例 POST provider/offline → 409", r.status_code == 409, r.status_code)

    # ② GET /scenario/account?case_id=
    r = c.get(base + "/scenario/account", params={"case_id": CASE_ID}, headers=h)
    check("GET /scenario/account 200", r.status_code == 200, r.status_code)
    acc = r.json()
    for key in ("user_id", "orders", "scenario_orders", "scenario_order_ids", "evidence",
                "deliverables", "ability_rows", "quiz_attempts", "threads", "notices"):
        check(f"account.{key} 存在", key in acc)

    # ③ POST /scenario/cases/{id}/import —— 组件读 order_id/demo_label/stage_index/scenario_marker/resources_injected
    r = c.post(base + f"/scenario/cases/{CASE_ID}/import", headers=h)
    check("POST …/import 200", r.status_code == 200, r.status_code)
    imp = r.json()
    for key in ("order_id", "case_id", "demo_label", "demo_data", "user_id", "stage_index",
                "scenario_marker", "resources_injected", "missing_fields", "next_action"):
        check(f"import.{key} 存在", key in imp)
    order_id = str(imp.get("order_id") or "")
    check("import.order_id 非空", bool(order_id), order_id)
    check("import.demo_data is True", imp.get("demo_data") is True)
    check("import.resources_injected 有 4 条", len(imp.get("resources_injected") or []) == 4, len(imp.get("resources_injected") or []))
    marker = imp.get("scenario_marker") or {}
    for key in ("scenario_id", "scenario_label", "demo_data"):
        check(f"import.scenario_marker.{key} 存在", key in marker)

    # ④ GET /scenario/orders/{id}/state —— 每步服务端状态
    r = c.get(base + f"/scenario/orders/{order_id}/state", headers=h)
    check("GET …/state 200", r.status_code == 200, r.status_code)
    stt = r.json()
    for key in ("order_id", "scenario_id", "demo_label", "demo_data", "status", "stage_index",
                "stage_name", "stage_id", "internal_step", "gate", "actions", "evidence_count",
                "deliverables", "incidents", "scores", "ability_written"):
        check(f"state.{key} 存在", key in stt)
    gate = stt.get("gate") or {}
    for key in ("step", "stage_name", "checks", "done", "total", "passed"):
        check(f"state.gate.{key} 存在", key in gate)
    cks = gate.get("checks") or []
    check("state.gate.checks 非空", bool(cks), len(cks))
    for key in ("action", "label", "hint", "where", "ok", "reason"):
        check(f"states.gate.checks[0].{key} 存在", key in (cks[0] if cks else {}))
    scores = stt.get("scores") or {}
    for key in ("evaluated", "pending_review", "average"):
        check(f"state.scores.{key} 存在", key in scores)

    # ⑤ GET /practice/messages（既有业务接口，本页用于指路）
    r = c.get(base + "/practice/messages", headers=h)
    check("GET /practice/messages 200", r.status_code == 200, r.status_code)
    check("practice/messages.groups 存在", "groups" in r.json())

    # ⑥ POST /scenario/cases/{id}/reset —— 组件读 scope/orders_targeted/deleted/before/after/isolation_note
    r = c.post(base + f"/scenario/cases/{CASE_ID}/reset", json=None, headers=h)
    check("POST …/reset 200", r.status_code == 200, r.status_code)
    rst = r.json()
    for key in ("ok", "user_id", "case_id", "scope", "orders_targeted", "deleted", "before", "after", "isolation_note"):
        check(f"reset.{key} 存在", key in rst)
    check("reset 命中刚才导入的订单", order_id in (rst.get("orders_targeted") or []), rst.get("orders_targeted"))
    check("reset.after.scenario_orders == 0", (rst.get("after") or {}).get("scenario_orders") == 0,
          (rst.get("after") or {}).get("scenario_orders"))

    # ⑦ 未知案例 / 不存在的订单：后端显式报错（页面显示真实错误）
    r = c.post(base + "/scenario/cases/no-such-case/import", headers=h)
    check("未知案例 import → 4xx", 400 <= r.status_code < 500, r.status_code)
    r = c.get(base + "/scenario/orders/not-an-order/state", headers=h)
    check("不存在订单 state → 4xx", 400 <= r.status_code < 500, r.status_code)

    server.should_exit = True
    time.sleep(0.6)

    ok_all = all(x["ok"] for x in checks)
    payload = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "base_url": base,
        "case_id": CASE_ID,
        "order_id": order_id,
        "total": len(checks),
        "failed": [x for x in checks if not x["ok"]],
        "checks": checks,
        "mode": st.get("mode"),
        "demo_label": cat.get("demo_label"),
    }
    (EVID / "api-contract.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf8")
    (LOGS / "scenario-demo-ui-api.log").write_text("\n".join(log_lines) + "\n", "utf8")
    log(f"checks={len(checks)} failed={len(payload['failed'])}")
    log("evidence: output/acceptance/evidence/scenario-demo-ui/api-contract.json")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
