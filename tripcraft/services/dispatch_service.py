"""派单与时限 —— 抢单竞争窗口 + 首呼/方案倒计时（PRD 第 6.1 节、C7.1）。

口径：
- 订单被平台派下来后有**抢单窗口**（默认 15 分钟）。同期还有别的定制师在抢，
  系统按订单号确定性地安排一位竞争者在窗口末段接走；学员没在窗口内抢单就丢单。
- 抢到之后开始**首呼时限**（1 小时）与**方案时限**（4 小时），超时会写成事件，
  既可被学员看到，也会进入 C7.1 的评分素材。

时间来自订单 payload 的 `dispatch_at`；没有就按创建时间补。窗口与时限可在 local.env 调。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {"DISPATCH_WINDOW_MIN": 15, "FIRST_CALL_LIMIT_MIN": 60, "PLAN_LIMIT_MIN": 240}


def _env() -> dict[str, int]:
    cfg = dict(DEFAULTS)
    p = ROOT / "local.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k in cfg:
                    try:
                        cfg[k] = int(float(v))
                    except ValueError:
                        pass
    return cfg


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _hash(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) % 100003
    return h


def dispatch_at(order_id: str, created_at: str | None, payload: dict) -> datetime:
    d = _parse(payload.get("dispatch_at")) or _parse(created_at) or datetime.now()
    return d


def rival_claim_at(order_id: str, base: datetime) -> datetime:
    """竞争者接走的时间：窗口的 80%~93%，按订单号确定（同一单每次算出来一样）。"""
    cfg = _env()
    window = cfg["DISPATCH_WINDOW_MIN"]
    ratio = 0.80 + (_hash(order_id) % 14) / 100.0     # 0.80 ~ 0.93
    return base + timedelta(minutes=window * ratio)


def status(order_id: str, created_at: str | None, payload: dict,
           grabbed: bool, first_call_at: str | None = None,
           now: datetime | None = None) -> dict:
    """返回派单/时限状态；纯计算，不落库。"""
    cfg = _env()
    now = now or datetime.now()
    base = dispatch_at(order_id, created_at, payload)
    window_end = base + timedelta(minutes=cfg["DISPATCH_WINDOW_MIN"])
    rival = rival_claim_at(order_id, base)

    out: dict = {
        "dispatch_at": base.isoformat(timespec="seconds"),
        "window_min": cfg["DISPATCH_WINDOW_MIN"],
        "window_end": window_end.isoformat(timespec="seconds"),
        "claimed": grabbed,
        "rivals": 2 + _hash(order_id) % 3,            # 同期竞争的定制师人数
        "seconds_left": max(0, int((window_end - now).total_seconds())),
        "expired": False,
        "lost": False,
        "first_call": None,
        "plan": None,
    }

    if not grabbed:
        if now >= rival:
            out["lost"] = True
            out["expired"] = True
            out["lost_reason"] = "已被其他定制师接走"
        elif now >= window_end:
            out["expired"] = True
            out["lost_reason"] = "抢单窗口已结束"
        out["rival_eta_min"] = round((rival - base).total_seconds() / 60, 1)
        return out

    out["seconds_left"] = 0        # 已认领：抢单窗口不再是关注点
    grab_at = _parse(payload.get("grabbed_at"))
    if grab_at:
        # 订单级覆盖：生成的派单按画像难度调整首呼时限（补救放宽、熟练收紧）
        try:
            fc_limit = int(payload.get("first_call_limit_min") or cfg["FIRST_CALL_LIMIT_MIN"])
        except (TypeError, ValueError):
            fc_limit = cfg["FIRST_CALL_LIMIT_MIN"]
        out["first_call_limit_min"] = fc_limit
        fc_due = grab_at + timedelta(minutes=fc_limit)
        plan_due = grab_at + timedelta(minutes=cfg["PLAN_LIMIT_MIN"])
        fc_done = _parse(first_call_at)
        out["first_call"] = {
            "limit_min": fc_limit,
            "due_at": fc_due.isoformat(timespec="seconds"),
            "done": bool(fc_done),
            "seconds_left": max(0, int((fc_due - now).total_seconds())),
            # 补做首呼后仍保留超时事实，不能因轮询时机不同而漏记时效考核。
            "missed": (fc_done or now) > fc_due,
        }
        out["plan"] = {
            "limit_min": cfg["PLAN_LIMIT_MIN"],
            "due_at": plan_due.isoformat(timespec="seconds"),
            "seconds_left": max(0, int((plan_due - now).total_seconds())),
            "missed": now > plan_due,
        }
    return out


def fmt_left(seconds: int) -> str:
    h, m = seconds // 3600, (seconds % 3600) // 60
    if h:
        return f"{h} 小时 {m} 分"
    return f"{m} 分 {seconds % 60} 秒"
