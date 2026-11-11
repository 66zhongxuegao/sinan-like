"""路线工具：多出行方式 + 途经点 + 静态地图（不联网，假装高德返回）。"""

from tripcraft.tools import external as ex


def fake_json(url: str):
    ex.LAST_URL = url
    if "/v3/direction/driving" in url:
        return {"status": "1", "route": {"paths": [{"distance": "12000", "duration": "1800",
                "steps": [{"polyline": "120.1,30.1;120.2,30.2"}]}]}}
    if "/v3/direction/walking" in url:
        return {"status": "1", "route": {"paths": [{"distance": "8000", "duration": "6000",
                "steps": [{"polyline": "120.1,30.1;120.2,30.2"}]}]}}
    if "/v4/direction/bicycling" in url:
        return {"errcode": 0, "data": {"paths": [{"distance": "9000", "duration": "2400",
                "steps": [{"polyline": "120.1,30.1;120.2,30.2"}]}]}}
    if "/v3/direction/transit" in url:
        return {"status": "1", "route": {"transits": [{"distance": "11000", "duration": "2700",
                "segments": [{"walking_distance": "800"}]}]}}
    return {"status": "1", "geocodes": [{"location": "120.1,30.1", "city": "杭州市"}]}


def pts(n=2):
    return [ex.GeoPoint(f"P{i}", 120.1 + i * 0.01, 30.1, "杭州") for i in range(n)]


def test_driving_supports_waypoints(monkeypatch):
    monkeypatch.setattr(ex, "_get_json", fake_json)
    out = ex.route_points(pts(3), "driving")
    assert "waypoints=" in ex.LAST_URL and out["distance_m"] == 12000
    assert out["note"].startswith("途经 1")
    assert out["polyline"]


def test_walking_and_bicycling_and_transit(monkeypatch):
    monkeypatch.setattr(ex, "_get_json", fake_json)
    walk = ex.route_points(pts(2), "walking")
    assert walk["mode"] == "walking" and walk["duration_s"] == 6000
    bike = ex.route_points(pts(2), "bicycling")
    assert bike["distance_m"] == 9000
    ex.LAST_URL = ""
    bus = ex.route_points(pts(2), "transit")
    assert bus["distance_m"] == 11000 and "city=" in ex.LAST_URL


def test_multileg_sums_distance(monkeypatch):
    monkeypatch.setattr(ex, "_get_json", fake_json)
    out = ex.route_points(pts(3), "walking")     # 步行不支持途经点 → 分两段累加
    assert out["distance_m"] == 16000 and len(out["legs"]) == 2


TRANSIT = {"status": "1", "route": {"transits": [{
    "distance": "35894", "duration": "5113", "cost": "7.0", "walking_distance": "2401",
    "segments": [
        # 真实结构：一段 = 步行 + 上一条线路
        {"walking": {"distance": "1335", "duration": "1259"},
         "bus": {"buslines": [{"name": "地铁3号线(吴山前村--星桥)", "type": "地铁线路",
                               "via_num": "2", "start_time": "0600", "end_time": "2247",
                               "distance": "3393", "duration": "600",
                               "departure_stop": {"name": "黄龙洞"},
                               "arrival_stop": {"name": "西湖文化广场"}}]}},
        {"walking": {"distance": "275", "duration": "415"},
         "bus": {"buslines": [{"name": "地铁19号线(火车西站--永盛路)", "type": "地铁线路",
                               "via_num": "6", "start_time": "0604", "end_time": "2315",
                               "distance": "30100", "duration": "1980",
                               "departure_stop": {"name": "西湖文化广场"},
                               "arrival_stop": {"name": "萧山国际机场"}}]}},
        {"walking": {"distance": "791", "duration": "859"}}]},
    {"distance": "36900", "duration": "5400", "cost": "8.0", "walking_distance": "3247",
     "segments": [
        {"walking": {"distance": "3247", "duration": "3200"},
         "bus": {"buslines": [{"name": "地铁19号线(火车西站--永盛路)", "type": "地铁线路",
                               "via_num": "9", "start_time": "0604", "end_time": "2315",
                               "distance": "33653", "duration": "2200",
                               "departure_stop": {"name": "黄龙洞"},
                               "arrival_stop": {"name": "萧山国际机场"}}]}}]}]}}


def test_transit_has_transfer_detail(monkeypatch):
    """公共交通要能说清：坐什么、哪站上哪站下、几站、运营时间、票价。"""
    monkeypatch.setattr(ex, "_get_json", lambda url: TRANSIT if "transit" in url else {})
    out = ex.route_points(pts(2), "transit")
    steps = out["extra"]["steps"]
    assert [s["type"] for s in steps] == ["walk", "transit", "walk", "transit", "walk"]
    ride = steps[1]
    assert ride["kind"] == "地铁" and ride["via"] == 2
    assert ride["from_stop"] == "黄龙洞" and ride["to_stop"] == "西湖文化广场"
    assert ride["start_time"] == "06:00" and ride["end_time"] == "22:47"
    assert out["extra"]["cost"] == "7.0" and out["extra"]["walking_m"] == 2401
    assert "换乘 1 次" in out["note"] and "步行 2401 米" in out["note"]
    # 高德一次给多套方案：全部带上，概览要能直接比较
    assert len(out["extra"]["alternatives"]) == 2
    a1, a2 = out["extra"]["alternatives"]
    assert (a1["label"], a2["label"]) == ("方案 1", "方案 2")
    assert a1["cost"] == "7.0" and a2["cost"] == "8.0"
    assert a2["walking_m"] == 3247 and len(a2["steps"]) == 2


def test_poi_tips(monkeypatch):
    tips = {"status": "1", "tips": [
        {"name": "杭州萧山国际机场", "district": "浙江省杭州市萧山区", "location": "120.4,30.2",
         "city": ["杭州市"]},
        {"name": "", "district": "", "location": ""}]}
    monkeypatch.setattr(ex, "_get_json", lambda url: tips)
    out = ex.poi_tips("萧山", "杭州")
    assert out and out[0]["name"] == "杭州萧山国际机场"
    assert out[0]["city"] == "杭州"          # 列表形式的 city 要归一化成字符串
    assert all(t["name"] for t in out)      # 没有名字的提示要过滤掉


def test_unknown_mode_falls_back_to_driving(monkeypatch):
    monkeypatch.setattr(ex, "_get_json", fake_json)
    out = ex.route_points(pts(2), "rocket")
    assert out["mode"] == "driving"
