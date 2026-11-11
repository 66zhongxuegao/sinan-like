"""Multi-Agent Orchestra 编排层测试。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.orchestration import (
    AgentRegistry,
    AgentResult,
    AgentTask,
    Blackboard,
    Conductor,
    Plan,
)
from tripcraft.services.thread_service import ThreadService
from tripcraft.storage import Store


class FakeLLM:
    def chat(self, messages, **kwargs):
        return "## 讲解\n\n预算要问清人均/总价和区间。\n\n<div class=\"refs\">参考来源：Rubric C2.2</div>"

    def chat_json(self, messages, **kwargs):
        return {"agents": ["retrieval", "profile"]}


def make_thread():
    path = os.path.join(tempfile.gettempdir(), f"orch_{uuid4().hex}.sqlite")
    store = Store(path)
    store.set_ability("u1", "C2.2", teach=60, real_v=40)
    store.upsert_order("9000000000000001", "u1", "客户 A", "江苏", "正常", 1)
    return ThreadService(store, FakeLLM()), store


def test_conductor_runs_dependencies_and_trace():
    registry = AgentRegistry()
    registry.bind("teaching.router", lambda task, board: AgentResult(
        task.id, task.agent, output={"agents": ["retrieval"]}))
    registry.bind("teaching.retrieval", lambda task, board: AgentResult(
        task.id, task.agent, output={"text": "facts"}))
    registry.bind("teaching.context", lambda task, board: AgentResult(
        task.id, task.agent, output={"text": board.get("retrieval")["text"]}))
    registry.bind("teaching.teacher", lambda task, board: AgentResult(
        task.id, task.agent, output={"content": "answer"}))

    conductor = Conductor(registry)
    plan = Plan("teaching.reply", "teaching", (
        AgentTask("retrieval", "teaching.retrieval", "retrieve"),
        AgentTask("context", "teaching.context", "assemble", depends_on=("retrieval",)),
        AgentTask("teacher", "teaching.teacher", "respond", depends_on=("context",)),
    ))
    result = conductor.run(plan, Blackboard())
    assert result.ok is True
    assert result.outputs["teacher"]["content"] == "answer"
    assert [t.task_id for t in result.trace] == ["retrieval", "context", "teacher"]
    assert all(t.ok for t in result.trace)


def test_optional_agent_can_fail_without_stopping_synthesis():
    registry = AgentRegistry()
    registry.bind("teaching.context", lambda task, board: AgentResult(
        task.id, task.agent, output={"text": "ctx"}))
    registry.bind("teaching.profile", lambda task, board: AgentResult(
        task.id, task.agent, ok=False, error="profile down"))
    registry.bind("teaching.teacher", lambda task, board: AgentResult(
        task.id, task.agent, output={"content": "still works"}))

    result = Conductor(registry).run(Plan("teaching.reply", "teaching", (
        AgentTask("context", "teaching.context", "assemble"),
        AgentTask("profile", "teaching.profile", "advise", depends_on=("context",), optional=True),
        AgentTask("teacher", "teaching.teacher", "respond", depends_on=("context",)),
    )))
    assert result.ok is True
    assert result.outputs["teacher"]["content"] == "still works"
    assert result.trace[1].ok is False


def test_thread_reply_runs_through_orchestra():
    svc, store = make_thread()
    out = svc.reply("u1", "C2.2", "预算这块怎么问？")
    assert out["content"]
    assert out["evidence"]
    trace = out["orchestra"]["trace"]
    agents = [event["agent"] for event in trace]
    assert agents[0] == "teaching.router"
    assert "teaching.retrieval" in agents
    assert "teaching.context" in agents
    assert "teaching.profile" in agents
    assert agents[-1] == "teaching.teacher"
    assert [m["role"] for m in store.messages(store.get_or_create_thread("u1", "C2.2")["thread_id"])] == ["user", "ai"]


def test_practice_and_phone_agents_are_bound():
    from tripcraft.services.call_service import CallService
    from tripcraft.services.supplier_service import SupplierService

    store = Store(os.path.join(tempfile.gettempdir(), f"orch_bind_{uuid4().hex}.sqlite"))
    supplier = SupplierService(store=store, llm=None)
    call = CallService(store=store, llm=None)
    assert supplier._conductor.registry.is_bound("practice.customer")
    assert supplier._conductor.registry.is_bound("practice.supplier")
    assert supplier._conductor.registry.is_bound("practice.guide")
    assert call._conductor.registry.is_bound("practice.phone_customer")
