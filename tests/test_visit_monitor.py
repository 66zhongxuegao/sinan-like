"""公网演示访问监控：IP 解析、过滤、去重、归属地回退（离线，不联网）。"""

import json
import time

import pytest

from tripcraft.services import visit_monitor as vm


# ---------------- IP 解析 ----------------

def test_client_ip_prefers_cloudflare_header():
    headers = {"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "5.6.7.8"}
    assert vm.client_ip(headers, "127.0.0.1") == "1.2.3.4"


def test_client_ip_falls_back_to_forwarded_then_socket():
    assert vm.client_ip({"x-forwarded-for": "5.6.7.8, 10.0.0.1"}, "127.0.0.1") == "5.6.7.8"
    assert vm.client_ip({}, "9.9.9.9") == "9.9.9.9"


def test_testclient_host_is_ignored(tmp_path):
    """测试客户端不是 IP，不能当成一次真实访问写进日志。"""
    mon = make_monitor(tmp_path)
    assert note(mon, ip="testclient") is False


def test_private_ip_detection():
    for ip in ("127.0.0.1", "::1", "10.1.2.3", "192.168.1.7", "172.20.0.3", "172.31.9.9", "", "testclient", "localhost"):
        assert vm.is_private(ip) is True, ip
    for ip in ("172.32.0.1", "220.181.38.150", "36.142.71.207"):
        assert vm.is_private(ip) is False, ip


def test_classify_user_agent():
    assert vm.classify_ua("Mozilla/5.0 Chrome/131 Safari/537.36") == "Chrome"
    assert vm.classify_ua("Mozilla/5.0 Edg/131.0") == "Edge"
    assert vm.classify_ua("Mozilla/5.0 MicroMessenger/8.0") == "微信内置"
    assert vm.classify_ua("curl/8.4.0") == "脚本/爬虫"
    assert vm.classify_ua("") == "未知"


# ---------------- 过滤与去重 ----------------

def make_monitor(tmp_path, stub_geo: bool = True) -> vm.VisitMonitor:
    mon = vm.VisitMonitor(log_dir=tmp_path, dedup_window_s=1800.0)
    if stub_geo:  # 归属地联网查询在单测里一律替换掉
        mon._resolve_geo = lambda ip, cf_country="": {
            "source": "stub", "country": "中国", "region": "上海市", "city": "", "isp": "China Telecom",
        }
    return mon


def note(mon, *, ip="220.181.38.150", path="/", accept="text/html", ua="Mozilla/5.0 Chrome/131"):
    return mon.note(headers={"cf-connecting-ip": ip, "accept": accept, "user-agent": ua}, client_host="127.0.0.1", path=path)


def test_records_page_visit_and_writes_logs(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon) is True
    mon.flush()
    records = [json.loads(x) for x in (tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["ip"] == "220.181.38.150"
    assert records[0]["geo"]["region"] == "上海市"
    assert records[0]["new_ip"] is True
    assert "新访客" in (tmp_path / "visits.log").read_text(encoding="utf-8")


def test_health_check_without_html_accept_still_counts(tmp_path):
    """前端启动时先请求 /（accept: */*），这也要算一次访问。"""
    mon = make_monitor(tmp_path)
    assert note(mon, accept="*/*") is True


def test_skips_static_assets_and_unrelated_paths(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon, path="/assets/index-abc123.js", accept="*/*") is False
    assert note(mon, path="/favicon.ico", accept="*/*") is False
    assert note(mon, path="/__vite_ping", accept="*/*") is False


def test_api_session_path_counts(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon, path="/profiles/u-demo/intake", accept="*/*") is True


def test_dedup_within_window_but_new_ip_always_recorded(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon) is True
    assert note(mon) is False, "同一 IP + 浏览器 30 分钟内只记一条"
    assert note(mon, ip="36.142.71.207") is True
    mon.flush()
    lines = (tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_different_browser_same_ip_is_separate(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon, ua="Mozilla/5.0 Chrome/131") is True
    assert note(mon, ua="Mozilla/5.0 Edg/131") is True


def test_local_ip_ignored_by_default(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon, ip="127.0.0.1") is False


def test_history_is_reloaded_so_restart_does_not_repeat(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon) is True
    mon.flush()
    again = vm.VisitMonitor(log_dir=tmp_path, dedup_window_s=1800.0)
    again._resolve_geo = lambda ip, cf="": {"source": "stub"}
    assert note(again) is False, "重启后仍要认得老访客"


# ---------------- 归属地回退 ----------------

def test_geo_uses_amap_first(monkeypatch, tmp_path):
    mon = make_monitor(tmp_path, stub_geo=False)
    mon._amap_key = "k"
    monkeypatch.setattr(vm, "_get_json", lambda url, timeout=0: {"status": "1", "province": "上海市", "city": "上海市"})
    geo = mon._resolve_geo("220.181.38.150")
    assert geo["source"] == "amap" and geo["region"] == "上海市" and geo["city"] == ""


def test_geo_falls_back_to_vore_then_cf_country(monkeypatch, tmp_path):
    mon = make_monitor(tmp_path, stub_geo=False)
    mon._amap_key = ""
    calls = []

    def fake(url, timeout=0):
        calls.append(url)
        if "vore.top" in url:
            raise OSError("blocked")
        if "ip-api.com" in url:
            return {"status": "fail"}
        raise AssertionError(url)

    monkeypatch.setattr(vm, "_get_json", fake)
    geo = mon._resolve_geo("8.8.8.8", cf_country="US")
    assert geo["country"] == "美国" and geo["source"] == "cf"
    assert any("vore.top" in c for c in calls) and any("ip-api.com" in c for c in calls)


def test_geo_uses_ip_api_isp_when_available(monkeypatch, tmp_path):
    mon = make_monitor(tmp_path, stub_geo=False)
    mon._amap_key = ""
    monkeypatch.setattr(
        vm, "_get_json",
        lambda url, timeout=0: {"status": "success", "country": "中国", "regionName": "广东", "city": "广州", "isp": "China Mobile"},
    )
    geo = mon._resolve_geo("36.142.71.207")
    assert geo["city"] == "广州" and geo["isp"] == "China Mobile"
# ---------------- 行为判定（真人操作 vs 扫描器） ----------------

def test_is_interactive_classification():
    assert vm.is_interactive("/", "GET") is False
    assert vm.is_interactive("/profiles/u-demo/intake", "GET") is False
    assert vm.is_interactive("/contracts/steps", "GET") is False
    assert vm.is_interactive("/messages", "GET") is True
    assert vm.is_interactive("/practice/orders/9001/flow", "GET") is True
    assert vm.is_interactive("/orders", "POST") is True
    assert vm.is_interactive("/", "POST") is True


def test_page_of_groups_routes():
    assert vm.page_of("/") == "首页"
    assert vm.page_of("/profiles/u-demo/trend") == "画像"
    assert vm.page_of("/practice/orders/1") == "订单"
    assert vm.page_of("/learn/map") == "学习地图"
    assert vm.page_of("/zzz") == "其他"


def test_net_tag_and_place_of():
    assert vm.net_tag({"hosting": True}) == "机房"
    assert vm.net_tag({"proxy": True}) == "代理"
    assert vm.net_tag({"hosting": False, "proxy": False}) == ""
    place = vm.place_of({"geo": {"country": "新加坡", "city": "新加坡", "isp": "GOIP Telecom", "hosting": True}})
    assert place.startswith("新加坡") and "GOIP Telecom" in place


def test_behavior_of():
    assert vm.behavior_of({"routes": ["首页"], "actions": 0}) == "1页"
    assert vm.behavior_of({"routes": ["首页", "订单"], "actions": 3}) == "2页·操作3次"


def test_first_real_action_writes_second_record(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon, path="/", accept="*/*") is True            # 打开：第一条
    assert note(mon, path="/", accept="*/*") is False           # 同一次打开，不重复记
    assert note(mon, path="/messages", accept="*/*") is True     # 首次真实操作：补一条
    assert note(mon, path="/practice/orders/1/flow", accept="*/*") is False
    mon.flush()
    recs = [json.loads(x) for x in (tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in recs] == ["open", "interact"]
    assert recs[0]["session"] == recs[1]["session"]
    assert recs[1]["actions"] == 1 and recs[1]["renders"] == 2
    merged = vm.merge_sessions(recs)
    assert len(merged) == 1 and merged[0]["actions"] == 1
    assert "有操作" in (tmp_path / "visits.log").read_text(encoding="utf-8")


def test_merge_sessions_keeps_latest_state():
    recs = [
        {"session": "s1", "ip": "1.1.1.1", "ts": 100, "kind": "open", "actions": 0,
         "renders": 1, "routes": ["首页"], "new_ip": True},
        {"session": "s1", "ip": "1.1.1.1", "ts": 130, "kind": "interact", "actions": 2,
         "renders": 3, "routes": ["首页", "订单"]},
    ]
    merged = vm.merge_sessions(recs)
    assert len(merged) == 1
    assert merged[0]["actions"] == 2 and merged[0]["kind"] == "interact"
    assert merged[0]["routes"] == ["首页", "订单"]
    assert merged[0]["first_seen"] == 100 and merged[0]["last_seen"] == 130
    assert merged[0]["new_ip"] is True


def test_geo_records_hosting_and_proxy_flags(monkeypatch, tmp_path):
    """机房 / 代理标记必须落到记录里——中国云主机也要标，否则会冒充"上海的真人"。"""
    mon = make_monitor(tmp_path, stub_geo=False)
    mon._amap_key = ""

    def fake(url, timeout=0):
        if "ip-api.com" in url:
            return {"status": "success", "country": "新加坡", "regionName": "Central Singapore",
                    "city": "新加坡", "isp": "GOIP Telecom", "as": "AS141389 GOIP Telecom",
                    "hosting": True, "proxy": False}
        raise OSError("skip")

    monkeypatch.setattr(vm, "_get_json", fake)
    geo = mon._resolve_geo("103.158.14.145", "SG")
    assert geo["flags"] is True and geo["hosting"] is True and geo["proxy"] is False
    assert geo["asn"].startswith("AS141389")
    assert vm.net_tag(geo) == "机房"
def test_duration_text():
    assert vm.duration_text(0, 3) == ""
    assert vm.duration_text(0, 45) == "45秒"
    assert vm.duration_text(0, 600) == "10分"
    assert vm.duration_text(0, 4000) == "1小时6分"


def test_behavior_of_includes_duration():
    rec = {"routes": ["首页"], "actions": 0, "first_seen": 0, "last_seen": 45}
    assert vm.behavior_of(rec) == "1页·45秒"


def test_websocket_counts_as_action(tmp_path):
    """语音通话走 WebSocket，http 中间件看不到，必须单独记一次。"""
    mon = make_monitor(tmp_path)
    scope = {
        "type": "websocket",
        "path": "/voice/realtime",
        "headers": [(b"cf-connecting-ip", b"220.181.38.150"), (b"user-agent", b"Mozilla/5.0 Chrome/131")],
        "client": ("127.0.0.1", 5353),
    }
    assert mon.note_from_scope(scope) is True
    mon.flush()
    rec = json.loads((tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["path"] == "/voice/realtime"
    assert rec["routes"] == ["语音通话"]
    assert rec["actions"] == 1


def test_flush_updates_writes_progress_record(tmp_path):
    """长时间停留要补写进度，否则记录只停在打开瞬间。"""
    mon = make_monitor(tmp_path)
    assert note(mon, path="/", accept="*/*") is True
    assert note(mon, path="/profiles/u-demo/trend", accept="*/*") is False
    assert note(mon, path="/profiles/u-demo/intake", accept="*/*") is False
    mon.flush()  # 先等 open 落盘，再补写 update（产品里两者都在同一个写线程里，天然有序）
    assert mon.flush_updates(now=time.time() + 120, force=True) == 1
    recs = [json.loads(x) for x in (tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in recs] == ["open", "update"]
    assert recs[-1]["requests"] == 3
    assert recs[-1]["routes"] == ["画像", "首页"]
    merged = vm.merge_sessions(recs)
    assert len(merged) == 1 and vm.behavior_of(merged[0]).startswith("2页")


def test_idle_session_is_recycled(tmp_path):
    mon = make_monitor(tmp_path)
    assert note(mon) is True
    with mon._lock:
        for sess in mon._sessions.values():
            sess["last_seen"] -= vm.DEDUP_WINDOW_S * 2
    assert note(mon, path="/profiles/u-demo/intake", accept="*/*") is True
    mon.flush()
    recs = [json.loads(x) for x in (tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len({r["session"] for r in recs}) == 2, "闲置超过窗口要算新会话"

# ---------------- 已知访客名单（自己人不再当外人） ----------------

def test_known_ip_is_labelled(tmp_path):
    mon = make_monitor(tmp_path)
    (tmp_path / "known_visitors.json").write_text('{"220.181.38.150": "本机代理"}', encoding="utf-8")
    assert note(mon) is True
    mon.flush()
    rec = json.loads((tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec.get("known") == "本机代理"


def test_unknown_ip_has_no_label(tmp_path):
    mon = make_monitor(tmp_path)
    (tmp_path / "known_visitors.json").write_text('{"1.1.1.1": "本机代理"}', encoding="utf-8")
    assert note(mon) is True
    mon.flush()
    rec = json.loads((tmp_path / "visits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "known" not in rec


def test_known_list_reloads_after_edit(tmp_path):
    mon = make_monitor(tmp_path)
    assert mon.known_label("220.181.38.150") == ""
    (tmp_path / "known_visitors.json").write_text('{"220.181.38.150": "队友"}', encoding="utf-8")
    assert mon.known_label("220.181.38.150") == "队友"
