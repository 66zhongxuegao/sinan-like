# -*- coding: utf-8 -*-
"""清理录屏沙箱里试跑出来的订单（>= 0044），让演示画面里不出现半途废单。"""
import sqlite3

DB = r"D:\lvyuan-main\TripCraft - 副本\_lvyuan\tripcraft.sqlite"
KEEP_BELOW = "9000000000000044"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
victims = [r[0] for r in con.execute("select order_id from biz_order where order_id >= ?", (KEEP_BELOW,))]
print("要删的订单:", victims)
if not victims:
    raise SystemExit(0)

sessions = []
for t in tables:
    cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
    if "order_id" in cols:
        if t == "im_session":
            sessions += [r[0] for r in con.execute(
                f'select session_id from "{t}" where order_id >= ?', (KEEP_BELOW,))]
        cur = con.execute(f'delete from "{t}" where order_id >= ?', (KEEP_BELOW,))
        print(f"  {t}: {cur.rowcount}")

if sessions:
    marks = ",".join("?" * len(sessions))
    for t in ("im_message",):
        cur = con.execute(f'delete from "{t}" where session_id in ({marks})', sessions)
        print(f"  {t}: {cur.rowcount}")
    sess = [r[0] for r in con.execute("select session_id from call_session where order_id >= ?", (KEEP_BELOW,))]
    if sess:
        marks2 = ",".join("?" * len(sess))
        print("  call_line:", con.execute(f'delete from call_line where session_id in ({marks2})', sess).rowcount)
    print("  call_session:", con.execute("delete from call_session where order_id >= ?", (KEEP_BELOW,)).rowcount)

cur = con.execute("delete from biz_order where order_id >= ?", (KEEP_BELOW,))
print("  biz_order:", cur.rowcount)
con.commit()
con.execute("VACUUM")
con.commit()
print("完成；剩余订单:", [r[0] for r in con.execute("select order_id from biz_order order by order_id")])
