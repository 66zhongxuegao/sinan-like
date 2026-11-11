"""方案版本：创建方案 → 发送方案 → 客户已读（vbooking 主链，PRD 28.31）。

真实平台里这三步是分开的：
- **创建方案**：定制师在平台里编行程（逐日）与报价，可以先存草稿、反复改；
- **发送方案**：选发给谁（客户群 / 客户单聊 / 平台留档），发出一个版本；
- **客户已读**：平台记录客户有没有读过、什么时候读的、读了多久；**读过才有反馈**。

实现口径：
- 方案 = 平台侧版本记录 + 复用「行程方案」交付物做渲染 / 证据 / 门槛（一个数据源，不另起一套表单）；
- 发送时先投卡片（状态=已发送，客户还没读），并给一个阅读到期时间；
- 到点后由客户 Agent 真的读一遍（生成反馈），才把状态改成「已读」——不是写死的假状态；
- 客户已读之后才允许登记「客户确认方案」门槛，避免学员自己点一下就算客户确认了。
"""

from __future__ import annotations

from .competition_mode import enabled as competition_easy
import json
from datetime import datetime, timedelta

READ_AFTER_SECONDS = 5      # 发送后多久算客户读完（演示节奏；真实平台由客户端回执驱动）


def _now() -> datetime:
    return datetime.now()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class PlanService:
    """订单方案版本：草稿 / 已发送 / 已读 / 客户已确认。"""

    def __init__(self, store, practice=None, deliverable=None, tools=None) -> None:
        self._store = store
        self._practice = practice
        self._deliverable = deliverable
        self._tools = tools

    # ---------- 查询 ----------

    def _row(self, order_id: str, plan_id: str) -> dict:
        row = self._store.plan(plan_id)
        if not row or row["order_id"] != order_id:
            raise ValueError(f"未找到方案: {plan_id}")
        return self._materialize_read(row)

    def list(self, order_id: str) -> list[dict]:
        return [self._materialize_read(r) for r in self._store.plans(order_id)]

    def detail(self, order_id: str, plan_id: str) -> dict:
        return self._row(order_id, plan_id)

    def _view(self, row: dict) -> dict:
        return {
            "plan_id": row["plan_id"], "order_id": row["order_id"], "version": row["version"],
            "title": row["title"], "note": row["note"], "status": row["status"],
            "values": json.loads(row.get("values_json") or "{}"),
            "channels": json.loads(row.get("channels") or "[]"),
            "created_at": row.get("created_at") or "", "sent_at": row.get("sent_at") or "",
            "read_at": row.get("read_at") or "", "feedback": row.get("feedback") or "",
            "confirm_at": row.get("confirm_at") or "", "read": bool(row.get("read_at")),
        }

    # ---------- 创建 / 编辑 ----------

    def create(self, order_id: str, values: dict, note: str = "") -> dict:
        order = self._store.order(order_id)
        if not order:
            raise ValueError(f"未找到订单: {order_id}")
        version = max([int(r["version"] or 1) for r in self._store.plans(order_id)] + [0]) + 1
        pid = f"plan-{order_id}-v{version}"
        title = str(values.get("title") or f"方案 V{version}")
        self._store.save_plan(pid, order_id, order["user_id"], version, title,
                              values.get("days") or [], [], note=note, status="草稿",
                              created_at=_fmt(_now()), values=values)
        return self._view(self._store.plan(pid))

    def update(self, order_id: str, plan_id: str, values: dict, note: str = "") -> dict:
        row = self._row(order_id, plan_id)
        if row["status"] != "草稿":
            raise ValueError("已发送的方案不能再改动，请另建一版")
        title = str(values.get("title") or row["title"])
        self._store.update_plan(plan_id, title=title,
                                days=json.dumps(values.get("days") or [], ensure_ascii=False),
                                note=note or row["note"],
                                values_json=json.dumps(values, ensure_ascii=False))
        return self._view(self._store.plan(plan_id))

    # ---------- 发送 ----------

    def send(self, order_id: str, plan_id: str, targets: list[str] | None = None) -> dict:
        row = self._row(order_id, plan_id)
        if row["status"] not in ("草稿", "已发送"):
            raise ValueError(f"方案当前状态为「{row['status']}」，不能重复发送")
        raw = self._store.plan(plan_id)
        values = json.loads(raw.get("values_json") or "{}")
        if not values:
            raise ValueError("方案内容为空，请先创建并填写方案")
        if self._deliverable is None:
            raise ValueError("投递服务不可用")
        # 走交付物同一条链：拦截网 → 证据 → 门槛 → 投卡片（但不立刻触发客户反馈）
        out = self._deliverable.submit(order_id, "行程方案", values,
                                       targets=targets or [], defer_customer_reply=True)
        if out.get("blocked"):
            return {"ok": False, "blocked": True, "guard": out.get("guard"),
                    "plan": self._view(raw)}
        due = _now() if competition_easy() else _now() + timedelta(seconds=READ_AFTER_SECONDS)
        self._store.update_plan(plan_id, status="已发送", sent_at=_fmt(_now()),
                                read_due_at=_fmt(due),
                                channels=json.dumps(targets or [], ensure_ascii=False))
        plan = (self._materialize_read(self._store.plan(plan_id)) if competition_easy()
                else self._view(self._store.plan(plan_id)))
        plan["routing"] = out.get("routing")
        plan["deliverable_version"] = out.get("version")
        if competition_easy() and self._practice is not None and int(
                (self._store.order(order_id) or {}).get("stage_index") or 0) == 1:
            # 客户已满意读完方案，登记确认动作；仍按阶段顺序只推进一阶。
            self._practice.record_action(order_id, "customer_confirmed_plan",
                                         {"plan_id": plan_id, "from": "competition_satisfied"})
        return {"ok": True, "blocked": False, "plan": plan}

    # ---------- 客户已读（到点由客户 Agent 真的读一遍） ----------

    def _materialize_read(self, row: dict) -> dict:
        if row["status"] != "已发送" or row.get("read_at") or not row.get("read_due_at"):
            return self._view(row)
        try:
            due = datetime.fromisoformat(row["read_due_at"])
        except ValueError:
            return self._view(row)
        if _now() < due:
            return self._view(row)

        values = json.loads(row.get("values_json") or "{}")
        rendered = self._render(values, row)
        reply, sentiment, asks = "", "", []
        if self._tools is not None:
            try:
                fb = self._tools.deliverable_feedback(
                    "行程方案", rendered, self._store.order(row["order_id"])["customer"], order_id=row["order_id"], channel="plan")
                reply = fb.get("reply", "")
                sentiment = fb.get("sentiment", "")
                asks = fb.get("asks", []) or []
            except Exception:
                reply = ""
        if not reply:
            from .customer_context import fallback_reply
            reply = fallback_reply(self._store.ensure_customer_card(row["order_id"]), feedback=True)
        self._store.update_plan(row["plan_id"], status="已读", read_at=_fmt(_now()),
                                feedback=reply)
        sess = self._customer_session(row["order_id"])
        if sess:
            customer = self._store.order(row["order_id"])["customer"]
            self._store.add_im_message(sess, customer, "other", reply)
            if self._practice is not None:
                self._practice.record_evidence(
                    row["order_id"], "客户已读",
                    f"【客户已读方案 V{row['version']}】{reply}"
                    + (f"｜追问：{'；'.join(asks)}" if asks else ""),
                    ref=row["plan_id"])
        view = self._view(self._store.plan(row["plan_id"]))
        view["sentiment"] = sentiment
        view["asks"] = asks
        return view

    def _render(self, values: dict, row: dict) -> str:
        """客户 Agent 读到的方案文本：必须是**客户输出**（脱敏版）。

        方案内容里如果混进了成本/毛利口径，客户这一侧不能看到；内部档案与评分走
        交付物链路的内部渲染（deliverable_service），与这里无关。
        """
        from ..contracts.deliverables_spec import render_for_customer, resolve
        spec = resolve("行程方案")
        order = self._store.order(row["order_id"]) or {}
        payload = json.loads(order.get("payload") or "{}")
        ctx = {"order_id": row["order_id"], "customer": order.get("customer", ""),
               "destination": order.get("destination", ""),
               "source_market": payload.get("source_market", ""),
               "language": payload.get("language", "中文")}
        return render_for_customer(spec, values, ctx)[0]

    def _customer_session(self, order_id: str) -> str:
        from .supplier_service import SupplierService
        svc = SupplierService(self._store)
        g = svc.group_by_name(order_id, "客户服务群")
        if not g or "客户" not in svc.added_contacts(order_id):
            return ""
        return g["session_id"]

    # ---------- 客户确认（已读之后才允许） ----------

    def confirm(self, order_id: str, plan_id: str) -> dict:
        row = self._row(order_id, plan_id)
        if not row.get("read_at") and not competition_easy():
            return {"ok": False, "error": "客户还没读过方案，先发送并等客户已读", "plan": row}
        self._store.update_plan(plan_id, status="客户已确认", confirm_at=_fmt(_now()))
        if self._practice is not None:
            self._practice.record_action(order_id, "customer_confirmed_plan",
                                         {"plan_id": plan_id, "version": row["version"]})
        return {"ok": True, "plan": self._view(self._store.plan(plan_id))}