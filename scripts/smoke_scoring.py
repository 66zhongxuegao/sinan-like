"""实战评分链路冒烟：通话/交付物 -> 证据 -> 评分 Agent -> 画像写回。

用法：python -X utf8 scripts/smoke_scoring.py [order_id]
前置：后端已启动（127.0.0.1:18020）。
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18020"


def call(method: str, path: str, body: dict | None = None, timeout: float = 180.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    order_id = sys.argv[1] if len(sys.argv) > 1 else "9000000000000002"

    print("== 1. 拨打（文本链路）==")
    sess = call("POST", f"/practice/orders/{order_id}/call")
    sid = sess["session_id"]
    print("   客户开场:", sess["lines"][-1]["text"][:60])

    script = [
        "您好，我是司南礼客定制游的定制师小李，请问怎么称呼您？方便说两分钟吗？",
        "王女士您好。想先确认下人数和出行日期，是3大1小、10月20日出发吗？",
        "明白。预算是按人均还是整团总价？大概区间是多少，含不含机票高铁？",
        "好的，我复述一下：3大1小，10月20日出发5天，预算人均5000-6000含大交通。对吗？",
    ]
    for line in script:
        out = call("POST", f"/practice/call/{sid}/messages", {"text": line})
        print("   我:", line[:34], "...")
        print("   客户:", out["reply"][:60])

    print("== 2. 挂断（登记证据）==")
    snap = call("POST", f"/practice/call/{sid}/end")
    print("   轮次:", snap["turns"])

    print("== 3. 投递行程方案（绑定订单）==")
    fb = call("POST", "/tools/deliverable", {
        "kind": "\u884c\u7a0b\u65b9\u6848",
        "customer": "客户",
        "order_id": order_id,
        "content": (
            "D1 抵达昆明，入住市区四星酒店；D2 石林一日游；D3 大理古城+洱海环湖；"
            "D4 丽江古城；D5 返程。全程7座商务车，含司导，已确认酒店房态。"
            "人均报价 5,400 元（含高铁），毛利约 11%。"
        ),
    })
    print("   客户反馈:", fb.get("reply", "")[:60], "| 情绪:", fb.get("sentiment"))

    print("== 4. 证据清单 ==")
    for e in call("GET", f"/practice/orders/{order_id}/evidence"):
        print(f"   - {e['kind']} / 步骤 {e['step']} / {e['chars']} 字")

    print("== 5. 运行评分 Agent（较慢）==")
    report = call("POST", f"/practice/orders/{order_id}/score")
    print("   候选技能点:", report["candidates"], "| 入库:", report["scored"],
          "| 因缺证据丢弃:", report["dropped"])
    for w in report["skill_points"]:
        print(f"   {w['skill_point_id']}  {w['score']:>3}  {w['level']}  {w['comment'][:36]}")

    print("== 6. 评分结果（按维度）==")
    sc = call("GET", f"/practice/orders/{order_id}/scores")
    print("   平均:", sc["average"], "| 已评:", sc["evaluated"], "/", sc["total"])
    for d in sc["dimensions"]:
        print(f"   {d['id']} {d['name']}: {d['score']}  ({d['evaluated']}/{d['total']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())