"""标准案例 provider 自检（scenario-core 的交付验收脚本，v2）。

跑法：
    python -X utf8 scripts/acceptance_scenario_provider.py

离线可核对的断言，全部走真实服务与真实存储（独立库）：
  1. 固定资料可复现：两次读取一致 + 内容哈希稳定；
  2. 案例 → 派单规范确定性（两次转换完全一致）；
  3. 离线响应器覆盖声明的调用点，未覆盖的调用点**抛错**（不静默返回空）；
  4. 会话状态隔离：两个通话会话**并发**推进，各自轮次互不消耗（无全局计数）；
  5. 导入走真实 PracticeService.spawn_order，payload 带标准案例标记 + 固定资源约束；
  6. 重置：先子后父 + 单事务 + **残留检查全 0**；另一账号数据完全不变；
  7. 模式作用域：常规实例不允许运行期切到确定性模式（只在演示实例里由启动变量声明）；
  8. status 诚实口径：key 存在 ≠ 连通已核验，认证状态按 security v2 如实报告。

任何断言失败 → 非零退出并打印停在哪一步。
证据落 output/acceptance/evidence/scenario-core/，原始日志落 output/acceptance/logs/。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 独立库：绝不碰根目录 tripcraft.sqlite
_db = Path(tempfile.gettempdir()) / "tripcraft_scenario_selfcheck.sqlite"
if _db.exists():
    _db.unlink()
os.environ["TRIPCRAFT_DB"] = str(_db)
os.environ.pop("TRIPCRAFT_SCENARIO_MODE", None)      # 先按「常规实例」验作用域

from tripcraft.agents.scenario import spec_from_case  # noqa: E402
from tripcraft.api.context import AppContext  # noqa: E402
from tripcraft.services import scenario_service as sc  # noqa: E402

def _out_base() -> Path:
    """--output-dir <dir> 可换输出根目录（默认 output/acceptance，旧证据不被覆盖）。"""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--output-dir" and i + 1 < len(argv):
            return Path(argv[i + 1]).resolve()
        if a.startswith("--output-dir="):
            return Path(a.split("=", 1)[1]).resolve()
    return ROOT / "output" / "acceptance"


_OUT = _out_base()
EVID = _OUT / "evidence" / "scenario-core"
LOGS = _OUT / "logs"
EVID.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

STEPS: list[dict] = []
FAILED = False


def record(name: str, ok: bool, detail: dict | None = None) -> None:
    global FAILED
    STEPS.append({"step": name, "ok": bool(ok), "detail": detail or {}})
    print(f"  [{'OK ' if ok else 'NG '}] {name}"
          + (f" → {json.dumps(detail, ensure_ascii=False)[:220]}" if detail else ""))
    if not ok:
        FAILED = True


def must(name: str, ok: bool, detail: dict | None = None) -> None:
    record(name, ok, detail)
    if not ok:
        raise SystemExit(_finish("断言失败，按纪律停在原地（不跳过）"))


def _finish(reason: str = "") -> int:
    out = {"script": "acceptance_scenario_provider.py", "version": 2,
           "db": os.environ["TRIPCRAFT_DB"], "ok": not FAILED, "reason": reason, "steps": STEPS}
    (EVID / "provider-selfcheck.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (LOGS / "scenario-provider-selfcheck.log").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据：{EVID / 'provider-selfcheck.json'}")
    print(f"日志：{LOGS / 'scenario-provider-selfcheck.log'}")
    return 0 if not FAILED else 1


def main() -> int:
    print("=" * 74)
    print("标准案例 provider 自检 v2（独立库）")
    print("=" * 74)

    print("\n[1] 固定资料可复现")
    d1, d2 = sc.load_case_document(), sc.load_case_document()
    digest1, digest2 = sc.case_digest(), sc.case_digest()
    must("两次读取案例内容完全一致", d1 == d2, {"cases": len(d1["cases"])})
    must("内容哈希稳定", digest1 == digest2, {"sha256": digest1})

    print("\n[2] 案例 → 派单规范确定性")
    case = sc.get_case("hk-huang-yunnan-5d")
    p1, p2 = spec_from_case(case).to_payload(), spec_from_case(case).to_payload()
    must("两次转换得到同一份 payload", p1 == p2, {"keys": len(p1)})
    for key in ("scenario_id", "scenario_label", "demo_data", "source_market", "language",
                "party", "dates", "days", "budget", "transport", "hotel", "special", "decision"):
        must(f"payload 含固定字段 {key}", key in p1, {key: p1.get(key)})
    must("固定日期写死", p1.get("dates") == case["tourist"]["dates"], {"dates": p1.get("dates")})
    must("固定预算写死", p1.get("budget") == case["tourist"]["budget"], {"budget": p1.get("budget")})

    print("\n[3] 离线响应器：覆盖已知调用点、未知调用点必须报错")
    llm = sc.ScenarioLLM(case)
    for label, system, user in (
        ("首呼客户开场", sc._CALL_SIG, "（定制师刚打来电话，你先接起）请给出你的第一句应答。"),
        ("首呼客户应答", sc._CALL_SIG, "您好，我是定制师小李，方便说两句吗？"),
        ("评分", sc._SCORER_SIG + "【C2.2】", '{"transcript":"..."}'),
        ("训练老师", sc._TEACHER_SIG, "讲义"),
        ("学习资料", sc._ASSET_SIG, "生成讲义"),
        ("掌握度判档", sc._JUDGE_SIG, "判档"),
        ("出题", sc._QUESTION_SIG, "出题"),
        ("调度器", sc._ROUTER_SIG, "学员这句话"),
        ("画像顾问", sc._PROFILE_SIG, "建议"),
        ("交付物客户反馈", sc._TOOLS_CUSTOMER_SIG, "定制师发来的「需求确认单」内容：..."),
        ("IM 客户", sc._IM_CUSTOMER_SIG, "在吗"),
        ("IM 供应商", sc._SUPPLIER_IM_SIG, "酒店什么价"),
        ("IM 司导", sc._GUIDE_SIG, "今天几点出发"),
        ("合规语义", sc._GUARD_SIG, "交付物类型：需求确认单"),
        ("画像 Agent", sc._PROFILER_SIG, "请输出画像 JSON"),
        ("六帽审查", sc._HAT_SIG, "待审查材料"),
        ("需求结构化", sc._REQUIREMENTS_SIG, "转写"),
        ("派单生成", sc._DISPATCH_SIG, "生成第 1 条"),
        ("工具询价", sc._TOOLS_SUPPLIER_SIG + "你是目的地酒店的团队销售。", "四星两间什么价"),
    ):
        text = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        record(f"覆盖调用点：{label}", bool(str(text).strip()), {"chars": len(str(text))})
    try:
        llm.chat([{"role": "system", "content": "一个全新的、没有覆盖的系统提示词"},
                  {"role": "user", "content": "hi"}])
        record("未覆盖调用点必须报错", False, {"error": "竟然返回了内容（静默兜底）"})
    except sc.ScenarioUnsupportedError as exc:
        record("未覆盖调用点必须报错", True, {"error": str(exc)[:80]})

    print("\n[4] 会话状态隔离：两个通话会话并发推进，轮次互不消耗")
    lines = list(case["first_call"]["customer_lines"])
    probe = sc.ScenarioLLM(case)

    def drive(tag: str, turns: int, out: dict) -> None:
        msgs = [{"role": "system", "content": sc._CALL_SIG}]
        seq = []
        for _ in range(turns):
            msgs.append({"role": "user", "content": f"[{tag}] 定制师第 N 句"})
            reply = probe.chat(list(msgs))
            msgs.append({"role": "assistant", "content": reply})
            seq.append(reply)
            time.sleep(0.02)          # 制造交错
        out[tag] = seq

    results: dict[str, list] = {}
    threads = [threading.Thread(target=drive, args=("A", 3, results)),
               threading.Thread(target=drive, args=("B", 2, results))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seqA, seqB = results.get("A", []), results.get("B", [])
    must("会话 A 得到自己的轮次序列 0,1,2", seqA == lines[:3], {"A": seqA})
    must("会话 B 得到自己的轮次序列 0,1（不被 A 消耗）", seqB == lines[:2], {"B": seqB})
    must("两个会话互不串词（A 第 3 轮 ≠ B 最后一轮）",
         bool(seqA) and bool(seqB) and seqA[-1] != seqB[-1], {"A_last": seqA[-1:], "B_last": seqB[-1:]})
    record("会话轮次来自消息历史（无全局计数）", not hasattr(probe, "_call_round"), {})

    print("\n[5] 导入走真实服务（独立库）")
    ctx = AppContext()
    svc = sc.ScenarioService(ctx)
    demo = svc.import_case("demo-lvyuan", "hk-huang-yunnan-5d")
    must("拿到订单号", bool(demo["order_id"]), {"order_id": demo["order_id"]})
    must("带标准案例标记", demo["scenario_marker"]["scenario_id"] == "hk-huang-yunnan-5d",
         demo["scenario_marker"])
    must("带演示数据标记", demo["scenario_marker"]["demo_data"] is True, {})
    row = ctx.store.order(demo["order_id"])
    must("订单已真实落库", bool(row), {"order_id": demo["order_id"], "stage": row["stage_index"]})
    must("资源约束已注入", len(demo["resources_injected"]) == 4,
         {"kinds": [r["kind"] for r in demo["resources_injected"]]})
    must("订单初始为阶段 0（未抢单）", int(row["stage_index"]) == 0, {"stage_index": row["stage_index"]})

    print("\n[6] 模式作用域：常规实例不允许运行期切到确定性模式")
    try:
        svc.activate_offline("hk-huang-yunnan-5d")
        record("常规实例运行期切换必须被拒绝", False, {"error": "竟然成功了"})
    except sc.ScenarioError as exc:
        record("常规实例运行期切换必须被拒绝", True, {"error": str(exc)[:70]})
    must("未声明时 status.mode=live", svc.status()["mode"] == "live", svc.status()["mode"])
    os.environ["TRIPCRAFT_SCENARIO_MODE"] = "offline"
    out = svc.activate_offline("hk-huang-yunnan-5d")          # 模拟演示实例启动声明后
    must("演示实例声明后可进入离线模式", out["mode"] == "offline",
         {"scope": out["scope"], "demo_instance": out.get("demo_instance"),
          "session_state": out.get("session_state")})
    st = svc.status()
    must("status 标注 scope=instance 且区分实例说明",
         st.get("scope") == "instance" and st.get("demo_instance") is True,
         {"scope": st.get("scope"), "instance_note": st.get("instance_note", "")[:60]})
    svc.deactivate()
    os.environ.pop("TRIPCRAFT_SCENARIO_MODE", None)

    print("\n[7] status 诚实口径（key 存在 ≠ 连通已核验；认证按 security v2）")
    deps = sc.dependency_status(probe_llm=False)
    for key in ("llm_key_present", "llm_connectivity_verified", "llm_not_verified_reason",
                "voice_key_present", "voice_connectivity_verified", "voice_not_verified_reason",
                "db_path", "auth_mode"):
        must(f"status 含诚实字段 {key}", key in deps, {key: deps.get(key)})
    must("未核验时 connectivity_verified=false 且写了原因",
         deps["llm_connectivity_verified"] is False and bool(deps["llm_not_verified_reason"]),
         {"reason": deps["llm_not_verified_reason"]})
    must("认证状态不再读已删除的 TRIPCRAFT_AUTH",
         "always-on" in str(deps["auth_mode"]) and "TRIPCRAFT_AUTH" not in deps,
         {"auth_mode": deps["auth_mode"]})
    must("语音明确未验收并写原因", deps["voice_connectivity_verified"] is False
         and bool(deps["voice_not_verified_reason"]), {"reason": deps["voice_not_verified_reason"]})

    print("\n[8] 重置：先子后父 + 单事务 + 残留检查；另一账号不变")
    other = ctx.practice.spawn_order("other_user_abc", spec_from_case(case))
    # 造出真实的子表记录：会话消息 + 通话行 + 交付物文件 + 学习数据
    sid = ctx.store.upsert_session("sess-demo-1", "demo-lvyuan", "客户服务群", "客户", [],
                                   order_id=demo["order_id"], code="group")
    ctx.store.add_im_message("sess-demo-1", "我", "me", "你好")
    ctx.store.add_im_message("sess-demo-1", "客户", "other", "收到")
    ctx.store.save_call_session("call-demo-1", demo["order_id"], "demo-lvyuan", "黄先生", "云南", "text")
    ctx.store.add_call_line("call-demo-1", "student", "您好")
    ctx.store.save_file("file-demo-1", demo["order_id"], "需求确认单", "需求确认单.md",
                        "text/markdown", 12, b"demo-bytes")
    ctx.store.save_deliverable(demo["order_id"], "需求确认单", {"guest": "黄先生"}, "# 需求确认单",
                               ["客户"], {}, [])
    ctx.store.save_plan("plan-demo-1", demo["order_id"], "demo-lvyuan", 1, "云南 5 日", "", "", "")
    ctx.store.add_attempt("demo-lvyuan", "C2.2", "q1", {"stem": "s"}, "B", True, 92.0)
    ctx.store.add_memory("demo-lvyuan", "note", "演示记忆")
    ctx.store.set_ability("demo-lvyuan", "C2.2", teach=70.0, real_v=0.0)
    before_other = svc.counts("other_user_abc")["orders"]
    reset = svc.reset("demo-lvyuan", "hk-huang-yunnan-5d", include_profile=True)
    must("重置返回残留检查且全为 0", reset["residual_clean"] is True
         and all(v == 0 for v in reset["residual"].values()),
         {"residual": {k: v for k, v in reset["residual"].items() if v}})
    must("订单级子表确实被清（消息/通话/文件/方案）",
         reset["deleted"].get("im_message", 0) >= 2 and reset["deleted"].get("call_line", 0) >= 1
         and reset["deleted"].get("deliverable_file", 0) >= 1
         and reset["deleted"].get("plan_version", 0) >= 1,
         {k: v for k, v in reset["deleted"].items() if k in
          ("im_message", "call_line", "deliverable_file", "plan_version", "im_session", "call_session")})
    must("账号级学习数据被清（ability/quiz/memory）",
         reset["after"]["ability_rows"] == 0 and reset["after"]["quiz_attempts"] == 0,
         {"ability_rows": reset["after"]["ability_rows"],
          "quiz_attempts": reset["after"]["quiz_attempts"]})
    must("另一账号订单不受影响", svc.counts("other_user_abc")["orders"] == before_other,
         {"before": before_other, "after": svc.counts("other_user_abc")["orders"],
          "other_order_id": other.get("order_id")})
    must("demo 账号订单清零", reset["after"]["orders"] == 0, reset["after"])

    print("\n[9] 重放：重置后再导入内容一致")
    again = svc.import_case("demo-lvyuan", "hk-huang-yunnan-5d")
    must("重放后的固定字段与首轮一致", again["fixed_fields"] == demo["fixed_fields"],
         {"dates": again["fixed_fields"]["dates"], "budget": again["fixed_fields"]["budget"]})
    must("重放得到新的订单号（不覆盖历史）", again["order_id"] != demo["order_id"],
         {"first": demo["order_id"], "second": again["order_id"]})

    return _finish()


if __name__ == "__main__":
    raise SystemExit(main())
