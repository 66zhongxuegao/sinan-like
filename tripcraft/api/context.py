"""应用装配上下文（AppContext）—— 拆分后取代 create_app 内的闭包单例。

对外契约（v1，Lead 冻结）：
- 每个 FastAPI 实例构造一个 AppContext；路由模块通过 `build(ctx)` 拿到同一份服务实例。
- 单例属性：runs / profiles / s2_sessions / store / practice / tools / guard / director /
  call_svc / supplier_svc / finance_svc / deliverable_svc / plan_svc
- 惰性 getter：get_llm / get_threads / get_deliverables / get_plans / get_tools / get_guard /
  get_director / get_call / get_finance / get_supplier / get_auth
- 路由模块不得自行 new 服务，避免同一 app 内出现两套状态（尤其是 director 与 practice 的绑定）。

变更此契约必须升版并通知全部 owner。
"""

from __future__ import annotations

import os

from tripcraft.agents.llm import DeepSeekClient, LLMError
from tripcraft.contracts.profile import LearnerProfile
from tripcraft.orchestration import Conductor
from tripcraft.services.call_service import CallService
from tripcraft.services.conversation_service import ConversationService
from tripcraft.services.deliverable_service import DeliverableService
from tripcraft.services.director_service import DirectorService
from tripcraft.services.finance_service import FinanceService
from tripcraft.services.guard_service import GuardService
from tripcraft.services.plan_service import PlanService
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.s2_session import S2Session
from tripcraft.services.supplier_service import SupplierService
from tripcraft.services.thread_service import ThreadService
from tripcraft.services.tools_service import ToolsService
from tripcraft.storage import Store


class AppContext:
    """一个 app 实例的全部可变状态与业务服务。"""

    def __init__(self) -> None:
        # ---- 内存态（M0 演练 / S2 垂直切片）----
        self.runs: dict = {}
        self.profiles: dict[str, LearnerProfile] = {}
        self.s2_sessions: dict[str, S2Session] = {}
        self.llm_holder: dict = {"client": None}
        self.threads_holder: dict = {"svc": None}

        # ---- 持久层与业务服务（构造顺序即依赖顺序）----
        self.store = Store()
        self.conductor = Conductor()
        self.conversation_svc = ConversationService(self.store)
        self.practice = PracticeService(self.store)
        # 启动期给 legacy demo 账号种种子数据是**可选**行为（默认关闭）：
        # - 正式训练账号走「注册 → generate_dispatch 发初始派单」；
        # - 演示/标准案例账号由 scenario 域按固定案例注入；
        # - 默认不种，避免为一个没有 users 记录的 "u-demo" 产生孤儿订单（硬编码用户残留）。
        # 需要旧行为时显式设 TRIPCRAFT_SEED_DEMO=1。
        if os.environ.get("TRIPCRAFT_SEED_DEMO", "").strip().lower() in ("1", "on", "true"):
            self.practice.seed("u-demo")
        self.tools = ToolsService(store=self.store)
        self.guard = GuardService(store=self.store, practice=self.practice)
        self.director = DirectorService(store=self.store, practice=self.practice)
        self.practice.attach_director(self.director)   # 学员动作自动进总线（D-047）
        self.call_svc = CallService(store=self.store, practice=self.practice, conductor=self.conductor)
        self.supplier_svc = SupplierService(store=self.store, practice=self.practice, conductor=self.conductor)
        self.finance_svc = FinanceService(store=self.store, practice=self.practice)
        self.deliverable_svc = DeliverableService(store=self.store, practice=self.practice)
        self.plan_svc = PlanService(store=self.store, practice=self.practice,
                                    deliverable=self.deliverable_svc)

        # 认证服务由 identity 模块提供；延迟导入，拆分期间不阻塞其它域。
        self._auth = None

    # ---------------- LLM 与惰性服务 ----------------

    def get_llm(self) -> DeepSeekClient:
        if self.llm_holder["client"] is None:
            self.llm_holder["client"] = DeepSeekClient()
        return self.llm_holder["client"]

    def get_threads(self) -> ThreadService:
        if self.threads_holder["svc"] is None:
            try:
                llm = self.get_llm()
            except LLMError:
                llm = None
            self.threads_holder["svc"] = ThreadService(self.store, llm, conductor=self.conductor)
        return self.threads_holder["svc"]

    def get_deliverables(self) -> DeliverableService:
        if self.deliverable_svc._guard is None:
            self.deliverable_svc._guard = self.get_guard()
        if self.deliverable_svc._tools is None:
            self.deliverable_svc._tools = self.get_tools()
        return self.deliverable_svc

    def get_plans(self) -> PlanService:
        if self.plan_svc._deliverable is None:
            self.plan_svc._deliverable = self.get_deliverables()
        if self.plan_svc._tools is None:
            self.plan_svc._tools = self.get_tools()
        return self.plan_svc

    def get_tools(self) -> ToolsService:
        if self.tools._llm is None:
            try:
                self.tools._llm = self.get_llm()
            except LLMError:
                pass
        return self.tools

    def get_guard(self) -> GuardService:
        if self.guard._llm is None:
            try:
                self.guard._llm = self.get_llm()
            except LLMError:
                pass
        return self.guard

    def get_director(self) -> DirectorService:
        if self.director._llm is None:
            try:
                self.director._llm = self.get_llm()
            except LLMError:
                pass
        return self.director

    def get_conversation(self) -> ConversationService:
        return self.conversation_svc

    def get_call(self) -> CallService:
        if self.call_svc._llm is None:
            try:
                self.call_svc._llm = self.get_llm()
            except LLMError:
                pass
        return self.call_svc

    def get_finance(self) -> FinanceService:
        return self.finance_svc

    def get_supplier(self) -> SupplierService:
        if self.supplier_svc._llm is None:
            try:
                self.supplier_svc._llm = self.get_llm()
            except LLMError:
                pass
        return self.supplier_svc

    # ---------------- 认证（owner: identity） ----------------

    def get_auth(self):
        """认证服务。模块缺失时给出明确错误而不是静默放行。"""
        if self._auth is None:
            from tripcraft.services.auth_service import AuthService
            self._auth = AuthService(self.store)
        return self._auth

