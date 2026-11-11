"""外部数据工具层（M2 地基）—— 地图路线 + 天气 + 方案可行性核验。

数据源：
- 地图路线：高德 Web 服务 API（AMAP_API_KEY）
- 天气：Open-Meteo（无需 key）

设计原则（PRD 第 23 章、DECISIONS D-012）：
- 学员查询与系统核验走同一套接口；
- 核验结果是**确定性**的（距离/耗时/折返），不是模型判断；
- 未来真实供应商接口按同一层接入（MCP 化）。

密钥只从 local.env 读取，不落库、不打印。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> dict[str, str]:
    """先读环境变量，再回退项目根 local.env（与 docs/DECISIONS.md D-024 口径一致）。

    注意：环境变量必须**覆盖** local.env。此前本函数只读 local.env，导致按文档
    「把 AMAP_API_KEY 设成环境变量」的部署方式失效，route() 会误报「缺少 AMAP_API_KEY」。
    """
    env: dict[str, str] = {}
    p = ROOT / "local.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # 环境变量优先（只收常见的大写下划线形式，避免把无关变量灌进来）
    for k, v in os.environ.items():
        if not v:
            continue
        if k and k.upper() == k and k.replace("_", "").isalnum():
            env[k] = v
    return env


def _get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TripCraft/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


@dataclass(frozen=True)
class GeoPoint:
    name: str
    lng: float
    lat: float
    city: str = ""

    @property
    def amap_location(self) -> str:
        return f"{self.lng},{self.lat}"


@dataclass
class RouteLeg:
    from_name: str
    to_name: str
    distance_m: int
    duration_s: int


@dataclass
class FeasibilityReport:
    total_distance_m: int = 0
    total_duration_s: int = 0
    legs: list[RouteLeg] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


# ---------------------------------------------------------------- 汇率

FX_BASE = "https://open.er-api.com/v6/latest"


def exchange_rates(base: str = "CNY") -> dict:
    """实时汇率（open.er-api.com，无需 key）。返回 {base, updated, rates{}}。"""
    data = _get_json(f"{FX_BASE}/{base.upper()}")
    if data.get("result") != "success":
        return {"base": base.upper(), "error": data.get("error-type", "查询失败"), "rates": {}}
    return {
        "base": data.get("base_code", base.upper()),
        "updated": data.get("time_last_update_utc", ""),
        "rates": data.get("rates", {}),
    }


# ---------------------------------------------------------------- 高德

_GEO_CACHE: dict[str, "GeoPoint"] = {}


def poi_tips(keywords: str, city: str = "", env: dict[str, str] | None = None) -> list[dict]:
    """输入联想（高德「输入提示」）：像地图 App 那样边打字边给候选。

    返回 [{name, district, address, location}]，location 为空的是行政区/分类提示。
    """
    env = load_env() if env is None else env
    key = env.get("AMAP_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 AMAP_API_KEY（请写入 local.env）")
    kw = (keywords or "").strip()
    if len(kw) < 1:
        return []
    params = {"keywords": kw, "key": key, "datatype": "all"}
    if city:
        params["city"] = city
    d = _get_json("https://restapi.amap.com/v3/assistant/inputtips?" +
                  urllib.parse.urlencode(params))
    if d.get("status") != "1":
        return []
    out = []
    for t in (d.get("tips") or [])[:10]:
        city_raw = t.get("city")
        if isinstance(city_raw, list):
            city_raw = city_raw[0] if city_raw else ""
        out.append({"name": str(t.get("name") or ""),
                    "district": str(t.get("district") or ""),
                    "address": str(t.get("address") or ""),
                    "location": str(t.get("location") or ""),
                    "city": str(city_raw or "").replace("市", "")})
    return [t for t in out if t["name"]]


def geocode(address: str, env: dict[str, str] | None = None) -> GeoPoint | None:
    """地址 -> 经纬度（高德地理编码）。同一进程内做过缓存，避免反复查同一个地名把配额打满。"""
    key_cache = (address or "").strip()
    if key_cache in _GEO_CACHE:
        return _GEO_CACHE[key_cache]
    env = load_env() if env is None else env
    key = env.get("AMAP_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 AMAP_API_KEY（请写入 local.env）")
    url = "https://restapi.amap.com/v3/geocode/geo?" + urllib.parse.urlencode(
        {"address": address, "key": key})
    d = _get_json(url)
    if d.get("status") != "1" or not d.get("geocodes"):
        return None
    g = d["geocodes"][0]
    lng, lat = (float(x) for x in g["location"].split(","))
    point = GeoPoint(name=address, lng=lng, lat=lat,
                     city=str(g.get("city") or g.get("province") or "").replace("市", ""))
    _GEO_CACHE[key_cache] = point
    return point


def driving(origin: GeoPoint, dest: GeoPoint, env: dict[str, str] | None = None) -> RouteLeg | None:
    """驾车路线（高德）。"""
    env = load_env() if env is None else env
    key = env.get("AMAP_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 AMAP_API_KEY（请写入 local.env）")
    url = "https://restapi.amap.com/v3/direction/driving?" + urllib.parse.urlencode(
        {"origin": origin.amap_location, "destination": dest.amap_location, "key": key})
    d = _get_json(url)
    paths = (d.get("route") or {}).get("paths") or []
    if d.get("status") != "1" or not paths:
        return None
    p = paths[0]
    return RouteLeg(origin.name, dest.name, int(p["distance"]), int(p["duration"]))


# ---------------------------------------------------------------- 路线（多出行方式 + 途经点）

_ROUTE_API = {
    "driving": ("v3", "direction/driving"),
    "walking": ("v3", "direction/walking"),
    "bicycling": ("v4", "direction/bicycling"),
}


def _hhmm(raw) -> str:
    """高德运营时间给的是 0600 / 2247 这种，转成 06:00 / 22:47。"""
    t = str(raw or "").strip()
    return f"{t[:2]}:{t[2:4]}" if len(t) == 4 and t.isdigit() else t


def _transit_steps(transit: dict) -> list[dict]:
    """把高德一套公共交通方案解析成换乘步骤（步行 / 公交 / 地铁 / 铁路）。"""
    steps: list[dict] = []
    for seg in transit.get("segments") or []:
        w = seg.get("walking") or {}
        if str(w.get("distance") or "0") not in ("0", ""):
            steps.append({"type": "walk", "distance_m": int(float(w["distance"])),
                          "duration_s": int(float(w.get("duration") or 0)),
                          "label": f"步行 {int(float(w['distance']))} 米"})
        for bl in (seg.get("bus") or {}).get("buslines") or []:
            btype = str(bl.get("type") or "")
            kind = "地铁" if "地铁" in btype else ("公交" if "公交" in btype else (btype or "公交"))
            via = int(float(bl.get("via_num") or 0))
            steps.append({
                "type": "transit", "kind": kind, "line": str(bl.get("name") or ""),
                "from_stop": str((bl.get("departure_stop") or {}).get("name") or ""),
                "to_stop": str((bl.get("arrival_stop") or {}).get("name") or ""),
                "via": via, "start_time": _hhmm(bl.get("start_time")),
                "end_time": _hhmm(bl.get("end_time")),
                "distance_m": int(float(bl.get("distance") or 0)),
                "duration_s": int(float(bl.get("duration") or 0)),
                "label": f"{kind} {bl.get('name') or ''}（{via} 站）"})
        rw = seg.get("railway") or {}
        if rw.get("name"):
            steps.append({"type": "railway", "kind": "铁路", "line": str(rw.get("name")),
                          "from_stop": str((rw.get("departure_stop") or {}).get("name") or ""),
                          "to_stop": str((rw.get("arrival_stop") or {}).get("name") or ""),
                          "start_time": str(rw.get("start_time") or ""),
                          "end_time": str(rw.get("end_time") or ""),
                          "label": f"铁路 {rw.get('name')}"})
    return steps


def _transit_alt(transit: dict, index: int) -> dict:
    """一套方案的概览：坐哪几种、换乘几次、多久、多少钱、走多少路。"""
    steps = _transit_steps(transit)
    rides = [x for x in steps if x["type"] in ("transit", "railway")]
    kinds: list[str] = []
    for r in rides:
        if not kinds or kinds[-1] != r["kind"]:
            kinds.append(r["kind"])
    return {"index": index + 1, "label": f"方案 {index + 1}",
            "kinds": kinds, "transfer": max(0, len(rides) - 1),
            "summary": "+".join(kinds) if kinds else "全程步行",
            "distance_m": int(float(transit.get("distance") or 0)),
            "duration_s": int(float(transit.get("duration") or 0)),
            "cost": str(transit.get("cost") or ""),
            "walking_m": int(float(transit.get("walking_distance") or 0)),
            "steps": steps}


def _polyline(route: dict) -> str:
    """把高德返回的步骤折线拼成一条（静态地图画线用）。"""
    parts = []
    for step in route.get("steps") or []:
        pl = step.get("polyline") or ""
        if pl:
            parts.append(pl)
    return ";".join(parts)


def route_points(points: list[GeoPoint], mode: str = "driving",
                 env: dict[str, str] | None = None) -> dict:
    """规划路线：驾车（支持途经点）/ 步行 / 骑行 / 公交。

    高德只有驾车接口支持 waypoints，其余方式按分段调用再累加；
    返回值里带 legs（每段距离/耗时）与 polyline（静态地图画线用）。
    """
    env = load_env() if env is None else env
    key = env.get("AMAP_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 AMAP_API_KEY（请写入 local.env）")
    if len(points) < 2:
        return {"error": "至少需要起点和终点"}
    mode = mode if mode in ("driving", "walking", "bicycling", "transit") else "driving"
    legs: list[dict] = []
    polyline = ""
    note = ""

    if mode == "driving":
        params = {"origin": points[0].amap_location, "destination": points[-1].amap_location,
                  "strategy": "0", "extensions": "base", "key": key}
        if len(points) > 2:
            params["waypoints"] = ";".join(p.amap_location for p in points[1:-1])
        d = _get_json("https://restapi.amap.com/v3/direction/driving?" +
                      urllib.parse.urlencode(params))
        paths = (d.get("route") or {}).get("paths") or []
        if d.get("status") != "1" or not paths:
            return {"error": d.get("info") or "驾车路线规划失败"}
        p0 = paths[0]
        legs = [RouteLeg(f"途经段 {i+1}", f"途经段 {i+2}",
                         int(p0["distance"]) if i == 0 else 0, int(p0["duration"]) if i == 0 else 0)
                for i in range(len(points) - 1)][:1] or []
        legs = [{"from": points[0].name, "to": points[-1].name,
                 "distance_m": int(p0["distance"]), "duration_s": int(p0["duration"])}]
        polyline = _polyline(p0)
        note = f"途经 {len(points) - 2} 个点" if len(points) > 2 else ""
        total_d = int(p0["distance"])
        total_t = int(p0["duration"])
    elif mode == "transit":
        # 公共交通一体化：公交 + 地铁（+ 城际铁路），逐段展开换乘明细
        city = points[0].city or points[-1].city or "全国"
        params = {"origin": points[0].amap_location, "destination": points[-1].amap_location,
                  "city": city, "cityd": points[-1].city or city, "extensions": "all", "key": key}
        d = _get_json("https://restapi.amap.com/v3/direction/transit/integrated?" +
                      urllib.parse.urlencode(params))
        transits = (d.get("route") or {}).get("transits") or []
        if d.get("status") != "1" or not transits:
            return {"error": d.get("info") or "公交路线规划失败（跨城可能查不到）"}
        # 高德一次通常给多套方案（最多 5 套）：全部带上，前端切换着看
        alts = [_transit_alt(t, i) for i, t in enumerate(transits[:5])]
        best = alts[0]
        total_d, total_t = best["distance_m"], best["duration_s"]
        legs = [{"from": points[0].name, "to": points[-1].name,
                 "distance_m": total_d, "duration_s": total_t}]
        extra = {"steps": best["steps"], "cost": best["cost"], "walking_m": best["walking_m"],
                 "alternatives": alts, "summary": f"共 {len(alts)} 套方案"}
        rides = [x for x in best["steps"] if x["type"] in ("transit", "railway")]
        note = (f"{best['summary']}，换乘 {best['transfer']} 次，步行 {best['walking_m']} 米"
                if rides else f"全程步行约 {best['walking_m']} 米")
    else:
        total_d, total_t = 0, 0
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            ver, path = _ROUTE_API[mode]
            d = _get_json(f"https://restapi.amap.com/{ver}/{path}?" + urllib.parse.urlencode(
                {"origin": a.amap_location, "destination": b.amap_location, "key": key}))
            if ver == "v4":
                paths = ((d.get("data") or {}).get("paths")) or []
                ok = d.get("errcode") == 0 and paths
                seg = paths[0] if ok else {}
            else:
                paths = (d.get("route") or {}).get("paths") or []
                ok = d.get("status") == "1" and paths
                seg = paths[0] if ok else {}
            if not ok:
                return {"error": d.get("info") or f"{mode} 路线规划失败"}
            dist = int(float(seg.get("distance") or 0))
            dur = int(float(seg.get("duration") or 0))
            total_d += dist
            total_t += dur
            legs.append({"from": a.name, "to": b.name, "distance_m": dist, "duration_s": dur})
            pl = _polyline(seg)
            if pl:
                polyline = (polyline + ";" + pl) if polyline else pl

    return {"mode": mode, "distance_m": total_d, "duration_s": total_t, "legs": legs,
            "polyline": polyline, "note": note, "extra": extra if mode == "transit" else {},
            "points": [p.name for p in points]}


def static_map(points: list[GeoPoint], polyline: str = "", size: str = "1000*560",
               env: dict[str, str] | None = None) -> bytes:
    """高德静态地图（PNG）：起终点与途经点打点，有折线就画线。key 只在服务端用。"""
    env = load_env() if env is None else env
    key = env.get("AMAP_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 AMAP_API_KEY（请写入 local.env）")
    labels = "ABCDEFGHIJKLMNOP"
    markers = "|".join(
        f"mid,0x2577e3,{labels[i % len(labels)]}:{p.amap_location}" for i, p in enumerate(points[:10]))
    # 静态地图必须给 center + zoom（不会自动适配），按所有点的外接框算一个够用的级别
    lngs = [p.lng for p in points] or [116.397]
    lats = [p.lat for p in points] or [39.909]
    span = max(max(lngs) - min(lngs), max(lats) - min(lats))
    zoom = next((z for limit, z in ((8, 5), (4, 6), (2, 7), (1, 8), (0.5, 9), (0.2, 10),
                                    (0.1, 11), (0.05, 12), (0.02, 13)) if span > limit), 14)
    center = f"{(min(lngs) + max(lngs)) / 2:.6f},{(min(lats) + max(lats)) / 2:.6f}"
    params = {"size": size, "scale": "1", "center": center, "zoom": str(zoom),
              "markers": markers, "key": key}
    if polyline:
        pts = polyline.split(";")
        step = max(1, len(pts) // 300)                 # 只取 300 个点，避免 URL 过长
        params["paths"] = "6,0x2577e3,0.9,,:" + ";".join(pts[::step])
    elif len(points) > 1:
        params["paths"] = "6,0x2577e3,0.9,,:" + ";".join(p.amap_location for p in points)
    url = "https://restapi.amap.com/v3/staticmap?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "TripCraft/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# ---------------------------------------------------------------- Open-Meteo

def weather(lat: float, lng: float, date: str | None = None, env: dict[str, str] | None = None) -> dict | None:
    """天气（Open-Meteo，无需 key）。给 date 则取当日预报，否则取当前。"""
    env = load_env() if env is None else env
    base = env.get("OPEN_METEO_BASE", "https://api.open-meteo.com").rstrip("/")
    if date:
        url = base + "/v1/forecast?" + urllib.parse.urlencode(
            {"latitude": lat, "longitude": lng,
             "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
             "start_date": date, "end_date": date, "timezone": "Asia/Shanghai"})
        d = _get_json(url)
        daily = d.get("daily", {})
        return {"date": date,
                "temp_max": daily.get("temperature_2m_max", [None])[0],
                "temp_min": daily.get("temperature_2m_min", [None])[0],
                "precipitation": daily.get("precipitation_sum", [None])[0]}
    url = base + "/v1/forecast?" + urllib.parse.urlencode(
        {"latitude": lat, "longitude": lng,
         "current": "temperature_2m,precipitation,weather_code",
         "timezone": "Asia/Shanghai"})
    d = _get_json(url)
    return d.get("current")


# ---------------------------------------------------------------- 方案可行性核验

def check_itinerary(stops: list[GeoPoint], env: dict[str, str] | None = None) -> FeasibilityReport:
    """核验行程点顺序的可行性（确定性）。

    检查：
    1. 折返：某个点被重复访问（A -> B -> A）；
    2. 累计驾车耗时（用于判断行程是否过满）。
    """
    report = FeasibilityReport()
    if len(stops) < 2:
        report.issues.append("行程点少于 2 个，无法核验")
        return report

    # 折返检测：名称重复
    seen: set[str] = set()
    for s in stops:
        if s.name in seen:
            report.issues.append(f"疑似折返：{s.name} 被重复访问")
        seen.add(s.name)

    for a, b in zip(stops, stops[1:]):
        leg = driving(a, b, env)
        if leg is None:
            report.issues.append(f"无法规划路线：{a.name} -> {b.name}")
            continue
        report.legs.append(leg)
        report.total_distance_m += leg.distance_m
        report.total_duration_s += leg.duration_s

    if report.total_duration_s > 6 * 3600:
        report.issues.append(f"累计驾车耗时过长（{report.total_duration_s // 3600} 小时），行程可能过满")
    return report