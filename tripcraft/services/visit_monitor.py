"""访问监控：记录公网演示地址（trycloudflare 隧道）的访客、行为与时间。

用途：把公网演示链接交给评委后，确认「谁、什么时候、从哪个地区、来的人做了什么」。

数据落在 logs/visits.jsonl（机读，一行一条）与 logs/visits.log（人读）；
IP 归属地结果缓存在 logs/visit_geo_cache.json，同一个 IP 只查一次。

判定说明
- renders：页面渲染类请求，打开页面就必然发生（`/`、`/profiles/*`、`/contracts/*`）。
- actions：需要点击或提交才会发生的请求（非 GET，或 GET 到消息中心 / 订单 / 工具台等），
  也包括 WebSocket（发起语音通话），这是「真人真的用了」的证据。
- hosting / proxy：ip-api 的机房、代理标记。中国云主机同样会被标成机房，
  这样才不至于把一台上海阿里云上的扫描器误认成「上海的真人」。
- 一个访问会话（同 IP + 同浏览器）会写多条记录：首次打开写 `open`，
  第一次真实操作写 `interact`，之后每 45 秒补一条 `update`，
  会话结束（闲置超过 30 分钟）时再补一条收尾。显示时按 `session` 合并，取最新状态。
  只写 open + interact 会严重低估停留时间与操作次数，所以必须定期更新。

设计要点
- 归属地与机房标记的查询全部放在后台守护线程里，不占用请求时间；
- 静态资源不记；本机与内网地址默认不记录，需要时设 VISIT_LOG_LOCAL=1。
"""

from __future__ import annotations

import ipaddress
import json
import os
import queue
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def default_log_dir() -> Path:
    """日志目录：默认项目根 logs/，测试可用 TRIPCRAFT_VISIT_LOG_DIR 改写。"""
    env = os.environ.get("TRIPCRAFT_VISIT_LOG_DIR", "").strip()
    return Path(env) if env else (ROOT / "logs")


DEDUP_WINDOW_S = 30 * 60.0      # 闲置超过这么久就视为新会话
UPDATE_TICK_S = 15.0            # 后台线程检查会话的间隔
UPDATE_MIN_INTERVAL_S = 45.0    # 同一会话两次补写记录的最小间隔
GEO_TIMEOUT_S = 6.0
MAX_JSONL_BYTES = 5 * 1024 * 1024
JSONL_KEEP_LINES = 2000

# 页面资源不值得记
STATIC_SUFFIXES = (
    ".js", ".mjs", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".mp3", ".mp4", ".webm", ".json",
)

# 命中这些前缀才算「一次访问」——SPA 打开必然调它们
SESSION_PATHS = (
    "/orders", "/practice", "/messages", "/im", "/profile", "/profiles", "/users",
    "/learn", "/threads", "/contracts", "/tools", "/voice", "/bootstrap",
)

# 页面渲染类请求：打开页面就发生，不算「操作」
PASSIVE_PREFIXES = ("/contracts", "/profiles", "/health", "/favicon")

# 路由 → 页面名，用于统计「看了几页」
ROUTE_NAMES = (
    ("/practice/orders", "订单"),
    ("/messages", "消息中心"),
    ("/learn", "学习地图"),
    ("/threads", "教学对话"),
    ("/im", "聊天"),
    ("/profiles", "画像"),
    ("/tools", "工具台"),
    ("/voice", "语音通话"),
    ("/contracts", "首页"),
    ("/users", "首页"),
)

CF_COUNTRY = {
    "CN": "中国", "HK": "中国香港", "TW": "中国台湾", "MO": "中国澳门",
    "US": "美国", "SG": "新加坡", "MY": "马来西亚", "TH": "泰国", "JP": "日本",
    "KR": "韩国", "VN": "越南", "ID": "印度尼西亚", "PH": "菲律宾", "IN": "印度",
    "GB": "英国", "DE": "德国", "FR": "法国", "IT": "意大利", "ES": "西班牙",
    "RU": "俄罗斯", "AU": "澳大利亚", "NZ": "新西兰", "CA": "加拿大",
    "AE": "阿联酋", "SA": "沙特阿拉伯", "NL": "荷兰", "CH": "瑞士",
    "SE": "瑞典", "BR": "巴西", "MX": "墨西哥", "TR": "土耳其",
}


def _txt(v, default: str = "") -> str:
    """高德等接口字段可能是字符串、空数组或空字典，统一成字符串。"""
    if isinstance(v, str):
        return v.strip()
    return default


def _get_json(url: str, timeout: float = GEO_TIMEOUT_S) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TripCraft-Monitor/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def classify_ua(ua: str) -> str:
    u = (ua or "").lower()
    if not u:
        return "未知"
    if "bot" in u or "spider" in u or "crawler" in u or "curl" in u or "python" in u or "wget" in u:
        return "脚本/爬虫"
    if "micromessenger" in u:
        return "微信内置"
    if "edg/" in u:
        return "Edge"
    if "firefox" in u:
        return "Firefox"
    if "chrome" in u or "chromium" in u:
        return "Chrome"
    if "safari" in u:
        return "Safari"
    return "其他"


def client_ip(headers, fallback: str) -> str:
    """按 Cloudflare → 反向代理 → 直连 的顺序取真实访客 IP。"""
    for name in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
        v = (headers.get(name) or "").strip()
        if v:
            return v
    xff = (headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return fallback or ""


def is_private(ip: str) -> bool:
    """本机、内网、保留地址，以及不是 IP 的字符串（如测试客户端名）都不记录。"""
    if not ip:
        return True
    if ip == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved)


def headers_from_scope(scope) -> dict:
    """ASGI scope（http / websocket）→ 小写 key 的 headers。"""
    out: dict[str, str] = {}
    for k, v in scope.get("headers") or []:
        try:
            out[k.decode("latin-1").lower()] = v.decode("latin-1")
        except Exception:
            continue
    return out


def page_of(path: str) -> str:
    p = path or "/"
    if p in ("", "/"):
        return "首页"
    for prefix, name in ROUTE_NAMES:
        if p.startswith(prefix):
            return name
    return "其他"


def is_interactive(path: str, method: str = "GET") -> bool:
    """需要点击或提交才会发生的请求才算「操作」。"""
    if (method or "GET").upper() not in ("GET", "HEAD", "OPTIONS"):
        return True
    p = path or "/"
    if p in ("", "/"):
        return False
    return not p.startswith(PASSIVE_PREFIXES)


def place_of(rec: dict) -> str:
    """一行里显示的归属地。"""
    geo = rec.get("geo") or {}
    parts, seen, uniq = (geo.get("country"), geo.get("region"), geo.get("city")), set(), []
    for p in parts:
        if p and p not in seen:
            uniq.append(p)
            seen.add(p)
    text = " ".join(uniq) or "归属地未知"
    isp = geo.get("isp") or ""
    if isp and isp not in text:
        text = f"{text} {isp}".strip()
    return text


def net_tag(geo: dict) -> str:
    """网络性质：机房 / 代理 / 空。"""
    geo = geo or {}
    if geo.get("proxy"):
        return "代理"
    if geo.get("hosting"):
        return "机房"
    return ""


def duration_text(first: float, last: float) -> str:
    d = max(0.0, float(last or 0) - float(first or 0))
    if d >= 3600:
        return f"{int(d // 3600)}小时{int((d % 3600) // 60)}分"
    if d >= 60:
        return f"{int(d // 60)}分"
    if d >= 5:
        return f"{int(d)}秒"
    return ""


def behavior_of(rec: dict) -> str:
    """行为摘要：看了几页、操作几次、待了多久。"""
    routes = rec.get("routes") or []
    pages = len(set(routes)) if routes else 1
    actions = int(rec.get("actions") or 0)
    parts = [f"{pages}页"]
    if actions:
        parts.append(f"操作{actions}次")
    dur = duration_text(rec.get("first_seen") or rec.get("ts") or 0, rec.get("last_seen") or 0)
    if dur:
        parts.append(dur)
    return "·".join(parts)


MERGE_FIELDS = (
    "ip", "ua", "ua_kind", "dedup_key", "session", "kind", "path", "method",
    "referer", "host", "cf_country", "cf_ray", "accept_language",
    "renders", "actions", "requests", "routes", "geo",
)


def merge_sessions(records: list[dict]) -> list[dict]:
    """把同一个会话的多条记录并成一条，取最后状态。"""
    out: dict[str, dict] = {}
    order: list[str] = []
    for rec in records:
        sid = rec.get("session") or f"{rec.get('ip')}|{rec.get('ts')}"
        cur = out.get(sid)
        if cur is None:
            cur = dict(rec)
            out[sid] = cur
            order.append(sid)
        else:
            for k in MERGE_FIELDS:
                if k in rec:
                    cur[k] = rec[k]
            if rec.get("new_ip"):
                cur["new_ip"] = True
        ts = float(rec.get("ts") or 0)
        if ts:
            first = float(cur.get("first_seen") or ts)
            cur["first_seen"] = min(first, ts) if first else ts
            cur["last_seen"] = max(float(cur.get("last_seen") or ts), ts)
    for sid in order:
        out[sid].setdefault("first_seen", out[sid].get("ts"))
        out[sid].setdefault("last_seen", out[sid].get("ts"))
    return [out[s] for s in order]


def format_line(rec: dict) -> str:
    """人读日志的一行。"""
    geo = rec.get("geo") or {}
    tag = net_tag(geo)
    marks = ["新访客" if rec.get("new_ip") else "回访"]
    if rec.get("known"):
        marks.append(str(rec["known"]))
    if tag:
        marks.append(tag)
    kind = rec.get("kind")
    if kind == "interact":
        marks.append("有操作")
    elif kind == "update":
        marks.append("进行中")
    return (
        f"{rec.get('time','')}  [{'·'.join(marks)}]  {rec['ip']}  {place_of(rec)}"
        + (f"  ({geo.get('asn','')})" if geo.get("asn") else "")
        + f"  |  {rec.get('ua_kind','')}  |  {behavior_of(rec)}  |  {rec.get('path','')}"
        + (f"  ← {rec['referer']}" if rec.get("referer") else "")
        + (f"  geo:{geo.get('source','')}" if geo.get("source") else "")
    )


class _Barrier:
    """队列屏障：写线程处理到它时唤醒等待者。"""

    __slots__ = ("done",)

    def __init__(self, done: threading.Event):
        self.done = done


class VisitMonitor:
    """把访问写进日志；归属地与机房标记异步补全。"""

    def __init__(self, log_dir: Path | None = None, dedup_window_s: float = DEDUP_WINDOW_S):
        self.log_dir = Path(log_dir) if log_dir else default_log_dir()
        self.dedup_window_s = dedup_window_s
        self.jsonl = self.log_dir / "visits.jsonl"
        self.human = self.log_dir / "visits.log"
        self.geo_file = self.log_dir / "visit_geo_cache.json"
        self.known_file = self.log_dir / "known_visitors.json"
        self._known: dict[str, str] = {}
        self._known_mtime = -1.0

        self._q: queue.Queue = queue.Queue()
        self._geo: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._known_ips: set[str] = set()
        self._lock = threading.Lock()
        self._seq = 0
        self._started = False
        self._log_local = os.environ.get("VISIT_LOG_LOCAL", "") not in ("", "0", "false", "False")
        self._amap_key: str | None = None

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._load_geo()
            self._load_known()
            self._load_history()
            threading.Thread(target=self._worker, name="visit-monitor", daemon=True).start()
            self._started = True

    def _load_geo(self) -> None:
        try:
            if self.geo_file.exists():
                data = json.loads(self.geo_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._geo = {k: v for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            self._geo = {}

    def _load_known(self) -> None:
        """自己人/队友的 IP 名单：命中就不再当外人提醒（文件改了自动重载）。"""
        try:
            if not self.known_file.exists():
                return
            mtime = self.known_file.stat().st_mtime
            if mtime == self._known_mtime:
                return
            data = json.loads(self.known_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._known = {str(k): str(v) for k, v in data.items()}
                self._known_mtime = mtime
        except Exception:
            pass

    def known_label(self, ip: str) -> str:
        self._load_known()
        return self._known.get(ip, "")

    def _load_history(self) -> None:
        """重启后仍认得老访客、仍能续上未结束的会话。"""
        if not self.jsonl.exists():
            return
        try:
            lines = self.jsonl.read_text(encoding="utf-8", errors="ignore").splitlines()[-1500:]
        except Exception:
            return
        now = time.time()
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ip = rec.get("ip") or ""
            if not ip:
                continue
            self._known_ips.add(ip)
            key = rec.get("dedup_key") or ip
            ts = float(rec.get("ts") or 0)
            last = float(rec.get("last_seen") or ts or 0)
            if now - last > self.dedup_window_s:
                continue
            sess = self._sessions.get(key)
            if sess is None:
                sess = {
                    "id": rec.get("session") or key, "key": key,
                    "ip": ip, "ua": rec.get("ua") or "", "ua_kind": rec.get("ua_kind") or "",
                    "first_seen": float(rec.get("first_seen") or ts or 0),
                    "last_seen": last,
                    "renders": 0, "actions": 0, "requests": 0, "routes": set(),
                    "logged_open": False, "logged_action": False,
                    "last_write": last, "written": None, "meta": {},
                }
                self._sessions[key] = sess
            sess["last_seen"] = max(sess["last_seen"], last)
            sess["logged_open"] = sess["logged_open"] or rec.get("kind") == "open"
            sess["logged_action"] = sess["logged_action"] or rec.get("kind") == "interact"
            for r in rec.get("routes") or []:
                sess["routes"].add(r)
            if rec.get("referer"):
                sess["meta"]["referer"] = rec["referer"]
            if rec.get("host"):
                sess["meta"]["host"] = rec["host"]
            if rec.get("cf_country"):
                sess["meta"]["cf_country"] = rec["cf_country"]
            if rec.get("cf_ray"):
                sess["meta"]["cf_ray"] = rec["cf_ray"]
            if rec.get("accept_language"):
                sess["meta"]["accept_language"] = rec["accept_language"]
            sess["written"] = self._counters(sess)
            sess["last_write"] = last

    # ---------------- 对外入口 ----------------

    def note(self, *, headers, client_host: str, path: str, method: str = "GET") -> bool:
        """只做判定与入队，不做网络请求。返回 True 表示这次调用写了一条记录。"""
        ip = client_ip(headers, client_host)
        if not ip:
            return False
        if is_private(ip) and not self._log_local:
            return False
        if self._is_static(path):
            return False
        accept = (headers.get("accept") or "").lower()
        if not (
            "text/html" in accept
            or method == "WS"                # 语音通话等 WebSocket
            or path in ("", "/")             # 前端启动时的健康检查
            or any(path.startswith(p) for p in SESSION_PATHS)
        ):
            return False
        self.start()

        ua = headers.get("user-agent") or ""
        kind = classify_ua(ua)
        key = f"{ip}|{kind}"
        action = is_interactive(path, method)
        page = page_of(path)
        now = time.time()
        meta = {
            "path": path, "method": method,
            "referer": (headers.get("referer") or "")[:200],
            "host": headers.get("host") or "",
            "cf_country": (headers.get("cf-ipcountry") or "").upper(),
            "cf_ray": headers.get("cf-ray") or "",
            "accept_language": (headers.get("accept-language") or "")[:80],
        }

        with self._lock:
            sess = self._sessions.get(key)
            if sess is None or now - sess["last_seen"] > self.dedup_window_s:
                sess = {
                    "id": self._session_id(key, now), "key": key, "ip": ip,
                    "ua": ua[:220], "ua_kind": kind,
                    "first_seen": now, "last_seen": now,
                    "renders": 0, "actions": 0, "requests": 0, "routes": set(),
                    "logged_open": False, "logged_action": False,
                    "last_write": 0.0, "written": None, "meta": meta,
                }
                self._sessions[key] = sess
            sess["last_seen"] = now
            sess["requests"] += 1
            sess["routes"].add(page)
            sess["meta"] = meta
            if action:
                sess["actions"] += 1
            else:
                sess["renders"] += 1

            record_kind = ""
            if not sess["logged_open"]:
                sess["logged_open"] = True
                record_kind = "open"
            elif action and not sess["logged_action"]:
                sess["logged_action"] = True
                record_kind = "interact"
            if not record_kind:
                return False

            sess["last_write"] = now
            sess["written"] = self._counters(sess)
            record = self._record(sess, record_kind, now, meta)

        self._q.put(record)
        return True

    def note_from_scope(self, scope) -> bool:
        """ASGI scope（http / websocket）→ 记一次访问。"""
        try:
            path = scope.get("path") or "/"
            client = scope.get("client") or ("", 0)
            method = "WS" if scope.get("type") == "websocket" else (scope.get("method") or "GET")
            return self.note(
                headers=headers_from_scope(scope),
                client_host=client[0] if client else "",
                path=path,
                method=method,
            )
        except Exception:
            return False

    def flush(self, timeout: float = 12.0) -> bool:
        """等后台线程把队列里已有的记录真正写完（退出、测试用）。

        只判断队列是否为空不够：出队到落盘之间还有一段窗口，
        所以插一个屏障对象，由写线程处理完前面的记录后再唤醒。
        """
        if not self._started:
            return True
        done = threading.Event()
        self._q.put(_Barrier(done))
        return done.wait(timeout)

    def flush_updates(self, now: float | None = None, force: bool = False) -> int:
        """补写「进行中」的会话（长时间停留 / 大量操作），并回收过期会话。"""
        now = time.time() if now is None else now
        records: list[dict] = []
        with self._lock:
            for key, sess in list(self._sessions.items()):
                idle = now - sess["last_seen"]
                changed = self._counters(sess) != sess.get("written")
                if idle > self.dedup_window_s:
                    if changed:
                        records.append(self._record(sess, "update", now, sess["meta"]))
                    self._sessions.pop(key, None)
                    continue
                if changed and (force or now - sess["last_write"] >= UPDATE_MIN_INTERVAL_S):
                    sess["last_write"] = now
                    sess["written"] = self._counters(sess)
                    records.append(self._record(sess, "update", now, sess["meta"]))
        for rec in records:
            self._write(rec)
        return len(records)

    # ---------------- 内部 ----------------

    def _session_id(self, key: str, now: float) -> str:
        """毫秒时间戳 + 自增序号：同一秒内连开两个会话也不会撞 id。"""
        self._seq += 1
        return f"{key}#{int(now * 1000)}-{self._seq}"

    @staticmethod
    def _counters(sess: dict) -> dict:
        return {
            "requests": sess["requests"], "renders": sess["renders"],
            "actions": sess["actions"], "routes": tuple(sorted(sess["routes"])),
        }

    def _record(self, sess: dict, kind: str, now: float, meta: dict) -> dict:
        return {
            "session": sess["id"], "kind": kind,
            "first_seen": sess["first_seen"], "last_seen": sess["last_seen"],
            "renders": sess["renders"], "actions": sess["actions"],
            "requests": sess["requests"], "routes": sorted(sess["routes"]),
            "ts": now,
            "time": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
            "ip": sess["ip"], "dedup_key": sess["key"],
            "ua": sess["ua"], "ua_kind": sess["ua_kind"],
            "path": meta.get("path", ""), "method": meta.get("method", "GET"),
            "referer": meta.get("referer", ""), "host": meta.get("host", ""),
            "cf_country": meta.get("cf_country", ""), "cf_ray": meta.get("cf_ray", ""),
            "accept_language": meta.get("accept_language", ""),
        }

    @staticmethod
    def _is_static(path: str) -> bool:
        if path.startswith("/assets/") or path.startswith("/@") or path.startswith("/node_modules/"):
            return True
        low = (path or "").lower()
        return any(low.endswith(s) for s in STATIC_SUFFIXES)

    def _worker(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=UPDATE_TICK_S)
            except queue.Empty:
                try:
                    self.flush_updates()
                except Exception:
                    pass
                continue
            if item is None:
                return
            if isinstance(item, _Barrier):
                item.done.set()
                continue
            try:
                self._write(item)
            except Exception:
                pass

    def _write(self, rec: dict) -> None:
        ip = rec["ip"]
        geo = self._geo.get(ip)
        if geo is None:
            geo = self._resolve_geo(ip, rec.get("cf_country") or "")
            self._geo[ip] = geo
            self._save_geo()
        rec["geo"] = geo
        rec["new_ip"] = ip not in self._known_ips
        self._known_ips.add(ip)
        label = self.known_label(ip)
        if label:
            rec["known"] = label

        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.human.open("a", encoding="utf-8") as f:
            f.write(format_line(rec) + "\n")
        self._rotate_if_needed()
        with self.jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _rotate_if_needed(self) -> None:
        try:
            if self.jsonl.exists() and self.jsonl.stat().st_size > MAX_JSONL_BYTES:
                lines = self.jsonl.read_text(encoding="utf-8", errors="ignore").splitlines()
                self.jsonl.write_text("\n".join(lines[-JSONL_KEEP_LINES:]) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _save_geo(self) -> None:
        try:
            self.geo_file.write_text(json.dumps(self._geo, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    # ---------------- 归属地与网络性质 ----------------

    def _amap_key_get(self) -> str:
        if self._amap_key is None:
            key = ""
            try:
                from tripcraft.tools.external import load_env
                key = (load_env().get("AMAP_API_KEY") or "").strip()
            except Exception:
                key = ""
            self._amap_key = key
        return self._amap_key

    @staticmethod
    def _ipapi(ip: str) -> dict | None:
        """ip-api 免费接口：同时给归属地与机房 / 代理标记。"""
        try:
            fields = "status,country,regionName,city,isp,org,as,hosting,proxy,mobile"
            url = "http://ip-api.com/json/" + urllib.parse.quote(ip) + "?lang=zh-CN&fields=" + fields
            d = _get_json(url)
            return d if d.get("status") == "success" else None
        except Exception:
            return None

    def _resolve_geo(self, ip: str, cf_country: str = "") -> dict:
        info = {
            "source": "", "country": "", "region": "", "city": "", "isp": "",
            "asn": "", "hosting": False, "proxy": False, "mobile": False, "flags": False,
        }

        # 1) 高德：国内 IP 最准
        key = self._amap_key_get()
        if key:
            try:
                url = "https://restapi.amap.com/v3/ip?" + urllib.parse.urlencode({"ip": ip, "key": key})
                d = _get_json(url)
                if str(d.get("status")) == "1":
                    prov, city = _txt(d.get("province")), _txt(d.get("city"))
                    if prov or city:
                        info.update(source="amap", country="中国", region=prov, city="" if city == prov else city)
            except Exception:
                pass

        # 2) vore.top：国内可直连，能给到运营商
        if not (info["city"] or info["region"]):
            try:
                d = _get_json("https://api.vore.top/api/IPdata?ip=" + urllib.parse.quote(ip))
                if str(d.get("code")) == "200":
                    ipdata = d.get("ipdata") or {}
                    info.update(
                        source="vore",
                        country=_txt(ipdata.get("info1")) or info["country"],
                        region=_txt(ipdata.get("info2")),
                        city=_txt(ipdata.get("info3")),
                        isp=_txt(ipdata.get("isp")),
                    )
            except Exception:
                pass

        # 3) ip-api：补归属地，同时拿到机房 / 代理标记（国内 IP 也要，防止云主机冒充真人）
        d = self._ipapi(ip)
        if d:
            info["flags"] = True
            info["asn"] = _txt(d.get("as")) or info["asn"]
            info["hosting"] = bool(d.get("hosting"))
            info["proxy"] = bool(d.get("proxy"))
            info["mobile"] = bool(d.get("mobile"))
            if not (info["city"] or info["region"]):
                info.update(
                    source="ip-api",
                    country=_txt(d.get("country")) or info["country"],
                    region=_txt(d.get("regionName")),
                    city=_txt(d.get("city")),
                    isp=_txt(d.get("isp")) or _txt(d.get("org")),
                )
            elif not info["isp"]:
                info["isp"] = _txt(d.get("isp")) or _txt(d.get("org"))

        # 4) 兜底：Cloudflare 自带国家码
        if not info["country"] and cf_country:
            info.update(source="cf", country=CF_COUNTRY.get(cf_country, cf_country))

        if not info["source"]:
            info["source"] = "none"
        return info


class VisitMonitorMiddleware:
    """纯 ASGI 中间件：http 与 websocket（语音通话）都记一条。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        stype = scope.get("type")
        if stype == "websocket":
            try:
                VISIT_MONITOR.note_from_scope(scope)
            except Exception:
                pass
            await self.app(scope, receive, send)
            return
        if stype != "http":
            await self.app(scope, receive, send)
            return
        await self.app(scope, receive, send)
        try:
            VISIT_MONITOR.note_from_scope(scope)
        except Exception:
            pass


VISIT_MONITOR = VisitMonitor()
