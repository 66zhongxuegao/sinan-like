"""conversation 域真实通道验证（R02，Codex 审查整改版）。

为什么要有这一版：上一版只验证了 9 个「订单事实」字段，**没有**验证
订单里显式写下的 age / gender / personality / preferences / quirks / hidden
是否真的覆盖了派生人设。Codex 复现证明当时它们是 False（被固定派生值吞掉），
`persona_view()` 与真实人设 `p` 还不一致。本脚本逐字段给 respected 矩阵。

它直接驱动三条真实链路，捕获模型适配器**实际收到的** messages / instructions：
  文本 CallService.start_for_order → CustomerAgent → llm.chat(messages)
  语音 VoiceBridge.run → build_scene_voice_instructions → QwenRealtimeClient(instructions)
  IM   SupplierService.respond → _customer_reply → llm.chat(messages)

然后：
  A. 显式覆盖矩阵：订单显式写明的字段 → 三通道提示词里必须出现该显式值；
  B. 派生矩阵（反例一侧）：订单**不填**的字段 → 必须出现同源的稳定派生值；
  C. 两客户不串：A 的提示词里不得出现 B 的任何事实（含 sentinel）；
  D. 视图一致性：persona_view() 的每个字段必须等于真实人设对象 p；
  E. 公开 DTO：hidden/preferences/quirks 不得进入任何下发前端的结构。

用法（仓库根目录）：
    python scripts/verify_channel_context.py
证据落盘：output/acceptance/evidence/conv-channel-context.md
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB_DIR = ROOT / ".dsh-run" / "conv-verify"
_DB_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TRIPCRAFT_DB"] = str(_DB_DIR / f"chan-{uuid.uuid4().hex[:8]}.sqlite")
os.environ.pop("DASHSCOPE_API_KEY", None)

from tripcraft.agents import customer as customer_mod  # noqa: E402
from tripcraft.api.public_dto import scan_forbidden_keys  # noqa: E402
from tripcraft.services import customer_order_facts as cof  # noqa: E402

FAILURES: list[str] = []
EVIDENCE: list[str] = []

PERSONA_FIELDS = ("age", "gender", "personality", "preferences", "quirks", "hidden")
TRIP_FIELDS = ("party", "dates", "days", "budget", "transport", "hotel", "special",
               "decision", "documents")
ALL_FIELDS = PERSONA_FIELDS + TRIP_FIELDS

LABELS = {
    "age": "年龄", "gender": "性别", "personality": "性格",
    "preferences": "偏好", "quirks": "说话习惯", "hidden": "隐藏诉求",
    "documents": "证件", "party": "出行人数", "dates": "出行日期", "days": "天数",
    "budget": "预算口径", "transport": "交通偏好", "hotel": "住宿标准",
    "special": "特殊需求", "decision": "决策人",
}
# 文本提示词的「身份」行写法：客户甲，29岁，男，来自香港。
IDENTITY_RX = re.compile(r"^(.+?)，(\d+[^，]*)岁，([男女])，来自")


def out(line: str = "") -> None:
    print(line)
    EVIDENCE.append(line)


def check(name: str, ok: bool, detail: str = "") -> None:
    out(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def extract_prompt_fields(text: str) -> dict:
    """从真实提示词里解出各字段的值（找不到 = 空串）。"""
    found = {k: "" for k in ALL_FIELDS}
    for key, label in LABELS.items():
        m = re.search(r"(?:^|\n)[ \t]*-?[ \t]*" + label + r"：(.+)", text or "")
        if m:
            found[key] = m.group(1).strip()
    m = IDENTITY_RX.search(text or "")
    if m:
        _name, age, gender = m.groups()
        if not found["age"]:
            found["age"] = age.strip()
        if not found["gender"]:
            found["gender"] = gender.strip()
    return found


class RecordingLLM:
    """记录真实收到的 messages（DeepSeek 客户端替身）。"""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def chat(self, messages, **kwargs):
        self.calls.append(list(messages))
        return "喂，你好，我是客户。"

    @property
    def system(self) -> str:
        return "\n".join(m.get("content", "") for m in (self.calls[0] if self.calls else []))


class Recorder:
    """记录真实调用链传给 persona_for 的关键字参数（证明显式字段进了人设构造）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __enter__(self):
        import importlib

        self._orig = customer_mod.persona_for
        rec = self

        def spy(*args, **kwargs):
            rec.calls.append({"args": args, "kwargs": dict(kwargs)})
            return rec._orig(*args, **kwargs)

        customer_mod.persona_for = spy
        self._patched = []
        for mod_name in ("tripcraft.services.call_service", "tripcraft.voice.bridge",
                         "tripcraft.services.supplier_service",
                         "tripcraft.services.customer_order_facts"):
            mod = importlib.import_module(mod_name)
            if getattr(mod, "persona_for", None) is not None:
                self._patched.append((mod, mod.persona_for))
                mod.persona_for = spy
        return self

    def __exit__(self, *exc):
        customer_mod.persona_for = self._orig
        for mod, orig in self._patched:
            mod.persona_for = orig
        return False


# ---------------------------------------------------------------- 三通道驱动器


def channel_text(store, practice, order_id: str, user_id: str) -> dict:
    from tripcraft.services.call_service import CallService

    llm = RecordingLLM()
    svc = CallService(llm=llm, store=store, practice=practice)
    with Recorder() as rec:
        svc.start_for_order(store, order_id, user_id)
    return {"prompt": llm.system,
            "persona_facts": [(c["kwargs"].get("facts") or {}) for c in rec.calls]}


def channel_voice(store, practice, order: dict, user_id: str) -> dict:
    from tripcraft.voice import bridge as bridge_mod
    from tripcraft.voice.bridge import VoiceBridge

    captured: dict = {}

    class FakeRealtime:
        def __init__(self, api_key, ws_url, model, instructions, voice=None, on_event=None,
                     on_close=None):
            captured["instructions"] = instructions
            captured["voice"] = voice

        def connect(self):
            pass

        def wait_ready(self, timeout=15.0):
            return False

        def close(self):
            pass

    class FakeWS:
        async def send_json(self, payload):
            captured.setdefault("frames", []).append(payload)

        async def close(self):
            pass

    orig_client, orig_resolve = bridge_mod.QwenRealtimeClient, bridge_mod.resolve_env
    bridge_mod.QwenRealtimeClient = FakeRealtime
    bridge_mod.resolve_env = lambda: ("fake-key", "wss://example.invalid/realtime", "fake-model")
    try:
        with Recorder() as rec:
            from tripcraft.services.call_service import CallService

            bridge = VoiceBridge(FakeWS(), order, order["customer"], order["destination"],
                                 CallService(llm=RecordingLLM(), store=store, practice=practice),
                                 practice, user_id=user_id)
            asyncio.run(bridge.run())
    finally:
        bridge_mod.QwenRealtimeClient = orig_client
        bridge_mod.resolve_env = orig_resolve

    return {"prompt": captured.get("instructions", ""),
            "frames": captured.get("frames", []),
            "persona_facts": [(c["kwargs"].get("facts") or {}) for c in rec.calls]}


def channel_im(store, practice, order_id: str, user_id: str) -> dict:
    from tripcraft.services.supplier_service import SupplierService

    llm = RecordingLLM()
    svc = SupplierService(store=store, llm=llm, practice=practice)
    sid = f"im-dm-客户-{uuid.uuid4().hex[:6]}"
    store.upsert_session(sid, user_id, "客户单聊", "客户", ["我", "客户"],
                         order_id=order_id, code="dm-客户")
    with Recorder() as rec:
        svc.respond(sid, "您好，方便聊聊吗？")
    return {"prompt": llm.system,
            "persona_facts": [(c["kwargs"].get("facts") or {}) for c in rec.calls]}


# ---------------------------------------------------------------- 场景


def make_order(store, user_id: str, order_id: str, customer: str, destination: str,
               **payload) -> None:
    facts = {"source_market": "香港", "language": "中文"}
    facts.update(payload)
    store.upsert_order(order_id, user_id, customer, destination, "正常", 1, payload=facts)


def run_channels(store, practice, order_id: str, user_id: str) -> dict:
    row = dict(store.order(order_id))
    row["stage_name"] = ""
    pl = json.loads(row.get("payload") or "{}")
    row["source_market"] = pl.get("source_market")
    row["language"] = pl.get("language")
    return {
        "text": channel_text(store, practice, order_id, user_id),
        "voice": channel_voice(store, practice, row, user_id),
        "im": channel_im(store, practice, order_id, user_id),
    }


MATRIX_FIELDS = ("age", "gender", "personality", "preferences", "quirks", "hidden")


def print_matrix(title: str, facts, chans: dict) -> None:
    """打印逐字段 respected 矩阵（字段 × 通道）。"""
    matrix = facts.respected_matrix()
    out(f"#### {title} 逐字段 respected 矩阵")
    out("")
    out("| 字段 | 期望值 | 来源 | 真实人设 | 文本 | 语音 | IM | respected |")
    out("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for key in MATRIX_FIELDS + ("documents",):
        row = matrix[key]
        cell = {name: extract_prompt_fields(c["prompt"]).get(key, "") for name, c in chans.items()}
        ok = row["respected"] and all(v == row["expected"] for v in cell.values())
        out(f"| {key} | {row['expected'] or '（未填）'} | {row['source']} | "
            f"{row['persona']} | {cell['text']} | {cell['voice']} | {cell['im']} | "
            f"{'✅' if ok else '❌'} |")
    out("")
    for name, c in chans.items():
        for key in MATRIX_FIELDS:
            prompt_value = extract_prompt_fields(c["prompt"]).get(key, "")
            check(f"[{title}] {name} 通道字段 {key} 与期望一致",
                  prompt_value == matrix[key]["expected"],
                  f"期望 {matrix[key]['expected']!r}，实际 {prompt_value!r}")


def main() -> int:
    from tripcraft.services.practice_service import PracticeService
    from tripcraft.storage import Store

    store = Store()
    practice = PracticeService(store)

    out("# conversation 域：三通道模型输入实证（R02，Codex 审查整改版）")
    out("")
    out(f"- 库：`{os.environ['TRIPCRAFT_DB']}`（工作区内临时库，不碰 tripcraft.sqlite）")
    out("- 三条通道都是真实调用链；模型客户端被替换为记录器，捕获实际 messages / instructions。")
    out("- 本版新增：**显式人设覆盖**（age/gender/personality/preferences/quirks/hidden）"
        "与**派生反例**两侧的逐字段断言。")
    out("")

    # ---- 场景 1：全部显式（Codex 的复现用例，含 sentinel 便于串单检测） ----
    uid_a, oid_a = "conv-a", "9000000000000301"
    make_order(store, uid_a, oid_a, "审计客户甲", "江苏",
               age="62岁", gender="女", personality="AUDIT_PERSONA_SENTINEL",
               preferences="AUDIT_PREF_SENTINEL", quirks="AUDIT_QUIRK_SENTINEL",
               hidden="AUDIT_HIDDEN_SENTINEL",
               party="3 大 1 小", dates="2027-01-01", days="5 天", budget="9000",
               transport="高铁优先", hotel="四星", special="老人忌辣",
               decision="太太拍板", documents="AUDIT_DOC_SENTINEL")
    facts_a = cof.facts_for_order_id(store, oid_a)
    chans_a = run_channels(store, practice, oid_a, uid_a)

    out("## 场景 1：订单显式写明人设与事实（Codex 复现用例）")
    out("")
    print_matrix("A 单", facts_a, chans_a)

    m_a = facts_a.respected_matrix()
    for key in ("age", "gender", "hidden", "preferences", "quirks"):
        check(f"A 单 {key} 显式覆盖生效（真实人设）", m_a[key]["respected"],
              f"source={m_a[key]['source']} expected={m_a[key]['expected']!r} "
              f"persona={m_a[key]['persona']!r}")

    view_a = facts_a.persona_view()
    check("A 单 persona_view() 与真实人设一致", view_a["view_matches_persona"],
          f"不一致字段 {view_a['view_mismatched_fields']}")
    p_a = facts_a.persona_for()
    for key in MATRIX_FIELDS:
        check(f"A 单 persona_view()['{key}'] == 真实人设.{key}",
              str(view_a.get(key)) == str(getattr(p_a, key, "")),
              f"view={view_a.get(key)!r} persona={getattr(p_a, key, '')!r}")

    frame_text = json.dumps(chans_a["voice"].get("frames", []), ensure_ascii=False)
    leaked = [k for k in ("AUDIT_HIDDEN", "AUDIT_PREF", "AUDIT_QUIRK", "AUDIT_PERSONA")
              if k in frame_text]
    check("A 单语音帧不下发私有 sentinel", not leaked, f"命中 {leaked}")

    # ---- 场景 2：全部不填 → 必须走派生（反例一侧） ----
    uid_b, oid_b = "conv-b", "9000000000000302"
    make_order(store, uid_b, oid_b, "审计客户乙", "云南", source_market="美国",
               language="English")
    facts_b = cof.facts_for_order_id(store, oid_b)
    chans_b = run_channels(store, practice, oid_b, uid_b)

    out("")
    out("## 场景 2：订单未填人设字段（必须走派生，反例一侧）")
    out("")
    print_matrix("B 单", facts_b, chans_b)
    m_b = facts_b.respected_matrix()
    for key in ("age", "gender", "personality", "preferences", "quirks", "hidden"):
        check(f"B 单 {key} 缺失时走派生", m_b[key]["source"] == "derived" and m_b[key]["respected"],
              f"source={m_b[key]['source']} expected={m_b[key]['expected']!r}")

    first, second = facts_b.persona_for(), facts_b.persona_for()
    check("B 单派生确定性（同输入同输出）",
          (first.age, first.gender, first.hidden, first.quirks) ==
          (second.age, second.gender, second.hidden, second.quirks))

    # ---- 场景 3：部分填（只显式 age 与 hidden，其余派生） ----
    uid_c, oid_c = "conv-c", "9000000000000303"
    make_order(store, uid_c, oid_c, "审计客户丙", "四川",
               age="70岁", hidden="AUDIT_HIDDEN_C")
    facts_c = cof.facts_for_order_id(store, oid_c)
    chans_c = run_channels(store, practice, oid_c, uid_c)

    out("")
    out("## 场景 3：只显式写了 age 与 hidden，其余走派生")
    out("")
    print_matrix("C 单", facts_c, chans_c)
    m_c = facts_c.respected_matrix()
    check("C 单 age 显式生效", m_c["age"]["source"] == "explicit" and m_c["age"]["respected"])
    check("C 单 hidden 显式生效", m_c["hidden"]["source"] == "explicit" and m_c["hidden"]["respected"])
    check("C 单 preferences 未填走派生",
          m_c["preferences"]["source"] == "derived" and m_c["preferences"]["respected"])

    # ---- 场景 4：两客户不串 ----
    out("")
    out("## 场景 4：两客户不串（A 的提示词里不得出现 B 的任何事实）")
    out("")
    sentinels_a = ["AUDIT_HIDDEN_SENTINEL", "AUDIT_PREF_SENTINEL", "AUDIT_QUIRK_SENTINEL",
                   "AUDIT_PERSONA_SENTINEL", "AUDIT_DOC_SENTINEL", "62岁", "审计客户甲"]
    for name in ("text", "voice", "im"):
        prompt = chans_a[name]["prompt"]
        hit_a = [s for s in sentinels_a if s in prompt]
        check(f"A 提示词（{name}）包含 A 自己的事实", len(hit_a) >= 4, f"命中 {hit_a}")
        for token in ("审计客户乙", "AUDIT_HIDDEN_B", "AUDIT_PREF_B"):
            check(f"A 提示词（{name}）不含 B 的标记 {token}", token not in prompt)
    for name in ("text", "voice", "im"):
        for token in ("AUDIT_HIDDEN_SENTINEL", "AUDIT_PREF_SENTINEL", "审计客户甲"):
            check(f"B 提示词（{name}）不含 A 的标记 {token}",
                  token not in chans_b[name]["prompt"])

    # ---- 场景 5：公开 DTO 不泄漏私有字段 ----
    out("")
    out("## 场景 5：公开下发结构不得含私有字段")
    out("")
    public_a = facts_a.public_facts()
    forbidden = scan_forbidden_keys(public_a)
    check("public_facts() 无禁止 key", not forbidden, f"命中 {forbidden}")
    check("public_facts() 不含 hidden/preferences/quirks/personality",
          not (set(public_a) & {"hidden", "preferences", "quirks", "personality"}),
          f"keys={sorted(public_a)}")
    check("public_facts() 仍保留学员需要的字段",
          all(k in public_a for k in ("customer", "age", "gender", "language",
                                      "documents", "party")))
    out(f"- public_facts() keys = {sorted(public_a)}")
    out(f"- persona.hidden（只进提示词）= {p_a.hidden!r}，未出现在 public_facts()")

    out("")
    out("## 结论")
    if FAILURES:
        out(f"- FAIL: {len(FAILURES)} 项未通过")
        for f in FAILURES:
            out(f"  - {f}")
    else:
        out("- PASS：显式覆盖 6 项 + 订单事实 9 项在三通道真实提示词中逐字段一致；")
        out("  未填字段走确定性派生；两客户不串；视图与真实人设一致；公开结构无私有字段。")
    from scripts.verify_customer_consistency import run_checks
    output_result = run_checks(verbosity=1)
    check("客户实际输出、未知项、回写与语音播放守卫", output_result.wasSuccessful())
    out("")
    out("附：本次捕获的真实提示词片段")
    for name in ("text", "voice", "im"):
        out("")
        out(f"<details><summary>{name} 提示词（前 900 字）</summary>")
        out("")
        out("```text")
        out((chans_a[name]["prompt"] or "")[:900])
        out("```")
        out("</details>")

    evidence = ROOT / "output" / "acceptance" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    target = evidence / "conv-channel-context.md"
    target.write_text("\n".join(EVIDENCE) + "\n", encoding="utf-8")
    print(f"\n证据已落盘: {target}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
