"""S2 垂直切片真实冒烟：对话 -> 需求单 -> 评分 -> 画像。

用法：python scripts/smoke_s2.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.agents.llm import DeepSeekClient  # noqa: E402
from tripcraft.contracts.profile import LearnerProfile  # noqa: E402
from tripcraft.services.s2_session import S2Session  # noqa: E402

# 模拟一个「开场还行、但预算口径没挖清」的学员
GUIDE_TURNS = [
    "您好，我是XX定制游的定制师小李，您在我们平台提交了云南的出行需求。请问怎么称呼您？现在方便聊几分钟吗？",
    "好的王女士，我想先了解下：您这次大概几位出行？和家人一起吗？",
    "打算几月几号出发、玩几天呢？",
    "预算这块大概是什么范围？",
    "好的，那我先按这个思路给您出个初步方案。",
]


def main() -> int:
    llm = DeepSeekClient()
    sess = S2Session(user_id="u-smoke", llm=llm, instance_id="s2-smoke")

    print("=" * 60)
    print("客户:", sess.start())
    for msg in GUIDE_TURNS:
        print("定制师:", msg)
        print("客户:", sess.send(msg))

    print("=" * 60)
    prof = LearnerProfile(user_id="u-smoke")
    report = sess.finish(profile=prof)

    print("【需求单】")
    for it in report["requirement_sheet"].get("items", []):
        print(f"  - {it.get('category')}: {it.get('content')} [{it.get('attribute')}/{it.get('status')}]")
    print("  缺失:", report["requirement_sheet"].get("missing"))
    print("  风险:", report["requirement_sheet"].get("risks"))

    print("\n【评分（每分带证据）】")
    for s in report["scores"]:
        print(f"  {s['skill_point_id']}  {s['level']}  {s['score']}  反例={s['hit_negative']}")
        print(f"     理由: {s['comment']}")
        for e in s["evidence"][:2]:
            print(f"     证据: {e.get('quote', '')[:50]}")

    print(f"\n平均分: {report['average']}")

    print("\n【画像写回】")
    print("  C2.2 =", prof.values()["C2.2"])
    print("  薄弱点数量:", len(prof.weak_points()))
    print("  其中 S2 相关:", [i for i in prof.weak_points() if i in ("C1.1", "C1.2", "C1.3", "C1.6", "C2.1", "C2.2")])
    print("\n>>> S2 垂直切片跑通")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())