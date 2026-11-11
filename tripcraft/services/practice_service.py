"""实战服务 —— 订单 / 平台状态 / 完成条件 / 评分复盘。

对应 PRD 第 26 章。订单是完整工作单元；进度用平台 8 态；
13 步阶段只作为内部映射与「完成条件」提示。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..services.learner_brief import LearnerBrief

from ..agents.scorer import ScoringAgent
from ..contracts.enums import DIMENSION_NAMES, STEP_ORDER, CheckpointType, Dimension, StepId
from ..contracts.rubric import RUBRICS
from ..contracts.entry_documents import FOREIGN_DOCUMENTS
from ..contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID, by_step
from ..storage.db import Store
from ..agents.scenario import DispatchGenerator, missing_fields
from ..agents.customer import persona_for
from . import dispatch_service as dispatch
from .learner_brief import build_brief
from ..contracts.steps import STEP_EVIDENCE
from .workflow import (ACTION_LABELS, MAX_STAGE, MANUAL_ACTIONS, gates_for,
                        is_known_action, stage_hint)
from .competition_mode import enabled as competition_easy
from .capability_compounding import compile_learning_signal, persist_learning_signal
from .evidence_verifier import get_verifier
from .source_registry import OfficialSourceRegistry

# 平台订单状态（8 态）
ORDER_STEPS = [
    "定制师接单", "定制师提供方案", "客户确认方案", "定制师提供合同",
    "客户确认合同", "客户出团", "定制师提交结算", "订单完成",
]

# （旧）文案版完成条件，已被 workflow.GATES 的可执行门槛取代，仅保留供参考
GATE_CHECKS: list[list[str]] = [
    ["抢单成功", "已识别派单缺失字段", "1 小时内发起首呼"],
    ["需求单已产出", "硬约束与软偏好已分开", "核心资源已确认可用", "行程方案已产出"],
    ["客户明确确认最终版本", "方案/报价版本可追溯"],
    ["合同已生成", "保险已购买"],
    ["客户已签署合同", "定金/首款已到账"],
    ["资源已锁定", "出团通知书已送达并确认"],
    ["账目核对一致", "尾款已结清"],
    ["客户回访完成", "复盘报告已生成"],
]

# 平台状态 -> 13 步阶段落点（用于流程进度）
STAGE_TO_STEP = [1, 3, 4, 6, 7, 9, 11, 12]

STEPS_13 = [
    "任务初始化与规则交底", "抢单接单", "首呼与需求挖掘", "需求结构化确认",
    "资源询价与可行性核验", "行程方案设计", "分项报价与利润测算", "客户反馈与方案迭代",
    "成交确认与系统录单", "资源锁定与行前准备", "行中执行与突发事件处理",
    "行后结算与回访", "复盘评分与个性化补救",
]

# 演示订单（模拟环境数据，非真实）
# (单号, 客户, 目的地, 状态, 平台阶段, 提交时间)
SEED_ORDERS = [
    ("9000000000000001", "客户 A", "江苏", "正常", 1, "2026-09-28 12:20:11"),
    ("9000000000000002", "客户 B", "云南", "正常", 2, "2026-09-27 09:41:02"),
    ("9000000000000003", "客户 C", "新疆", "禁用", 0, "2026-09-25 15:07:48"),
    ("9000000000000004", "客户 D", "浙江", "正常", 4, "2026-09-24 11:12:30"),
    ("9000000000000005", "客户 E", "四川", "正常", 1, "2026-09-29 09:05:41"),
    ("9000000000000006", "客户 F", "贵州", "正常", 0, "2026-10-08 09:12:00"),
    # 候选池：默认未发布，由消息中心按间隔逐条放出（“一直在更新可抢的单”）
    ("9000000000000007", "客户 G", "四川", "正常", 0, "2026-10-08 09:20:00"),
    ("9000000000000008", "客户 H", "福建", "正常", 0, "2026-10-08 09:28:00"),
    ("9000000000000009", "客户 I", "湖南", "正常", 0, "2026-10-08 09:36:00"),
    ("9000000000000010", "客户 J", "陕西", "正常", 0, "2026-10-08 09:44:00"),
]

# 未发布的候选单（客源市场与目的地各不相同）
UNPUBLISHED_IDS = ("9000000000000007", "9000000000000008", "9000000000000009", "9000000000000010")
PUBLISH_INTERVAL_MIN = 2

# 现有演示池采用入境客源；国内订单的人设由共享客户规则另行处理。
SEED_ORDER_META: dict[str, dict] = {
    "9000000000000001": {"source_market": "香港", "language": "中文",
                         "documents": "港澳居民来往内地通行证（回乡证）"},
    "9000000000000002": {"source_market": "新加坡", "language": "中文",
                         "documents": FOREIGN_DOCUMENTS},
    "9000000000000003": {"source_market": "台湾", "language": "中文",
                         "documents": "台湾居民来往大陆通行证（台胞证）"},
    "9000000000000004": {"source_market": "澳门", "language": "中文",
                         "documents": "港澳居民来往内地通行证（回乡证）"},
    "9000000000000005": {"source_market": "美国", "language": "English",
                         "documents": FOREIGN_DOCUMENTS},
    "9000000000000006": {"source_market": "香港", "language": "中文",
                         "documents": "港澳居民来往内地通行证（回乡证）"},
    "9000000000000007": {"source_market": "台湾", "language": "中文", "published": False,
                         "documents": "台湾居民来往大陆通行证（台胞证）"},
    "9000000000000008": {"source_market": "新加坡", "language": "中文", "published": False,
                         "documents": FOREIGN_DOCUMENTS},
    "9000000000000009": {"source_market": "澳门", "language": "中文", "published": False,
                         "documents": "港澳居民来往内地通行证（回乡证）"},
    "9000000000000010": {"source_market": "英国", "language": "English", "published": False,
                         "documents": FOREIGN_DOCUMENTS},
}

DEFAULT_SOURCE_MARKET = "香港"

# 演示联系记录（模拟环境数据）
SEED_CONTACTS: dict[str, list[tuple[str, str, str, bool, str]]] = {
    "9000000000000001": [
        ("电话", "2026-09-28 12:23:45", "已接通(16s)", True, "首呼完成，已确认称呼与出行意向"),
        ("电话", "2026-09-27 18:40:02", "未接通", False, ""),
    ],
    "9000000000000002": [
        ("电话", "2026-09-27 09:52:10", "已接通(2m38s)", True, "需求挖掘完成，日期待确认"),
        ("微信", "2026-09-27 11:05:00", "已添加", False, "已加企微，发送需求清单"),
    ],
    "9000000000000004": [
        ("电话", "2026-09-24 11:20:31", "已接通(4m02s)", True, "需求确认，进入方案设计"),
        ("电话", "2026-09-25 16:11:09", "已接通(1m12s)", True, "方案沟通，客户要求换酒店"),
    ],
}

# 平台通知分类（消息中心左侧）
MESSAGE_GROUPS = [
    {"key": "important", "label": "重要通知", "children": []},
    {"key": "order", "label": "订单通知", "children": [
        {"key": "custom-wait", "label": "定制游待接单通知", "star": True},
        {"key": "custom", "label": "定制游通知"},
        {"key": "holiday", "label": "度假订单通知"},
        {"key": "cruise", "label": "邮轮订单通知"},
        {"key": "play", "label": "玩乐订单通知"},
    ]},
    {"key": "product", "label": "产品通知", "children": []},
    {"key": "finance", "label": "财务通知", "children": []},
    {"key": "marketing", "label": "营销推广", "children": []},
    {"key": "other", "label": "其他通知", "children": []},
]

# 每个平台阶段对应的跟进提示
STAGE_HINTS = [
    "1 小时内发起首呼，确认称呼、意向与后续联系方式",
    "4 小时内提交方案；先确认核心资源可用，再给确定报价",
    "跟进客户确认最终版本，保留版本可追溯记录",
    "生成合同并购买保险后发送客户",
    "跟进客户签署合同，确认定金到账",
    "锁定资源并发出团通知书，拉客户群",
    "核对地接结算单与实际成本，提交结算",
    "完成客户回访与复盘，记录实际利润",
]


# 交付物 / 证据种类 -> 13 步落点（决定会考到哪些技能点）
DELIVERABLE_STEP: dict[str, str] = {
    "需求确认单": StepId.S3_REQUIREMENT.value,
    "行程方案": StepId.S5_ITINERARY.value,
    "分项报价": StepId.S6_QUOTATION.value,
    "合同与保险": StepId.S8_ORDER.value,
}
EVIDENCE_STEP: dict[str, str] = {
    "call": StepId.S2_FIRST_CALL.value,
    "im": StepId.S2_FIRST_CALL.value,
    "供应商询价": StepId.S4_RESOURCE.value,
}

# 群聊证据的 13 步落点：决定这通群聊会考到哪些技能点
GROUP_STEP: dict[str, str] = {
    # 新模型：资源大群 / 单聊 / 自己拉的群
    "hub": "S4",
    "dm-客户": "S2", "dm-地接社": "S4", "dm-酒店": "S4", "dm-车队": "S4",
    "dm-票务": "S6", "dm-导游": "S10", "dm-司机": "S10",
    "group": "S2", "custom": "S2",
    # 兼容旧房间（迁移前留下的）
    "customer": "S2", "supplier": "S4", "hotel": "S4",
    "vehicle": "S4", "ticket": "S6", "guide": "S10",
}

# 单次评分最多送入多少条 Rubric（控制提示词长度）
SCORE_BATCH = 8

# 单次测试的目标技能点上限（PRD 19.3：不是 61 点全考，而是有界清单）
def injectable_points() -> set[str]:
    """有事件规则兜底的 B 型技能点：只有它们才可能被注入、被回应、被评分。"""
    from .director_service import INCIDENT_RULES
    out: set[str] = set()
    for r in INCIDENT_RULES:
        out.update(r.get("skill_points") or ())
    return out


PLAN_LIMIT = 12

# 覆盖度参考线：用于复盘提示，不限制画像写回。
COVERAGE_THRESHOLD = 0.8

# 低置信度升级阈值（PRD 25.6）
MASTERY_FLOOR = 60          # M1 上限：低于它才算「暴露薄弱」
CONF_THRESHOLD = 0.7
BOUNDARY_DELTA = 3
BOUNDARIES = (60, 70, 80, 90)

# 会产生「可评分交付物」的步骤：只有这些步骤的 A 型考点才可能被覆盖
DELIVERABLE_STEPS = {"S2", "S3", "S4", "S5", "S6", "S8", "S9", "S11"}


def _hash(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) % 100003
    return h


def score_of(order_id: str, sp: str) -> int:
    """演示评分：按订单+技能点稳定生成（线程接口接入后改为真实评分）。"""
    return 42 + _hash(sp + order_id) % 56


def level_of(v: int) -> str:
    return "M5" if v >= 90 else "M4" if v >= 80 else "M3" if v >= 70 else "M2" if v >= 60 else "M1"


class PracticeService:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._director = None      # 由 app 装配（避免与 DirectorService 循环依赖）

    def attach_director(self, director) -> None:
        """挂上导演总线：学员动作会自动送入总线并触发事件注入（D-047）。"""
        self._director = director

    def seed(self, user_id: str) -> None:
        """播种**演示**订单（模拟环境数据）。

        只允许给单一 demo 账号用：SEED_ORDERS 是固定 order_id 的演示单，
        第二次用另一个 user_id 调它会把这些单整体改归属（多账号隔离直接破）。
        因此这里对**已有归属**的订单直接跳过，绝不抢别人的单。
        新用户的初始订单请用 `generate_dispatch(user_id, llm=None, count=1)`
        （由 spawn_order 生成全局唯一 order_id，不需要模型）。
        """
        boot = datetime.now()
        # 教学侧基线（只在账号没有任何能力数据时写一次）：
        # 演示学员「每个维度的前 3 个技能点已经学过」（教学掌握度 ≥ 60），
        # 这些点对应的突发事件因此在实战里解锁；其余点还没学，事件锁着。
        # 这就是「教 → 练 → 考」的入口：没学过的点不注入事件、也不计入覆盖率分母。
        if not self._store.abilities(user_id):
            from ..contracts.enums import Dimension
            for dim in Dimension:
                pts = [sp for sp in SKILL_POINTS if sp.dimension is dim]
                for i, sp in enumerate(pts):
                    # 演示账号：基础课都上过（教学掌握度 70），每个维度留最后一个点没学（30），
                    # 用来演示「没学 → 事件锁着 → 先去学习地图补课」这条闭环
                    self._store.set_ability(user_id, sp.id, teach=30 if i == len(pts) - 1 else 70,
                                            real_v=0)
        for oid, cust, dest, status, stage, created in SEED_ORDERS:
            old_row = self._store.order(oid)
            if old_row and (old_row.get("user_id") or "") not in ("", user_id):
                continue          # 已被别人持有：不抢、不改归属（多账号隔离）
            old = json.loads((old_row or {}).get("payload") or "{}")
            payload = {**old, "created_at": created, **SEED_ORDER_META.get(oid, {})}
            if oid in UNPUBLISHED_IDS and not payload.get("published"):
                # 候选单：服务启动后每隔 PUBLISH_INTERVAL_MIN 分钟放出 1 单，
                # 消息中心因此「一直在更新可抢的单」
                slot = UNPUBLISHED_IDS.index(oid) + 1
                payload["publish_at"] = (boot + timedelta(minutes=PUBLISH_INTERVAL_MIN * slot)) \
                    .isoformat(timespec="seconds")
            self._store.upsert_order(oid, user_id, cust, dest, status, stage, payload=payload)
        self._seed_contacts()
        self._seed_notices(user_id)
        self._backfill_actions(user_id)

    def _backfill_actions(self, user_id: str) -> None:
        """种子里已经处在较后阶段的订单，把「此前应该做过的动作」补齐，
        否则门槛账本与实际阶段对不上（例如阶段 4 却没抢过单）。

        只补**属于该账号**的演示单：动作账本是考核证据，绝不能写到别人的订单上。
        """
        from datetime import datetime, timedelta
        for oid, _cust, _dest, status, stage, created in SEED_ORDERS:
            row = self._store.order(oid)
            if not row or (row.get("user_id") or "") != user_id:
                continue
            if status == "禁用" or stage <= 0 or self._store.actions(oid):
                continue
            try:
                base = datetime.fromisoformat(created)
            except ValueError:
                base = datetime.now()
            t = base
            for st in range(stage):
                for gate in gates_for(st):
                    if st == 0 and gate.action == "grab":
                        t = base + timedelta(minutes=1)
                    else:
                        t = t + timedelta(minutes=8)
                    self._store.add_action(oid, gate.action, {"backfill": True})
                    # 动作时间用可控时间戳，保证「1 小时内首呼」这类时限门槛能算对
                    self._store._exec("UPDATE order_action SET at=? WHERE order_id=? AND action=?",
                                      (t.isoformat(timespec="seconds"), oid, gate.action))

    def _seed_contacts(self) -> None:
        for oid, rows in SEED_CONTACTS.items():
            if self._store.has_contacts(oid):
                continue
            for kind, at, status, rec, detail in rows:
                self._store.add_contact(oid, kind, at, status, rec, detail)

    def _seed_notices(self, user_id: str) -> None:
        if self._store.notices(user_id):
            return
        for oid, cust, dest, status, stage, created in SEED_ORDERS:
            if status == "禁用":
                self._store.upsert_notice(f"n-{oid}-cancel", user_id, "custom",
                                          "客户已取消", f"需求单号 {oid}，客户已取消行程。",
                                          "2026-09-25 15:20", False, oid)
                continue
            if stage <= 1:
                self._store.upsert_notice(f"n-{oid}-wait", user_id, "custom-wait",
                                          "待接单信息！",
                                          f"需求单号 {oid}，【{dest}】，客户有出行意向，请及时沟通！",
                                          "2026-09-28 13:21", True, oid)
            if stage >= 1:
                self._store.upsert_notice(f"n-{oid}-read", user_id, "custom",
                                          "方案已被阅读",
                                          f"需求单号 {oid}，客户已阅读您发送的方案。",
                                          "2026-09-28 10:18", False, oid)
            if stage == 1:
                self._store.upsert_notice(f"n-{oid}-limit", user_id, "important",
                                          "方案时限提醒",
                                          f"需求单号 {oid}，请在 4 小时内提交方案，超时将影响成团机会。",
                                          "2026-09-28 13:30", True, oid)

    @staticmethod
    def _to_order(o: dict) -> dict:
        from .customer_card import render_intent
        idx = int(o["stage_index"] or 0)
        payload = json.loads(o.get("payload") or "{}")
        return {
            "order_id": o["order_id"], "customer": o["customer"], "destination": o["destination"],
            "status": o["status"], "stage_index": idx,
            "stage_name": ORDER_STEPS[min(idx, len(ORDER_STEPS) - 1)],
            "created_at": payload.get("created_at", o.get("created_at", "")),
            "difficulty": payload.get("difficulty", ""),
            "target_skill_points": payload.get("target_skill_points", []),
            "rationale": (payload.get("brief") or {}).get("rationale", ""),
            "intent": render_intent(o["_customer_card"]) if o.get("_customer_card") else payload.get("intent", ""),
            "generated": bool(payload.get("generated", False)),
            "source_market": payload.get("source_market", DEFAULT_SOURCE_MARKET),
            "language": payload.get("language", "中文"),
            "personality": payload.get("personality", ""),
            "documents": payload.get("documents", ""),
            "hint": STAGE_HINTS[min(idx, len(STAGE_HINTS) - 1)],
            "urgent": idx == 1,
        }

    def _payload(self, order_id: str) -> dict:
        row = self._store.order(order_id)
        return json.loads((row or {}).get("payload") or "{}")

    def _set_payload(self, order_id: str, **kv) -> None:
        row = self._store.order(order_id)
        if not row:
            return
        payload = json.loads(row["payload"] or "{}")
        payload.update(kv)
        self._store.upsert_order(order_id, row["user_id"], row["customer"], row["destination"],
                                 row["status"], int(row["stage_index"] or 0), payload=payload)

    def dispatch_info(self, order_id: str, now=None) -> dict:
        """派单/时限状态；未抢单且已过竞争者时点则**惰性判负**（丢单）。"""
        row = self._store.order(order_id)
        if not row:
            return {}
        payload = json.loads(row["payload"] or "{}")
        grabbed = self._store.has_action(order_id, "grab")
        # 派单时刻：第一次被看到时起算（真实平台是派给你的那一刻），避免种子订单一上来就超时
        if not grabbed and not payload.get("dispatch_at") and row["status"] == "正常":
            payload["dispatch_at"] = datetime.now().isoformat(timespec="seconds")
            self._set_payload(order_id, dispatch_at=payload["dispatch_at"])
        info = dispatch.status(order_id, row["created_at"], payload, grabbed,
                               first_call_at=self._store.action_at(order_id, "first_call"), now=now)
        # 演示实例专用：固定案例单在「注册 → 初测/学习 → 接单」的等待期内不作废（可重复续期）。
        # 普通实例/普通订单：maybe_renew_demo_window 立刻返回 None，规则与原来完全一致。
        if info.get("lost") or info.get("expired"):
            try:
                from tripcraft.services.scenario_service import maybe_renew_demo_window
                renewed = maybe_renew_demo_window(self._store, order_id, row)
            except Exception:                     # noqa: BLE001 - 演示续期失败不得影响普通派单语义
                renewed = None
            if renewed and not grabbed:
                row = self._store.order(order_id) or row
                payload = json.loads(row["payload"] or "{}")
                info = dispatch.status(order_id, row["created_at"], payload, grabbed,
                                       first_call_at=self._store.action_at(order_id, "first_call"),
                                       now=now)
        if info.get("lost") and row["status"] == "正常":
            self._store.upsert_order(order_id, row["user_id"], row["customer"], row["destination"],
                                     "已派他人", int(row["stage_index"] or 0), payload=payload)
            self._store.add_event(order_id, "dispatch_lost", {"reason": info.get("lost_reason", "")})
        fc = info.get("first_call")
        if fc and fc.get("missed") and \
                not self._store.has_action(order_id, "deadline_miss:first_call"):
            self._store.add_action(order_id, "deadline_miss:first_call", {})
            self._store.add_event(order_id, "deadline_miss", {"what": "首呼超时"})
        return info

    def list_orders(self, user_id: str, mine_only: bool = True) -> list[dict]:
        """订单管理只展示本人成功抢到的订单，各阶段与取消状态均遵守同一规则。"""
        out = []
        for o in self._store.orders(user_id):
            claimed = False
            stage_index = int(o["stage_index"] or 0)
            for action in self._store.actions(o["order_id"]):
                if action["action"] != "grab":
                    continue
                evidence = json.loads(action.get("payload") or "{}")
                if not isinstance(evidence, dict):
                    continue
                # 种子历史单的 grab 是流程补录；只要订单已进入后续阶段，
                # 它就是学员订单管理中的历史单，而不是消息中心里的待抢派单。
                if evidence.get("backfill"):
                    claimed = stage_index > 0
                    break
                if evidence.get("by") not in (None, "", user_id):
                    continue
                claimed = True
                break
            item = self._to_order(o)
            # 普通阶段 0 派单尚未抢到，只出现在消息中心；禁用/取消的历史单
            # 仍应在订单管理中可见，供学员复盘，不应因没有 grab 动作而消失。
            if mine_only and not claimed and not (
                    item["stage_index"] == 0 and item["status"] != "正常"):
                continue
            item["claimed"] = claimed
            if item["stage_index"] == 0 and item["status"] == "正常":
                item["dispatch"] = self.dispatch_info(item["order_id"])
            out.append(item)
        return out

    def _publish_due(self) -> list[str]:
        """把到点的候选单放出来（消息中心因此会持续出现新的可抢单）。"""
        published, now = [], datetime.now()
        for oid in UNPUBLISHED_IDS:
            row = self._store.order(oid)
            if not row:
                continue
            payload = json.loads(row["payload"] or "{}")
            if payload.get("published"):
                continue
            at = payload.get("publish_at")
            if not at:
                continue
            try:
                due = datetime.fromisoformat(at)
            except ValueError:
                continue
            if now >= due:
                payload["published"] = True
                payload["dispatch_at"] = now.isoformat(timespec="seconds")   # 放出即开始抢单窗口
                self._store.upsert_order(oid, row["user_id"], row["customer"], row["destination"],
                                         row["status"], int(row["stage_index"] or 0), payload=payload)
                self._store.add_event(oid, "dispatch_published",
                                      {"at": now.isoformat(timespec="seconds")})
                published.append(oid)
        return published

    # ---------- 派单生成（画像驱动，D-045） ----------

    def carried_over_points(self, user_id: str) -> list[str]:
        """上一单「未覆盖」的技能点：本单接着考（PRD 19.4 的补考）。"""
        rows = self._store.orders(user_id)
        for o in sorted(rows, key=lambda x: x["created_at"] or "", reverse=True):
            targets = self._store.targets(o["order_id"])
            if not targets:
                continue
            missed = [t["skill_point_id"] for t in targets if not t["covered"]]
            if missed:
                return missed[:3]
            return []
        return []

    def brief_for(self, user_id: str) -> dict:
        """当前画像对应的本单简报（给前端展示「为什么给你这单」）。"""
        abilities = self._store.abilities(user_id)
        brief = build_brief(abilities, carried_over=self.carried_over_points(user_id))
        daily = dispatch._env()
        d = brief.to_dict()
        d["first_call_limit_min"] = None
        # 把旋钮翻译成人类可读的最终参数
        from ..agents.scenario import _first_call_limit, _preset_incidents
        d["plan"] = {
            "first_call_limit_min": _first_call_limit(brief.knobs["time_pressure"]),
            "default_first_call_limit_min": daily["FIRST_CALL_LIMIT_MIN"],
            "preset_incidents": list(_preset_incidents(brief.knobs["resource_conflict"])),
        }
        return d

    def spawn_order(self, user_id: str, spec, brief: dict | None = None) -> dict:
        """把生成器产出的游客落成一条真实派单（阶段 0、已发布、抢单窗口立即起算）。"""
        ids = [int(o["order_id"]) for o in self._store.orders()
               if str(o["order_id"]).isdigit()]
        oid = str(max(ids) + 1) if ids else "9000000000000001"
        now = datetime.now()
        payload = spec.to_payload()
        payload.update({
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "dispatch_at": now.isoformat(timespec="seconds"),
            "published": True,
            "generated": True,
        })
        if brief:
            payload["brief"] = brief
            payload["difficulty"] = brief.get("label", "")
            payload["target_skill_points"] = brief.get("target_skill_points", [])
        self._store.upsert_order(oid, user_id, spec.customer, spec.destination,
                                 "正常", 0, payload=payload)
        from .customer_card import render_intent
        payload["intent"] = render_intent(self._store.ensure_customer_card(oid))
        self._set_payload(oid, intent=payload["intent"])
        self._store.add_event(oid, "dispatch_generated",
                              {"difficulty": payload.get("difficulty", ""),
                               "source_market": spec.source_market,
                               "language": spec.language})
        return self._store.order(oid) or {}

    def generate_dispatch(self, user_id: str, llm=None, count: int = 1,
                          language: str = "") -> dict:
        """按画像生成 N 条新派单；`language` 为空=随机出各国，指定了就只出该语言的客源。"""
        brief = self.brief_for(user_id)
        existing = [{"source_market": json.loads(o["payload"] or "{}").get("source_market", ""),
                     "destination": o["destination"]} for o in self._store.orders(user_id)]
        gen = DispatchGenerator(llm)
        created = []
        for i in range(max(1, min(count, 5))):
            spec = gen.generate(_brief_obj(brief), existing=existing, seq=len(existing) + i,
                                language=language)
            row = self.spawn_order(user_id, spec, brief=brief)
            created.append({"order_id": row.get("order_id"), "customer": row.get("customer"),
                            "destination": row.get("destination"),
                            "source_market": spec.source_market, "language": spec.language,
                            "difficulty": brief.get("label", "")})
            existing.append({"source_market": spec.source_market, "destination": spec.destination})
        return {"brief": brief, "created": created}

    def available_orders(self, user_id: str) -> list[dict]:
        """消息中心「待接单」用的可抢订单：阶段 0、正常、未抢、未丢单。

        这里的单还不属于学员——抢到之后才会进入「订单管理」。
        """
        self._publish_due()
        out = []
        for o in self._store.orders(user_id):
            # 演示实例专用：此前已被惰性判负的固定案例单，在这里复活为「正常」再参与筛选；
            # 已抢单/已完成/普通订单不受影响（helper 内部逐条判定，普通实例直接 None）。
            if int(o["stage_index"] or 0) == 0 and o["status"] != "正常" \
                    and not self._store.has_action(o["order_id"], "grab"):
                try:
                    from tripcraft.services.scenario_service import maybe_renew_demo_window
                    if maybe_renew_demo_window(self._store, o["order_id"], o):
                        o = self._store.order(o["order_id"]) or o
                except Exception:                 # noqa: BLE001
                    pass
            if int(o["stage_index"] or 0) != 0 or o["status"] != "正常":
                continue
            if self._store.has_action(o["order_id"], "grab"):
                continue
            if json.loads(o["payload"] or "{}").get("published") is False:
                continue          # 还没到放出时间的候选单
            info = self.dispatch_info(o["order_id"])
            if info.get("lost") and not competition_easy():
                continue
            item = self._to_order(o)
            item["dispatch"] = info
            item["missing_fields"] = self._missing_fields(o)
            out.append(item)
        out.sort(key=lambda x: (x.get("dispatch") or {}).get("seconds_left") or 0)
        return out

    @staticmethod
    def _missing_fields(row: dict) -> list[str]:
        """对照派单信息实算缺失字段（首呼要补问的就是这些）。"""
        return missing_fields(json.loads(row.get("payload") or "{}"))

    def get_order(self, order_id: str) -> dict | None:
        row = self._store.order(order_id)
        return self._to_order(row) if row else None

    def order_detail(self, order_id: str) -> dict | None:
        row = self._store.order(order_id)
        if not row:
            return None
        o = self._to_order(row)
        o["steps"] = self.order_steps(order_id)
        o["contacts"] = [
            {"time": c["at"], "kind": c["kind"], "status": c["status"],
             "has_record": bool(c["has_record"]), "detail": c["detail"]}
            for c in self._store.contacts(order_id)
        ]
        o["gate"] = self.gate_report(order_id)
        o["dispatch"] = self.dispatch_info(order_id)
        # 订单级客户人设（与语音/群聊同源）：通话界面在拨打前就能显示"对方是什么人"。
        # R08：这里只出**公开白名单**字段（与 api/public_dto.public_customer_from_facts 同字段集），
        # 隐藏人设（hidden/quirks/preferences/traits/personality）与成本底牌一律不下发前端。
        from .customer_order_facts import facts_from_order_row
        facts = facts_from_order_row(row)
        o["persona"] = {
            "name": facts.customer or "客户",
            "nationality": facts.source_market,
            "age": facts.age,
            "gender": facts.gender,
            "language": facts.language,
            "docs": facts.public_facts()["documents"],
        }
        return o

    def order_steps(self, order_id: str) -> list[dict]:
        """平台 8 态时间轴。

        注意：截止时间一律取自真实的时限计算（dispatch_service），**不写死日期**；
        前端拿到 `deadline_at` 后自己渲染倒计时。
        """
        o = self._store.order(order_id)
        if not o:
            return []
        idx = int(o["stage_index"] or 0)
        info = self.dispatch_info(order_id)
        fc, plan = info.get("first_call"), info.get("plan")
        out = []
        for i, name in enumerate(ORDER_STEPS):
            state = "done" if i < idx else "current" if i == idx else "todo"
            note, urgent, deadline_at = "", False, ""
            if state == "current" and o["status"] != "禁用":
                note = STAGE_HINTS[i]
                if i == 1 and plan:                       # 定制师提供方案 → 方案时限
                    deadline_at = plan["due_at"]
                    urgent = bool(plan["missed"] or plan["seconds_left"] <= 3600)
                elif i == 0 and fc and not fc["done"]:    # 定制师接单 → 首呼时限
                    deadline_at = fc["due_at"]
                    urgent = bool(fc["missed"] or fc["seconds_left"] <= 900)
            out.append({"label": name, "state": state, "note": note,
                        "urgent": urgent, "deadline_at": deadline_at})
        return out

    def messages(self, user_id: str) -> dict:
        """消息中心：身份必须由调用方从登录会话传入，禁止默认成 demo 用户。"""
        rows = self._store.notices(user_id)
        msgs = [{
            "id": r["notice_id"], "group": r["group_key"], "time": r["at"],
            "title": r["title"], "body": r["body"],
            "starred": bool(r["starred"]), "order_id": r["order_id"],
        } for r in rows]
        groups = []
        for g in MESSAGE_GROUPS:
            children = []
            for c in g["children"]:
                children.append({**c, "count": sum(1 for m in msgs if m["group"] == c["key"])})
            groups.append({**g, "children": children,
                           "count": sum(1 for m in msgs if m["group"] == g["key"])})
        return {"groups": groups, "messages": msgs}

    # ---------- 流程通关驱动（D-033） ----------

    def record_action(self, order_id: str, action: str, payload: dict | None = None) -> dict:
        """登记一个学员动作；若本阶段门槛因此全部达成，自动推进平台状态。"""
        if not self._store.order(order_id):
            raise ValueError(f"未找到订单: {order_id}")
        if not is_known_action(action):
            raise ValueError(f"未知动作: {action}")
        if action == "grab":
            info = self.dispatch_info(order_id)
            if info.get("lost") and not competition_easy():
                raise ValueError(info.get("lost_reason", "该单已被接走"))
            if not self._store.has_action(order_id, "grab"):
                self._set_payload(order_id, grabbed_at=datetime.now().isoformat(timespec="seconds"))
        fresh = not self._store.has_action(order_id, action)
        if fresh:
            self._store.add_action(order_id, action, payload)
        advance = self.try_advance(order_id)
        # 动作自动进导演总线：命中规则就注入事件型考点（学员无需手动触发）
        incident = None
        # 门槛动作是幂等的：重复投递同一交付物或重复登记同一动作，
        # 只能推进状态，不能让导演总线把同一个突发事件再触发一次。
        if fresh and self._director is not None:
            try:
                incident = self._director.on_action(order_id, action)
            except Exception:
                incident = None
        return {"order_id": order_id, "action": action, "recorded": fresh,
                "label": ACTION_LABELS.get(action, action),
                "advance": advance, "incident": incident}

    def _action_ok(self, order_id: str, gate) -> tuple[bool, str]:
        # 演示放行只跳过表单/拦截网，不跳过阶段动作；否则任何动作都会跨阶。
        if not self._store.has_action(order_id, gate.action):
            return False, f"待完成：{gate.hint}"
        if gate.within_min:
            # 时效属于考核记录；补做后按动作完成推进，不能把历史超时变成永久死锁。
            # 首呼时限与派单倒计时同源（含订单难度覆盖），并补记未被轮询捕获的超时。
            limit = gate.within_min
            start = self._store.action_at(order_id, "grab")
            if gate.action == "first_call":
                fc = self.dispatch_info(order_id).get("first_call") or {}
                limit = fc.get("limit_min", limit)
                start = self._payload(order_id).get("grabbed_at") or start
            done = self._store.action_at(order_id, gate.action)
            if start and done:
                from datetime import datetime
                minutes = (datetime.fromisoformat(done) - datetime.fromisoformat(start)).total_seconds() / 60
                if minutes > limit:
                    return True, (f"已完成；距抢单 {minutes:.0f} 分钟，超过 {limit} 分钟时限，"
                                  "超时已单独记录")
        return True, ""

    def gate_report(self, order_id: str) -> dict:
        """本阶段完成条件：逐条对着**真实动作**判定，不再是文案。"""
        o = self._store.order(order_id)
        if not o:
            return {"order_id": order_id, "checks": [], "done": 0, "total": 0, "passed": False}
        stage = int(o["stage_index"] or 0)
        gates = gates_for(stage)
        checks = []
        for g in gates:
            ok, reason = self._action_ok(order_id, g)
            checks.append({"action": g.action, "label": g.label, "hint": g.hint,
                           "where": g.where, "ok": ok, "reason": reason,
                           "manual": g.action in MANUAL_ACTIONS})
        done = sum(1 for c in checks if c["ok"])
        return {
            "order_id": order_id, "stage_index": stage,
            "stage_name": ORDER_STEPS[min(stage, len(ORDER_STEPS) - 1)],
            "stage_hint": stage_hint(stage),
            "step": f"S{STAGE_TO_STEP[min(stage, len(STAGE_TO_STEP) - 1)]}",
            "step_evidence": STEP_EVIDENCE.get(
                f"S{STAGE_TO_STEP[min(stage, len(STAGE_TO_STEP) - 1)]}", ""),
            "checks": checks, "done": done, "total": len(checks),
            "passed": done == len(checks),
            "next": next((c for c in checks if not c["ok"]), None),
        }

    def try_advance(self, order_id: str, max_steps: int = 4) -> dict:
        """本阶段门槛全达成则推进平台状态；比赛演示一次动作最多推进一阶。"""
        if competition_easy():
            max_steps = 1
        o = self._store.order(order_id)
        if not o:
            return {"order_id": order_id, "advanced": []}
        start = int(o["stage_index"] or 0)
        cur = start
        for _ in range(max_steps):
            if cur >= MAX_STAGE:
                break
            rep = self.gate_report(order_id)
            if not rep["checks"] or not rep["passed"]:
                break
            cur += 1
            self._store.set_stage(order_id, cur)
            self._store.add_event(order_id, "stage_advanced",
                                  {"from": cur - 1, "to": cur, "stage_name": ORDER_STEPS[min(cur, 7)]})
            # 进入「客户出团」= 出团发生：登记动作，让行中类事件（如车辆故障）有触发点
            if cur == 5 and not self._store.has_action(order_id, "depart"):
                self._store.add_action(order_id, "depart", {"auto": "stage_advanced"})
                if self._director is not None:
                    try:
                        self._director.on_action(order_id, "depart")
                    except Exception:
                        pass
        return {"order_id": order_id, "from": start, "to": cur,
                "advanced": list(range(start + 1, cur + 1)),
                "stage_name": ORDER_STEPS[min(cur, len(ORDER_STEPS) - 1)]}

    def flow_progress(self, order_id: str) -> dict:
        o = self._store.order(order_id)
        idx = int(o["stage_index"] or 0) if o else 0
        current = STAGE_TO_STEP[min(idx, len(STAGE_TO_STEP) - 1)]
        return {
            "current": current,
            "steps": [{"index": i, "name": n, "evidence": STEP_EVIDENCE.get(f"S{i}", ""),
                       "state": "done" if i < current else "current" if i == current else "todo"}
                      for i, n in enumerate(STEPS_13)],
            "step_evidence": STEP_EVIDENCE.get(f"S{current}", ""),
        }

    # ---------- 证据 ----------

    def record_evidence(self, order_id: str, kind: str, text: str,
                        step: str | None = None, ref: str = "") -> int | None:
        """登记一条实战证据（通话 / 交付物 / 询价）。返回 evidence_id，订单不存在时返回 None。"""
        if not self._store.order(order_id):
            return None
        st = step or DELIVERABLE_STEP.get(kind) or EVIDENCE_STEP.get(kind) or ""
        return self._store.add_evidence(order_id, kind, st, ref, text)

    def evidence(self, order_id: str) -> list[dict]:
        return self._store.evidence(order_id)

    def target_skill_points(self, order_id: str) -> list[str]:
        """由「已有证据覆盖的步骤」推出本次要评的技能点。"""
        steps: list[str] = []
        for e in self._store.evidence(order_id):
            st = e.get("step") or ""
            if st and st not in steps:
                steps.append(st)
        ids: list[str] = []
        for st in steps:
            try:
                sid = StepId(st)
            except ValueError:
                continue
            for sp in by_step(sid):
                if sp.id in RUBRICS and sp.id not in ids:
                    ids.append(sp.id)
        return ids

    def supplier_facts_text(self, order_id: str) -> str:
        """本单资源方的客观口径（询到的价 + 已发生的事件），交给评分 Agent 做核对参照。

        它是**客观事实**，不是学员表现：评分时只用来判断学员有没有按资源口径报价、
        有没有在资源不可用/涨价后留出空间，不能拿它当学员证据给分。
        """
        lines: list[str] = []
        for kind, q in (self._store.quotations(order_id) or {}).items():
            q = q or {}
            if not q.get("summary"):
                continue
            extra = f"；{q['note']}" if q.get("note") else ""
            lines.append(f"{kind}：{q['summary']}（可用性 {q.get('availability') or '—'}"
                         f"，回复时限 {q.get('deadline') or '—'}{extra}）")
        for i in self._store.incidents(order_id):
            lines.append(f"事件·{i['title']}（{i['channel']} / {i['step']}）：{i['body']}")
        return "\n".join(lines)

    def scoring_reference(self, order_id: str) -> str:
        """评分 Agent 的核对参照：资源方客观口径 + 本单成本/损失/结算账目。

        两者都不是学员证据，只用来核对「报价是否低于资源成本、损失有没有处理、
        自报利润与实际毛利差多少」。给分仍必须引用学员原话或交付物片段（PRD 21.2）。
        """
        from .finance_service import FinanceService
        parts = [self.supplier_facts_text(order_id),
                 FinanceService(self._store).facts_text(order_id)]
        return "\n".join(p for p in parts if p)

    def _render_evidence(self, order_id: str) -> str:
        blocks = []
        for e in self._store.evidence(order_id):
            head = f"【{e['kind']}】(步骤 {e['step'] or '—'} / {e['created_at']})"
            blocks.append(head + "\n" + (e["text"] or "").strip())
        return "\n\n".join(blocks)

    # ---------- 考核目标 / 覆盖校验（PRD 19.4） ----------

    def mark_trigger(self, order_id: str, sp: str, step: str) -> None:
        """导演注入了对应触发事件：B 型考点进入「已触发，等待反应」。"""
        row = self._store.target(order_id, sp)
        if row and row["trigger_state"] == "reacted":
            return
        sk = SKILL_POINTS_BY_ID.get(sp)
        if sk is None:
            return
        self._store.upsert_target(order_id, sp, sk.checkpoint.value, step,
                                  trigger_state="triggered", covered=False)

    def mark_reacted(self, order_id: str, sp: str) -> None:
        """学员对注入事件有可观测反应：B 型考点算覆盖。"""
        row = self._store.target(order_id, sp)
        sk = SKILL_POINTS_BY_ID.get(sp)
        if sk is None:
            return
        step = row["step"] if row else (sk.steps[0].value if sk.steps else "")
        self._store.upsert_target(order_id, sp, sk.checkpoint.value, step,
                                  trigger_state="reacted", covered=True, reason="触发已发生且学员有反应")

    def plan_steps(self, order_id: str) -> set[str]:
        o = self._store.order(order_id)
        if not o:
            return set()
        idx = int(o["stage_index"] or 0)
        current = STAGE_TO_STEP[min(idx, len(STAGE_TO_STEP) - 1)]
        steps = {st.value for st in list(STEP_ORDER)[:current + 1]}
        steps |= {e["step"] for e in self._store.evidence(order_id) if e["step"]}
        return steps

    def build_plan(self, order_id: str, persist: bool = True, rebuild: bool = False) -> list[str]:
        """本单目标技能点清单：已注入的 B 型 → 画像薄弱点 → 稳定补充，最多 PLAN_LIMIT 条。

        清单一旦生成就**固定下来**（否则每次重算会漂移，覆盖度无法比较）；
        导演后续注入的 B 型考点会作为新行追加进来。
        """
        o = self._store.order(order_id)
        if not o:
            return []
        if not rebuild:
            existing = [t["skill_point_id"] for t in self._store.targets(order_id)]
            # 清单要「固定」但不能「冻结」：导演注入的 B 型考点会先写进目标表，
            # 若直接返回就等于把整单考核范围缩成那 1-2 个事件点（实测踩过）。
            # 因此已有点保留、顺序稳定，不足 PLAN_LIMIT 时按同一套规则补齐。
            if len(existing) >= PLAN_LIMIT:
                return existing
        steps = self.plan_steps(order_id)
        abilities = self._store.abilities(o["user_id"])
        triggered = {t["skill_point_id"] for t in self._store.targets(order_id)
                     if t["trigger_state"] in ("triggered", "reacted")}

        injectable = injectable_points()
        pool = []
        for sp in SKILL_POINTS:
            own = {st.value for st in sp.steps}
            if not (own & steps):
                continue
            if sp.checkpoint is CheckpointType.A_DELIVERABLE and not (own & DELIVERABLE_STEPS):
                continue
            if sp.checkpoint is CheckpointType.B_EVENT and sp.id not in injectable:
                continue     # 没有事件规则能触发它，抽进来也永远考不到
            pool.append(sp)

        def real_of(sid: str) -> float:
            v = (abilities.get(sid) or {}).get("real_v")
            return 999.0 if v is None else float(v)

        tier1 = [sp for sp in pool if sp.id in triggered]
        rest = [sp for sp in pool if sp.id not in triggered]
        rest.sort(key=lambda sp: (real_of(sp.id), _hash(order_id + sp.id)))
        # 维度轮转：每个维度轮流取一个（弱项在前），避免名额被少数维度霸占，
        # 让「还没考过 / 空白的维度」也有机会被考到
        by_dim: dict[str, list] = {}
        for sp in rest:
            by_dim.setdefault(sp.dimension.value, []).append(sp)
        rotated: list = []
        while any(by_dim.values()):
            for dim in list(by_dim):
                if by_dim[dim]:
                    rotated.append(by_dim[dim].pop(0))
        rest = rotated
        chosen = (tier1 + rest)[:max(PLAN_LIMIT, len(tier1))]

        if persist:
            for sp in chosen:
                if self._store.target(order_id, sp.id):
                    continue     # 保留导演侧已写下的触发状态（含触发/反应状态）
                step = next((st.value for st in sp.steps if st.value in steps), "")
                self._store.upsert_target(order_id, sp.id, sp.checkpoint.value, step)
            # 统一按库里顺序返回，保证多次调用结果一致
            return [t["skill_point_id"] for t in self._store.targets(order_id)]
        return sorted(sp.id for sp in chosen)

    def coverage(self, order_id: str, persist: bool = True) -> dict:
        """覆盖校验：A 型看交付物是否存在，B 型看触发+反应（PRD 19.4）。"""
        plan_ids = self.build_plan(order_id, persist=persist)
        evidence_steps = {e["step"] for e in self._store.evidence(order_id) if e["step"]}
        # 事件型考点：记下事件落在哪个会话，未回应时能直接告诉学员去哪补
        where: dict[str, str] = {}
        for inc in self._store.incidents(order_id):
            try:
                sps = json.loads(inc["skill_points"] or "[]")
            except Exception:
                sps = []
            label = " · ".join(x for x in (inc.get("channel"), inc.get("speaker")) if x)
            for sp in sps:
                where.setdefault(sp, label)

        items, covered_n = [], 0
        for sp_id in plan_ids:
            t = self._store.target(order_id, sp_id)
            if not t:
                continue
            sk = SKILL_POINTS_BY_ID.get(t["skill_point_id"])
            if sk is None:
                continue
            counted = True
            if t["checkpoint"] == CheckpointType.B_EVENT.value:
                ok = t["trigger_state"] == "reacted"
                # 事件型：没注入过事件（没解锁 / 没排到）就不算进分母——
                # 本单根本考不到的点，不该拿来扣学员的分
                counted = t["trigger_state"] in ("triggered", "reacted")
                loc = where.get(sp_id, "")
                reason = ("触发已发生且学员有反应" if ok else
                          (f"事件已注入（{loc}），你还没在那个会话里回应" if loc
                           else "触发已注入但学员未在群里回应") if t["trigger_state"] == "triggered" else
                          "本单未注入该事件（技能点未解锁或未排到），不计入覆盖率")
            else:
                own = {st.value for st in sk.steps}
                ok = bool(own & evidence_steps)
                reason = "交付物已产出且可评分" if ok else "本单未产出对应交付物"
            if ok != bool(t["covered"]):
                self._store.upsert_target(order_id, t["skill_point_id"], t["checkpoint"],
                                          t["step"], t["trigger_state"], ok, reason)
            if counted:
                covered_n += 1 if ok else 0
            items.append({"skill_point_id": t["skill_point_id"], "name": sk.name,
                          "checkpoint": t["checkpoint"], "step": t["step"], "counted": counted,
                          "covered": ok, "reason": reason})
        total = sum(1 for i in items if i["counted"])
        ratio = round(covered_n / total, 4) if total else 0.0
        return {"order_id": order_id, "targets": total, "covered": covered_n, "ratio": ratio,
                "threshold": COVERAGE_THRESHOLD, "passed": bool(total and ratio >= COVERAGE_THRESHOLD),
                "items": items}

    # ---------- 评分 ----------

    # ---------- 校准基线（PRD 25.7 验收红线） ----------

    def thresholds(self) -> dict:
        """升级阈值：优先用校准集标定出来的值，没有基线时退回经验值。"""
        run = self._store.latest_calibration()
        if run and run["passed"]:
            return {"confidence": float(run["threshold_conf"]),
                    "boundary_delta": int(run["threshold_delta"]),
                    "source": "校准集标定", "run_id": run["run_id"]}
        return {"confidence": CONF_THRESHOLD, "boundary_delta": BOUNDARY_DELTA,
                "source": "经验默认值（未标定）", "run_id": ""}

    def calibration_gate(self) -> dict:
        """评分 Agent 的准入（PRD 25.7）。

        - **没有校准基线** → 未经校准集验证，本次不写画像（weight=0）。
        - **有基线但未达标** → 允许进入主链但**降权**：只允许「暴露薄弱」（下调），
          不允许用一次未达标记准的判定抬高画像（weight=0.5）。
        - **达标** → 正常写入（weight=1）。
        """
        run = self._store.latest_calibration()
        if not run:
            return {"baseline": False, "passed": False, "weight": 0.0, "run_id": "",
                    "agreement": 0.0, "evidence_accuracy": 0.0, "samples": 0,
                    "reason": "尚未建立校准基线：评分 Agent 未经校准集验证，本次不写画像"}
        ok = bool(run["passed"])
        return {
            "baseline": True, "passed": ok, "weight": 1.0 if ok else 0.5,
            "run_id": run["run_id"],
            "agreement": run["agreement"], "evidence_accuracy": run["evidence_accuracy"],
            "samples": run["samples"], "predictions": run["predictions"],
            "reason": "" if ok else (
                f"最近一次校准未达标（M 档一致率 {run['agreement']:.0%} / "
                f"证据准确率 {run['evidence_accuracy']:.0%}），本次按降权写入：只下调、不上调"),
        }

    def _escalation_reason(self, r) -> str:
        """低置信度升级判据（PRD 25.6）：低置信 / 贴边界 → 转人工，不直接写画像。

        阈值来自校准集标定结果；注意「本单未覆盖」属于覆盖校验，单独处理。
        """
        th = self.thresholds()
        if r.confidence and r.confidence < th["confidence"]:
            return f"评分置信度 {r.confidence:.2f} 低于阈值 {th['confidence']}（{th['source']}）"
        for b in BOUNDARIES:
            if abs(r.score - b) <= th["boundary_delta"]:
                return f"分数 {round(r.score)} 贴近 M 档边界 {b}（±{th['boundary_delta']}），易漂移"
        return ""

    def score_order(self, order_id: str, llm) -> dict:
        """按已有证据评分并写回画像；覆盖度独立用于复盘。"""
        o = self._store.order(order_id)
        if not o:
            return {"ok": False, "error": f"未找到订单: {order_id}", "scored": 0}
        if not self._store.evidence(order_id):
            return {"ok": False, "scored": 0, "skill_points": [],
                    "error": "本单暂无可评分证据：先拨打一通首呼电话，或投递一次交付物"}
        if llm is None:
            raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")

        cov = self.coverage(order_id)
        cal = self.calibration_gate()
        # 演示订单的数据标记：点击生成后把完整评分直接采纳。
        # 普通订单不带此标记，仍严格走置信度／边界复核。
        try:
            order_payload = json.loads(o.get("payload") or "{}")
        except (TypeError, ValueError):
            order_payload = {}
        demo_auto_accept = bool(order_payload.get("auto_accept_scores"))
        if demo_auto_accept:
            cal = {**cal, "weight": 1.0, "demo_auto_accept": True}
        covered_ids = {i["skill_point_id"] for i in cov["items"] if i["covered"]}
        # 只评「已覆盖」的目标技能点：未覆盖的没有素材，评分也只会是幻觉
        ids = [i for i in covered_ids if i in RUBRICS]
        if not ids:
            return {"ok": False, "scored": 0, "skill_points": [],
                    "coverage": {"targets": cov["targets"], "covered": cov["covered"],
                                 "ratio": cov["ratio"], "threshold": cov["threshold"],
                                 "passed": cov["passed"]},
                    "error": "本单目标技能点均未覆盖（无交付物或学员未回应），无法评分"}

        transcript = self._render_evidence(order_id)
        facts = self.scoring_reference(order_id)       # 资源方口径 + 成本账目（核对用，非证据）
        agent = ScoringAgent(llm)
        results = []
        for i in range(0, len(ids), SCORE_BATCH):
            batch = [RUBRICS[j] for j in ids[i:i + SCORE_BATCH]]
            results.extend(agent.score(transcript, batch, facts=facts))

        entries, dropped, escalated, written = [], [], [], []
        for r in results:
            if r.skill_point_id not in ids:
                continue
            if not r.evidence:
                dropped.append(r.skill_point_id)      # 每分必有证据（PRD 21.2）
                continue
            reason = self._escalation_reason(r)
            # 评分模型说“有证据”还不够：把评分理由与引文再送一次 claim 级审计，
            # 防止引用存在但评论中的结论没有被引文支持。这里只把高风险/缺支持
            # 的判定升级到人工复核，低风险词项偏差保留在 evidence_audit 中可追踪。
            audit_rows = []
            quotes = []
            for idx, ev in enumerate(r.evidence or [], 1):
                if isinstance(ev, dict):
                    quote = str(ev.get("quote") or ev.get("text") or ev.get("content") or "").strip()
                    source = str(ev.get("source") or f"practice:{order_id}:{r.skill_point_id}:{idx}")
                else:
                    quote = str(ev or "").strip()
                    source = f"practice:{order_id}:{r.skill_point_id}:{idx}"
                if quote:
                    quotes.append(quote)
                    audit_rows.append({"id": f"P:{r.skill_point_id}:{idx}", "source": source,
                                       "text": quote, "trust": "observed"})
            registry = OfficialSourceRegistry(self._store)
            evidence_audit = get_verifier().audit(
                "\n".join([str(r.comment or ""), *quotes]), audit_rows,
                strict_provenance=True, snapshot_resolver=registry.resolve,
            )
            if evidence_audit.get("decision") == "human_review" and not reason:
                reason = "评分 claim 证据审计未通过：" + str(evidence_audit.get("reason") or "需人工复核")
            status = "已入库" if demo_auto_accept else ("待复核" if reason else "已入库")
            if demo_auto_accept and reason:
                reason = "演示订单自动采纳（原复核原因：" + reason + "）"
            self._store.upsert_order_score(order_id, r.skill_point_id, r.score, r.level,
                                           r.hit_negative, r.evidence, r.comment, "实战",
                                           confidence=r.confidence, status=status, review_reason=reason)
            item = {"skill_point_id": r.skill_point_id, "score": round(r.score), "level": r.level,
                    "comment": r.comment, "confidence": round(r.confidence, 2),
                    "evidence": list(r.evidence or []), "evidence_audit": evidence_audit,
                    "covered": True, "status": status, "review_reason": reason}
            entries.append(item)
            if status == "待复核":
                escalated.append(item)
                continue
            if cal["weight"] <= 0:
                continue                              # 校准与低置信度规则独立保留。
            if cal["weight"] < 1.0:
                # 降权（校准未达标）下只采信「暴露薄弱」的判定：
                # 低于掌握门槛（M1，<60）才写画像；「证明能力」的高判定一律不采信，
                # 否则等于用一次未达标的评审去抬高学员画像。
                prev = float((self._store.abilities(o["user_id"]).get(r.skill_point_id) or {})
                             .get("real_v") or 0)
                if r.score >= MASTERY_FLOOR or (prev and r.score >= prev):
                    item["status"] = "已入库（降权·仅记薄弱）"
                    item["review_reason"] = item["review_reason"] or "校准未达标：只采信暴露薄弱的判定"
                    continue
                item["status"] = "已入库（降权）"
            self._store.set_ability(o["user_id"], r.skill_point_id, real_v=r.score)
            # 实战评分同样进入反馈回流：把证据、错误类型和置信度落成学习信号，
            # 供后续错误模式聚合与技能资产候选使用，而不是只更新一个平均分。
            try:
                signal = compile_learning_signal(
                    o["user_id"], r.skill_point_id, r.score >= MASTERY_FLOOR, r.score,
                    r.evidence, context=f"order:{order_id}", source="practice",
                    confidence=float(r.confidence or 0.6))
                item["learning_signal"] = persist_learning_signal(self._store, signal)
            except Exception as exc:  # 反馈持久化异常不能回滚已完成的有效评分
                item["feedback_error"] = f"{type(exc).__name__}: {exc}"
            written.append(item)

        return {
            "ok": True, "order_id": order_id,
            "scored": len(entries), "written": len(written),
            "dropped": dropped, "escalated": escalated, "candidates": len(ids),
            "coverage": {"targets": cov["targets"], "covered": cov["covered"],
                         "ratio": cov["ratio"], "threshold": cov["threshold"],
                         "passed": cov["passed"]},
            "calibration": cal,
            "thresholds": self.thresholds(),
            "deferred": cal["weight"] <= 0 and bool(entries),
            "deferred_reason": self._deferred_reason(cal),
            "skill_points": entries,
            "average": round(sum(e["score"] for e in entries) / len(entries)) if entries else None,
        }

    @staticmethod
    def _deferred_reason(cal: dict) -> str:
        return cal.get("reason", "") if cal["weight"] < 1.0 else ""

    def review_score(self, order_id: str, sp: str, decision: str, score: float | None = None) -> dict:
        """人工复核低置信度判定：accept 采纳 / override 改判 / reject 驳回。"""
        o = self._store.order(order_id)
        if not o:
            raise ValueError(f"未找到订单: {order_id}")
        row = self._store.order_scores(order_id).get(sp)
        if not row:
            raise ValueError(f"该订单没有 {sp} 的评分记录")
        if decision == "accept":
            self._store.set_score_status(order_id, sp, "已入库（人工采纳）")
            self._store.set_ability(o["user_id"], sp, real_v=row["score"])
            return {"order_id": order_id, "skill_point_id": sp, "decision": decision,
                    "score": round(row["score"]), "written": True}
        if decision == "override":
            if score is None:
                raise ValueError("override 必须提供 score")
            lvl = level_of(score)
            self._store.upsert_order_score(order_id, sp, score, lvl, bool(row["hit_negative"]),
                                           json.loads(row["evidence"] or "[]"), row["comment"],
                                           "人工复核改判", confidence=1.0,
                                           status="已入库（人工改判）", review_reason="人工复核改判")
            self._store.set_ability(o["user_id"], sp, real_v=score)
            return {"order_id": order_id, "skill_point_id": sp, "decision": decision,
                    "score": round(score), "level": lvl, "written": True}
        if decision == "reject":
            self._store.set_score_status(order_id, sp, "已驳回")
            return {"order_id": order_id, "skill_point_id": sp, "decision": decision, "written": False}
        raise ValueError("decision 只能是 accept / override / reject")

    def pending_reviews(self, order_id: str) -> list[dict]:
        return [{"skill_point_id": r["skill_point_id"], "score": round(r["score"]),
                 "level": r["level"], "confidence": round(r["confidence"] or 0, 2),
                 "review_reason": r["review_reason"], "comment": r["comment"],
                 "evidence": json.loads(r["evidence"] or "[]")}
                for r in self._store.pending_reviews(order_id)]

    def order_scores(self, order_id: str) -> dict:
        o = self.get_order(order_id)
        if not o:
            return {"order_id": order_id, "dimensions": [], "average": None,
                    "evaluated": 0, "total": 0}
        saved = self._store.order_scores(order_id)
        dims = []
        for d in Dimension:
            points = []
            for sp in SKILL_POINTS:
                if sp.dimension is not d:
                    continue
                row = saved.get(sp.id)
                if row:
                    points.append({
                        "id": sp.id, "name": sp.name, "score": round(row["score"]),
                        "level": row["level"], "evaluated": True,
                        "hit_negative": bool(row["hit_negative"]), "comment": row["comment"],
                        "evidence": json.loads(row["evidence"] or "[]"),
                        "confidence": round(row.get("confidence") or 0, 2),
                        "status": row.get("status") or "已入库",
                        "review_reason": row.get("review_reason") or "",
                    })
                else:
                    points.append({"id": sp.id, "name": sp.name, "score": None,
                                   "level": "", "evaluated": False,
                                   "hit_negative": False, "comment": "", "evidence": [],
                                   "confidence": 0, "status": "", "review_reason": ""})
            vals = [p["score"] for p in points if p["evaluated"]]
            dims.append({"id": d.value, "name": DIMENSION_NAMES[d],
                         "score": round(sum(vals) / len(vals)) if vals else None,
                         "evaluated": len(vals), "total": len(points), "points": points})
        allv = [p["score"] for d in dims for p in d["points"] if p["evaluated"]]
        return {
            "order_id": order_id, "customer": o["customer"], "destination": o["destination"],
            "source_market": o.get("source_market", DEFAULT_SOURCE_MARKET),
            "language": o.get("language", "中文"),
            "stage_index": o["stage_index"], "stage_name": o["stage_name"],
            "average": round(sum(allv) / len(allv)) if allv else None,
            "evaluated": len(allv), "total": sum(len(d["points"]) for d in dims),
            "dimensions": dims,
        }


def _brief_obj(brief: dict) -> LearnerBrief:
    """把 dict 还原成简报对象（生成器需要它的 knobs）。"""
    return LearnerBrief(
        user_id=brief.get("user_id", ""), level=int(brief.get("level", 0)),
        branch=brief.get("branch", ""), label=brief.get("label", ""),
        target_skill_points=tuple(brief.get("target_skill_points") or ()),
        target_names=tuple(brief.get("target_names") or ()),
        target_dimensions=tuple(brief.get("target_dimensions") or ()),
        mastery=brief.get("mastery") or {}, knobs=brief.get("knobs") or {},
        rationale=brief.get("rationale", ""),
        carried_over=tuple(brief.get("carried_over") or ()),
    )