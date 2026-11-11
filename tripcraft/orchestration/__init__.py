"""Multi-Agent Orchestra 编排层。"""

from .catalog import AGENT_SPECS, PRACTICE_AGENTS, TEACHING_AGENTS, catalog, get_spec
from .conductor import Conductor
from .contracts import (
    AgentResult,
    AgentSpec,
    AgentTask,
    Blackboard,
    Plan,
    RunResult,
    TraceEvent,
)
from .registry import AgentNotBound, AgentRegistry

__all__ = [
    "AGENT_SPECS", "TEACHING_AGENTS", "PRACTICE_AGENTS", "catalog", "get_spec",
    "Conductor", "AgentRegistry", "AgentNotBound",
    "AgentSpec", "AgentTask", "AgentResult", "Blackboard", "Plan", "RunResult", "TraceEvent",
]
