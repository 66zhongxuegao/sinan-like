"""Agent 基类与上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import DeepSeekClient


@dataclass
class AgentContext:
    """一次演练的对话历史与元数据。"""

    instance_id: str
    user_id: str
    language: str = "中文"
    messages: list[dict[str, str]] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def transcript(self) -> str:
        lines = []
        for m in self.messages:
            who = {"assistant": "客户", "user": "定制师"}.get(m["role"], m["role"])
            lines.append(f"{who}: {m['content']}")
        return "\n".join(lines)


class BaseAgent:
    name = "agent"

    def __init__(self, llm: DeepSeekClient) -> None:
        self._llm = llm