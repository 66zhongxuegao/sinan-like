"""Agent 注册表：把角色契约和具体实现分开。"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import AGENT_SPECS
from .contracts import AgentHandler, AgentSpec


class AgentNotBound(RuntimeError):
    pass


@dataclass
class BoundAgent:
    spec: AgentSpec
    handler: AgentHandler


class AgentRegistry:
    def __init__(self, specs: dict[str, AgentSpec] | None = None) -> None:
        self._specs = dict(specs or AGENT_SPECS)
        self._bound: dict[str, BoundAgent] = {}

    def bind(self, agent_id: str, handler: AgentHandler, *, replace: bool = False) -> None:
        spec = self._specs.get(agent_id)
        if spec is None:
            raise KeyError(f"未注册的角色契约: {agent_id}")
        if agent_id in self._bound and not replace:
            return
        self._bound[agent_id] = BoundAgent(spec=spec, handler=handler)

    def unbind(self, agent_id: str) -> None:
        self._bound.pop(agent_id, None)

    def get(self, agent_id: str) -> BoundAgent:
        agent = self._bound.get(agent_id)
        if agent is None:
            raise AgentNotBound(f"角色 {agent_id} 尚未绑定实现")
        return agent

    def spec(self, agent_id: str) -> AgentSpec | None:
        return self._specs.get(agent_id)

    def is_bound(self, agent_id: str) -> bool:
        return agent_id in self._bound

    def catalog(self) -> list[dict]:
        rows = []
        for spec in self._specs.values():
            rows.append({
                "id": spec.id,
                "name": spec.name,
                "section": spec.section,
                "capabilities": list(spec.capabilities),
                "description": spec.description,
                "bound": spec.id in self._bound,
            })
        return rows
