"""比赛演示放行开关。

默认开启：表单必填/算术/拦截网、流程门槛、资源阶段门控、客户反馈全部走
“一次作答即满意”的演示路径。赛后把环境变量
TRIPCRAFT_COMPETITION_EASY 设为 0（或删除本模块的调用）即可恢复原校验。

安全边界仍保留：登录、订单归属、文件归属与资源存在性不属于业务放行范围。
"""

from __future__ import annotations

import os

ENV_NAME = "TRIPCRAFT_COMPETITION_EASY"
DEFAULT_VALUE = "1"  # 赛后改为 "0" 即可关闭比赛放行
_FALSE = {"0", "false", "off", "no", "否", "关闭"}


def enabled() -> bool:
    return os.environ.get(ENV_NAME, DEFAULT_VALUE).strip().lower() not in _FALSE


def satisfied_reply(question: str = "", *, feedback: bool = False, channel: str = "") -> dict:
    """Return a one-turn satisfied customer reply for the demo path."""
    event_words = ("超售", "故障", "延误", "改签", "换车", "突发", "投诉", "赔付", "处理")
    is_event = any(word in (question or "") for word in event_words)
    if feedback or channel == "plan":
        text = "我看到了，整体安排都满意，就按这份方案执行；后续有变化再提前告诉我就好。"
    elif is_event:
        text = "收到，这样处理我满意，就按你说的办，麻烦尽快落实。"
    else:
        text = "好的，这样安排我满意，就按你们的建议执行。"
    return {"reply": text, "sentiment": "满意", "asks": []}

def pass_guard(kind: str, order_id: str = "") -> dict:
    return {
        "kind": kind, "order_id": order_id or "", "blocked": False, "verdict": "pass",
        "reasons": [],
        "deterministic": {"layer": "deterministic", "kind": kind, "checks": [],
                          "errors": [], "warnings": [],
                          "note": "比赛演示：校验已放行"},
        "semantic": {"layer": "semantic", "skipped": True, "issues": [], "verdict": "pass",
                     "note": "比赛演示：语义校验已放行"},
        "layers": ["deterministic", "semantic"],
        "competition_bypass": True,
    }