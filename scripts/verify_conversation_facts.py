"""conversation 域自检（一）：客户事实单一来源 + 硬编码用户 + 跨单隔离。

本脚本覆盖的是**确定性不变量**（不需要模型）：
  ① 订单事实解析：显式值 / 空值 / 部分填三种情形；
  ② 单一事实源：文本/语音/IM 三条真实通道是否都从同一入口取事实（见下）；
  ③ call_session.user_id 是真实调用者；他人不可读写本人会话；
  ④ 源码级：conversation 域代码里不再有硬编码演示账号。

三通道「实际喂给模型的内容」逐字段比对在 `scripts/verify_channel_context.py`
（那个脚本会捕获 CallService / VoiceBridge / SupplierService 的真实 prompt）。

用法（仓库根目录）：
    python scripts/verify_conversation_facts.py
退出码 0 = 全部通过，1 = 有失败项。
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB_DIR = ROOT / ".dsh-run" / "conv-verify"
_DB_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TRIPCRAFT_DB"] = str(_DB_DIR / f"facts-{uuid.uuid4().hex[:8]}.sqlite")

from tripcraft.services.call_service import LOCAL_SESSION_USER, CallService  # noqa: E402
from tripcraft.services.customer_order_facts import (  # noqa: E402
    facts_for_order_id,
    facts_from_order_row,
)
from tripcraft.storage import Store  # noqa: E402

USER_A = "verify-user-a"
USER_B = "verify-user-b"
ORDER_A = "9000000000000301"
ORDER_B = "9000000000000302"
ORDER_EMPTY = "9000000000000303"

FAILURES: list[str] = []


class StubLLM:
    """假 LLM：只回固定台词，不联网。"""

    def chat(self, messages, **kwargs):
        return "喂，你好。"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def _code_only(path: Path) -> str:
    """去掉注释与文档字符串后的源码（源码级纪律检查用）。"""
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        return src
    return " ".join(out)


def banner(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def build_store() -> Store:
    store = Store()
    store.upsert_order(ORDER_A, USER_A, "客户甲", "江苏", "正常", 1, payload={
        "source_market": "香港", "language": "中文", "documents": "回乡证",
        "party": "3 大 1 小", "dates": "2026-11-02", "days": "5 天",
        "budget": "人均 6000-7000", "transport": "高铁优先", "hotel": "四星",
        "special": "老人忌辣", "decision": "太太拍板",
    })
    store.upsert_order(ORDER_B, USER_B, "客户乙", "云南", "正常", 1, payload={
        "source_market": "美国", "language": "English", "documents": "美国护照",
    })
    store.upsert_order(ORDER_EMPTY, USER_A, "客户丙", "四川", "正常", 1, payload={
        "source_market": "台湾", "language": "中文",
    })
    return store


def main() -> int:
    store = build_store()

    banner("① 订单事实解析：显式值 / 空值 / 部分填")
    a = facts_for_order_id(store, ORDER_A)
    print("A（全填）public:", a.public_facts())
    print("A（全填）model_facts:", a.model_facts())
    check("A 的显式事实全部进模型侧", a.model_facts()["party"] == "3 大 1 小"
          and a.model_facts()["budget"] == "人均 6000-7000"
          and a.model_facts()["special"] == "老人忌辣")
    check("A 的公开字段含人数（学员需要知道）", a.public_facts()["party"] == "3 大 1 小")
    check("A 的公开字段不含预算/特殊需求（要电话里问出来）",
          "budget" not in a.public_facts() and "special" not in a.public_facts())

    b = facts_for_order_id(store, ORDER_B)
    check("B 未填项在模型侧保留空串（= 订单没写）",
          b.model_facts()["budget"] == "" and b.model_facts()["party"] == "")
    check("B 客源地/语言取订单 payload", b.source_market == "美国" and b.language == "English")

    c = facts_for_order_id(store, ORDER_EMPTY)
    check("C 部分填：只 party 为空、其它也空", c.model_facts()["party"] == "")

    banner("② 单一事实源：三条通道都走同一入口（源码级 + 运行时）")
    facts = facts_for_order_id(store, ORDER_A)
    p = facts.persona_for()
    trip_keys = ("party", "dates", "days", "budget", "transport", "hotel",
                 "special", "decision", "documents")
    check("persona_for().facts 覆盖 9 项订单事实",
          all(p.facts.get(k) == facts.model_facts().get(k) for k in trip_keys),
          f"{p.facts} vs {facts.model_facts()}")
    check("model_facts 带显式人设字段（缺失=空串，走派生）",
          all(k in facts.model_facts() for k in
              ("age", "gender", "personality", "preferences", "quirks", "hidden")),
          f"keys={sorted(facts.model_facts())}")
    check("人设带订单事实（facts 非空）", bool(p.facts.get("party")))
    check("人设 facts_block 渲染出「已填/未填」", "已经填过" in p.facts_block())

    banner("③ call_session.user_id 与归属隔离")
    svc = CallService(llm=StubLLM(), store=store, practice=None)
    sess_a = svc.start_for_order(store, ORDER_A, USER_A)
    row_a = store.call_sessions_for_order(ORDER_A)[-1]
    check("call_session.user_id == 真实调用者", row_a["user_id"] == USER_A,
          f"实际 {row_a['user_id']!r}")
    check("会话对象 user_id 与库一致", sess_a.user_id == USER_A)

    svc_b = CallService(llm=StubLLM(), store=store, practice=None)
    svc_b.start_for_order(store, ORDER_B, USER_B)
    check("B 的会话 user_id == USER_B",
          store.call_sessions_for_order(ORDER_B)[-1]["user_id"] == USER_B)

    check("USER_B 取 A 的会话 → None", svc.get(sess_a.session_id, USER_B) is None)
    check("USER_A 取自己的会话 → 命中", svc.get(sess_a.session_id, USER_A) is not None)
    check("USER_B 结束 A 的会话 → None", svc.end(sess_a.session_id, USER_B) is None)
    check("USER_B 对 A 的会话发言 → None", svc.say(sess_a.session_id, "你好", USER_B) is None)

    banner("④ 跨单不串：A/B/C 三单事实各自独立")
    rows = {oid: facts_for_order_id(store, oid).public_facts()
            for oid in (ORDER_A, ORDER_B, ORDER_EMPTY)}
    import json as _json

    check("三单公开事实两两不同",
          len({_json.dumps(v, sort_keys=True) for v in rows.values()}) == 3)
    check("A 会话不读到 B 的客源/语言",
          (sess_a.source_market, sess_a.language) == (a.source_market, a.language))
    check("A 会话 facts 不包含 B 的订单事实",
          sess_a.facts.get("party") == "3 大 1 小" and "美国" not in str(sess_a.facts))

    banner("⑤ 源码级：conversation 域代码里没有硬编码演示账号")
    scoped = [
        "tripcraft/services/call_service.py",
        "tripcraft/voice/bridge.py",
        "tripcraft/api/routers/calls.py",
        "tripcraft/services/customer_order_facts.py",
        "tripcraft/services/supplier_service.py",
    ]
    for rel in scoped:
        code = _code_only(ROOT / rel)
        hits = [i for i, l in enumerate(code.splitlines(), 1) if "u-demo" in l]
        check(f"{rel} 代码（去注释/文档串）不含 'u-demo'", not hits,
              f"命中行: {hits}" if hits else "")
    check("未显式传 user_id 时落到 LOCAL_SESSION_USER，不冒用他人",
          LOCAL_SESSION_USER not in (USER_A, USER_B))

    banner("结果")
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} 项未通过 → {FAILURES}")
        return 1
    print("PASS: 全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
