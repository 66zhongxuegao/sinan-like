"""外部数据工具层离线单测（不联网，mock 网络层）。"""

from unittest.mock import patch

from tripcraft.tools import external as ext


def test_geocode_parses_amap_response():
    fake = {"status": "1", "geocodes": [{"location": "116.397463,39.909187", "city": "北京市"}]}
    with patch.object(ext, "_get_json", return_value=fake):
        p = ext.geocode("北京市天安门", env={"AMAP_API_KEY": "x"})
    assert p is not None
    assert round(p.lng, 3) == 116.397
    assert round(p.lat, 3) == 39.909
    assert p.amap_location == "116.397463,39.909187"


def test_geocode_returns_none_on_empty():
    with patch.object(ext, "_get_json", return_value={"status": "1", "geocodes": []}):
        assert ext.geocode("不存在的地方", env={"AMAP_API_KEY": "x"}) is None


def test_driving_parses_route():
    fake = {"status": "1", "route": {"paths": [{"distance": "29471", "duration": "2244"}]}}
    a = ext.GeoPoint("A", 116.397428, 39.90923)
    b = ext.GeoPoint("B", 116.603, 40.079)
    with patch.object(ext, "_get_json", return_value=fake):
        leg = ext.driving(a, b, env={"AMAP_API_KEY": "x"})
    assert leg is not None
    assert leg.distance_m == 29471
    assert leg.duration_s == 2244


def test_weather_parses_current():
    fake = {"current": {"temperature_2m": 21.2, "weather_code": 0}}
    with patch.object(ext, "_get_json", return_value=fake):
        w = ext.weather(39.9, 116.4, env={})
    assert w["temperature_2m"] == 21.2


def test_check_itinerary_flags_backtracking():
    a = ext.GeoPoint("天安门", 116.397, 39.909)
    b = ext.GeoPoint("故宫", 116.398, 39.913)
    leg = ext.RouteLeg("x", "y", 500, 120)
    with patch.object(ext, "driving", return_value=leg):
        rep = ext.check_itinerary([a, b, a])
    assert any("折返" in i for i in rep.issues)
    assert not rep.ok


def test_check_itinerary_ok_and_totals():
    a = ext.GeoPoint("A", 116.39, 39.90)
    b = ext.GeoPoint("B", 116.40, 39.91)
    c = ext.GeoPoint("C", 116.41, 39.92)
    with patch.object(ext, "driving", return_value=ext.RouteLeg("x", "y", 1000, 600)):
        rep = ext.check_itinerary([a, b, c])
    assert rep.ok
    assert rep.total_distance_m == 2000
    assert rep.total_duration_s == 1200


def test_missing_key_raises():
    try:
        ext.geocode("北京", env={})
        raise AssertionError("应报错")
    except RuntimeError:
        pass

def test_supplier_state_persists_and_feeds_prompt():
    import os
    import tempfile
    from uuid import uuid4

    import pytest

    from tripcraft.services.tools_service import ToolsService, render_state
    from tripcraft.storage import Store

    store = Store(os.path.join(tempfile.gettempdir(), f"ts_{uuid4().hex}.sqlite"))
    svc = ToolsService(store=store)
    # tools_service 已升版：user_id 必填，不接受空归属（不再有 "u-demo" 默认值）
    assert svc.supplier_states("u-test") == {}
    svc.set_supplier_state("\u7968\u52a1", {"availability": "\u7d27\u5f20", "price_factor": 1.15, "note": "\u8fd4\u7a0b\u9ad8\u5cf0"},
                           user_id="u-test")
    states = svc.supplier_states("u-test")
    assert states["\u7968\u52a1"]["availability"] == "\u7d27\u5f20"
    assert states["\u7968\u52a1"]["price_factor"] == 1.15
    rendered = render_state(states["\u7968\u52a1"])
    assert "\u7d27\u5f20" in rendered and "1.15" in rendered
    # 另一个用户看不到 u-test 的资源方状态（按归属隔离）
    assert svc.supplier_states("u-other") == {}
    # 空归属必须明确失败，不得退化成 demo 账号
    with pytest.raises(ValueError):
        svc.supplier_states("")


def test_supplier_state_rejects_unknown_kind():
    import pytest
    from tripcraft.services.tools_service import ToolsService

    svc = ToolsService()
    with pytest.raises(ValueError):
        svc.set_supplier_state("\u4e0d\u5b58\u5728", {"availability": "\u6709\u8d27"}, user_id="u-test")
