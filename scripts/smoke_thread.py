"""线程服务真实冒烟：讲解 → 出题 → 判分 → 生成资产。

用法：python scripts/smoke_thread.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.agents.llm import DeepSeekClient  # noqa: E402
from tripcraft.services.practice_service import PracticeService  # noqa: E402
from tripcraft.services.thread_service import ThreadService  # noqa: E402
from tripcraft.storage import Store  # noqa: E402

SP = "C2.2"
USER = "u-smoke"


def main() -> int:
    store = Store(os.path.join(ROOT, "data", "smoke_thread.sqlite"))
    PracticeService(store).seed(USER)
    svc = ThreadService(store, DeepSeekClient())

    print("=" * 60)
    print("【1】上下文来源")
    ctx = svc.build_context(USER, SP)
    for s in ctx.sources():
        print("   -", s)

    print("\n【2】问老师（真实 LLM）")
    r = svc.reply(USER, SP, "预算这块我该怎么问客户？")
    print("   来源:", r["evidence"])
    print("   回复:", r["content"][:220].replace("\n", " "), "…")

    print("\n【3】出题（AI 按 Rubric 判档 → 定难度）")
    q = svc.pick_question(USER, SP)
    print(f"   判定档位: {q['judged_level']} → 难度 {q['difficulty']}")
    print("   题干:", str(q.get("stem"))[:70])
    if q.get("options"):
        print("   选项:", " / ".join(str(o)[:16] for o in q["options"]))

    print("\n【4】作答（故意答错，看纠错）")
    wrong = "A" if str(q.get("answer", "B")).upper()[:1] != "A" else "B"
    res = svc.submit_answer(USER, SP, q, wrong)
    print(f"   对错: {res['correct']} | 得分 {res['score']} | 教学掌握度 {res['teach']} ({res['level']}) | 需纠错: {res['reteach']}")

    print("\n【5】生成讲义（Markdown，带参考来源）")
    a = svc.generate_asset(USER, SP, "lecture")
    print("   标题:", a["title"], "| 长度:", len(a["content"]), "| 来源:", a["evidence"])
    print("   预览:", a["content"][:160].replace("\n", " "), "…")

    print("\n>>> 线程服务真实跑通")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())