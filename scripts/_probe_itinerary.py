"""一次性排查：行程方案投递为何被拦截（打印确定性/语义拦截原因）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = ROOT / "output" / "journey" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
db = _TMP / "probe-itinerary.sqlite"
db.unlink(missing_ok=True)
os.environ["TRIPCRAFT_DB"] = str(db)
os.environ["TRIPCRAFT_VISIT_LOG_DIR"] = str(_TMP / "logs-probe")

from tripcraft.contracts.deliverables_spec import render, resolve  # noqa: E402

ITIN = {
    "title": "香港黄先生 · 云南 5 日亲子长辈同行版",
    "dates": "2026-11-16 至 2026-11-20", "people": "3 大 1 小",
    "days": [
        {"day": "D1", "time": "09:00", "transport": "专车接机 40 分钟", "spot": "滇池海埂大坝",
         "meal": "午餐过桥米线 / 晚餐清淡", "hotel": "昆明 4 星（已确认）", "guide": "导游小周"},
        {"day": "D2", "time": "08:30", "transport": "高铁 2 小时", "spot": "大理古城 / 洱海",
         "meal": "午餐白族菜（无猪肉无酒）", "hotel": "大理海景 4 星（已确认）", "guide": "导游小周"},
    ],
}
spec = resolve("行程方案")
md = render(spec, ITIN, {"order_id": "9000000000000003", "customer": "黄先生",
                         "destination": "云南", "source_market": "香港", "language": "中文"})
print("--- rendered (first 40 lines) ---")
print("\n".join(md.splitlines()[:40]))
from tripcraft.services.deliverable_service import DeliverableService, check_arithmetic  # noqa: E402
from tripcraft.services.guard_service import GuardService  # noqa: E402
from tripcraft.storage import Store  # noqa: E402

store = Store()
g = GuardService(store=store, practice=None)
print("--- validate ---", DeliverableService.validate("行程方案", ITIN))
print("--- arithmetic ---", check_arithmetic(spec.code, ITIN))
out = g.check("行程方案", md, "9000000000000003")
print("--- guard blocked ---", out["blocked"], out["reasons"])
print("--- deterministic ---", out["deterministic"])
