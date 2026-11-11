"""Multi-Agent Orchestra 的共享契约。

这一层只定义「谁上场、拿什么任务、回什么结果、留下什么轨迹」，
不导入任何具体 Agent，避免编排层与业务服务互相依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AgentSpec:
    """一个可被 Orchestra 调度的角色。"""

    id: str
    name: str
    section: str
    capabilities: tuple[str, ...]
    description: str = ""


@dataclass(frozen=True)
class AgentTask:
    """一次可执行的角色任务。"""

    id: str
    agent: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    optional: bool = False


@dataclass
class AgentResult:
    """角色返回的结构化结果。"""

    task_id: str
    agent: str
    ok: bool = True
    output: Any = None
    error: str = ""
    evidence: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceEvent:
    """一次角色调用留下的审计记录。"""

    run_id: str
    seq: int
    task_id: str
    agent: str
    action: str
    ok: bool
    duration_ms: int
    error: str = ""
    evidence: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "seq": self.seq,
            "task_id": self.task_id,
            "agent": self.agent,
            "action": self.action,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "evidence": list(self.evidence),
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class Plan:
    """由 Conductor 执行的一次任务编排。"""

    intent: str
    section: str
    tasks: tuple[AgentTask, ...]


@dataclass
class RunResult:
    """一次 Orchestra 执行的最终结果。"""

    ok: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    trace: list[TraceEvent] = field(default_factory=list)
    error: str = ""
    run_id: str = ""

    def trace_dicts(self) -> list[dict]:
        return [event.as_dict() for event in self.trace]


class Blackboard:
    """一次编排内共享的黑板。

    Agent 不直接互相调用；它们只读黑板、写结果，由 Conductor 负责合并。
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def merge(self, values: dict[str, Any] | None) -> None:
        if values:
            self._data.update(values)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._data)


AgentHandler = Callable[[AgentTask, Blackboard], AgentResult]
PlanBuilder = Callable[[Any, Blackboard], Plan]
