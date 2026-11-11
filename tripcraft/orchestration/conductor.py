"""Conductor —— Multi-Agent Orchestra 的总指挥。

职责只有四件事：
1. 按 Plan 顺序调度角色；
2. 检查依赖，避免角色在上下文未就绪时抢跑；
3. 把角色结果写入 Blackboard；
4. 为每次调用留下 Trace。

Conductor 不生成业务内容，不直接调用模型。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .contracts import (
    AgentResult,
    AgentTask,
    Blackboard,
    Plan,
    PlanBuilder,
    RunResult,
    TraceEvent,
)
from .registry import AgentRegistry


class Conductor:
    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self.registry = registry or AgentRegistry()

    def run(self, plan: Plan, blackboard: Blackboard | None = None) -> RunResult:
        board = blackboard or Blackboard()
        run_id = uuid.uuid4().hex[:12]
        outputs: dict[str, Any] = {}
        trace: list[TraceEvent] = []
        seq = 0
        error = ""

        for task in plan.tasks:
            missing = [dep for dep in task.depends_on if dep not in outputs]
            if missing:
                error = f"{task.id} 缺少上游结果: {', '.join(missing)}"
                trace.append(TraceEvent(
                    run_id=run_id, seq=seq, task_id=task.id, agent=task.agent,
                    action=task.action, ok=False, duration_ms=0, error=error))
                return RunResult(False, outputs, trace, error, run_id)

            seq += 1
            started = time.perf_counter()
            try:
                bound = self.registry.get(task.agent)
                result = bound.handler(task, board)
                if not isinstance(result, AgentResult):
                    result = AgentResult(task.id, task.agent, ok=True, output=result)
            except Exception as exc:  # 角色失败不能击穿整条主链
                result = AgentResult(task.id, task.agent, ok=False,
                                     error=f"{type(exc).__name__}: {exc}")
            duration = int((time.perf_counter() - started) * 1000)

            trace.append(TraceEvent(
                run_id=run_id, seq=seq, task_id=task.id, agent=task.agent,
                action=task.action, ok=result.ok, duration_ms=duration,
                error=result.error, evidence=tuple(result.evidence),
                meta={"section": plan.section, **result.meta}))

            if not result.ok:
                if task.optional:
                    continue
                error = result.error or f"{task.agent} 执行失败"
                return RunResult(False, outputs, trace, error, run_id)

            outputs[task.id] = result.output
            board.set(task.id, result.output)
            board.merge(result.meta)

        return RunResult(True, outputs, trace, "", run_id)

    def run_dynamic(self, planner_task: AgentTask, build_plan: PlanBuilder,
                    blackboard: Blackboard | None = None) -> RunResult:
        """先让调度器角色产出意图，再按意图生成可执行 Plan。"""
        board = blackboard or Blackboard()
        first = self.run(Plan("orchestra.plan", "orchestra", (planner_task,)), board)
        if not first.ok:
            return first
        try:
            plan = build_plan(first.outputs.get(planner_task.id), board)
        except Exception as exc:
            message = f"PlanBuilder 失败: {type(exc).__name__}: {exc}"
            return RunResult(False, dict(first.outputs), list(first.trace), message, first.run_id)

        second = self.run(plan, board)
        return RunResult(
            ok=second.ok,
            outputs={**first.outputs, **second.outputs},
            trace=[*first.trace, *second.trace],
            error=second.error,
            run_id=first.run_id,
        )
