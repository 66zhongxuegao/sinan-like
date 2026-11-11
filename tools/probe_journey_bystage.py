"""用**真实 journey 投影代码**生成各平台阶段的内洽投影，落盘给前端回归用（一次性脚本）。

背景：真实订单要跨过平台阶段 0 需要「首呼」动作，而首呼依赖 LLM（`start_for_call` 会抛 LLMError）。
因此这里不伪造 journey 结果，而是造一个**只提供事实输入**的假 store，把
`tripcraft.services.journey_service.journey()` 这份唯一口径实现在每个平台阶段上真跑一遍：
`stages` / `current_stage` / `next_action` / 文档投递态全部由真实代码算出来，自洽。

用法：
  $env:PROBE_DUMP_DIR="$env:TEMP\tc-journey-dump"; python tools/probe_journey_bystage.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tripcraft.contracts.deliverables_spec import BY_ID  # noqa: E402
from tripcraft.services.journey_service import journey  # noqa: E402

DUMP_DIR = Path(os.environ.get("PROBE_DUMP_DIR", ""))
ORDER_ID = "9000000000000099"

# 平台阶段 → 该阶段「已经发生过」的学业事实（到这一步为止真实会有的东西）
STAGE_FACTS: list[dict] = [
    {"docs": (), "actions": {"grab"}, "plans": 0, "incidents": 0, "scores": False},
    {"docs": ("需求确认单",), "actions": {"grab", "first_call"}, "plans": 0, "incidents": 0, "scores": False},
    {"docs": ("需求确认单", "行程方案"), "actions": {"grab", "first_call"}, "plans": 1,
     "plan_status": "已发送", "incidents": 0, "scores": False},
    {"docs": ("需求确认单", "行程方案", "分项报价"), "actions": {"grab", "first_call"}, "plans": 2,
     "plan_status": "客户已确认", "incidents": 0, "scores": False},
    {"docs": ("需求确认单", "行程方案", "分项报价", "合同与保险"),
     "actions": {"grab", "first_call", "customer_confirmed_plan"}, "plans": 2,
     "plan_status": "客户已确认", "incidents": 0, "scores": False},
    {"docs": ("需求确认单", "行程方案", "分项报价", "合同与保险", "出团通知书"),
     "actions": {"grab", "first_call", "customer_confirmed_plan", "depart", "resources_locked"},
     "plans": 2, "plan_status": "客户已确认", "incidents": 1, "scores": False},
    {"docs": ("需求确认单", "行程方案", "分项报价", "合同与保险", "出团通知书", "地接结算核对单"),
     "actions": {"grab", "first_call", "customer_confirmed_plan", "depart", "resources_locked"},
     "plans": 2, "plan_status": "客户已确认", "incidents": 1, "scores": False},
    {"docs": tuple(BY_ID), "actions": {"grab", "first_call", "customer_confirmed_plan", "depart",
                                       "resources_locked", "review_done"},
     "plans": 2, "plan_status": "客户已确认", "incidents": 1, "scores": True},
]


class FactStore:
    """只回答 journey 需要的事实；不含任何阶段/动作判定（判定仍走真实 journey()）。"""

    def __init__(self, stage_index: int) -> None:
        self.facts = STAGE_FACTS[min(stage_index, len(STAGE_FACTS) - 1)]
        self.stage_index = stage_index

    def order(self, order_id: str) -> dict:
        return {"order_id": order_id, "stage_index": self.stage_index,
                "customer": "客户 Z", "destination": "陕西", "status": "正常"}

    def deliverables(self, order_id: str) -> list[dict]:
        out = []
        for i, cid in enumerate(self.facts["docs"]):
            spec = BY_ID[cid]
            out.append({"deliverable_id": cid, "code": spec.code, "id": cid,
                        "title": spec.title, "version": 1 + i, "rendered": "（阶段夹具）"})
        return out

    def plans(self, order_id: str) -> list[dict]:
        n = self.facts["plans"]
        return [{"plan_id": f"p{i}", "version": i + 1,
                 "status": self.facts.get("plan_status", "草稿") if i == n - 1 else "已读",
                 "sent_at": "2026-10-16T10:00:00", "read_at": "2026-10-16T11:00:00",
                 "feedback": "客户同意" if i == n - 1 else ""} for i in range(n)]

    def action_keys(self, order_id: str) -> set[str]:
        return set(self.facts["actions"])

    def events(self, order_id: str) -> list[dict]:
        return []

    def incidents(self, order_id: str) -> list[dict]:
        return [{"incident_id": f"i{i}"} for i in range(self.facts["incidents"])]

    def evidence(self, order_id: str) -> list[dict]:
        return [{"kind": "需求确认单"} for _ in self.facts["docs"]]

    def order_scores(self, order_id: str) -> dict:
        return {"s": {}} if self.facts["scores"] else {}


def main() -> int:
    if not DUMP_DIR:
        print("需要 PROBE_DUMP_DIR")
        return 2
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    seen = set()
    for stage_index in range(len(STAGE_FACTS)):
        j = journey(FactStore(stage_index), ORDER_ID)
        if j is None:
            print(f"[stage {stage_index}] journey 返回 None")
            return 1
        seen.add(j["current_stage"])
        na = j["next_action"] or {}
        sub = sum(1 for s in j["stages"] for d in s["substeps"] if d["done"])
        docs = sum(1 for s in j["stages"] for d in s["deliverables"] if d["submitted"])
        print(f"platform_stage={stage_index} current={j['current_stage']:18} "
              f"next={na.get('kind')}/{na.get('deliverable') or na.get('label')} -> {na.get('route')} "
              f"substeps_done={sub} docs_submitted={docs}")
        p = DUMP_DIR / f"journey-stage{stage_index}-{j['current_stage']}.json"
        p.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[summary] 覆盖阶段 {sorted(seen)}（{len(seen)}/6）")
    return 0 if len(seen) >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
