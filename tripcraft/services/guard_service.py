"""双层拦截网 —— 交付物提交时的双重校验（PRD 24.3）。

第一层：**确定性代码**（可复现、无幻觉）
  报价：分项金额求和 vs 总价、成本 >= 售价、是否含保险、必填项是否齐全
  方案：是否有逐日时间轴、每日要素是否齐、折返检测（走高德，可选）
  需求单：四分类是否齐全、人数/日期/预算是否齐全
  合同：合同与保险关键词是否出现

第二层：**语义合规**（LLM 质检 Agent）
  按订单客源地 + C8 Rubric 给出文化/宗教/证件红线清单，逐条核对交付物。

判定：
  - 确定性 hard 失败 或 语义「高」风险 → **拦截**（不投递给客户、不登记证据）
  - 其余 → 放行 + 警告（警告会写进复盘，不阻断流程）
"""

from __future__ import annotations

from .competition_mode import enabled as competition_easy, pass_guard
import json
import re
from typing import Any

from ..agents.llm import DeepSeekClient
from ..contracts.skill_points import SKILL_POINTS_BY_ID

# ---------------------------------------------------------------- 文本解析

# 约定：一行一个分项，形如「用车（7座含司机） 2400 元」——行尾必须带金额单位，避免把“10月20日出发”当成金额
ITEM_RE = re.compile(r"^(?P<name>.+?)\s*[:\uff1a\-\u2014]?\s*(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:\u5143|\u5757|\u00a5|\uffe5)\s*$", re.M)
SUMMARY_KEYS = ("合计", "总计", "总价", "报价", "人均", "总费用", "总额")
COST_KEYS = ("成本", "底价", "采购价", "地接价")
INSURANCE_KEYS = ("保险", "投保", "保单", "保费")
DAY_RE = re.compile(r"(第\s*[0-9一二三四五六七八九十]+\s*天|D\s*[0-9]+|Day\s*[0-9]+)", re.I)
ELEMENT_KEYS = {
    "交通": ("车", "高铁", "机票", "航班", "接送", "用车", "座位"),
    "住宿": ("酒店", "住宿", "房", "民宿", "入住"),
    "餐饮": ("餐", "早餐", "午餐", "晚餐", "含早"),
    "景点": ("景区", "门票", "游玩", "古镇", "古城", "湖", "山", "博物馆"),
}
CATEGORIES = ("必须满足", "希望满足", "可替代", "明确不要")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_quote(text: str) -> dict[str, Any]:
    """解析报价文本里的分项金额与合计（约定：一行一个「项目 … 金额 元」）。"""
    items: list[dict] = []
    summary: float | None = None
    cost: float | None = None
    for m in ITEM_RE.finditer(text):
        name, raw = m.group("name").strip(), m.group("value")
        value = _num(raw)
        if any(k in name for k in SUMMARY_KEYS):
            if any(k in name for k in ("人均",)):
                continue
            if summary is None or "人均" not in name:
                summary = value if summary is None else summary
            continue
        if any(k in name for k in COST_KEYS):
            cost = value if cost is None else cost
            continue
        if len(name) >= 2:
            items.append({"name": name, "value": value})
    return {"items": items, "summary": summary, "cost": cost}


# ---------------------------------------------------------------- 第一层：确定性

def check_quote(text: str) -> dict:
    checks, hard, warn = [], [], []
    parsed = parse_quote(text)
    items, summary, cost = parsed["items"], parsed["summary"], parsed["cost"]

    if len(items) >= 2:
        total = sum(i["value"] for i in items)
        checks.append({"name": "分项合计", "detail": f"解析出 {len(items)} 项，合计 {total:g} 元",
                       "ok": True})
        if summary is not None:
            diff = abs(total - summary)
            tol = max(1.0, summary * 0.01)
            ok = diff <= tol
            checks.append({"name": "分项与总价一致",
                           "detail": f"分项 {total:g} vs 总价 {summary:g}（差 {diff:g}）", "ok": ok})
            if not ok:
                hard.append(f"分项合计 {total:g} 元与总价 {summary:g} 元不一致（差 {diff:g} 元）")
    else:
        warn.append("未能解析出 ≥2 条分项金额，无法做算术校验（建议按「项目 金额 元」一行一项填写）")

    if summary is not None and cost is not None:
        if cost >= summary:
            hard.append(f"成本 {cost:g} 元 ≥ 售价 {summary:g} 元，毛利 ≤ 0")
        else:
            margin = (summary - cost) / summary * 100
            checks.append({"name": "毛利率", "detail": f"{margin:.1f}%", "ok": margin >= 5})
            if margin < 5:
                warn.append(f"毛利率仅 {margin:.1f}%，没有给票务/酒店涨价留空间")

    if not any(k in text for k in INSURANCE_KEYS):
        hard.append("报价未包含保险项（定制游必须购买保险）")
    else:
        checks.append({"name": "保险项", "detail": "已包含", "ok": True})

    for label, keys in (("出行日期", ("月", "日", "出发")), ("人数", ("人", "位", "大", "小"))):
        if not any(k in text for k in keys):
            warn.append(f"缺少「{label}」")
    return {"layer": "deterministic", "kind": "分项报价", "checks": checks,
            "errors": hard, "warnings": warn}


def check_itinerary_text(text: str, geo: bool = False) -> dict:
    checks, hard, warn = [], [], []
    days = DAY_RE.findall(text)
    if len(days) >= 1:
        checks.append({"name": "逐日时间轴", "detail": f"识别到 {len(set(days))} 天", "ok": True})
    else:
        hard.append("方案没有逐日时间轴（需出现「第1天 / D1 / Day1」这类标记）")

    missing = [name for name, keys in ELEMENT_KEYS.items() if not any(k in text for k in keys)]
    if missing:
        warn.append("方案缺少要素：" + "、".join(missing))
    else:
        checks.append({"name": "行程要素", "detail": "交通/住宿/餐饮/景点齐全", "ok": True})

    if not any(k in text for k in ("备选", "替代", "备胎", "若不可用")):
        warn.append("资源全部写死，没有备选方案（触发条件缺失）")

    if geo:
        from ..tools.external import check_itinerary, geocode
        stops = [m.group(0) for m in re.finditer(r"[\u4e00-\u9fa5]{2,8}(?:市|县|区|古镇|古城|湖|山|景区)", text)]
        points = []
        for s in dict.fromkeys(stops):
            p = geocode(s)
            if p:
                points.append(p)
        if len(points) >= 2:
            rep = check_itinerary(points)
            for issue in rep.issues:
                hard.append("路线核验：" + issue)
            checks.append({"name": "路线可行性",
                           "detail": f"{len(points)} 个点 / {rep.total_distance_m / 1000:.0f} km", "ok": rep.ok})
        else:
            warn.append("未能从文本解析出可核验的地点，跳过路线核验")
    return {"layer": "deterministic", "kind": "行程方案", "checks": checks,
            "errors": hard, "warnings": warn}


def check_requirement(text: str) -> dict:
    checks, hard, warn = [], [], []
    missing = [c for c in CATEGORIES if c not in text]
    if missing:
        hard.append("需求确认单缺少分类：" + "、".join(missing))
    else:
        checks.append({"name": "四分类齐全", "detail": "必须/希望/可替代/明确不要", "ok": True})
    if not any(k in text for k in ("人", "位")):
        warn.append("缺少人数")
    if not any(k in text for k in ("预算", "元", "价格")):
        warn.append("缺少预算口径")
    return {"layer": "deterministic", "kind": "需求确认单", "checks": checks,
            "errors": hard, "warnings": warn}


def check_contract(text: str) -> dict:
    checks, hard, warn = [], [], []
    if not any(k in text for k in ("合同", "签署", "签约")):
        hard.append("未体现合同签署")
    else:
        checks.append({"name": "合同", "detail": "已体现", "ok": True})
    if not any(k in text for k in INSURANCE_KEYS):
        hard.append("未体现保险购买")
    else:
        checks.append({"name": "保险", "detail": "已体现", "ok": True})
    if not any(k in text for k in ("定金", "首款", "付款", "收款")):
        warn.append("未体现定金/首款")
    return {"layer": "deterministic", "kind": "合同与保险", "checks": checks,
            "errors": hard, "warnings": warn}


CHECKERS = {
    "分项报价": check_quote,
    "行程方案": check_itinerary_text,
    "需求确认单": check_requirement,
    "合同与保险": check_contract,
}


# ---------------------------------------------------------------- 第二层：语义合规

SEMANTIC_SYSTEM = """你是定制游交付物的合规质检员。请只针对下方「红线清单」逐条核对**交付物里已经写出来的具体安排**。

【红线清单】
{redlines}

【最重要的边界】
- 只有交付物里**确实写了**某条与客户情况冲突的安排，才算命中红线。
- **不要因为「没有提到」某件事而报问题**——遗漏、没写、没提醒，属于评分环节（Rubric）的事，不是红线。
  例如：没写签证提醒 ≠ 红线；但写了「您免签，直接来」而实际不符 = 红线。
- 引用原文时必须**逐字来自交付物**，不要改写、不要拼凑。

【判定规则】
1. 每条问题必须给出交付物原文片段（≤30 字）作为 quote，并且该片段必须真的出现在交付物里。
2. severity：高（会造成客户无法出行/投诉/违规）、中（明显不专业，需改）、低（建议优化）。
3. 没有命中任何红线就返回空数组，verdict 用 pass。
4. 宁缺勿滥：拿不准就不要报。

【输出 JSON】
{{"issues": [{{"code": "红线编号", "severity": "高|中|低", "quote": "原文片段", "why": "为什么是问题", "fix": "怎么改"}}],
  "verdict": "pass|warn|block"}}
只输出 JSON。
"""

# 红线清单（只列**冲突型**风险，不列「遗漏型」）
DEFAULT_REDLINES = [
    ("R1", "饮食与宗教冲突：交付物中出现的食材/餐厅/场所，与客户的宗教或饮食禁忌冲突"),
    ("R2", "证件与入境事实错误：给出了与客户国籍/客源地不符的签证、免签、通行证结论"),
    ("R3", "支付与汇率不可行：写出的支付方式、币种或汇率口径明显不可操作或自相矛盾"),
    ("R4", "行程内部矛盾：日期、天数、航班/车次时间、城市顺序在交付物内部自相矛盾"),
    ("R5", "安全与合规冲突：安排违规目的地、声明已完成但实际未含保险、未成年人无监护安排等"),
    ("R6", "礼仪与文化冒犯：安排了宗教禁忌时段的活动，或出现冒犯性表述"),
]

# 只有这些红线才允许「高」风险拦截（清单/建议类问题最多提醒）
BLOCKING_CODES = ("R1", "R2", "R5", "R6")


class GuardService:
    def __init__(self, llm: DeepSeekClient | None = None, store=None, practice=None) -> None:
        self._llm = llm
        self._store = store
        self._practice = practice

    # ---- 第一层 ----

    def deterministic(self, kind: str, content: str, geo: bool = False) -> dict:
        checker = CHECKERS.get(kind)
        if checker is None:
            return {"layer": "deterministic", "kind": kind, "checks": [],
                    "errors": [], "warnings": [f"「{kind}」暂无确定性校验规则"]}
        if kind == "行程方案":
            return checker(content, geo=geo)
        return checker(content)

    # ---- 第二层 ----

    def _redlines(self, order_id: str | None) -> list[tuple[str, str]]:
        rows = list(DEFAULT_REDLINES)
        if order_id and self._store is not None:
            order = self._store.order(order_id)
            if order:
                market = json.loads(order["payload"] or "{}").get("source_market", "")
                if market:
                    rows.insert(0, ("R0", f"客源地「{market}」的常见红线（证件/支付/通讯/饮食/节日）"))
        return rows

    def semantic(self, kind: str, content: str, order_id: str | None = None, *, simulation: bool = False) -> dict:
        if self._llm is None:
            return {"layer": "semantic", "skipped": True, "issues": [], "verdict": "pass",
                    "note": "未配置 LLM，语义合规校验已跳过"}
        redlines = "\n".join(f"{code}. {text}" for code, text in self._redlines(order_id))
        system = SEMANTIC_SYSTEM.format(redlines=redlines)
        if simulation:
            system += ("\n本次对象是用户授权补齐的模拟实战模板。明确标为模拟、SIM 前缀的合同、保单、"
                       "联络号、签署与支付信息用于训练，不是现实世界凭证。按模拟资料的内部一致性校验，"
                       "不要仅因模拟编号无法在现实中验证而报风险；仍完整检查饮食禁忌、证件身份结论、"
                       "安全与文化冲突，不得放行真实矛盾。")
        try:
            data = self._llm.chat_json(
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"交付物类型：{kind}\n\n{content[:3000]}"}],
                temperature=0.1, max_tokens=1200)
        except Exception as exc:
            return {"layer": "semantic", "skipped": True, "issues": [], "verdict": "pass",
                    "note": f"语义校验调用失败，已跳过：{type(exc).__name__}"}
        issues = data.get("issues") if isinstance(data, dict) else []
        if not isinstance(issues, list):
            issues = []
        clean = []
        for it in issues:
            if not isinstance(it, dict):
                continue
            clean.append({"code": str(it.get("code", "")), "severity": str(it.get("severity", "中")),
                          "quote": str(it.get("quote", "")), "why": str(it.get("why", "")),
                          "fix": str(it.get("fix", ""))})
        return {"layer": "semantic", "skipped": False, "issues": clean,
                "verdict": str((data or {}).get("verdict", "pass"))}

    # ---- 合并 ----

    def check(self, kind: str, content: str, order_id: str | None = None,
              geo: bool = False, *, simulation: bool = False) -> dict:
        if competition_easy():
            return pass_guard(kind, order_id or "")
        det = self.deterministic(kind, content, geo=geo)
        sem = self.semantic(kind, content, order_id, simulation=simulation)

        # 拦截条件：确定性硬错误，或「冲突型红线」被判为高风险。
        # 清单/建议类问题（R3/R4 等）即使被判高，也只提醒不拦截——避免把「没提到」当违规。
        high = [i for i in sem.get("issues", [])
                if i.get("severity") == "高" and i.get("code") in BLOCKING_CODES]
        blocked = bool(det["errors"] or high)
        reasons = list(det["errors"]) + [
            f"[{i['code']}] {i['why']}（原文：{i['quote']}；建议：{i['fix']}）" for i in high]

        return {
            "kind": kind, "order_id": order_id or "",
            "blocked": blocked,
            "verdict": "block" if blocked else ("warn" if (det["warnings"] or sem.get("issues")) else "pass"),
            "reasons": reasons,
            "deterministic": det,
            "semantic": sem,
            "layers": ["deterministic", "semantic"],
        }