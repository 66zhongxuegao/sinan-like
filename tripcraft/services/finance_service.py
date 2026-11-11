"""成本 · 损失 · 结算台账（PRD 6.2 / 28.24）。

**为什么需要它**：能力点 C5.1–C5.8（成本核算 / 毛利测算 / 结算对账）与 C6.7（成本记录闭环）
一直都在，但系统里原本没有「真实的账」——学员在交付物里填多少利润就是多少，没人核对。
这里把每一步真实发生的成本、损失、赔付记成台账，最后算出这一单的实际毛利。

**口径（全部写死，可审计）**
- 收入 = 客户确认的报价总额（分项报价交付物）+ 收入类台账
- 成本 = 资源口径成本 + 必选保险；资源口径成本**优先取地接社的组合报价**，
  没有地接组合报价时用酒店/车队/票务分项加总（避免同一笔钱算两遍）
- 损失 = 突发事件造成的、最终由我方承担的金额（涨价差额 / 换车费 / 超售差价 / 结算差额 / 客户补偿）
- 毛利 = 收入 − 成本 − 损失；毛利率 = 毛利 / 收入

**责任认定（写死，这是「协调赔偿」的评分依据）**
- 向资源方追偿比例：车队 100% / 酒店 60% / 地接社 50% / 票务 0%（航司调价不可追偿）
- 转嫁客户：只有「可转嫁」的费用、且订单**还没走到客户确认合同**时才成立；否则客户不接受，仍由我方承担
- 一直不处理的：默认我方承担（不处理就是自己吃下，这也是一种成本控制失分）
"""

from __future__ import annotations

import json
import re
import time

from .supplier_service import _party

# 责任认定（写死）
RECOURSE_RATIO: dict[str, float] = {"车队": 1.0, "酒店": 0.6, "地接社": 0.5, "票务": 0.0}
# 客户拒绝接纳的临界阶段：走到「客户确认合同」之后，再涨价只能我方消化
CUSTOMER_ACCEPT_MAX_STAGE = 3
# 必选保险（定制游必须买保险，PRD 硬规则）
INSURANCE_PER_PERSON = 30

# 愿意承担责任的追偿话术关键词（学员在资源方群里说这些话 = 发起追偿/索赔）
RECOURSE_WORDS = ("承担", "赔付", "赔偿", "补差", "差价你们", "免了", "减免", "扣掉",
                  "你们负责", "你们这边出", "走你们的", "认这笔")
# 学员明确表示自己吃下
ABSORB_WORDS = ("我们自己承担", "我们承担", "算我们的", "公司承担", "先垫", "我方承担")

DAYS_RE = re.compile(r"(\d+)\s*(?:天|日|晚)")


def _days(payload: dict) -> int:
    """出行天数：从派单的 days 字段解析，缺就按 5 天估（并在返回里标注）。"""
    text = str(payload.get("days") or "")
    m = DAYS_RE.search(text)
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"(\d+)", text)
    if m:
        return max(1, int(m.group(1)))
    return 5


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


class FinanceService:
    """订单级成本 / 损失 / 结算台账。"""

    def __init__(self, store, practice=None) -> None:
        self._store = store
        self._practice = practice

    # ---------- 台账 ----------

    def add_entry(self, order_id: str, code: str, label: str, amount: float,
                  category: str = "loss", supplier_kind: str = "", source: str = "",
                  ref: str = "", note: str = "", transferable: bool = False,
                  entry_id: str = "") -> dict:
        """记一笔成本/损失/赔付。金额为 0 的不记（避免台账全是噪声）。"""
        amount = round(float(amount or 0), 2)
        if not amount:
            return {}
        eid = entry_id or f"fin-{order_id}-{code}-{int(time.time() * 1000) % 1000000}"
        note = note or ("" if not transferable else "此类费用在客户确认合同前可与客户协商")
        self._store.add_finance_entry(eid, order_id, code, label, category, amount,
                                      supplier_kind=supplier_kind, source=source, ref=ref,
                                      note=note)
        return self._store.finance_entry(eid) or {}

    def add_incident_cost(self, order_id: str, cost: dict, ref: str = "",
                          order: dict | None = None) -> dict:
        """把突发事件折算成台账金额（口径写死在规则里）。"""
        if not cost:
            return {}
        row = order or self._store.order(order_id) or {}
        payload = json.loads(row.get("payload") or "{}")
        party = _party(payload)
        amount = float(cost.get("amount_fixed") or 0)
        unit = cost.get("unit") or ""
        per = float(cost.get("amount_per") or 0)
        if per and unit == "人":
            amount += per * max(1, party["total"])
        elif per and unit == "间晚":
            rooms = max(1, -(-party["total"] // 2))
            amount += per * rooms
        elif per:
            amount += per
        return self.add_entry(order_id, cost.get("code") or cost.get("label") or "INCIDENT",
                              cost.get("label") or "突发损失", amount,
                              category=cost.get("category") or "loss",
                              supplier_kind=cost.get("kind") or "", source="incident",
                              ref=ref, transferable=bool(cost.get("transferable")))

    def entries(self, order_id: str) -> list[dict]:
        return self._store.finance_entries(order_id)

    def decide(self, order_id: str, entry_id: str, bearer: str, note: str = "") -> dict:
        """给一笔损失定责：我方承担 / 向资源方追偿 / 转嫁客户。

        比例与是否允许全部写死：这是「协调赔偿」能被考核的关键——
        不是学员说一句「你们赔」就真能追回来。
        """
        row = self._store.finance_entry(entry_id)
        if not row or row["order_id"] != order_id:
            raise ValueError(f"未找到台账项: {entry_id}")
        amount = float(row["amount"] or 0)
        kind = row["supplier_kind"] or ""
        msg, ours, status = "", amount, "已定责"
        if bearer == "资源方":
            ratio = RECOURSE_RATIO.get(kind, 0.5)
            ours = round(amount * (1 - ratio), 2)
            if ratio <= 0:
                msg = (f"{kind}这边是航司/上游调价，我们承担不了；你要留位就得尽快确认。")
                status = "已定责"
            else:
                msg = (f"行，这次是我们的问题，{round(amount * ratio, 2):g} 元我们认，"
                       f"结算单上直接扣。")
        elif bearer == "客户":
            order = self._store.order(order_id) or {}
            stage = int(order.get("stage_index") or 0)
            if not row["note"].startswith("此类费用在客户确认合同前") and "可转嫁" not in (row["note"] or ""):
                ours, msg = amount, "这笔属于我方或资源方责任，客户不会接受，还是要我们承担。"
            elif stage > CUSTOMER_ACCEPT_MAX_STAGE:
                ours = amount
                msg = "合同都确认了才说涨价，客户不认；这笔只能我们自己吃下。"
            else:
                ours, msg = 0.0, "客户接受了这笔调整（需要你在方案里说明清楚）。"
        else:
            ours, msg = amount, "记在我方成本里。"
        if note:
            msg = f"{msg}（{note}）"
        self._store.update_finance_entry(entry_id, bearer=bearer, ours=ours, status=status,
                                         note=((row["note"] + " / ") if row["note"] else "") + msg)
        # 定责动作本身要留痕：复盘要能引用「学员把哪一笔损失谈给了谁」，
        # 只留在台账里的话，评分 Agent 看不到学员做过什么。
        if self._practice is not None:
            # 证据里写清「哪一笔损失谈给了哪个具体资源方」：复盘与评分要能指认责任方，
            # 只写「资源方」的话标准案例里指认不出是酒店还是车队。
            responsible = kind or ("我方" if bearer == "我方" else bearer)
            self._practice.record_evidence(
                order_id, "定责",
                f"【损失定责·{row['label']}】{amount:g} 元 → {bearer}"
                f"（责任方：{responsible}；我方承担 {ours:g} 元）｜{msg}",
                ref=entry_id)
        result = {"entry": self._store.finance_entry(entry_id), "message": msg,
                  "supplier_kind": kind, "bearer": bearer}
        return result

    def resolve_supplier_kind(self, order_id: str, text: str,
                              session_kind: str = "") -> str:
        """把「学员在群里说的这句话」定位到具体资源方（供追偿归因）。

        这是「资源大群追偿找不到具体资源方」的修复核心：
        资源大群的会话 kind 是笼统的「资源方」，而台账里的 supplier_kind 是
        酒店/车队/地接社/票务；不先定位就会出现「说了追偿但匹配不到任何台账项」。
        规则：话里点名优先 → 会话本身就是具体资源方 → 该单只有一类待处理损失时用它。
        """
        from .supplier_service import CONCRETE_SUPPLIER_KINDS, mentioned_supplier_kind

        named = mentioned_supplier_kind(text)
        if named:
            return named
        if session_kind in CONCRETE_SUPPLIER_KINDS:
            return session_kind
        pending: list[str] = []
        for e in self.entries(order_id):
            kind = str(e.get("supplier_kind") or "")
            if e.get("status") == "待处理" and kind and kind not in pending:
                pending.append(kind)
        return pending[0] if len(pending) == 1 else ""

    def maybe_attribute_from_chat(self, order_id: str, supplier_kind: str,
                                  text: str) -> dict | None:
        """学员在资源方群里谈追偿/赔付 → 按写死比例定责，并给一句资源方回复。

        这是「协调赔偿」的入口：学员得真的开口谈，不然损失全算在自己头上。
        返回形状：
        - None：没有待处理损失 / 这句话不是追偿或自担话术；
        - {"need_supplier": [...], "message": ...}：待处理损失有多类而话里没指名，
          要求学员点名（不替他猜是酒店还是车队）；
        - decide() 结果：已定责，附带 resolved_supplier_kind / supplier_kind。
        """
        if not text:
            return None
        pending_by_kind: dict[str, list[dict]] = {}
        for e in self.entries(order_id):
            if e["status"] == "待处理" and e.get("supplier_kind"):
                pending_by_kind.setdefault(e["supplier_kind"], []).append(e)
        if not pending_by_kind:
            return None

        resolved = supplier_kind if supplier_kind in pending_by_kind else ""
        if not resolved:
            resolved = self.resolve_supplier_kind(order_id, text, supplier_kind)
        if not resolved:
            if len(pending_by_kind) > 1:
                return {"need_supplier": sorted(pending_by_kind),
                        "message": "请指明向哪一家追偿：" + "、".join(sorted(pending_by_kind))
                                   + "（在群里点名说清楚，责任才能落到具体资源方）"}
            resolved = next(iter(pending_by_kind))

        target_entries = pending_by_kind.get(resolved) or []
        if not target_entries:
            return None
        if any(w in text for w in ABSORB_WORDS):        # 「我们自己承担」优先于追偿关键词
            target, bearer = target_entries[0], "我方"
        elif any(w in text for w in RECOURSE_WORDS):
            target, bearer = target_entries[0], "资源方"
        else:
            return None
        result = self.decide(order_id, target["entry_id"], bearer)
        result["supplier_kind"] = resolved
        return result

    # ---------- 成本口径 ----------

    def baseline_cost(self, order_id: str) -> dict:
        """资源口径成本：按该单询到的资源价 × 人数/间数/天数算出来，是客观基线。

        优先用地接社的组合报价（真实业务里地接就是打包），没有才分项加总，
        否则同一笔住宿会被算两遍。
        """
        row = self._store.order(order_id) or {}
        payload = json.loads(row.get("payload") or "{}")
        party = _party(payload)
        days = _days(payload)
        nights = max(1, days - 1)
        rooms = max(1, -(-party["total"] // 2))
        quotes = self._store.quotations(order_id) or {}
        items: list[dict] = []

        def price(kind: str, needle: str) -> float:
            q = quotes.get(kind) or {}
            items = q.get("items") or []
            for it in items:
                if needle in str(it.get("name") or ""):
                    return _num(it.get("price"))
            # 地接组合报价把车型写成“7 座商务/5 座轿车”，没有“用车”二字；
            # 结算仍要按同一组合报价里的车型单价计入用车成本，不能漏项。
            if needle == "用车":
                for it in items:
                    name = str(it.get("name") or "")
                    if ("座" in name or "车" in name) and _num(it.get("price")) > 0:
                        return _num(it.get("price"))
            return 0.0

        if quotes.get("地接社"):
            items.append({"name": "住宿（地接组合）", "qty": f"{rooms} 间 × {nights} 晚",
                          "amount": round(price("地接社", "住宿") * rooms * nights)})
            items.append({"name": "用车（地接组合）", "qty": f"{days} 天",
                          "amount": round(price("地接社", "用车") * days)})
            items.append({"name": "导游（地接组合）", "qty": f"{days} 天",
                          "amount": round(price("地接社", "导游") * days)})
            items.append({"name": "门票（首道）", "qty": f"{party['total']} 人",
                          "amount": round(price("地接社", "门票") * party["total"])})
            source = "地接社组合报价"
        else:
            if quotes.get("酒店"):
                items.append({"name": "住宿", "qty": f"{rooms} 间 × {nights} 晚",
                              "amount": round(price("酒店", "四星") * rooms * nights)})
            if quotes.get("车队"):
                items.append({"name": "用车", "qty": f"{days} 天",
                              "amount": round(price("车队", "7 座") * days)})
            if quotes.get("票务"):
                items.append({"name": "大交通", "qty": f"{party['total']} 人",
                              "amount": round(price("票务", "高铁") * party["total"])})
            source = "分项资源方报价"

        items.append({"name": "旅游意外保险（必选）", "qty": f"{party['total']} 人",
                      "amount": INSURANCE_PER_PERSON * party["total"]})
        items = [i for i in items if i["amount"]]
        estimated = not (payload.get("days") or payload.get("party"))
        return {"total": round(sum(i["amount"] for i in items), 2), "items": items,
                "source": source, "days": days, "rooms": rooms, "people": party["total"],
                "estimated": estimated,
                "note": ("派单没给人数/天数，按 2 人 5 天估算" if estimated else "")}

    # ---------- 收入 / 结算 ----------

    def declared(self, order_id: str) -> dict:
        """学员自己在交付物里填的口径（报价总额、成本、实际成本、实际利润）。"""
        out: dict[str, float] = {}
        spec = (("分项报价", ("total", "per_person", "cost")),
                ("地接结算核对单", ("total_settle", "total_ours", "diff", "actual_cost", "actual_margin")),
                ("回访与复盘记录", ("profit",)))
        for did, keys in spec:
            row = self._store.deliverable(order_id, did)
            if not row:
                continue
            try:
                values = json.loads(row["values_json"] or "{}")
            except Exception:
                values = {}
            for k in keys:
                if values.get(k) not in (None, ""):
                    out[f"{did}.{k}"] = _num(values[k])
        return out

    def summary(self, order_id: str) -> dict:
        """本单实际账：收入 − 资源口径成本 − 我方承担的损失 = 实际毛利。"""
        base = self.baseline_cost(order_id)
        entries = self.entries(order_id)
        declared = self.declared(order_id)

        def effective(e: dict) -> float:
            """没定责的损失默认我方承担——不处理就是自己吃下（这是成本控制失分点）。"""
            return float(e["amount"] or 0) if e["status"] == "待处理" else float(e["ours"] or 0)

        revenue = declared.get("分项报价.total", 0.0)
        revenue += sum(float(e["amount"] or 0) for e in entries if e["category"] == "revenue")
        extra_cost = sum(effective(e) for e in entries if e["category"] == "cost")
        cost = round(base["total"] + extra_cost, 2)
        loss = round(sum(effective(e) for e in entries
                         if e["category"] in ("loss", "compensation")), 2)
        profit = round(revenue - cost - loss, 2)
        margin = round(profit / revenue, 4) if revenue else 0.0
        # 还没提交分项报价就没有收入口径，不能拿「未报价」当亏损
        grade = settlement_grade(margin) if revenue else "未报价"

        pending = [e for e in entries if e["status"] == "待处理"]
        # 与学员填报口径的偏差——成本控制与盈利能力的考核点
        gaps = []
        claim_cost = declared.get("分项报价.cost")
        if claim_cost is not None:
            gaps.append({"name": "自报成本 vs 资源口径", "declared": claim_cost,
                         "actual": base["total"], "diff": round(base["total"] - claim_cost, 2)})
        claim_profit = declared.get("回访与复盘记录.profit")
        if claim_profit is None:
            claim_profit = declared.get("地接结算核对单.actual_margin")
        if claim_profit is not None:
            gaps.append({"name": "自报利润 vs 实际毛利", "declared": claim_profit,
                         "actual": profit, "diff": round(profit - claim_profit, 2)})
        return {"order_id": order_id, "revenue": round(revenue, 2), "cost": cost, "loss": loss,
                "profit": profit, "margin": margin, "grade": grade,
                "cost_source": base["source"], "cost_items": base["items"],
                "people": base["people"], "days": base["days"], "rooms": base["rooms"],
                "cost_estimated": base.get("estimated", False), "cost_note": base.get("note", ""),
                "entries": entries, "pending": len(pending), "gaps": gaps,
                "declared": declared}

    def settle(self, order_id: str) -> dict:
        """结账：汇总并落库；同时写一条 S11 证据，让评分 Agent 看得到真实账目。"""
        summary = self.summary(order_id)
        detail = {"cost_items": summary["cost_items"], "gaps": summary["gaps"],
                  "entries": [{"code": e["code"], "label": e["label"], "amount": e["amount"],
                               "bearer": e["bearer"], "ours": e["ours"], "status": e["status"]}
                              for e in summary["entries"]]}
        self._store.save_settlement(order_id, {**summary, "detail": detail})

        evidence_id = None
        if self._practice is not None:
            lines = [f"【结算·订单 {order_id}】",
                     f"客户确认收入 {summary['revenue']:g} 元",
                     f"资源口径成本 {summary['cost']:g} 元（{summary['cost_source']}）"]
            for it in summary["cost_items"]:
                lines.append(f"　- {it['name']} {it['qty']}：{it['amount']:g} 元")
            for e in summary["entries"]:
                lines.append(f"　- {e['label']} {e['amount']:g} 元 → {e['bearer']}"
                             f"（我方承担 {e['ours']:g}）")
            lines.append(f"损失与赔付合计 {summary['loss']:g} 元；实际毛利 {summary['profit']:g} 元，"
                         f"毛利率 {summary['margin']:.0%}（{summary['grade']}）")
            for g in summary["gaps"]:
                lines.append(f"　- {g['name']}：自报 {g['declared']:g} vs 实际 {g['actual']:g}"
                             f"（差 {g['diff']:g}）")
            evidence_id = self._practice.record_evidence(order_id, "结算", "\n".join(lines),
                                                         step="S11", ref="finance-settle")
        return {**summary, "evidence_id": evidence_id}

    def facts_text(self, order_id: str) -> str:
        """给评分 Agent 的账目参照：客观成本、损失、赔付与最终毛利。"""
        summary = self.summary(order_id)
        if not summary["revenue"] and not summary["entries"]:
            return ""
        lines = [f"资源口径成本：{summary['cost']:g} 元（{summary['cost_source']}）"]
        for e in summary["entries"]:
            mine = e["amount"] if e["status"] == "待处理" else e["ours"]
            lines.append(f"损失项·{e['label']}：{e['amount']:g} 元，承担方 {e['bearer']}"
                         f"（我方 {float(mine or 0):g} 元，{e['status']}）")
        lines.append(f"客户确认收入：{summary['revenue']:g} 元；实际毛利 {summary['profit']:g} 元"
                     f"，毛利率 {summary['margin']:.0%}（{summary['grade']}）")
        if summary["pending"]:
            lines.append(f"未定责的损失项：{summary['pending']} 笔（不处理即默认我方承担）")
        return "\n".join(lines)


def settlement_grade(margin: float) -> str:
    """毛利率分档（写死）：≥15% 优秀，≥8% 达标，≥0 偏低，其余亏损。"""
    return ("优秀" if margin >= 0.15 else "达标" if margin >= 0.08
            else "偏低" if margin >= 0 else "亏损")
