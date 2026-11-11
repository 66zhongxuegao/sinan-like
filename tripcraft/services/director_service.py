"""导演总线 —— 学员动作自动进总线，按画像难度自动注入事件型考点（PRD 19 / 20 / 24 章）。

**口径（D-047）**
- 学员**不需要也不应该**手动注入事件：动作由 `PracticeService.record_action` 自动送入总线；
- 导演按订单的画像简报（`brief`）决定**注入几起**（= 资源冲突旋钮）与**触发强度**：
    · 补救（level 0–1）→ `explicit`：把问题与方向点明，相当于给线索；
    · 正常（level 2–3）→ `normal`：只说现象，学员自己判断；
    · 加压（level 4）→ `implicit`：现象更隐蔽、信息更残缺；
- 每个事件绑定它要考的 B 型技能点，命中后写进对应聊天群；
- 学员在群里回应 → 该 B 型考点算「覆盖」。

规则表按 13 步组织，覆盖 S2/S3/S4/S5/S6/S7/S8/S9/S10/S11 的事件型考点。
"""

from __future__ import annotations

import json
import time
from .competition_mode import enabled as competition_easy
from typing import Any

from .finance_service import FinanceService
from .supplier_service import SupplierService

# 学员动作 -> 总线事件
ACTION_TO_EVENT: dict[str, str] = {
    "grab": "grab",
    "first_call": "call_done",
    "deliverable:需求确认单": "requirement_confirmed",
    "deliverable:行程方案": "plan_sent",
    "deliverable:分项报价": "quote_sent",
    "customer_confirmed_plan": "customer_confirmed",
    "contract_signed": "contract_signed",
    "customer_signed_contract": "contract_confirmed",
    "deposit_paid": "deposit_paid",
    "resources_locked": "resource_locked",
    "pre_trip_notice": "pre_trip",
    "deliverable:出团通知书": "pre_trip",
    "depart": "depart",
    "settlement_verified": "settlement_submitted",
    "balance_paid": "balance_paid",
    "review_done": "review_done",
    "deliverable:合同与保险": "contract_signed",
}

EVENTS = ("grab", "call_done", "requirement_confirmed", "plan_sent", "quote_sent",
          "customer_confirmed", "contract_signed", "contract_confirmed", "deposit_paid",
          "resource_locked", "pre_trip", "depart", "settlement_submitted", "balance_paid", "review_done")

# 注入强度
EXPLICIT, NORMAL, IMPLICIT = "explicit", "normal", "implicit"


def rule(code: str, step: str, trigger: tuple[str, ...], channel: str, speaker: str,
         title: str, body: str, skill_points: tuple[str, ...], stage_min: int = 0,
         hint: str = "", implicit: str = "", effect: tuple[str, dict] | None = None,
         cost: dict | None = None) -> dict[str, Any]:
    """一条注入规则。

    - `hint`：补救档追加的一句「把方向点明」；
    - `implicit`：加压档换用的更隐蔽说法（缺省则沿用 body）；
    - `effect`：(资源方, 事实补丁)；
    - `cost`：这起事件造成的成本口径（金额按人数/间晚/固定值折算，进成本台账）。事件与**这一单**的资源方事实必须同源：
      群里说了酒店超售，学员再去酒店群问，拿到的也必须是超售后的口径。
    """
    return {"code": code, "step": step, "trigger": tuple(trigger), "channel": channel,
            "speaker": speaker, "title": title, "body": body, "hint": hint,
            "implicit": implicit or body, "skill_points": tuple(skill_points),
            "stage_min": stage_min, "effect": effect, "cost": cost}


INCIDENT_RULES: tuple[dict[str, Any], ...] = (
    # ---------- S2 / S3 需求阶段 ----------
    rule("INC-DEMAND-CONFLICT", "S3", ("call_done",), "客户服务群", "客户",
         "需求补充（含冲突）",
         "对了，酒店能不能一间大床加一间双床？还有预算我想再压一压，之前说的可能偏高了。",
         ("C2.4", "C2.5"), stage_min=1,
         hint="（提醒：这两条和刚才确认的需求冲突，先判断哪个优先再回客户）",
         implicit="酒店和预算你再帮我看看？"),
    rule("INC-TIMEZONE-TOOL", "S2", ("call_done",), "客户服务群", "客户",
         "时差与通讯工具",
         "对了，你们那边现在是白天吧？我这边刚下班。我平时用 WhatsApp，你加我一下方便点。",
         ("C8.4",), stage_min=1,
         hint="（提醒：客户在另一个时区、而且不用微信，联系方式和沟通时间都要调）"),
    # ---------- S4 资源询价 ----------
    rule("INC-RESOURCE-VAGUE", "S4", ("requirement_confirmed",), "地接资源信息群", "XX地接·张经理",
         "资源方模糊回复",
         "车的事应该没问题，具体价格我再看看，回头跟你说。",
         ("C4.4",), stage_min=1,
         hint="（提醒：这是模糊口径，得追问车型、座位、日价、含不含司机和油、几点前回复）"),
    rule("INC-RESOURCE-UNAVAILABLE", "S4", ("plan_sent",), "酒店沟通群", "酒店·李",
         "首选资源不可用",
         "不好意思，您问的那家这三天满房了。同区还有一家，条件差不多，贵 60 一间。",
         ("C4.6",), stage_min=2,
         effect=("酒店", {"availability": "紧张",
                         "note": "首选那家这三天满房；同区替代酒店条件相近，贵 60 元/间/晚，可保留到明天中午"}),
         cost={"code": "COST-HOTEL-ALT", "label": "替代酒店差价", "kind": "酒店",
               "amount_per": 60, "unit": "间晚"}),
    # ---------- S5 / S6 方案与报价 ----------
    rule("INC-CULTURE-REDLINE", "S5", ("plan_sent",), "地接资源信息群", "XX地接·张经理",
         "文化红线提醒",
         "提醒一下，您方案里那天安排的是含猪肉的餐，客人是{market}来的，可能不方便；那天还是他们的节日，景点可能提前关门。",
         ("C8.3", "C8.2"), stage_min=2,
         hint="（提醒：这是在提示你方案里有宗教/饮食与节日冲突，需要替换并说明）",
         implicit="您再看看那天的安排，客人那边我不太确定方不方便。",
         effect=("地接社", {"note": "客人行程里那天有含猪肉的餐，而且当天是客人的节日，部分景点可能提前关门"})),
    rule("INC-TICKET-PRICE-HIKE", "S6", ("plan_sent",), "票务沟通群", "票务·陈",
         "机票涨价与余位",
         "先别跟客人报死价——这个航班这两天涨了 220 一个人，而且只剩 5 个位。要锁的话今天得先付 80% 预留。",
         ("C4.4", "C4.6", "C5.5"), stage_min=2,
         effect=("票务", {"availability": "紧张", "price_factor": 1.15,
                         "note": "该航班这两天涨了 220 元/人，只剩 5 个位；要锁位得先付 80% 预留"}),
         cost={"code": "COST-TICKET-HIKE", "label": "机票涨价差额", "kind": "票务",
               "amount_per": 220, "unit": "人", "transferable": True}),
    rule("INC-FX-PAYMENT", "S6", ("quote_sent",), "客户服务群", "客户",
         "外币支付与汇率",
         "我们是刷信用卡的，你们能收外币吗？汇率按哪天的算？还有能不能开发票，收据和发票有区别吗？",
         ("C8.6",), stage_min=2,
         hint="（提醒：要讲清汇率口径与锁定时间、支付方式与手续费、发票与收据的差别）"),
    rule("INC-TICKET-FAIL", "S10", ("quote_sent",), "票务沟通群", "票务·陈",
         "高铁票抢不到",
         "你报的那趟高铁我这边没锁到票，同车次只剩一等座，差价约 180/人；换别的班次会晚到 2 小时。你定一下，30 分钟内要答复。",
         ("C6.2", "C6.3", "C4.6"), stage_min=2,
         effect=("票务", {"availability": "紧张",
                         "note": "原车次没锁到票；同车次只剩一等座，差价约 180 元/人；换其他班次会晚到 2 小时"}),
         cost={"code": "COST-TICKET-FAIL", "label": "一等座差价", "kind": "票务",
               "amount_per": 180, "unit": "人"}),
    # ---------- S7 反馈与迭代 ----------
    rule("INC-CUSTOMER-OBJECTION", "S7", ("quote_sent", "customer_confirmed"), "客户服务群", "客户",
         "客户对方案有异议",
         "这个行程我看了一下，感觉一般，价格也超出我预期。你们再想想吧。",
         ("C1.7", "C3.7", "C5.5"), stage_min=2,
         hint="（提醒：客户没说清哪里不满意，先问清真实诉求再给取舍方案）",
         implicit="再看看吧。"),
    # ---------- S8 录单 ----------
    rule("INC-VAGUE-CONFIRM", "S8", ("customer_confirmed",), "客户服务群", "客户",
         "关键项模糊确认",
         "合同我大概看了一下，应该没问题吧。房型和接送时间到时候再说，应该差不多。",
         ("C7.6",), stage_min=3,
         hint="（提醒：「应该」「差不多」不是确认，关键项要逐条拿到明确答复）",
         implicit="合同就这样吧。"),
    # ---------- S9 行前 ----------
    rule("INC-PRE-TRIP-GAP", "S9", ("resource_locked",), "司导沟通群", "导游·小周",
         "行前要素缺失",
         "客人的饮食禁忌跟酒店确认了吗？我这边没收到书面要求，另外接机时间要不要按他们的时区再核一遍？",
         ("C8.3", "C8.4"), stage_min=4,
         hint="（提醒：要把禁忌与时间要求书面传给地接和导游，并留确认）"),
    # ---------- S10 行中 ----------
    rule("INC-HOTEL-OVERBOOK", "S10", ("resource_locked",), "酒店沟通群", "酒店·李",
         "酒店超售",
         "不好意思，您锁的那家四星今天超售了。同档次只有一家离景区 20 分钟车程的，房价还要贵 60/间。您看是换酒店还是我帮您压价？",
         ("C6.1", "C6.3", "C6.4", "C4.6"), stage_min=4,
         effect=("酒店", {"availability": "无档期",
                         "note": "已锁的四星酒店超售；同档次替代酒店离景区 20 分钟车程，贵 60 元/间/晚"}),
         cost={"code": "COST-HOTEL-OVERBOOK", "label": "替代酒店差价", "kind": "酒店",
               "amount_per": 60, "unit": "间晚"}),
    rule("INC-VEHICLE-BREAKDOWN", "S10", ("pre_trip", "depart"), "司导沟通群", "司机·赵师傅",
         "车辆故障",
         "车出问题了，早上怕是赶不上 8 点出发，我正在联系换车。客人那边您先帮我安抚一下，最快 7 点前给你们准信。",
         ("C6.1", "C6.2", "C6.3", "C6.5", "C6.7"), stage_min=4,
         effect=("车队", {"availability": "无档期",
                         "note": "原定 7 座车故障；换车最快 7:00 前给准信，可能要等到 8 点后才能出发"}),
         cost={"code": "COST-VEHICLE-BREAKDOWN", "label": "临时换车费", "kind": "车队",
               "amount_fixed": 400}),
    # ---------- S11 结算与回访 ----------
    rule("INC-SETTLEMENT-DISPUTE", "S11", ("settlement_submitted",), "地接资源信息群", "XX地接·张经理",
         "结算单差异",
         "结算单发你了：门票和用车比你们报价单上多出 1200。这两笔你之前是同意的，麻烦今天把尾款结一下。",
         ("C5.8", "C6.7"), stage_min=5,
         effect=("地接社", {"note": "结算单已发出：门票与用车比报价单多出 1200 元，请在今天内核对回复"}),
         cost={"code": "COST-SETTLE-DIFF", "label": "结算单差额", "kind": "地接社",
               "amount_fixed": 1200}),
    rule("INC-BAD-REVIEW", "S11", ("balance_paid",), "客户服务群", "客户",
         "行后差评",
         "我这次体验一般，平台上我打了三星。主要是中间那次换酒店，没人提前跟我说清楚。",
         ("C1.5", "C1.8", "C8.7"), stage_min=6,
         hint="（提醒：差评要先回应情绪、问清原因、给补救，再做二次回访闭环）",
         implicit="我给了个评价，你们自己看吧。",
         cost={"code": "COST-REVIEW-COMP", "label": "客户补偿", "kind": "客户",
               "amount_fixed": 300, "category": "compensation"}),
)


class DirectorService:
    """进程内事件总线：动作 → 事件 → 按画像难度自动注入。"""

    def __init__(self, store, practice=None, llm=None) -> None:
        self._store = store
        self._practice = practice
        self._llm = llm

    # ---------- 难度口径 ----------

    @staticmethod
    def _brief(payload: dict) -> dict:
        return payload.get("brief") or {}

    TEACH_UNLOCK = 60      # 教学掌握度到 60 才算「学过」，学过才解锁对应事件

    def _abilities(self, order_row: dict) -> dict:
        """按订单归属取学员能力；**不**在缺归属时退化成 demo 用户（否则 A 单会读 B 的画像）。"""
        user_id = (order_row.get("user_id") or "").strip()
        if not user_id:
            return {}
        try:
            return self._store.abilities(user_id)
        except Exception:
            return {}

    @staticmethod
    def _teach(abilities: dict, sp: str) -> float:
        return float((abilities.get(sp) or {}).get("teach") or 0)

    def unlocked(self, rule: dict, abilities: dict) -> bool:
        """事件解锁条件：要考的技能点里，至少有一个是学员「学过」的（教学掌握度 ≥ 60）。

        没学过的点不注入、也不计入覆盖率分母——先把课上了再来考，否则是耍人。
        """
        return any(self._teach(abilities, sp) >= self.TEACH_UNLOCK for sp in rule["skill_points"])

    def candidates(self, order_row: dict) -> list[dict]:
        """本单可注入的事件（已解锁、且技能点已学）。学习地图也用它显示解锁情况。"""
        abilities = self._abilities(order_row)
        return [r for r in INCIDENT_RULES if self.unlocked(r, abilities)]

    def quota(self, payload: dict) -> int:
        """本单注入几起：由画像的「资源冲突」旋钮决定。

        **最少 1 起**——B 型考点必须真的发生才可能被考到；补救档的区别是
        「触发点显式 + 给线索」（见 `strength`），不是「不触发」。
        """
        knobs = self._brief(payload).get("knobs") or {}
        try:
            n = int(knobs.get("resource_conflict", 2))
        except (TypeError, ValueError):
            n = 2
        # 这里只是**上限保护**（别一单塞 10 起），不再是「只给 1-2 起」。
        # 真正的数量由「本单可考、且已解锁的 B 型事件」决定（见 _decide / candidates）。
        return min(6, 3 + max(0, min(4, n)) // 2)

    def strength(self, payload: dict) -> str:
        """整单兜底强度（没有按事件算的时候用）。"""
        level = int(self._brief(payload).get("level", 2) or 0)
        if level <= 1:
            return EXPLICIT
        if level >= 4:
            return IMPLICIT
        return NORMAL

    def strength_for(self, rule: dict, order_row: dict, payload: dict) -> str:
        """逐事件难度：看这起事件要考的技能点里，学员**最弱**的那个掌握度。

        <60（还没学会）→ explicit：把问题和方向点明，相当于给线索；
        60-79 → normal：只说现象，自己判断；
        ≥80（已经熟了）→ implicit：现象更隐蔽、信息更残缺。
        """
        abilities = self._abilities(order_row)
        vals = [max(self._teach(abilities, sp),
                    float((abilities.get(sp) or {}).get("real_v") or 0))
                for sp in rule["skill_points"]]
        if not vals:
            return self.strength(payload)
        v = min(vals)
        if v < 60:
            return EXPLICIT
        if v >= 80:
            return IMPLICIT
        return NORMAL

    def materialize_resource_pool(self, order_id: str, text: str, kinds: list[str],
                                  city: str, date: str = "") -> dict:
        """地接回答后，把本单本城需要的资源加入可添加联系人池。

        只写订单事实与资源池，不直接替学员添加联系人。允许资源：
        酒店、车队、导游、司机、门票。门票不进联系人目录，由地接报价。
        """
        allowed = {"酒店", "车队", "导游", "司机", "门票"}
        kinds = [kind for kind in dict.fromkeys(kinds or []) if kind in allowed]
        row = self._store.order(order_id)
        if not row or not city:
            return {}
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            payload = {}
        old = payload.get("resource_pool") or {}
        merged = set(kinds)
        if old.get("city") == city:
            merged |= {kind for kind in old.get("kinds") or [] if kind in allowed}
        pool = {"city": city, "kinds": sorted(merged), "date": date or old.get("date") or "",
                "inquiry": str(text or "")[:800], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        payload["resource_pool"] = pool
        self._store._exec("UPDATE biz_order SET payload=? WHERE order_id=?",
                          (json.dumps(payload, ensure_ascii=False), order_id))
        self._store.add_event(order_id, "resource_pool_updated", pool)
        return pool

    # ---------- 学员动作 → 自动注入 ----------

    def on_action(self, order_id: str, action: str) -> dict | None:
        """学员动作自动进总线；命中规则且还有配额就注入。返回注入的事件（或 None）。"""
        event = ACTION_TO_EVENT.get(action)
        if not event:
            return None
        row = self._store.order(order_id)
        if not row:
            return None
        self._store.add_event(order_id, event, {"from_action": action})
        return self._decide(order_id, row, event)

    def _decide(self, order_id: str, row: dict, event: str) -> dict | None:
        payload = json.loads(row["payload"] or "{}")
        stage = int(row["stage_index"] or 0)
        injected = self._store.incidents(order_id)
        if len(injected) >= self.quota(payload):
            return None                       # 本单的注入配额已用完
        fired = {i["code"] for i in injected}
        abilities = self._abilities(row)
        svc = SupplierService(self._store)
        for r in INCIDENT_RULES:
            if event not in r["trigger"] or stage < r["stage_min"] or r["code"] in fired:
                continue
            if not self.unlocked(r, abilities):
                continue      # 这一步要考的技能还没学过：不注入（否则是无教而考）
            if not svc.group_by_name(order_id, r["channel"]):
                continue      # 对应的人还没加（或客户还没加微信）：这条事件这次不发生
            return self._fire(order_id, row, r, self.strength_for(r, row, payload))
        return None

    def _fire(self, order_id: str, row: dict, r: dict, strength: str) -> dict:
        payload = json.loads(row["payload"] or "{}")
        market = payload.get("source_market", "香港")
        body = r["implicit"] if strength == IMPLICIT else r["body"]
        if strength == EXPLICIT and r["hint"]:
            body = body + "\n" + r["hint"]
        body = body.replace("{market}", market)

        if r.get("effect"):
            kind, patch = r["effect"]
            SupplierService(self._store).apply_fact(order_id, kind, patch)

        session_id = self._ensure_channel(row, r["channel"], r["speaker"])
        speaker = self._speaker_name(row, r["speaker"])
        # 只把「已经学过（教学掌握度 ≥ 60）」的点纳入这起事件的考核范围：
        # 规则里还没教过的点不进分母——和 unlocked 同一口径，不用没教过的东西扣分。
        abilities = self._abilities(row)
        tested = [sp for sp in r["skill_points"]
                  if self._teach(abilities, sp) >= self.TEACH_UNLOCK] or list(r["skill_points"])
        incident_id = f"inc-{order_id}-{r['code']}-{int(time.time() * 1000) % 100000}"
        self._store.add_incident(incident_id, order_id, r["code"], r["step"], r["title"],
                                 r["channel"], session_id, speaker, body,
                                 list(tested), f"步骤 {r['step']} · 强度 {strength}")
        self._store.add_im_message(session_id, speaker, "other", body)
        if r.get("cost"):
            FinanceService(self._store, practice=self._practice).add_incident_cost(
                order_id, r["cost"], ref=incident_id, order=row)
        if self._practice is not None:
            for sp in tested:
                self._practice.mark_trigger(order_id, sp, r["step"])
                if competition_easy():
                    self._practice.mark_reacted(order_id, sp)
        return {"incident_id": incident_id, "code": r["code"], "title": r["title"],
                "step": r["step"], "channel": r["channel"], "speaker": r["speaker"],
                "body": body, "skill_points": list(tested),
                "strength": strength, "session_id": session_id}

    # ---------- 兼容：显式送事件（MCP / 调试用，学员界面不暴露） ----------

    def emit(self, order_id: str, type_: str, payload: dict | None = None) -> dict:
        row = self._store.order(order_id)
        if not row:
            raise ValueError(f"未找到订单: {order_id}")
        if type_ not in EVENTS:
            raise ValueError(f"未知事件类型: {type_}（可选 {', '.join(EVENTS)}）")
        self._store.add_event(order_id, type_, payload or {})
        return {"event": type_, "injected": self._decide(order_id, row, type_)}

    def _speaker_name(self, order: dict, speaker: str) -> str:
        """规则里的占位发言人换成这一单的真实联系人名。"""
        try:
            names = SupplierService(self._store).names(order["order_id"])
        except Exception:
            return speaker
        for kind in ("导游", "司机"):
            if speaker.startswith(kind):
                return names.get(kind) or speaker
        if speaker.startswith("客户"):
            return order.get("customer") or speaker
        if speaker.startswith("XX地接") or speaker.startswith("地接"):
            return names.get("地接社") or speaker
        if speaker.startswith("酒店"):
            return names.get("酒店") or speaker
        if speaker.startswith("车队"):
            return names.get("车队") or speaker
        if speaker.startswith("票务"):
            return names.get("票务") or speaker
        return speaker

    def _ensure_channel(self, order: dict, name: str, speaker: str = "") -> str:
        """事件落到实际存在的会话：司导事件优先按发言角色，缺失时落到已有导游单聊。"""
        svc = SupplierService(self._store)
        order_id = order["order_id"]
        if name == "司导沟通群":
            kind = "司机" if speaker.startswith("司机") else "导游"
            sid = svc.contact_dm(order["user_id"], kind, order_id)
            if not sid and kind == "司机":
                sid = svc.contact_dm(order["user_id"], "导游", order_id)
            if sid:
                return sid
        g = svc.group_by_name(order_id, name)
        if g:
            return g["session_id"]
        return svc.ensure_hub(order["user_id"], order_id)["session_id"]
    # ---------- 学员反应 ----------

    def react(self, session_id: str) -> list[str]:
        marked: list[str] = []
        for inc in self._store.incidents_by_session(session_id):
            try:
                sps = json.loads(inc["skill_points"] or "[]")
            except Exception:
                sps = []
            for sp in sps:
                if self._practice is None or sp in marked:
                    continue
                self._practice.mark_reacted(inc["order_id"], sp)
                marked.append(sp)
            if inc.get("code") == "INC-VEHICLE-BREAKDOWN":
                self._vehicle_followup(inc)
        return marked

    def _vehicle_followup(self, inc: dict) -> None:
        """学员第一次回应车辆故障后，给一次确定结果，避免“7 点准信”永远悬着。"""
        session_id = inc.get("session_id") or ""
        if not session_id:
            return
        for msg in self._store.im_messages(session_id):
            try:
                payload = json.loads(msg.get("payload") or "{}")
            except Exception:
                payload = {}
            if payload.get("incident_followup") == "INC-VEHICLE-BREAKDOWN":
                return
        speaker = inc.get("speaker") or "司机"
        body = ("换到车了：替换车 7:20 到酒店，8 点出发来得及。"
                "临时换车费 400 元由车队承担，麻烦你跟客人同步一下。")
        self._store.add_im_message(
            session_id, speaker, "other", body, kind="text",
            payload={"incident_followup": "INC-VEHICLE-BREAKDOWN"})
        try:
            SupplierService(self._store).apply_fact(
                inc["order_id"], "车队",
                {"availability": "可用",
                 "note": "替换车 7:20 到酒店；8 点出发；临时换车费 400 元由车队承担"})
        except Exception:
            pass

    # ---------- 时间线 / 规则表 ----------

    def timeline(self, order_id: str) -> dict:
        events = [{"type": e["type"], "at": e["at"],
                   "payload": json.loads(e["payload"] or "{}")} for e in self._store.events(order_id)]
        incidents = [{
            "incident_id": i["incident_id"], "code": i["code"], "title": i["title"],
            "step": i["step"], "channel": i["channel"], "session_id": i["session_id"],
            "speaker": i["speaker"], "body": i["body"],
            "skill_points": json.loads(i["skill_points"] or "[]"), "rule": i["rule"], "at": i["at"],
        } for i in self._store.incidents(order_id)]
        return {"order_id": order_id, "events": events, "incidents": incidents}

    def catalog(self) -> list[dict]:
        return [{"code": r["code"], "step": r["step"], "trigger": list(r["trigger"]),
                 "stage_min": r["stage_min"], "channel": r["channel"], "speaker": r["speaker"],
                 "title": r["title"], "skill_points": list(r["skill_points"])}
                for r in INCIDENT_RULES]
