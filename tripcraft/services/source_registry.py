"""官方来源快照注册表。

证据闸门不再信任调用方自行计算的哈希。生产链路必须先把官方 URL
交给服务端抓取，保存不可变正文与 SHA256，再用 snapshot_id 回查。
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler, Request, build_opener,
)

from .evidence_verifier import allowed_official_host, is_official_http_url

MAX_SOURCE_BYTES = 2_000_000
FETCH_TIMEOUT_SECONDS = 10
_ALLOWED_CONTENT_TYPES = {
    "text/html", "application/xhtml+xml", "text/plain",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class SourceRegistryError(ValueError):
    """来源不可抓取、不可验证或不在可信边界内。"""


@dataclass(frozen=True)
class FetchedOfficialSource:
    url: str
    content: str
    title: str
    content_type: str
    raw_size: int


class _OfficialRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        target = urljoin(req.full_url, newurl)
        if not is_official_http_url(target):
            raise SourceRegistryError("官方页面重定向到了非白名单域名")
        _assert_public_host(urlsplit(target).hostname or "")
        return super().redirect_request(req, fp, code, msg, headers, target)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "div", "br", "li", "tr", "td", "th", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return normalize_source_text(" ".join(self.parts))

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()


def normalize_source_text(text: str) -> str:
    value = str(text or "").replace("\u00a0", " ").replace("\r", "\n")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


def _canonical_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/",
                       parts.query, ""))


def _validate_url(url: str) -> str:
    value = str(url or "").strip()
    if not is_official_http_url(value):
        raise SourceRegistryError("只允许抓取白名单内的 http/https 官方域名")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as exc:
        raise SourceRegistryError("URL 端口非法") from exc
    if port not in (None, 80, 443):
        raise SourceRegistryError("只允许标准 HTTP/HTTPS 端口")
    return _canonical_url(value)


def _assert_public_host(host: str) -> None:
    if not allowed_official_host(host):
        raise SourceRegistryError("域名不在官方来源白名单")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise SourceRegistryError(f"无法解析官方域名: {host}") from exc
    if not addresses:
        raise SourceRegistryError("官方域名没有可用地址")
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            raise SourceRegistryError("官方域名解析到了非公网地址")


def fetch_official_url(url: str) -> FetchedOfficialSource:
    """抓取官方正文；仅允许白名单域名、标准端口和公网地址。"""
    canonical = _validate_url(url)
    host = urlsplit(canonical).hostname or ""
    _assert_public_host(host)
    req = Request(canonical, headers={
        "User-Agent": "TripCraft-Evidence/1.0 (+official-source-snapshot)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
    })
    charset = "utf-8"
    try:
        with build_opener(_OfficialRedirectHandler()).open(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            final_url = _validate_url(resp.geturl())
            content_type = str(resp.headers.get_content_type() or "").lower()
            charset = resp.headers.get_content_charset() or "utf-8"
            declared = str(resp.headers.get("Content-Length") or "").strip()
            if declared.isdigit() and int(declared) > MAX_SOURCE_BYTES:
                raise SourceRegistryError("官方页面超过快照大小上限")
            raw = resp.read(MAX_SOURCE_BYTES + 1)
    except SourceRegistryError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceRegistryError(f"官方页面抓取失败: {exc}") from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise SourceRegistryError("官方页面超过快照大小上限")
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise SourceRegistryError(f"暂不支持该官方正文类型: {content_type or 'unknown'}")

    try:
        decoded = raw.decode(charset, errors="replace")
    except LookupError:
        decoded = raw.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _TextExtractor()
        parser.feed(decoded)
        content = parser.text
        title = parser.title
    else:
        content = normalize_source_text(decoded)
        title = ""
    if len(content) < 20:
        raise SourceRegistryError("官方页面没有可用的正文文本")
    return FetchedOfficialSource(
        url=final_url, content=content, title=title,
        content_type=content_type, raw_size=len(raw),
    )


class OfficialSourceRegistry:
    """把官方 URL 转换为可重复校验的数据库快照。"""

    def __init__(self, store, fetcher: Callable[[str], FetchedOfficialSource] | None = None) -> None:
        self._store = store
        self._fetcher = fetcher or fetch_official_url

    def capture(self, url: str, created_by: str) -> dict:
        requested = _validate_url(url)
        fetched = self._fetcher(requested)
        canonical = _validate_url(fetched.url)
        host = urlsplit(canonical).hostname or ""
        if not allowed_official_host(host):
            raise SourceRegistryError("抓取结果不属于官方来源白名单")
        content = normalize_source_text(fetched.content)
        if len(content) < 20:
            raise SourceRegistryError("官方快照正文过短")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        snapshot_id = "snap_" + hashlib.sha256(
            (canonical + "\n" + content_hash).encode("utf-8")
        ).hexdigest()[:32]
        row = self._store.save_source_snapshot(
            snapshot_id=snapshot_id,
            url=str(url or "").strip(),
            canonical_url=canonical,
            host=host,
            title=normalize_source_text(fetched.title)[:500],
            content=content,
            content_hash=content_hash,
            content_type=fetched.content_type,
            raw_size=fetched.raw_size,
            created_by=created_by,
            fetched_at=datetime.now().isoformat(timespec="seconds"),
            fetch_method="server_http",
            status="verified",
        )
        return self.public_snapshot(row)

    def resolve(self, snapshot_id: str) -> dict | None:
        """返回通过完整性复算的持久化快照；任何篡改都会返回 None。"""
        row = self._store.source_snapshot(str(snapshot_id or "").strip())
        if not row or row.get("status") != "verified":
            return None
        if not is_official_http_url(str(row.get("canonical_url") or row.get("url") or "")):
            return None
        content = str(row.get("content") or "")
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not row.get("content_hash") or row["content_hash"] != expected:
            return None
        return row

    def verify_excerpt(self, snapshot_id: str, text: str) -> dict | None:
        row = self.resolve(snapshot_id)
        if not row:
            return None
        content = re.sub(r"\s+", "", str(row.get("content") or ""))
        needle = re.sub(r"\s+", "", str(text or ""))
        if not needle or needle not in content:
            return None
        return row

    @staticmethod
    def public_snapshot(row: dict | None) -> dict:
        row = row or {}
        return {
            "snapshot_id": row.get("snapshot_id", ""),
            "url": row.get("url", ""),
            "canonical_url": row.get("canonical_url", ""),
            "host": row.get("host", ""),
            "title": row.get("title", ""),
            "content_hash": row.get("content_hash", ""),
            "content_type": row.get("content_type", ""),
            "raw_size": int(row.get("raw_size") or 0),
            "fetched_at": row.get("fetched_at", ""),
            "fetch_method": row.get("fetch_method", ""),
            "status": row.get("status", ""),
            "content_excerpt": str(row.get("content") or "")[:500],
        }


__all__ = [
    "FetchedOfficialSource", "OfficialSourceRegistry", "SourceRegistryError",
    "fetch_official_url", "normalize_source_text",
]
