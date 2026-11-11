"""工具台服务 —— 外部客观环境 + 资源方 Agent + 交付物投递。

对应前端「工具台」：
  ① 外部客观环境参数：天气 / 路线 / 行程可行性（确定性，来自真实 API）
  ② 资源方 Agent：地接社 / 酒店 / 车队 / 票务 —— 模拟它们的反馈
  ③ 交付物投递：让「客户」读取学员交付物并给反馈
"""

from __future__ import annotations

import json
import time

from ..agents.llm import DeepSeekClient
from ..contracts.rubric import RUBRICS
from ..tools import external
from ..tools.external import GeoPoint, check_itinerary, driving, exchange_rates, geocode, weather
from ..tools.external import poi_tips as amap_tips
from ..tools.external import route_points as amap_route
from ..tools.external import static_map as amap_static_map

SUPPLIER_ROLES = {
    "地接社": "你是江苏/云南一带的地接社计调。给定制师报资源：住宿、用车、门票、导游。",
    "酒店": "你是目的地酒店的团队销售。回答房型、房价、房态与保留时限。",
    "车队": "你是当地车队调度。回答车型、座位、日租价与档期。",
    "票务": "你是旅行社票务。回答机票/高铁票价、余票紧张度与价格波动。",
}

SUPPLIER_SYSTEM = """{role}

【规则】
1. 用口语简短回复（3-6 句），像微信里对接工作的语气。
2. 报价要具体（单价 + 单位），库存/档期要说清「有 / 紧张 / 没有」。
3. 热门时段可以提示「建议先付 80% 预留」。
4. 不得编造与定制师无关的内容；不确定就说需要再确认。
5. 必须遵守下方「当前情景约束」，它是导演设定的客观事实，不得偏离。

【当前情景约束】
{state}

【输出 JSON】{{"reply":"...","price":"","availability":"有货|紧张|无货|无档期","note":""}}
只输出 JSON。
"""

STATE_LABELS = {
    "availability": "库存状态",
    "price_factor": "价格系数（1.0 = 常规价）",
    "note": "补充说明",
}


def render_state(state: dict) -> str:
    if not state:
        return "无特殊约束，按常规市场行情回复。"
    lines = []
    for k, label in STATE_LABELS.items():
        v = state.get(k)
        if v in (None, "", 0):
            continue
        lines.append(f"- {label}：{v}")
    return "\n".join(lines) or "无特殊约束，按常规市场行情回复。"

CUSTOMER_SYSTEM = """你是那位客户，正在微信/电话里看定制师发来的方案或报价。

【规则】
1. 用客户口吻回复（2-4 句），可以满意、可以挑刺、可以问细节。
2. 常见反应：说超预算、不喜欢某个景点、想换酒店、问含不含某某费用。
3. 不给专业建议、不出戏。

【输出 JSON】{{"reply":"...","sentiment":"满意|犹豫|不满","asks":["..."]}}
只输出 JSON。
"""


class ToolsService:
    def __init__(self, llm: DeepSeekClient | None = None, store=None) -> None:
        self._llm = llm
        self._store = store
        self._states: dict[str, dict] = {}

    def _require_llm(self) -> DeepSeekClient:
        if self._llm is None:
            raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
        return self._llm

    # ---------- ① 外部客观环境 ----------

    def weather(self, city: str, date: str | None = None) -> dict:
        p = geocode(city)
        if not p:
            return {"city": city, "error": "未能解析城市"}
        if date:
            w = weather(p.lat, p.lng, date=date)
            return {"city": city, "lng": p.lng, "lat": p.lat, "daily": w}
        w = weather(p.lat, p.lng)
        return {"city": city, "lng": p.lng, "lat": p.lat, "current": w}

    def _points(self, names: list[str]) -> tuple[list, list[str]]:
        pts, missing = [], []
        for n in names:
            p = geocode(n)
            if p is None:
                missing.append(n)
            else:
                pts.append(p)
        return pts, missing

    def route(self, origin: str, destination: str, mode: str = "driving",
              waypoints: list[str] | None = None) -> dict:
        """一条真实路线：驾车（可带途经点）/ 步行 / 骑行 / 公交。"""
        names = [origin, *(waypoints or []), destination]
        pts, missing = self._points([n for n in names if n])
        if missing or len(pts) < 2:
            return {"error": f"地址解析失败：{'、'.join(missing) or '起点/终点必填'}",
                    "origin": origin, "destination": destination}
        out = amap_route(pts, mode)
        if out.get("error"):
            return {"error": out["error"], "origin": origin, "destination": destination}
        out.update({"origin": origin, "destination": destination,
                    "waypoints": waypoints or []})
        return out

    def poi_tips(self, keywords: str, city: str = "") -> list[dict]:
        """输入联想：像地图 App 一样边打字边给候选（地点/机场/景区/酒店都能联想）。"""
        return amap_tips(keywords, city)

    def map_image(self, origin: str, destination: str, mode: str = "driving",
                  waypoints: list[str] | None = None, size: str = "900*520") -> bytes:
        """静态地图 PNG（key 只在服务端用；前端只拿图）。"""
        names = [origin, *(waypoints or []), destination]
        pts, missing = self._points([n for n in names if n])
        if missing or len(pts) < 2:
            raise ValueError(f"地址解析失败：{'、'.join(missing) or '起点/终点必填'}")
        poly = ""
        if mode == "driving":
            poly = (amap_route(pts, mode) or {}).get("polyline", "")
        return amap_static_map(pts, poly, size=size)

    def check_itinerary(self, stops: list[str]) -> dict:
        points: list[GeoPoint] = []
        for s in stops:
            p = geocode(s)
            if p:
                points.append(p)
        if len(points) < 2:
            return {"error": "至少需要 2 个可解析的地点", "resolved": [p.name for p in points]}
        rep = check_itinerary(points)
        return {
            "resolved": [p.name for p in points],
            "total_distance_m": rep.total_distance_m,
            "total_duration_s": rep.total_duration_s,
            "legs": [{"from": l.from_name, "to": l.to_name, "distance_m": l.distance_m,
                      "duration_s": l.duration_s} for l in rep.legs],
            "issues": rep.issues, "ok": rep.ok,
        }

    def fx(self, base: str = "CNY", quotes: list[str] | None = None) -> dict:
        """实时汇率。quotes 缺省取常用币种。"""
        want = [q.upper() for q in (quotes or ["USD", "EUR", "JPY", "GBP", "KRW", "THB", "SGD", "HKD"])]
        data = exchange_rates(base)
        rates = data.get("rates", {})
        return {
            "base": data.get("base", base.upper()),
            "updated": data.get("updated", ""),
            "rates": {q: rates.get(q) for q in want if q in rates},
            "error": data.get("error"),
        }

    # ---------- ② 资源方 Agent ----------

    # 情景状态（导演控制）：控制资源方 Agent 的客观约束
    # user_id 必须由调用方（API 层 = 当前登录用户；场景域 = 案例账号）显式传入。
    # 这里不再给 "u-demo" 默认值：要么拿到真实归属，要么明确失败，绝不退化成 demo 账号（R02/R07）。
    def supplier_states(self, user_id: str) -> dict[str, dict]:
        if not user_id:
            raise ValueError("supplier_states 需要明确的 user_id（不接受空归属）")
        if self._store is not None:
            return self._store.supplier_states(user_id)
        return dict(self._states)

    def set_supplier_state(self, kind: str, state: dict, user_id: str) -> dict:
        if not user_id:
            raise ValueError("set_supplier_state 需要明确的 user_id（不接受空归属）")
        if kind not in SUPPLIER_ROLES:
            raise ValueError(f"未知资源方: {kind}")
        clean = {k: v for k, v in state.items() if k in STATE_LABELS and v not in (None, "")}
        if self._store is not None:
            self._store.set_supplier_state(user_id, kind, clean)
        else:
            self._states[kind] = clean
        return clean

    # ---------- ② 资源方 Agent ----------

    def supplier(self, kind: str, request: str, user_id: str) -> dict:
        role = SUPPLIER_ROLES.get(kind)
        if not role:
            raise ValueError(f"未知资源方: {kind}")
        state = self.supplier_states(user_id).get(kind, {})
        data = self._require_llm().chat_json(
            [{"role": "system", "content": SUPPLIER_SYSTEM.format(role=role, state=render_state(state))},
             {"role": "user", "content": f"定制师的询价：{request}"}],
            temperature=0.6, max_tokens=500)
        return {"kind": kind, "request": request,
                "reply": str(data.get("reply", "")),
                "price": str(data.get("price", "")),
                "availability": str(data.get("availability", "")),
                "note": str(data.get("note", ""))}

    # ---------- ③ 交付物投递（客户读取） ----------

    def deliverable_feedback(self, kind: str, content: str, customer: str = "客户", *, order_id: str = "", channel: str = "document") -> dict:
        if order_id and self._store is not None:
            from .customer_context import guarded_reply
            row = self._store.order(order_id)
            if not row:
                raise ValueError(f"未找到订单: {order_id}")
            payload = json.loads(row.get("payload") or "{}")
            if kind in ("出团通知书", "departure_notice") and (
                    payload.get("demo_data") or payload.get("showcase_realistic")):
                stamp = f"{channel}:demo-notice:{int(time.time() * 1000)}"
                reply = "出团通知书我看到了，集合时间和联系人我会再核对一下。"
                # 关键：把客户收到的文档正文写入客户记忆。只记一句「知道」会让
                # 后续追问时客户完全不知道自己收到过什么，只能复述最初需求。
                self._store.add_customer_turn(
                    order_id, channel, "consultant",
                    f"定制师发来的「{kind}」内容：\n{str(content or '')[:6000]}",
                    stamp + ":doc")
                self._store.add_customer_turn(order_id, channel, "customer", reply, stamp)
                return {"kind": kind, "customer": row["customer"], "reply": reply,
                        "sentiment": "满意", "asks": [],
                        "consistency": {"fallback": False, "demo_notice_ack": True}}
            out = guarded_reply(self._store, self._llm, order_id, channel,
                                f"定制师发来的「{kind}」内容：\n{content[:6000]}", reference=content,
                                feedback=True)
            return {"kind": kind, "customer": row["customer"], **out}
        raise ValueError("客户文档反馈需要绑定订单")
