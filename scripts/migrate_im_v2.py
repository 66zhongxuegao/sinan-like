"""把旧的「每个订单 6 个群」迁到「一个资源大群 + 单聊 + 自己拉的群」（DECISIONS D-059）。

做三件事：
1. 给每个学员建/补一个资源大群（im-hub-{user}）；
2. 删掉旧的按订单自动建的房间（code = customer/supplier/hotel/vehicle/ticket/guide）及其消息；
   这些房间对应的突发事件记录一并删掉，避免指向不存在的会话；
3. 联系人保留（他们的单聊 im-dm-* 不动），只是通讯录变成学员级。

可重复执行；只会删掉上面那批"自动建的房间"，不会碰学员自己拉的群和单聊。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tripcraft.services.supplier_service import SupplierService   # noqa: E402
from tripcraft.storage import Store                              # noqa: E402

LEGACY_CODES = ("customer", "supplier", "hotel", "vehicle", "ticket", "guide")


def main(db: str = "") -> None:
    store = Store(db or None)
    users = {r["user_id"] for r in store._all("SELECT DISTINCT user_id FROM im_session")}
    users |= {r["user_id"] for r in store._all("SELECT DISTINCT user_id FROM contact")}
    users |= {r["user_id"] for r in store._all("SELECT DISTINCT user_id FROM biz_order")}
    svc = SupplierService(store)

    for user in sorted(u for u in users if u):
        hub = svc.ensure_hub(user)
        print(f"资源大群：{user} → {hub['session_id']}（{hub['name']}）")

    legacy = [r for r in store._all("SELECT session_id, code FROM im_session")
              if (r["code"] or "") in LEGACY_CODES]
    for row in legacy:
        sid = row["session_id"]
        store._exec("DELETE FROM im_message WHERE session_id=?", (sid,))
        store._exec("DELETE FROM incident WHERE session_id=?", (sid,))
        store._exec("DELETE FROM im_session WHERE session_id=?", (sid,))
    print(f"删除旧的自动房间：{len(legacy)} 个")
    print("保留的会话：")
    for s in store._all("SELECT session_id, name, code FROM im_session ORDER BY code"):
        print(f"  · [{s['code'] or '—'}] {s['name']}  ({s['session_id']})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
