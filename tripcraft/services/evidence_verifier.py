"""证据约束校验：把生成内容拆成 claim，并逐条检查证据支持。

当前版本采用可复现的确定性校验器（词项覆盖 + 数字一致性 + 高风险规则），
定位是可离线运行的第一道闸门，不把它冒充成 NLI 模型：
- 有数字/日期/时限的 claim，必须有同类数字证据；
- 签证、入境、海关、保险、安全、宗教、法律等高风险 claim，证据不足时直接 block；
- 低风险事实可以标记 weak，交给后续 LLM verifier 或人工复核。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ALNUM_RE = re.compile(r"[a-zA-Z0-9]+")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?%?")
_SENT_RE = re.compile(r"(?<=[。！？；;])(?:\s*)|\n+")
_HIGH_RISK = (
    "签证", "入境", "海关", "证件", "移民", "法律", "保险", "安全", "宗教", "清真",
    "医疗", "疫苗", "开放时间", "门票", "赔付", "合同", "政策", "禁令", "违法",
)
_MEDIUM_RISK = ("价格", "费用", "预算", "时间", "小时", "天", "公里", "元", "岁", "人数")

# 高风险 claim 的证据来源白名单。rubric / skill graph 是项目内已审阅的教学契约；
# official 是政府或官方机构；observed 是学员在系统中的直接可复核行为记录。
_HIGH_RISK_TRUST = {"official", "curated", "observed"}
# 官方来源不能只看“国家移民管理局”这种可伪造的显示名。服务端只把
# allowlisted 官方域名 + 对得上的内容哈希视为严格可验证来源；兼容模式
# 仅供内部离线回放，API 边界必须使用 strict_provenance=True。
_OFFICIAL_DOMAINS = (
    "gov.cn", "nia.gov.cn", "mfa.gov.cn", "customs.gov.cn", "mct.gov.cn",
    "moe.gov.cn", "nhc.gov.cn", "nmpa.gov.cn", "12315.cn", "gov.hk", "gov.mo",
)
_OFFICIAL_MARKERS = (
    "gov.cn", "政府", "国务院", "国家移民管理局", "外交部", "海关总署",
    "文化和旅游部", "教育部", "卫健委", "文旅部", "移民局", "官方",
    "中华人民共和国", "政策原文", "法律法规",
)
_CURATED_MARKERS = ("rubric:", "skill_graph:", "contract:", "expert:", "prd:", "项目规则")
_OBSERVED_MARKERS = ("practice:", "order:", "call:", "deliverable:", "evidence:direct")
_SECONDARY_MARKERS = (
    "百度百科", "百度", "知乎", "微信", "公众号", "微博", "视频", "bilibili",
    "youtube", "搜狐", "新浪", "csdn", "小红书", "马蜂窝", "游记",
)
_TEACHING_MARKERS = ("knowledge:", "teaching:", "retrieval:", "教学", "资料")


def _terms(text: str) -> set[str]:
    text = str(text or "").lower()
    out: set[str] = set()
    cjk = "".join(_CJK_RE.findall(text))
    if len(cjk) >= 2:
        out.update(cjk[i:i + 2] for i in range(len(cjk) - 1))
    out.update(w for w in _ALNUM_RE.findall(text) if len(w) >= 2)
    return out


def _numbers(text: str) -> set[str]:
    return {x.replace(",", "") for x in _NUM_RE.findall(str(text or ""))}


def _risk_level(text: str) -> str:
    value = str(text or "")
    if any(word in value for word in _HIGH_RISK):
        return "high"
    if any(word in value for word in _MEDIUM_RISK) or _numbers(value):
        return "medium"
    return "low"


def _host_from_source(source: str) -> str:
    value = str(source or "").strip()
    if not value:
        return ""
    if "://" not in value:
        return ""
    try:
        return (urlparse(value).hostname or "").lower().strip(".")
    except ValueError:
        return ""


def allowed_official_host(host: str) -> bool:
    host = str(host or "").lower().strip(".")
    return bool(host) and any(host == domain or host.endswith("." + domain)
                               for domain in _OFFICIAL_DOMAINS)


def is_official_http_url(url: str) -> bool:
    """只允许 http/https 的官方白名单域名，用于服务端抓取边界。"""
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return False
    return (parsed.scheme in ("http", "https") and not parsed.username
            and not parsed.password and allowed_official_host(parsed.hostname or ""))


def _source_host(source: str, item: dict[str, Any] | None = None) -> str:
    item = item or {}
    for key in ("url", "source_url", "canonical_url"):
        host = _host_from_source(str(item.get(key) or ""))
        if host:
            return host
    return _host_from_source(source)


@dataclass(frozen=True)
class SourceAssessment:
    trust: str
    verified: bool
    reason: str
    host: str = ""
    content_hash_ok: bool = False
    snapshot_id: str = ""
    snapshot_verified: bool = False


def _snapshot_contains(snapshot: dict[str, Any], text: str) -> bool:
    """证据片段必须能在服务端保存的官方原文中定位。"""
    content = re.sub(r"\s+", "", str((snapshot or {}).get("content") or ""))
    needle = re.sub(r"\s+", "", str(text or ""))
    return bool(needle) and needle in content


def assess_source(source: str, item: dict[str, Any] | None = None,
                  text: str = "", *, strict_provenance: bool = False,
                  snapshot: dict[str, Any] | None = None) -> SourceAssessment:
    """判定来源等级和“是否真的经过服务端可核验”的生产来源。

    严格模式下，官方来源必须是 allowlisted 域名，且 evidence 携带的
    content_hash / snapshot_hash 与当前文本一致。仅写“国家移民管理局”
    或客户端自报 trust 都只能算未验证标签，不能放行高风险 claim。
    内部 curated / observed 前缀是服务端流水线生成的，按内部快照处理。
    """
    item = item or {}
    value = str(source or "").strip()
    trust = classify_source(value)
    if trust in ("curated", "observed"):
        return SourceAssessment(trust, True, "服务端内部受控来源")
    host = _source_host(value, item)
    raw_hash = next((str(item.get(key) or "").strip().lower()
                      for key in ("content_hash", "snapshot_hash", "sha256")
                      if str(item.get(key) or "").strip()), "")
    expected = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()
    hash_ok = bool(raw_hash) and hmac.compare_digest(
        raw_hash.removeprefix("sha256:"), expected)
    if trust == "official":
        snapshot_id = str((item or {}).get("snapshot_id") or "").strip()
        snapshot = snapshot or {}
        snapshot_host = str(snapshot.get("host") or "").lower().strip(".")
        snapshot_url = str(snapshot.get("url") or "")
        if not host and snapshot_url:
            host = _host_from_source(snapshot_url)
        allowed = allowed_official_host(host or snapshot_host)
        if not strict_provenance:
            # 兼容既有离线调用；生产 API 显式开启严格来源验证。
            return SourceAssessment("official", allowed or bool(value), "兼容模式：未启用来源强校验",
                                    host=host, content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        if not allowed:
            return SourceAssessment("official", False,
                                    "官方来源缺少 allowlisted 域名", host=host,
                                    content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        if not snapshot_id:
            return SourceAssessment("official", False,
                                    "官方来源缺少服务端 snapshot_id；客户端哈希只能证明提交内容未变",
                                    host=host, content_hash_ok=hash_ok,
                                    snapshot_id="", snapshot_verified=False)
        if not snapshot:
            return SourceAssessment("official", False,
                                    "服务端未找到或无法校验该官方快照", host=host,
                                    content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        if not allowed_official_host(snapshot_host):
            return SourceAssessment("official", False,
                                    "官方快照域名不在白名单", host=host,
                                    content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        if host and host != snapshot_host:
            return SourceAssessment("official", False,
                                    "证据来源域名与服务端快照域名不一致", host=host,
                                    content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        snapshot_hash = str(snapshot.get("content_hash") or "").lower()
        actual_snapshot_hash = hashlib.sha256(
            str(snapshot.get("content") or "").encode("utf-8")
        ).hexdigest()
        if not snapshot_hash or not hmac.compare_digest(snapshot_hash, actual_snapshot_hash):
            return SourceAssessment("official", False,
                                    "官方快照完整性校验失败", host=host,
                                    content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        if not _snapshot_contains(snapshot, text):
            return SourceAssessment("official", False,
                                    "证据原文无法在服务端官方快照中定位", host=host,
                                    content_hash_ok=hash_ok,
                                    snapshot_id=snapshot_id, snapshot_verified=False)
        return SourceAssessment("official", True, "服务端官方快照完整且命中证据原文",
                                host=snapshot_host, content_hash_ok=True,
                                snapshot_id=snapshot_id, snapshot_verified=True)
    if trust == "secondary":
        return SourceAssessment(trust, False, "二级社区/百科来源不能单独支持高风险结论")
    if trust == "teaching":
        return SourceAssessment(trust, False, "教学召回不是外部事实原文")
    return SourceAssessment(trust, False, "来源等级未知")


def classify_source(source: str) -> str:
    """把来源映射为可解释的信任等级，供高风险 claim 做硬闸门。

    等级不是“真理概率”，而是证据治理策略：
    - official：政府、监管机构、官方政策页面；
    - curated：项目内经审阅的 Rubric / 技能图 / 专家契约；
    - observed：系统内直接观测到的学员话语、交付物或行为；
    - teaching：普通知识召回 / 教学资料；
    - secondary：百科、社区、视频和搜索结果；
    - unknown：无法判断，默认不能单独支持高风险结论。
    """
    value = str(source or "").strip().lower()
    if not value:
        return "unknown"
    host = _host_from_source(value)
    if allowed_official_host(host):
        return "official"
    if any(marker in value for marker in _OFFICIAL_MARKERS):
        return "official"
    if any(marker in value for marker in _CURATED_MARKERS):
        return "curated"
    if any(marker in value for marker in _OBSERVED_MARKERS):
        return "observed"
    if any(marker in value for marker in _SECONDARY_MARKERS):
        return "secondary"
    if any(marker in value for marker in _TEACHING_MARKERS):
        return "teaching"
    return "unknown"


def _clean(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^[#>*\-\s]+", "", value).strip()
    value = re.sub(r"`{1,3}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return value.strip()


def split_claims(content: str) -> list[str]:
    """按句号/分号/换行拆 claim，过滤标题、来源行和过短行。"""
    claims: list[str] = []
    for raw in _SENT_RE.split(str(content or "")):
        claim = _clean(raw)
        if len(claim) < 8:
            continue
        if claim.startswith(("参考来源", "资料依据", "【", "|")):
            continue
        if claim not in claims:
            claims.append(claim)
    return claims[:32]


def normalize_evidence(evidence: list[Any] | tuple[Any, ...] | None,
                      *, strict_provenance: bool = False,
                      snapshot_resolver: Callable[[str], dict[str, Any] | None] | None = None
                      ) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(evidence or [], 1):
        if isinstance(item, str):
            text = item
            source = f"evidence:{i}"
            eid = f"E{i}"
            assessment = SourceAssessment("unknown", False, "裸文本无来源")
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("snippet") or item.get("content") or "")
            source = str(item.get("source") or item.get("id") or f"evidence:{i}")
            eid = str(item.get("id") or f"E{i}")
            # 信任等级由服务端根据来源标识重新判定，不能采信调用方自报的
            # trust 字段；否则 API 调用方可以把百度百科伪装成官方来源。
            snapshot_id = str(item.get("snapshot_id") or "").strip()
            snapshot = None
            if snapshot_id and snapshot_resolver is not None:
                try:
                    snapshot = snapshot_resolver(snapshot_id)
                except Exception:
                    snapshot = None
            assessment = assess_source(source, item, text,
                                       strict_provenance=strict_provenance,
                                       snapshot=snapshot)
        else:
            continue
        text = text.strip()
        if text:
            rows.append({
                "id": eid, "source": source, "text": text, "trust": assessment.trust,
                "source_verified": assessment.verified,
                "verification_reason": assessment.reason,
                "source_host": assessment.host,
                "content_hash_ok": assessment.content_hash_ok,
                "snapshot_id": assessment.snapshot_id,
                "snapshot_verified": assessment.snapshot_verified,
            })
    return rows


@dataclass
class ClaimVerdict:
    claim: str
    risk: str
    status: str
    confidence: float
    evidence_id: str
    matched_terms: int
    number_ok: bool
    source_trust: str = ""
    source_verified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"claim": self.claim, "risk": self.risk, "status": self.status,
                "confidence": round(self.confidence, 3), "evidence_id": self.evidence_id,
                "matched_terms": self.matched_terms, "number_ok": self.number_ok,
                "source_trust": self.source_trust,
                "source_verified": self.source_verified}


class EvidenceVerifier:
    """可替换的证据闸门；未来可在同一接口后接入 cross-encoder / NLI。"""

    thresholds = {"high": 0.42, "medium": 0.28, "low": 0.18}

    def _score(self, claim: str, evidence: dict[str, str]) -> tuple[float, int, bool]:
        cterms = _terms(claim)
        eterms = _terms(evidence["text"])
        if not cterms:
            return 0.0, 0, True
        matched = cterms & eterms
        overlap = len(matched) / max(1, len(cterms))
        cnums, enums = _numbers(claim), _numbers(evidence["text"])
        number_ok = not cnums or cnums <= enums
        if cnums and not number_ok:
            overlap *= 0.55
        # 长词命中比单纯的字符 bigram 更可靠，少量加成为可解释的排序信号。
        phrase_bonus = 0.08 if any(len(t) >= 3 and t in evidence["text"].lower() for t in cterms) else 0.0
        return min(1.0, overlap + phrase_bonus), len(matched), number_ok

    def verify_claim(self, claim: str, evidence: list[dict[str, str]]) -> ClaimVerdict:
        risk = _risk_level(claim)
        eligible = evidence
        if risk == "high":
            # 高风险结论不能靠普通百科、社区或教学召回“撞词”通过；
            # 官方来源还必须有服务端可核验的域名/哈希，不能只看显示名。
            eligible = [row for row in evidence
                        if row.get("trust") in _HIGH_RISK_TRUST
                        and (row.get("trust") != "official" or row.get("source_verified"))]
        if not eligible:
            return ClaimVerdict(claim, risk, "unsupported", 0.0, "", 0, False)
        scored = []
        for row in eligible:
            score, matched, number_ok = self._score(claim, row)
            scored.append((score, matched, number_ok, row["id"], row.get("trust", "unknown"),
                           bool(row.get("source_verified"))))
        score, matched, number_ok, eid, trust, verified = max(
            scored, key=lambda x: (x[0], x[1]))
        threshold = self.thresholds.get(risk, 0.25)
        if score >= threshold and number_ok:
            status = "supported"
        elif score > 0.12 and number_ok:
            status = "weak"
        else:
            status = "unsupported"
        return ClaimVerdict(claim, risk, status, score, eid, matched, number_ok, trust, verified)

    def audit(self, content: str, evidence: list[Any] | tuple[Any, ...] | None,
              *, strict_provenance: bool = False,
              snapshot_resolver: Callable[[str], dict[str, Any] | None] | None = None
              ) -> dict[str, Any]:
        rows = normalize_evidence(evidence, strict_provenance=strict_provenance,
                                  snapshot_resolver=snapshot_resolver)
        claims = split_claims(content)
        verdicts = [self.verify_claim(claim, rows) for claim in claims]
        supported = sum(1 for v in verdicts if v.status == "supported")
        cited = sum(1 for v in verdicts if v.evidence_id)
        high_fail = [v for v in verdicts if v.risk == "high" and v.status != "supported"]
        weak = [v for v in verdicts if v.status == "weak"]
        support_rate = supported / max(1, len(verdicts))
        citation_coverage = cited / max(1, len(verdicts))
        trust_counts: dict[str, int] = {}
        verified_counts: dict[str, int] = {}
        source_issues: list[dict[str, Any]] = []
        for row in rows:
            trust = row.get("trust", "unknown")
            trust_counts[trust] = trust_counts.get(trust, 0) + 1
            if row.get("source_verified"):
                verified_counts[trust] = verified_counts.get(trust, 0) + 1
            elif trust in _HIGH_RISK_TRUST:
                source_issues.append({"id": row.get("id", ""), "source": row.get("source", ""),
                                      "trust": trust,
                                      "reason": row.get("verification_reason", "")})
        if high_fail:
            decision = "human_review"
            reason = f"高风险 claim 未获充分证据支持：{len(high_fail)} 条"
        elif not verdicts:
            decision = "allow"
            reason = "没有可核验的事实 claim"
        elif support_rate < 0.7 or weak:
            decision = "retry"
            reason = f"支持率 {support_rate:.0%}，存在弱证据 claim"
        else:
            decision = "allow"
            reason = "claim 证据覆盖通过"
        return {
            "method": "deterministic_lexical_numeric_gate_v2",
            "source_policy": "high_risk_requires_official_curated_or_observed",
            "source_verification_policy": "official_requires_server_snapshot_and_evidence_span",
            "strict_provenance": bool(strict_provenance),
            "source_verified_counts": verified_counts,
            "source_issues": source_issues,
            "decision": decision,
            "blocked": bool(high_fail),
            "reason": reason,
            "claim_count": len(verdicts),
            "supported": supported,
            "weak": len(weak),
            "unsupported": sum(1 for v in verdicts if v.status == "unsupported"),
            "support_rate": round(support_rate, 3),
            "citation_coverage": round(citation_coverage, 3),
            "high_risk_failures": [v.as_dict() for v in high_fail],
            "claims": [v.as_dict() for v in verdicts],
            "evidence_count": len(rows),
            "source_trust_counts": trust_counts,
        }

    def verify(self, content: str, evidence: list[Any] | tuple[Any, ...] | None,
               *, strict_provenance: bool = False,
               snapshot_resolver: Callable[[str], dict[str, Any] | None] | None = None
               ) -> dict[str, Any]:
        return self.audit(content, evidence, strict_provenance=strict_provenance,
                          snapshot_resolver=snapshot_resolver)


_verifier: EvidenceVerifier | None = None


def get_verifier() -> EvidenceVerifier:
    global _verifier
    if _verifier is None:
        _verifier = EvidenceVerifier()
    return _verifier
