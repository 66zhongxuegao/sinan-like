"""通话服务 —— 订单绑定的实时客户 Agent。

两种模式：
  - text：学员输入一句 → 客户 Agent 回复一句（文本链路，DeepSeek）。
  - voice：浏览器麦克风 ⇄ DashScope Qwen-Omni-Realtime 流式语音（见 voice/bridge.py）。

两种模式的每一句都会写回数据库（call_session / call_line），并在通话结束时
登记为本单的实战证据，供评分 Agent 评。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..agents.base import AgentContext
from ..agents.customer import CustomerAgent, CustomerPersona
from ..agents.llm import DeepSeekClient

# 客户人设只有一份定义（agents/customer.py）：语音通话、文本通话、群聊共用，
# 避免出现「语音说德语、文本说中文」这种同一个客人自相矛盾的情况。
from ..agents.customer import persona_for  # noqa: E402  （放在此处以免改动既有导入顺序）
from .customer_order_facts import facts_for_order_id  # noqa: E402
from ..orchestration import AgentResult, AgentTask, Blackboard, Conductor, Plan

# 本地/离线调用未显式给出用户时的兜底标识。
# 运行时的 API 路径**必须**传真实 user_id（由 security.current_user 解析后传入），
# 这样 call_session.user_id 才反映真实调用者，而不是写死某一个演示账号。
LOCAL_SESSION_USER = "u-local"


@dataclass
class CallSession:
    session_id: str
    order_id: str
    customer: str
    destination: str
    source_market: str = "香港"
    language: str = "中文"
    personality: str = ""
    llm: DeepSeekClient | None = None
    mode: str = "text"
    user_id: str = LOCAL_SESSION_USER
    facts: dict = field(default_factory=dict)
    lines: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended: bool = False
    store: object = field(default=None, repr=False)
    conductor: object | None = field(default=None, repr=False)
    _agent: CustomerAgent | None = field(default=None, init=False)
    _ctx: AgentContext | None = field(default=None, init=False)

    def persona(self):
        """本单客户人设 —— 语音/文本/群聊共用同一份（含订单事实 facts）。"""
        return persona_for(self.customer, self.destination, self.source_market,
                           self.language, self.order_id, self.personality,
                           facts=self.facts)

    def _ensure_agent(self) -> None:
        if self._agent is None:
            if self.llm is None:
                raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
            self._agent = CustomerAgent(self.llm, persona_for(
                self.customer, self.destination, self.source_market, self.language,
                self.order_id, self.personality, facts=self.facts))
            # 演练上下文必须挂真实用户：以前写死 u-demo，多个用户的会话在上下文层混成一个。
            self._ctx = AgentContext(instance_id=self.session_id, user_id=self.user_id,
                                     language=self.language)

    def add(self, who: str, text: str) -> dict:
        line = {"who": who, "text": text, "at": self._stamp()}
        self.lines.append(line)
        return line

    def _orchestrated(self, question: str, history=None, opening: bool = False) -> str:
        if self.conductor is None or self.store is None or not self.store.order(self.order_id):
            return ""
        task = AgentTask("reply", "practice.phone_customer", "reply", {
            "order_id": self.order_id,
            "question": question,
            "history": history or [],
            "exclude_session": self.session_id,
            "opening": opening,
        })
        result = self.conductor.run(
            Plan("practice.phone_reply", "practice", (task,)),
            Blackboard({"session_id": self.session_id, "order_id": self.order_id}),
        )
        if not result.ok:
            return ""
        out = result.outputs.get("reply") or {}
        return str(out.get("reply") or "")

    def opening(self) -> str:
        if self.store is not None and self.store.order(self.order_id):
            line = self._orchestrated("定制师刚打来电话，请先简短接听。", opening=True)
            if not line:
                from .customer_context import guarded_reply
                line = guarded_reply(self.store, self.llm, self.order_id, "text",
                                     "定制师刚打来电话，请先简短接听。", exclude_session=self.session_id)["reply"]
            self.add("agent", line)
            return line
        self._ensure_agent()
        assert self._agent is not None and self._ctx is not None
        line = self._agent.opening(self._ctx)
        self.add("agent", line)
        return line

    def reply(self, text: str) -> str:
        if self.store is not None and self.store.order(self.order_id):
            history = [{"role": "assistant" if item["who"] == "agent" else "user", "content": item["text"]}
                       for item in self.lines[-10:]]
            self.add("student", text)
            line = self._orchestrated(text, history=history)
            if not line:
                from .customer_context import guarded_reply
                line = guarded_reply(self.store, self.llm, self.order_id, "text", text,
                                     history=history, exclude_session=self.session_id)["reply"]
            self.add("agent", line)
            return line
        self._ensure_agent()
        assert self._agent is not None and self._ctx is not None
        self.add("student", text)
        line = self._agent.reply(self._ctx, text)
        self.add("agent", line)
        return line

    def transcript(self) -> str:
        return "\n".join(
            ("客户: " if l["who"] == "agent" else "定制师: ") + l["text"] for l in self.lines
        )

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id, "order_id": self.order_id,
            "customer": self.customer, "destination": self.destination,
            "source_market": self.source_market, "language": self.language,
            "mode": self.mode, "lines": self.lines,
            "turns": sum(1 for l in self.lines if l["who"] == "student"),
            "ended": self.ended,
        }
    def _stamp(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime())


class CallService:
    """按订单维护通话会话。文本链路走内存 + 落库；语音链路由 voice/bridge.py 复用本类。"""

    def __init__(self, llm: DeepSeekClient | None = None, store=None,
                 practice=None, conductor: Conductor | None = None) -> None:
        self._llm = llm
        self._store = store
        self._practice = practice
        self._conductor = conductor or Conductor()
        self._sessions: dict[str, CallSession] = {}
        self._bind_agents()

    def _bind_agents(self) -> None:
        self._conductor.registry.bind("practice.phone_customer", self._agent_phone_customer)

    def _agent_phone_customer(self, task: AgentTask, board: Blackboard) -> AgentResult:
        from .customer_context import guarded_reply
        p = task.payload
        out = guarded_reply(
            self._store, self._llm, str(p.get("order_id") or ""), "text",
            str(p.get("question") or ""),
            history=p.get("history") or [],
            exclude_session=p.get("exclude_session") or "",
        )
        return AgentResult(task.id, task.agent, ok=bool(out.get("reply")), output=out)

    def _require_llm(self) -> DeepSeekClient:
        if self._llm is None:
            raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
        return self._llm

    def open_session(self, order_id: str, customer: str, destination: str,
                     mode: str = "text", source_market: str = "香港",
                     language: str = "中文", personality: str = "",
                     user_id: str = "", facts: dict | None = None) -> CallSession:
        """开一个通话会话。`user_id` 由 API 边界传入真实登录用户。

        `user_id` 会写进 `call_session.user_id` 与 AgentContext；不传时（仅离线/测试）
        落到 `LOCAL_SESSION_USER`，但绝不写死成某个演示账号。
        `facts` 是订单里显式写下的出行事实，必须一路传到客户 Agent 的提示词（R02）。
        """
        sid = f"call-{order_id}-{int(time.time() * 1000) % 1000000}"
        owner = (user_id or "").strip() or LOCAL_SESSION_USER
        sess = CallSession(session_id=sid, order_id=order_id, customer=customer,
                           destination=destination, source_market=source_market,
                           language=language, personality=personality,
                           llm=self._llm, mode=mode, user_id=owner, facts=dict(facts or {}), store=self._store, conductor=self._conductor)
        self._sessions[sid] = sess
        if self._store is not None:
            self._store.save_call_session(sid, order_id, owner, customer, destination, mode)
        return sess

    def start(self, order_id: str, customer: str, destination: str,
              source_market: str = "香港", language: str = "中文",
              personality: str = "", user_id: str = "",
              facts: dict | None = None) -> CallSession:
        """文本模式：建立会话并让客户先说第一句。"""
        sess = self.open_session(order_id, customer, destination, mode="text",
                                 source_market=source_market, language=language,
                                 personality=personality, user_id=user_id, facts=facts)
        self._require_llm()
        sess.opening()
        self._persist(sess)
        return sess

    def start_for_order(self, store, order_id: str, user_id: str) -> CallSession:
        """按订单号起文本通话：客户事实统一从 `customer_order_facts` 取（R02）。

        这是 API 路径唯一应该用的入口——传订单号而不是一堆调用方各自
        `detail.get(...)` 出来的字段，避免三通道各取一套。
        """
        facts = facts_for_order_id(store, order_id)
        return self.start(facts.order_id, facts.customer, facts.destination,
                          facts.source_market, facts.language, facts.personality,
                          user_id=user_id, facts=facts.model_facts())

    def get_for_user(self, sid: str, user_id: str) -> CallSession | None:
        """按归属取会话：不是本人的会话一律当作不存在（API 层 fail-closed）。"""
        sess = self._sessions.get(sid)
        if sess is None:
            return None
        if (user_id or "").strip() and sess.user_id != (user_id or "").strip():
            return None
        return sess

    def get(self, sid: str, user_id: str = "") -> CallSession | None:
        return self._resolve(sid, user_id)

    def say(self, sid: str, text: str, user_id: str = "") -> str | None:
        """学员说一句 → 客户回一句。`user_id` 非空时校验会话归属（跨用户返回 None）。"""
        sess = self._resolve(sid, user_id)
        if sess is None:
            return None
        line = sess.reply(text)
        self._persist(sess)
        return line

    def _resolve(self, sid: str, user_id: str = "") -> CallSession | None:
        """统一取会话入口：给了 user_id 就必须归属一致，否则视为不存在。"""
        if (user_id or "").strip():
            return self.get_for_user(sid, user_id)
        return self._sessions.get(sid)

    # ---- 落库 / 收口 ----

    def _persist(self, sess: CallSession) -> None:
        if self._store is None:
            return
        seen = getattr(sess, "_persisted", 0)
        for line in sess.lines[seen:]:
            self._store.add_call_line(sess.session_id, line["who"], line["text"])
        setattr(sess, "_persisted", len(sess.lines))

    def record_line(self, sess: CallSession, who: str, text: str) -> None:
        if not text.strip():
            return
        sess.add(who, text)
        if self._store is not None:
            self._store.add_call_line(sess.session_id, who, text)
            setattr(sess, "_persisted", len(sess.lines))

    def end(self, sid: str, user_id: str = "") -> dict | None:
        """结束通话：登记实战证据，并写一条联系记录。`user_id` 非空时校验归属。"""
        sess = self._resolve(sid, user_id)
        if sess is None:
            return None
        if sess.ended:
            return sess.snapshot()
        sess.ended = True
        self._persist(sess)
        text = sess.transcript()
        if self._store is not None and self._store.order(sess.order_id):
            from .customer_context import observe_reply
            question = ""
            for index, line in enumerate(sess.lines):
                if line["who"] == "student":
                    question = line["text"]
                else:
                    observe_reply(self._store, sess.order_id, line["text"], sess.mode,
                                  f"{sid}:end:{index}", question)
        if text and self._practice is not None:
            self._practice.record_evidence(sess.order_id, "call", text, ref=sid)
        if self._store is not None:
            turns = sum(1 for l in sess.lines if l["who"] == "student")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            status = f"已接通({turns}轮)" if turns else "未接通"
            self._store.add_contact(sess.order_id, "电话", stamp, status, True,
                                    f"{'语音' if sess.mode == 'voice' else '文字'}通话，共 {turns} 轮")
        return sess.snapshot()
