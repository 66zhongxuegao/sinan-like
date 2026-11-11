"""标准案例 provider —— 确定性/离线演示的**显式**资料与响应注入。

设计口径（对应交接文档第五节与 R01–R17 的安全边界）：

1. **固定资料只来自一个文件**：`data/scenario/standard_case.json`。客人、日期、需求、
   预算、资源约束、四份文档字段、行中事件、结算与复盘值全部写死；本模块不做随机、
   不按画像调难度（`agents.scenario.spec_from_case` 是确定性转换）。
2. **状态变化一律走真实服务**：导入订单调用 `PracticeService.spawn_order`，文档走
   `DeliverableService.submit`，结算走 `FinanceService.settle`，评分走
   `PracticeService.score_order` —— provider 只提供「内容」，不直接改库状态置完成。
3. **离线响应器是显式的、会出声的**：`ScenarioLLM` 实现 `DeepSeekClient` 的
   `chat / chat_json` 协议，按调用点的系统提示词分派固定回答；**没覆盖到的调用点抛
   `ScenarioUnsupportedError`**，绝不返回空串或静默跳过。
4. **不假装实时**：`mode` 只有 `offline` / `live` 两种，由 `status()` 如实汇报；
   离线判定的置信度被**压下 0.6 上限**，让系统的「低置信度转人工复核」这条真实闸门
   自己生效——演示数据不许自动写进画像，必须经人工复核采纳（真实产品路径）。
5. **重置只动当前账号**：`reset()` 只删指定账号名下（可选只限本案例）的订单与其从属
   数据，删除清单逐表返回；其它账号的数据一律不碰。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
import os
import re
from pathlib import Path
from typing import Any

from tripcraft.agents.llm import LLMError, load_env, parse_json
from tripcraft.agents.scenario import DEMO_LABEL, TouristSpec, spec_from_case
from tripcraft.contracts import stages as stage_contract

ROOT = Path(__file__).resolve().parents[2]
CASE_FILE = ROOT / "data" / "scenario" / "standard_case.json"

MODE_OFFLINE = "offline"
MODE_LIVE = "live"

# 离线演示判定的置信度上限：低于 practice_service 的 CONF_THRESHOLD（0.7），
# 因此确定性判定一定会"转人工复核"，不会自动写进画像。这是有意的安全设计。
SCENARIO_CONFIDENCE_CAP = 0.6

# 重置时的删除顺序（**先子后父**，监督者审核指出原顺序会留孤儿记录）：
#   1. 订单级叶子表（直接带 order_id）
#   2. 会话/通话的子表（通过父表子查询定位）
#   3. 会话/通话父表
#   4. 订单主表
#   5. （可选）账号级学习/画像数据：线程子表 → 线程父表 → 其余账号表
CASE_LEAF_TABLES = (
    "customer_fact_event", "customer_feedback_turn", "order_customer",
    "order_evidence", "order_score", "order_target", "order_action", "incident",
    "director_event", "deliverable_doc", "deliverable_draft", "deliverable_file", "order_contact",
    "finance_entry", "order_settlement", "plan_version", "notice", "supplier_quote",
    "contact",
)
CASE_CHILD_TABLES = (
    ("im_message", "session_id", "im_session", "session_id"),
    ("call_line", "session_id", "call_session", "session_id"),
)
CASE_PARENT_TABLES = ("im_session", "call_session")
CASE_MAIN_TABLE = "biz_order"
# 账号级（重置到空白）：同样先子后父
USER_CHILD_TABLES = (("thread_message", "thread_id", "thread", "thread_id"),)
USER_PARENT_TABLES = ("thread",)
USER_TABLES = ("asset", "quiz_attempt", "memory", "profile_snapshot", "profile_baseline",
               "ability", "profile", "doc_template")
# 资源方状态：按 order_id 的随订单删，全局默认行（order_id='')按账号删
SUPPLIER_TABLE = "supplier_state"


class ScenarioError(RuntimeError):
    """标准案例的显式错误（资料缺失/口径不符/调用点未覆盖）。"""


class ScenarioUnsupportedError(ScenarioError):
    """离线响应器没有覆盖这个 LLM 调用点——必须报错，不许静默兜底。"""


# ---------------------------------------------------------------- 资料读取

def case_file(path: str | Path | None = None) -> Path:
    return Path(path) if path else CASE_FILE


def load_case_document(path: str | Path | None = None) -> dict:
    p = case_file(path)
    if not p.exists():
        raise ScenarioError(f"标准案例资料不存在: {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"标准案例资料不是合法 JSON: {exc}") from exc
    if not isinstance(doc, dict) or not doc.get("cases"):
        raise ScenarioError("标准案例资料缺少 cases 段")
    return doc


def case_digest(path: str | Path | None = None) -> str:
    """资料文件的内容哈希：用于核对「两次读取完全一致」。"""
    return hashlib.sha256(case_file(path).read_bytes()).hexdigest()


def list_cases(path: str | Path | None = None) -> list[dict]:
    return list(load_case_document(path)["cases"])


def get_case(case_id: str, path: str | Path | None = None) -> dict:
    for c in list_cases(path):
        if str(c.get("case_id")) == case_id:
            return c
    raise ScenarioError(f"未知标准案例: {case_id}")


def case_summary(case: dict) -> dict:
    """给前端/脚本的案例摘要（不含任何隐藏评分口径之外的敏感字段——本案例无隐藏字段）。"""
    t = case.get("tourist") or {}
    return {
        "case_id": case.get("case_id"),
        "title": case.get("title"),
        "demo_label": case.get("demo_label") or DEMO_LABEL,
        "demo_data": bool(case.get("demo_data", True)),
        "customer": t.get("customer"),
        "source_market": t.get("source_market"),
        "language": t.get("language"),
        "destination": t.get("destination"),
        "party": t.get("party"),
        "dates": t.get("dates"),
        "days": t.get("days"),
        "budget": t.get("budget"),
        "hotel": t.get("hotel"),
        "transport": t.get("transport"),
        "special": t.get("special"),
        "resource_constraints": list(case.get("resource_constraints") or []),
        "demo_account": (case.get("isolation") or {}).get("demo_account_username", ""),
        "stage_ids": list((case.get("acceptance") or {}).get("stage_ids") or []),
        "realtime_dependencies": case.get("realtime_dependencies") or {},
    }


def stage_plan() -> list[dict]:
    """六阶段口径（唯一来源：contracts/stages.py）+ 每一步该做什么（给指南/前端用）。"""
    plan = []
    for st in stage_contract.STAGES:
        plan.append({
            "id": st.id, "name": st.name, "short": st.short, "order": st.order,
            "steps": list(st.steps), "deliverables": list(st.deliverables),
            "focus": st.focus,
            "substeps": [{"id": s.id, "name": s.name, "hint": s.hint,
                          "step": s.step, "deliverable": s.deliverable}
                         for s in st.substeps],
        })
    return plan


def dependency_status(probe_llm: bool = False) -> dict:
    """实时依赖状态：**区分「配置存在」与「真实连通已核验」**（监督者审核第 3 条）。

    - `*_key_present`：只在 local.env / 环境变量里找到了 key，不代表能用。
    - `*_connectivity_verified`：只有真的发过一次请求并拿到回应才是 true。
    - `*_not_verified_reason`：没核验时写清原因，不谎报。
    认证状态不再读已删除的 TRIPCRAFT_AUTH：security v2 是**始终强制**。
    """
    env = load_env()
    llm_key = (os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY") or "").strip()
    voice_key = (os.environ.get("DASHSCOPE_API_KEY") or env.get("DASHSCOPE_API_KEY") or "").strip()
    out: dict[str, Any] = {
        "llm_key_present": bool(llm_key),
        "llm_key_source": ("env" if os.environ.get("DEEPSEEK_API_KEY") else
                           ("local.env" if env.get("DEEPSEEK_API_KEY") else "")),
        "llm_connectivity_verified": False,
        "llm_not_verified_reason": "尚未核验（未设置 key）" if not llm_key else "尚未发起真实请求核验",
        "voice_key_present": bool(voice_key),
        "voice_key_source": ("env" if os.environ.get("DASHSCOPE_API_KEY") else
                             ("local.env" if env.get("DASHSCOPE_API_KEY") else "")),
        "voice_connectivity_verified": False,
        "voice_not_verified_reason": ("实时语音需要浏览器麦克风参与，声学链路不能由文本脚本代替验收"
                                      + ("；当前未设置 DASHSCOPE_API_KEY" if not voice_key else "")),
        "db_path": os.environ.get("TRIPCRAFT_DB") or str(ROOT / "tripcraft.sqlite"),
        "auth_mode": "always-on（security v2：认证始终强制，无 off 开关）",
        "scenario_mode_env": os.environ.get("TRIPCRAFT_SCENARIO_MODE", "").strip().lower() or "(unset→live)",
    }
    if probe_llm and llm_key:
        # 真发一次最小请求：成功才算 verified
        try:
            from tripcraft.agents.llm import DeepSeekClient
            client = DeepSeekClient(env if not os.environ.get("DEEPSEEK_API_KEY") else None)
            reply = client.chat([{"role": "user", "content": "ping"}], temperature=0, max_tokens=1)
            out["llm_connectivity_verified"] = bool(str(reply).strip() or reply == "")
            out["llm_not_verified_reason"] = "" if out["llm_connectivity_verified"] else "请求返回空内容"
            out["llm_probe_model"] = getattr(client, "model", "")
        except Exception as exc:                      # LLMError 或任何网络错误：如实记录
            out["llm_connectivity_verified"] = False
            out["llm_not_verified_reason"] = f"真实请求失败：{type(exc).__name__}: {exc}"[:200]
    elif probe_llm and not llm_key:
        out["llm_not_verified_reason"] = "未设置 DEEPSEEK_API_KEY，无法核验真实连通"
    return out


# ---------------------------------------------------------------- 离线响应器

_CALL_SIG = "你在扮演一位正在接听定制师首呼电话的客户"
_SCORER_SIG = "你是定制师实训的评分专家"
_TEACHER_SIG = "你是「司南」"
_ASSET_SIG = "你是定制师培训教研专家"
_JUDGE_SIG = "你是评分专家。依据给定 Rubric"
_QUESTION_SIG = "你是实战出题老师"
_ROUTER_SIG = "你是定制师实训系统的核心调度器"
_PROFILE_SIG = "你是画像顾问"
_TOOLS_CUSTOMER_SIG = "你是那位客户，正在微信/电话里看定制师发来的方案或报价"
_IM_CUSTOMER_SIG = "你在扮演一位来中国旅行的客户，正在客户服务群里和你的定制师沟通"
_GUIDE_SIG = "这一个团的"
_SUPPLIER_IM_SIG = "【这一单的客观事实（只能基于这些回答，不得编造或改动数字）】"
_GUARD_SIG = "你是定制游交付物的合规质检员"
_PROFILER_SIG = "你是入境游定制师训练系统的「画像 Agent」"
_HAT_SIG = "六帽审查"
_REQUIREMENTS_SIG = "你是需求结构化专家"
_DISPATCH_SIG = "你是携程定制游平台的派单系统"
_TOOLS_SUPPLIER_SIG = "【当前情景约束】"

_SP_RE = re.compile(r"【([A-Z]\d+\.\d+)】")
# 训练卡选择：从提示词里抓技能点（thread_service 第二条 system 消息含「【本次技能点】…（C6.1）」）
_SP_ANY_RE = re.compile(r"C[1-8]\.\d+")

# ============================================================================
# 内部演示实例：把「随机游客」替换成固定标准案例
# ----------------------------------------------------------------------------
# 开关完全由**启动期后台配置**决定，不看账号名 / localStorage / 公开 UI 按钮：
#   TRIPCRAFT_SCENARIO_MODE=offline  实例被声明为确定性演示实例（既有口径）
#   TRIPCRAFT_DEMO_TOURIST=on        显式开启「固定案例替换随机游客」
#   TRIPCRAFT_DEMO_CASE=<case_id>    可选：指定用哪个案例（默认标准案例）
# 两个都要满足才生效；只开 offline（例如 provider 自检）不会替换任何游客。
# ============================================================================
DEMO_TOURIST_ENV = "TRIPCRAFT_DEMO_TOURIST"
DEMO_CASE_ENV = "TRIPCRAFT_DEMO_CASE"
_TRUE = ("1", "on", "true", "yes")


def default_case_id() -> str:
    """案例文件里的第一个案例（默认标准案例），不用硬编码字符串。"""
    cases = list_cases()
    if not cases:
        raise ScenarioError("案例文件里没有案例")
    return str(cases[0].get("case_id") or "")


def demo_instance() -> dict:
    """当前实例是否启用「固定案例替换随机游客」（供路由开关与状态展示）。"""
    env_mode = str(os.environ.get("TRIPCRAFT_SCENARIO_MODE", "")).strip().lower()
    flag = str(os.environ.get(DEMO_TOURIST_ENV, "")).strip().lower()
    case_id = str(os.environ.get(DEMO_CASE_ENV, "")).strip() or default_case_id()
    enabled = env_mode == "offline" and flag in _TRUE
    if enabled:
        reason = f"{DEMO_TOURIST_ENV}={flag} 且 TRIPCRAFT_SCENARIO_MODE=offline"
    elif env_mode != "offline":
        reason = "本实例未声明为演示实例（TRIPCRAFT_SCENARIO_MODE != offline）：保持随机游客/真实链路"
    else:
        reason = f"演示实例但未显式开启替换（{DEMO_TOURIST_ENV} 未设为 on）：保持随机游客"
    return {"enabled": enabled, "case_id": case_id, "mode": env_mode or "live", "reason": reason}


def _demo_brief(case: dict) -> dict:
    """与随机派单 brief 同形状的最小确定性简报（调用方只读 label/create 等信息）。"""
    tourist = case.get("tourist") or {}
    return {"label": tourist.get("difficulty_label") or DEMO_LABEL,
            "source_market": tourist.get("source_market", ""),
            "destination": tourist.get("destination", ""),
            "language": tourist.get("language", ""),
            "scenario_id": case.get("case_id", ""), "demo_data": True}


def demo_replacement(ctx, user_id: str, count: int = 1) -> dict | None:
    """演示实例里把「新派单 / 注册初始单」改派成固定标准案例。

    返回 None = 不是演示实例，调用方照常走随机游客链路。
    幂等：该账号已有本案例订单（含已完成）时**复用**，不重复建单、不动已有记录。
    """
    info = demo_instance()
    if not info["enabled"]:
        return None
    case_id = info["case_id"]
    svc = ScenarioService(ctx)
    brief = _demo_brief(get_case(case_id))
    existing = _case_order_of(ctx, user_id, case_id)
    if existing:
        # 复用前续期：注册后先做初测/学习（可能远超抢单窗口），固定单仍要能被接单
        maybe_renew_demo_window(ctx.store, existing["order_id"])
        return {"replaced": True, "reused": True, "seeded": True, "case_id": case_id,
                "brief": brief, "orders": [existing["order_id"]],
                "created": [_created_entry(existing)],
                "how": f"scenario 演示实例：复用已有固定案例单（{case_id}）"}
    imported = svc.import_case(user_id, case_id)
    return {"replaced": True, "reused": False, "seeded": True, "case_id": case_id,
            "brief": brief, "orders": [imported.get("order_id")],
            "created": [{"order_id": imported.get("order_id"),
                         "customer": imported.get("customer"),
                         "destination": imported.get("destination"),
                         "source_market": (imported.get("fixed_fields") or {}).get("source_market", ""),
                         "language": (imported.get("fixed_fields") or {}).get("language", ""),
                         "scenario_id": case_id, "demo_data": True}],
            "import": imported,
            "how": f"scenario 演示实例：按固定案例 {case_id} 改派（替换随机游客）"}


def _case_order_of(ctx, user_id: str, case_id: str) -> dict | None:
    """该账号名下本案例的订单（最新一条；含已完成，用于幂等与保留）。"""
    for o in ctx.store.orders(user_id):
        try:
            payload = json.loads(o.get("payload") or "{}")
        except json.JSONDecodeError:
            continue
        if str(payload.get("scenario_id") or "") == case_id:
            return {"order_id": o.get("order_id"), "customer": o.get("customer"),
                    "destination": o.get("destination"),
                    "source_market": payload.get("source_market", ""),
                    "language": payload.get("language", ""),
                    "stage_index": o.get("stage_index"), "status": o.get("status"),
                    "scenario_id": case_id, "demo_data": True}
    return None


def maybe_renew_demo_window(store, order_id: str, row: dict | None = None) -> dict | None:
    """**演示实例专用**：未接单的固定案例单不因学习等待/竞争者而作废（可重复、安全）。

    生效条件（全部满足，否则返回 None，普通实例与普通订单完全不受影响）：
      · 本实例是显式内部演示实例（TRIPCRAFT_DEMO_TOURIST=on + SCENARIO_MODE=offline）
      · 该订单 payload.scenario_id == 本案例 id（就是那张固定单）
      · stage_index == 0 且**没有** grab 动作且状态不是禁用/已完成/已取消
    动作：把 dispatch_at 续到当前时间（重置抢单窗口），必要时把「已派他人」改回「正常」，
    并记一条 dispatch_window_renewed 事件留证。已抢单/已完成/其它订单一律不动。
    """
    info = demo_instance()
    if not info["enabled"]:
        return None
    row = row or store.order(order_id)
    if not row:
        return None
    if store.has_action(order_id, "grab"):
        return None
    if int(row.get("stage_index") or 0) != 0:
        return None
    status = str(row.get("status") or "")
    if status in ("禁用", "已完成", "已取消"):
        return None
    payload = json.loads(row.get("payload") or "{}")
    if str(payload.get("scenario_id") or "") != info["case_id"]:
        return None
    payload["dispatch_at"] = datetime.now().isoformat(timespec="seconds")
    store.upsert_order(order_id, row["user_id"], row["customer"], row["destination"],
                       "正常", 0, payload=payload)
    store.add_event(order_id, "dispatch_window_renewed", {
        "why": "演示实例固定案例：注册后先做初测/学习，等待期间保持可接",
        "case_id": info["case_id"], "from_status": status})
    return {"renewed": True, "order_id": order_id, "case_id": info["case_id"],
            "from_status": status}


def _created_entry(order: dict) -> dict:
    return {"order_id": order.get("order_id"), "customer": order.get("customer"),
            "destination": order.get("destination"),
            "source_market": order.get("source_market", ""),
            "language": order.get("language", ""),
            "scenario_id": order.get("scenario_id", ""), "demo_data": True}


def _hash(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) % 100003
    return h


class ScenarioLLM:
    """离线确定性响应器：实现 DeepSeekClient 的 chat / chat_json 协议。

    分派依据是调用点的系统提示词（各 Agent 的系统提示词首句，稳定且有辨识度）；
    未覆盖的调用点抛 `ScenarioUnsupportedError`，并带上提示词片段，方便补齐。
    所有回答都来自 `data/scenario/standard_case.json` 或案例内的确定性规则。
    """

    def __init__(self, case: dict, *, confidence_cap: float = SCENARIO_CONFIDENCE_CAP) -> None:
        self.case = case
        self.confidence_cap = confidence_cap
        self.calls: list[dict] = []          # 审计：谁调用了、走了哪个 handler

    @property
    def model(self) -> str:
        return "scenario-deterministic"

    # ---- LLM 客户端协议 ----

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.7,
             max_tokens: int = 2000, json_mode: bool = False) -> str:
        system = "\n".join(str(m.get("content") or "") for m in messages
                           if m.get("role") == "system")
        user = ""
        for m in messages:
            if m.get("role") == "user":
                user = str(m.get("content") or "")
        card_match = re.search(r"<CUSTOMER_CARD>(.*?)</CUSTOMER_CARD>", system, re.S)
        if card_match:
            from .customer_context import fallback_reply
            card = json.loads(card_match.group(1))
            if "【客户文档反馈】" in system:
                text = self._deliverable_feedback(system, user)
                data = json.loads(text)
                # 标准案例原话中的事实随当前事实卡同步，保留案例的行程反馈规则。
                tourist = self.case.get("tourist") or {}
                for key, fact in card["fields"].items():
                    previous = str(tourist.get(key) or "")
                    if previous and fact["value"]:
                        data["reply"] = data["reply"].replace(previous, fact["value"])
                text = json.dumps(data, ensure_ascii=False)
            elif "刚打来电话" in user or "刚打来" in user:
                text = fallback_reply(card, "定制师刚打来电话")
            else:
                text = fallback_reply(card, user)
            self.calls.append({"handler": "_customer_card", "chars": len(text)})
            return text
        handler = self._pick(system)
        if handler is None:
            raise ScenarioUnsupportedError(
                "离线响应器未覆盖该调用点，拒绝返回空值。system 片段："
                + system.strip().replace("\n", " ")[:120])
        # 只有「客户通话」需要会话内的轮次：轮次从**本会话的消息历史**推导，
        # 不用全局计数器——两个账号/两个订单并发时互不消耗对方的轮次。
        # 注意：绑定方法每次访问都是新对象，必须按名字比较（不能用 `is`）。
        if getattr(handler, "__name__", "") == "_customer_call":
            text = handler(system, user, messages)
        else:
            text = handler(system, user)
        self.calls.append({"handler": handler.__name__, "chars": len(text)})
        return text

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.2,
                  max_tokens: int = 4000):
        return parse_json(self.chat(messages, temperature=temperature, max_tokens=max_tokens,
                                    json_mode=True))

    def audit(self) -> dict:
        counts: dict[str, int] = {}
        for c in self.calls:
            counts[c["handler"]] = counts.get(c["handler"], 0) + 1
        return {"calls": len(self.calls), "by_handler": counts}

    # ---- 分派 ----

    def _pick(self, system: str):
        table = (
            (_CALL_SIG, self._customer_call),
            (_SCORER_SIG, self._scorer),
            (_TEACHER_SIG, self._teacher),
            (_ASSET_SIG, self._asset),
            (_JUDGE_SIG, self._judge),
            (_QUESTION_SIG, self._question),
            (_ROUTER_SIG, self._router_plan),
            (_PROFILE_SIG, self._profile_advice),
            (_TOOLS_CUSTOMER_SIG, self._deliverable_feedback),
            (_IM_CUSTOMER_SIG, self._im_customer),
            (_SUPPLIER_IM_SIG, self._im_supplier),
            (_GUIDE_SIG, self._im_guide),
            (_GUARD_SIG, self._guard_semantic),
            (_PROFILER_SIG, self._profiler),
            (_HAT_SIG, self._hat),
            (_REQUIREMENTS_SIG, self._requirements),
            (_DISPATCH_SIG, self._dispatch),
            (_TOOLS_SUPPLIER_SIG, self._tools_supplier),
        )
        for sig, fn in table:
            if sig in system:
                return fn
        return None

    # ---- 客户（首呼 / IM / 交付物反馈）----

    def _customer_call(self, system: str, user: str, messages: list[dict] | None = None) -> str:
        """客户台词：轮次 = 本会话消息历史里已有的 assistant 条数（**无全局计数**）。

        两个账号/两个订单并发时，各自的轮次只取决于各自会话的 messages，
        因此互不消耗、互不串词。"""
        lines = list((self.case.get("first_call") or {}).get("customer_lines") or [])
        if not lines:
            raise ScenarioError("标准案例缺少 first_call.customer_lines")
        prior = sum(1 for m in (messages or []) if m.get("role") == "assistant")
        return lines[min(prior, len(lines) - 1)]

    def _d4_verdict(self, content: str) -> str:
        """看客户版渲染内容里 D4 到底是初稿还是已改：museum / adjusted / unknown。

        只看**第 4 天那一行**（渲染的逐日表格行含 D4），避免正文里其它提到"博物馆"的地方
        （例如复盘、备注）干扰判断。
        """
        for line in (content or "").splitlines():
            if "D4" in line:
                if "翠湖短线" in line or "花市手工" in line:
                    return "adjusted"
                if "博物馆" in line:
                    return "museum"
        if "翠湖短线" in content or "花市手工" in content:
            return "adjusted"
        if "博物馆" in content:
            return "museum"
        return "unknown"

    def _deliverable_feedback(self, system: str, user: str) -> str:
        kind = ""
        m = re.search(r"「(.+?)」", user)
        if m:
            kind = m.group(1)
        replies = self.case.get("customer_replies") or {}
        rules = self.case.get("plan_feedback_rules") or {}
        text = replies.get(kind) or replies.get("行程方案") or "收到，我看一下。"
        if kind == "行程方案":
            # 行程方案的反馈必须**基于实际渲染内容**：
            #   D4 还是博物馆 → 客户要求改；D4 已改成翠湖短线+花市手工 → 客户明确认可改后的版本。
            # 不能对任何版本都回"别安排博物馆"（那样 V2 会被误判为没改）。
            v1 = str(rules.get("v1_reply") or replies.get("行程方案") or text)
            v2 = str(rules.get("v2_reply") or replies.get("行程方案_已按反馈修改") or v1)
            verdict = self._d4_verdict(user)
            text = v2 if verdict == "adjusted" else v1
            self.calls.append({"handler": "_deliverable_feedback_verdict", "chars": 0,
                               "d4_verdict": verdict, "kind": kind})
        return json.dumps({"reply": text, "sentiment": "满意", "asks": []},
                          ensure_ascii=False)

    def _im_customer(self, system: str, user: str) -> str:
        lines = self.case.get("im_lines") or {}
        return str(lines.get("customer_hub") or "收到，我这边没问题。")

    def _im_supplier(self, system: str, user: str) -> str:
        lines = self.case.get("im_lines") or {}
        return str(lines.get("supplier") or "我这边核一下，今天 18 点前给你准信。")

    def _im_guide(self, system: str, user: str) -> str:
        lines = self.case.get("im_lines") or {}
        return str(lines.get("guide") or "收到，我按原计划执行，有事群里说。")

    # ---- 训练 / 评测 / 学习 ----

    def _card(self, system: str) -> tuple[str, dict, bool]:
        """按提示词里的技能点选固定训练卡。

        返回 (技能点, 卡, 是否通用兜底)。案例只给 C2.2 / C6.1 写了专属卡；
        其它技能点用默认卡但**显式标注是通用教案**，不冒充专属内容（避免"货不对板"）。
        """
        cards = self.case.get("training_cards") or {}
        default_sp = str((self.case.get("training") or {}).get("skill_point_id") or "C2.2")
        found = [sp for sp in dict.fromkeys(_SP_ANY_RE.findall(system or "")) if sp in cards]
        if found:
            return found[0], dict(cards[found[0]]), False
        card = dict(cards.get(default_sp) or {})
        if not card:
            card = {
                "lecture_text": str((self.case.get("training") or {}).get("lecture_text") or ""),
                "asset_text": str((self.case.get("learning") or {}).get("asset_text") or ""),
                "quiz": dict((self.case.get("training") or {}).get("quiz") or {}),
            }
        asked = _SP_ANY_RE.findall(system or "")
        return (asked[0] if asked else default_sp), card, True

    def _teacher(self, system: str, user: str) -> str:
        sp, card, generic = self._card(system)
        head = f"【{sp} · 教学】\n\n"
        if generic:
            head = (f"【{sp} · 通用教案】\n\n"
                    f"（本演示只为 C2.2 与 C6.1 提供固定讲义；当前技能点 {sp} 使用通用教案，"
                    f"内容不专属该技能点）\n\n")
        return head + str(card.get("lecture_text") or "")

    def _asset(self, system: str, user: str) -> str:
        sp, card, generic = self._card(system)
        text = str(card.get("asset_text") or "")
        if not text:
            raise ScenarioError(f"标准案例缺少 {sp} 的讲义内容（training_cards.{sp}.asset_text）")
        if generic:
            text = (f"> 说明：本演示只为 C2.2 与 C6.1 提供固定讲义；当前技能点 {sp} 使用通用教案，"
                    f"内容不专属该技能点。\n\n") + text
        return text

    def _judge(self, system: str, user: str) -> str:
        return json.dumps({"level": "M3", "score": 74,
                           "reason": "标准案例固定判定：该技能点已有基础，尚未稳定到 M4。"},
                          ensure_ascii=False)

    def _question(self, system: str, user: str) -> str:
        sp, card, _generic = self._card(system)
        q = dict(card.get("quiz") or {})
        if not q:
            raise ScenarioError(f"标准案例缺少 {sp} 的固定题卡（training_cards.{sp}.quiz）")
        return json.dumps(q, ensure_ascii=False)

    def _router_plan(self, system: str, user: str) -> str:
        return json.dumps({"agents": ["retrieval", "profile"]}, ensure_ascii=False)

    def _profile_advice(self, system: str, user: str) -> str:
        return "先补 C3.1：把逐日行程按体力分级写清；再练 C6.1 的止损顺序。"

    def _profiler(self, system: str, user: str) -> str:
        prof = ((self.case.get("assessment") or {}).get("profile") or {})
        if not prof:
            raise ScenarioError("标准案例缺少 assessment.profile")
        return json.dumps(prof, ensure_ascii=False)

    def _hat(self, system: str, user: str) -> str:
        return json.dumps({"verdict": "合格", "note": "标准案例资料已按红线预审，无需修改。"},
                          ensure_ascii=False)

    def _requirements(self, system: str, user: str) -> str:
        doc = (self.case.get("documents") or {}).get("requirement_sheet") or {}
        return json.dumps({"requirement": doc}, ensure_ascii=False)

    def _dispatch(self, system: str, user: str) -> str:
        t = self.case.get("tourist") or {}
        return json.dumps({
            "customer": t.get("customer", "客户"),
            "source_market": t.get("source_market", ""),
            "destination": t.get("destination", ""),
            "party": t.get("party", ""), "dates": t.get("dates", ""),
            "days": t.get("days", ""), "budget": t.get("budget", ""),
            "transport": t.get("transport", ""), "hotel": t.get("hotel", ""),
            "special": t.get("special", ""), "decision": t.get("decision", ""),
            "intent": t.get("intent", ""), "personality": t.get("personality", ""),
        }, ensure_ascii=False)

    # ---- 资源方（工具询价 / 群里对接）----

    def _tools_supplier(self, system: str, user: str) -> str:
        rc = self._constraint_for(system)
        note = str(rc.get("note") or "")
        return json.dumps({
            "reply": f"{note}。要锁的话请今天 18 点前确认，我这边给你预留。",
            "price": note,
            "availability": rc.get("availability") or "紧张",
            "note": note,
        }, ensure_ascii=False)

    def _constraint_for(self, system: str) -> dict:
        for rc in self.case.get("resource_constraints") or []:
            if str(rc.get("kind")) and str(rc.get("kind")) in system:
                return rc
        return {}

    # ---- 合规拦截网第二层 ----

    def _guard_semantic(self, system: str, user: str) -> str:
        return json.dumps({"issues": [], "verdict": "pass",
                           "scenario": "offline-deterministic",
                           "note": "标准案例资料已按红线预审：离线模式不做语义判定"},
                          ensure_ascii=False)

    # ---- 评分 ----

    def _scorer(self, system: str, user: str) -> str:
        ids = _SP_RE.findall(system)
        cfg = (self.case.get("scoring") or {}).get("explicit_scores") or {}
        scores = []
        for sp in ids:
            item = cfg.get(sp)
            if item:
                score, level, comment = item.get("score"), item.get("level"), item.get("comment")
                conf = float(item.get("confidence") or self.confidence_cap)
            else:
                score = 76 + (_hash(sp) % 7)
                level = "M4" if score >= 80 else ("M3" if score >= 70 else "M2")
                comment = "标准案例确定性演示判定（未单独列出的技能点按固定规则计算）"
                conf = self.confidence_cap
            # 离线演示判定一律压到置信度上限：逼系统走「低置信度转人工复核」真实闸门
            conf = min(conf, self.confidence_cap)
            scores.append({
                "skill_point_id": sp, "level": level, "score": score,
                "evidence": [{"kind": "quote", "quote": self._quote_for(sp)}],
                "hit_negative": False,
                "comment": str(comment) + "（离线确定性判定，演示数据）",
                "confidence": conf,
            })
        if not scores:
            raise ScenarioError("评分调用点没有解析到任何技能点，拒绝返回空评分")
        return json.dumps({"scores": scores}, ensure_ascii=False)

    def _quote_for(self, sp: str) -> str:
        """每条评分必须引用学员原话/交付物片段（PRD 21.2）：这里取案例里的固定证据。"""
        call = (self.case.get("first_call") or {}).get("student_lines") or []
        if sp.startswith(("C1", "C2")):
            return str(call[1] if len(call) > 1 else (call[0] if call else "标准案例固定素材"))
        if sp.startswith("C6"):
            return str((self.case.get("incident") or {}).get("student_reply") or "")
        if sp.startswith(("C4", "C5")):
            doc = (self.case.get("documents") or {}).get("quotation") or {}
            return str(doc.get("freeform") or doc.get("pending") or "分项报价已提交")
        if sp.startswith("C3"):
            plan = self.case.get("plan") or {}
            return str(plan.get("backup") or plan.get("freeform") or "行程方案已提交")
        return str((self.case.get("documents") or {}).get("requirement_sheet", {}).get("freeform")
                   or "标准案例固定素材")


# ---------------------------------------------------------------- 服务

class ScenarioService:
    """标准案例的运行入口：导入 / 重置 / 状态 / 离线 provider 开关。"""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._active_llm: ScenarioLLM | None = None

    # ---- 目录与展开 ----

    def catalog(self, case_id: str = "") -> dict:
        cases = [case_summary(c) for c in list_cases()]
        out = {"cases": cases, "digest": case_digest(), "stage_plan": stage_plan(),
               "demo_label": DEMO_LABEL, "status": self.status()}
        if case_id:
            out["case"] = self.case_view(case_id)
        return out

    def case_view(self, case_id: str) -> dict:
        case = get_case(case_id)
        view = case_summary(case)
        view["stage_plan"] = stage_plan()
        view["documents"] = {k: (v if v is not None else None)
                             for k, v in (case.get("documents") or {}).items()}
        view["plan"] = case.get("plan") or {}
        view["first_call"] = case.get("first_call") or {}
        view["incident"] = case.get("incident") or {}
        view["acceptance"] = case.get("acceptance") or {}
        view["replay"] = case.get("replay") or {}
        return view

    # ---- 状态（不虚报）----

    def status(self, probe_llm: bool = False) -> dict:
        deps = dependency_status(probe_llm=probe_llm)
        active = self._active_llm is not None
        mode = MODE_OFFLINE if active else MODE_LIVE
        return {
            "mode": mode,
            "scope": "instance",
            "demo_instance": bool(active),
            "scenario_mode_env": os.environ.get("TRIPCRAFT_SCENARIO_MODE", "").strip().lower() or "",
            "switch_policy": ("确定性模式只由启动期 TRIPCRAFT_SCENARIO_MODE=offline 决定（演示实例）；"
                              "不提供运行期全局切换，普通实例始终走真实模型"),
            "instance_note": ("本实例是专用演示实例：其内所有账号都会拿到确定性回答（不含真实模型调用）；"
                              "其它实例/进程不受任何影响" if active
                              else "本实例是常规实例：全部模型调用走真实客户端"),
            "session_state": "客户通话轮次按会话消息历史推导（无全局计数）",
            "scenario_llm_active": active,
            "provider_model": self._active_llm.model if active else "",
            "provider_audit": self._active_llm.audit() if active else {},
            "demo_label": DEMO_LABEL,
            "case_digest": case_digest(),
            "confidence_cap": SCENARIO_CONFIDENCE_CAP,
            "deps": deps,
            "honest_notes": [
                "离线模式：客户对话/训练老师/评分/画像刷新由 scenario provider 提供确定性回答（演示数据），不是实时模型。",
                "离线判定置信度上限 0.6：系统按低置信度转人工复核处理，复核采纳后才写画像。",
                "实时语音未做离线替代：声学效果不能用文本测试冒充。",
                "llm/voice 的 key 存在 ≠ 已连通：只有 connectivity_verified=true 才是真跑通过。",
            ],
        }

    def ensure_env_mode(self) -> dict:
        """按启动环境变量决定初始模式：TRIPCRAFT_SCENARIO_MODE=offline 时进入演示实例模式。"""
        want = os.environ.get("TRIPCRAFT_SCENARIO_MODE", "").strip().lower()
        case = list_cases()[0]
        if want == MODE_OFFLINE and self._active_llm is None:
            out = self.activate_offline(str(case.get("case_id")), by_env=True)
            out["activated_by"] = "TRIPCRAFT_SCENARIO_MODE=offline"
            return out
        if want == MODE_LIVE and self._active_llm is not None:
            return self.deactivate()
        return {"ok": True, "mode": MODE_OFFLINE if self._active_llm else MODE_LIVE,
                "activated_by": ""}

    # ---- 离线 provider 开关（进程级，明示）----

    def activate_offline(self, case_id: str, *, by_env: bool = False) -> dict:
        """进入确定性离线模式。

        **作用域（监督者审核第 1 条，采用方案 b）**：确定性演示只允许在
        **启动期显式声明的演示实例**里生效（`TRIPCRAFT_SCENARIO_MODE=offline`），
        不提供运行期全局切换；普通生产实例永远走真实模型。
        进程内的模型注入仍是共享的，但实例本身就是"专用演示实例"，所以不影响任何常规实例。
        """
        if not by_env and os.environ.get("TRIPCRAFT_SCENARIO_MODE", "").strip().lower() != MODE_OFFLINE:
            raise ScenarioError(
                "确定性离线模式必须作为**演示实例**在启动时声明："
                "启动前设置 TRIPCRAFT_SCENARIO_MODE=offline（建议同时用独立端口 + 独立 TRIPCRAFT_DB）；"
                "运行期不提供全局切换，普通生产实例不受影响。")
        case = get_case(case_id)
        llm = ScenarioLLM(case)
        ctx = self.ctx
        ctx.llm_holder["client"] = llm
        holders = [getattr(ctx, name, None) for name in
                   ("tools", "guard", "director", "call_svc", "supplier_svc")]
        touched = []
        for svc in holders:
            if svc is not None and hasattr(svc, "_llm"):
                svc._llm = llm
                touched.append(type(svc).__name__)
        holder = ctx.threads_holder.get("svc")
        if holder is not None and hasattr(holder, "_llm"):
            holder._llm = llm
            touched.append(type(holder).__name__)
        else:
            ctx.threads_holder["svc"] = None
        self._active_llm = llm
        return {"ok": True, "mode": MODE_OFFLINE, "model": llm.model,
                "injected_into": touched, "scope": "instance",
                "demo_instance": True,
                "affects_other_users": "instance 内所有账号共用确定性响应器（该实例本就是演示实例）",
                "session_state": "客户通话轮次按各会话消息历史推导，无全局计数；多账号/多订单并发互不影响",
                "activated_by": "TRIPCRAFT_SCENARIO_MODE=offline（启动期声明）" if by_env else "演示实例声明",
                "demo_label": DEMO_LABEL}

    def deactivate(self) -> dict:
        """回到真实模型（仅演示实例内部使用；普通实例本来就没有开启过）。"""
        ctx = self.ctx
        ctx.llm_holder["client"] = None
        cleared = []
        for name in ("tools", "guard", "director", "call_svc", "supplier_svc"):
            svc = getattr(ctx, name, None)
            if svc is not None and hasattr(svc, "_llm"):
                svc._llm = None
                cleared.append(type(svc).__name__)
        ctx.threads_holder["svc"] = None
        self._active_llm = None
        return {"ok": True, "mode": MODE_LIVE, "cleared": cleared,
                "note": "演示实例回到实时模式；普通实例从未受影响"}

    def provider(self) -> ScenarioLLM | None:
        return self._active_llm

    # ---- 导入（真实服务落单 + 固定资源约束）----

    def import_case(self, user_id: str, case_id: str) -> dict:
        case = get_case(case_id)
        spec: TouristSpec = spec_from_case(case)          # 确定性，不调模型
        row = self.ctx.practice.spawn_order(user_id, spec)
        order_id = str(row.get("order_id") or "")
        if not order_id:
            raise ScenarioError("spawn_order 没有返回订单号")
        payload = json.loads(row.get("payload") or "{}")
        from tripcraft.services.tools_service import SUPPLIER_ROLES
        applied = []
        for rc in case.get("resource_constraints") or []:
            kind = str(rc.get("kind") or "")
            if kind not in SUPPLIER_ROLES:
                # 案例口径与服务契约不一致时**报错**，不要跳过（跳过等于静默丢固定资料）
                raise ScenarioError(
                    f"标准案例的资源约束类型 {kind!r} 不在服务契约内（可选："
                    + "、".join(SUPPLIER_ROLES) + "）")
            state = self.ctx.get_tools().set_supplier_state(
                kind, {"availability": rc.get("availability"),
                       "price_factor": rc.get("price_factor"),
                       "note": rc.get("note")}, user_id=user_id)
            applied.append({"kind": kind, "state": state})
        detail = self.ctx.practice.order_detail(order_id) or {}
        return {
            "order_id": order_id,
            "case_id": case_id,
            "demo_label": case.get("demo_label") or DEMO_LABEL,
            "demo_data": True,
            "user_id": user_id,
            "customer": row.get("customer"),
            "destination": row.get("destination"),
            "stage_index": row.get("stage_index"),
            "scenario_marker": {
                "scenario_id": payload.get("scenario_id", ""),
                "scenario_label": payload.get("scenario_label", ""),
                "demo_data": bool(payload.get("demo_data")),
            },
            "fixed_fields": {k: payload.get(k, "") for k in
                             ("source_market", "language", "documents", "party", "dates",
                              "days", "budget", "transport", "hotel", "special", "decision",
                              "preset_incidents")},
            "missing_fields": detail.get("missing_fields") or [],
            "resources_injected": applied,
            "next_action": "在消息中心点「抢单」接手本单（POST /practice/orders/{order_id}/grab）",
        }

    # ---- 计数（重置/隔离证据用）----

    def counts(self, user_id: str) -> dict:
        store = self.ctx.store
        one = lambda sql, args=(): (store._one(sql, args) or {}).get("n", 0)
        orders = store.orders(user_id)
        scenario_orders = []
        for o in orders:
            try:
                p = json.loads(o.get("payload") or "{}")
            except json.JSONDecodeError:
                p = {}
            if p.get("scenario_id"):
                scenario_orders.append(o["order_id"])
        return {
            "user_id": user_id,
            "orders": len(orders),
            "scenario_orders": len(scenario_orders),
            "scenario_order_ids": scenario_orders,
            "evidence": sum(one("SELECT COUNT(*) n FROM order_evidence WHERE order_id=?", (oid,))
                            for oid in [o["order_id"] for o in orders]),
            "deliverables": sum(one("SELECT COUNT(*) n FROM deliverable_doc WHERE order_id=?", (oid,))
                                for oid in [o["order_id"] for o in orders]),
            "ability_rows": one("SELECT COUNT(*) n FROM ability WHERE user_id=?", (user_id,)),
            "quiz_attempts": one("SELECT COUNT(*) n FROM quiz_attempt WHERE user_id=?", (user_id,)),
            "threads": one("SELECT COUNT(*) n FROM thread WHERE user_id=?", (user_id,)),
            "notices": one("SELECT COUNT(*) n FROM notice WHERE user_id=?", (user_id,)),
            "calibration_runs": one("SELECT COUNT(*) n FROM calibration_run"),
        }

    # ---- 重置（只动当前账号）----

    def reset(self, user_id: str, case_id: str = "", *, include_profile: bool = True,
              all_orders: bool = False) -> dict:
        """重置：只清当前账号名下（可选只限本案例）的订单与其从属数据。

        - **先子后父**，全部放进**一个事务**：任何一步失败就整体回滚，不留半截状态。
        - 结束时做**残留检查**：目标订单的从属表逐表计数必须为 0，结果一并返回。
        """
        store = self.ctx.store
        before = self.counts(user_id)
        rows = store.orders(user_id)
        target: list[str] = []
        for o in rows:
            if all_orders:
                target.append(o["order_id"])
                continue
            try:
                p = json.loads(o.get("payload") or "{}")
            except json.JSONDecodeError:
                p = {}
            sid = str(p.get("scenario_id") or "")
            if case_id:
                if sid == case_id:
                    target.append(o["order_id"])
            elif sid:                      # 不指定案例：清本账号所有标准案例订单
                target.append(o["order_id"])
        deleted: dict[str, int] = {}
        if target or include_profile:
            marks = ",".join("?" for _ in target) or "''"
            args = tuple(target) or ("",)
            conn = store._conn
            with store._lock:
                try:
                    if target:
                        for table in CASE_LEAF_TABLES:
                            cur = conn.execute(
                                f"DELETE FROM {table} WHERE order_id IN ({marks})", args)
                            if cur.rowcount:
                                deleted[table] = cur.rowcount
                        for child, col, parent, pcol in CASE_CHILD_TABLES:
                            cur = conn.execute(
                                f"DELETE FROM {child} WHERE {col} IN "
                                f"(SELECT {pcol} FROM {parent} WHERE order_id IN ({marks}))", args)
                            if cur.rowcount:
                                deleted[child] = cur.rowcount
                        for table in CASE_PARENT_TABLES:
                            cur = conn.execute(
                                f"DELETE FROM {table} WHERE order_id IN ({marks})", args)
                            if cur.rowcount:
                                deleted[table] = cur.rowcount
                        cur = conn.execute(
                            f"DELETE FROM {SUPPLIER_TABLE} WHERE order_id IN ({marks})", args)
                        if cur.rowcount:
                            deleted["supplier_state(order)"] = cur.rowcount
                        cur = conn.execute(
                            f"DELETE FROM {CASE_MAIN_TABLE} WHERE order_id IN ({marks})", args)
                        if cur.rowcount:
                            deleted[CASE_MAIN_TABLE] = cur.rowcount
                    if include_profile:
                        # 账号自己拉的、不挂订单的会话（如资源大群）也属于该账号的演示数据
                        for table in ("im_session", "call_session"):
                            cur = conn.execute(
                                f"DELETE FROM {table} WHERE user_id=? AND (order_id='' OR order_id IS NULL)",
                                (user_id,))
                            if cur.rowcount:
                                deleted[table + "(account)"] = cur.rowcount
                        for child, col, parent, pcol in USER_CHILD_TABLES:
                            cur = conn.execute(
                                f"DELETE FROM {child} WHERE {col} IN "
                                f"(SELECT {pcol} FROM {parent} WHERE user_id=?)", (user_id,))
                            if cur.rowcount:
                                deleted[child] = cur.rowcount
                        for table in USER_PARENT_TABLES:
                            cur = conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
                            if cur.rowcount:
                                deleted[table] = cur.rowcount
                        for table in USER_TABLES:
                            cur = conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
                            if cur.rowcount:
                                deleted[table] = cur.rowcount
                        cur = conn.execute(
                            f"DELETE FROM {SUPPLIER_TABLE} WHERE user_id=? AND (order_id='' OR order_id IS NULL)",
                            (user_id,))
                        if cur.rowcount:
                            deleted["supplier_state(account)"] = cur.rowcount
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        residual = self._residual(user_id, target)
        after = self.counts(user_id)
        return {
            "ok": True, "user_id": user_id, "case_id": case_id,
            "scope": "当前登录账号" + ("（全部订单）" if all_orders else "（标准案例订单）")
                     + ("+ 学习/画像数据" if include_profile else "（不动学习/画像数据）"),
            "orders_targeted": target,
            "deleted": deleted,
            "before": before, "after": after,
            "residual": residual,
            "residual_clean": all(v == 0 for v in residual.values()),
            "transaction": "单个事务（先子后父）；异常整体回滚",
            "isolation_note": "只删当前账号名下记录；其它账号数据不在删除范围内（见 before/after 计数对比）。",
        }

    def _residual(self, user_id: str, order_ids: list[str]) -> dict:
        """残留检查：目标订单的从属表 + 该账号应清空的表，计数应全为 0。"""
        store = self.ctx.store
        out: dict[str, int] = {}
        if order_ids:
            marks = ",".join("?" for _ in order_ids)
            args = tuple(order_ids)
            for table in CASE_LEAF_TABLES + CASE_PARENT_TABLES:
                out[table] = (store._one(
                    f"SELECT COUNT(*) n FROM {table} WHERE order_id IN ({marks})", args) or {}).get("n", 0)
            for child, col, parent, pcol in CASE_CHILD_TABLES:
                out[child] = (store._one(
                    f"SELECT COUNT(*) n FROM {child} WHERE {col} IN "
                    f"(SELECT {pcol} FROM {parent} WHERE order_id IN ({marks}))", args) or {}).get("n", 0)
            out["supplier_state"] = (store._one(
                f"SELECT COUNT(*) n FROM {SUPPLIER_TABLE} WHERE order_id IN ({marks})", args) or {}).get("n", 0)
            out[CASE_MAIN_TABLE] = (store._one(
                f"SELECT COUNT(*) n FROM {CASE_MAIN_TABLE} WHERE order_id IN ({marks})", args) or {}).get("n", 0)
        for table in USER_TABLES:
            out[table + "(account)"] = (store._one(
                f"SELECT COUNT(*) n FROM {table} WHERE user_id=?", (user_id,)) or {}).get("n", 0)
        out["thread(account)"] = (store._one(
            "SELECT COUNT(*) n FROM thread WHERE user_id=?", (user_id,)) or {}).get("n", 0)
        out["thread_message(account)"] = (store._one(
            "SELECT COUNT(*) n FROM thread_message WHERE thread_id IN "
            "(SELECT thread_id FROM thread WHERE user_id=?)", (user_id,)) or {}).get("n", 0)
        return out

    # ---- 校准（live 才做真实标定；离线只跑机器不伪造结果）----

    def calibrate(self, repeats: int = 1, use_scenario_provider: bool = True) -> dict:
        from tripcraft.calibration import load_samples, run_calibration
        samples = load_samples()
        if not samples:
            raise ScenarioError("校准样本缺失：data/calibration/samples.jsonl")
        if use_scenario_provider:
            if self._active_llm is None:
                raise ScenarioError("离线校准需要先 activate_offline，否则会走到真实模型")
            report = run_calibration(self._active_llm, samples=samples, repeats=repeats)
            label = "scenario-deterministic"
        else:
            try:
                llm = self.ctx.get_llm()
            except LLMError as exc:
                raise ScenarioError(f"实时模型不可用（{exc}），不做假标定") from exc
            report = run_calibration(llm, samples=samples, repeats=repeats)
            label = f"live:{getattr(llm, 'model', 'unknown')}"
        return {
            "label": label,
            "run_id": report.get("run_id"),
            "samples": report.get("samples"),
            "agreement": report.get("agreement"),
            "evidence_accuracy": report.get("evidence_accuracy"),
            "passed": report.get("passed"),
            "note": ("离线确定性评分器的标定结果**不代表**真实模型能力；"
                     "真实基线必须用 --live 跑。" if use_scenario_provider else "真实模型标定"),
        }
