"""反馈回流：把一次答题/任务结果编译为可复用的学习信号和技能资产候选。

原则：原始反馈不等于技能。只有带错误模式、证据、适用边界和复盘结论的记录，
才允许进入能力组合图；低置信记录先留在候选区，等待人工确认。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FeedbackRecord:
    user_id: str
    skill_point_id: str
    correct: bool
    score: float
    evidence: tuple[str, ...] = ()
    error_type: str = ""
    context: str = ""
    source: str = "quiz"
    confidence: float = 0.6
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "skill_point_id": self.skill_point_id,
                "correct": self.correct, "score": round(float(self.score), 1),
                "evidence": list(self.evidence), "error_type": self.error_type,
                "context": self.context, "source": self.source,
                "confidence": round(float(self.confidence), 3), "tags": list(self.tags),
                "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def infer_error_type(correct: bool, score: float) -> str:
    if correct:
        return "mastery_signal"
    if score < 40:
        return "knowledge_gap"
    if score < 70:
        return "procedure_or_reasoning_gap"
    return "boundary_or_transfer_gap"


def compile_learning_signal(user_id: str, skill_point_id: str, correct: bool,
                            score: float, evidence: list[str] | tuple[str, ...] | None = None,
                            *, context: str = "", source: str = "quiz",
                            confidence: float = 0.6) -> FeedbackRecord:
    return FeedbackRecord(user_id=user_id, skill_point_id=skill_point_id,
                          correct=bool(correct), score=float(score),
                          evidence=tuple(str(x) for x in (evidence or [])),
                          error_type=infer_error_type(bool(correct), float(score)),
                          context=str(context), source=source,
                          confidence=float(confidence))


def persist_learning_signal(store: Any, signal: FeedbackRecord) -> dict[str, Any]:
    payload = signal.as_dict()
    store.add_memory(signal.user_id, "learning_signal",
                     json.dumps(payload, ensure_ascii=False),
                     source_thread=f"signal:{signal.skill_point_id}",
                     importance=min(1.0, max(0.3, signal.confidence)))
    return payload


def mine_error_patterns(signals: list[dict[str, Any]] | list[FeedbackRecord]) -> list[dict[str, Any]]:
    """把多次反馈聚合成可行动的错误模式，供后续技能图/课程更新。"""
    counts: dict[tuple[str, str], int] = {}
    for raw in signals:
        item = raw.as_dict() if isinstance(raw, FeedbackRecord) else raw
        if not isinstance(item, dict) or item.get("correct"):
            continue
        key = (str(item.get("skill_point_id") or ""), str(item.get("error_type") or "unknown"))
        counts[key] = counts.get(key, 0) + 1
    rows = [{"skill_point_id": key[0], "error_type": key[1], "count": count,
             "update_action": "补前置技能" if key[1] == "knowledge_gap" else "补反例/边界练习"}
            for key, count in counts.items()]
    return sorted(rows, key=lambda x: (-x["count"], x["skill_point_id"]))


def load_learning_signals(store: Any, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """从 memory 只读取 learning_signal，避免把画像/聊天等其它记忆混入聚合。"""
    out: list[dict[str, Any]] = []
    for row in store.memories(user_id, limit=limit):
        if str(row.get("type") or "") != "learning_signal":
            continue
        try:
            item = json.loads(row.get("content") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict):
            item.setdefault("created_at", row.get("created_at", ""))
            out.append(item)
    return out


def capability_candidates(signals: list[dict[str, Any]] | list[FeedbackRecord],
                          *, min_count: int = 1) -> list[dict[str, Any]]:
    """将重复失败模式转成技能资产候选；不直接改图谱，保留人工审核闸门。"""
    patterns = [p for p in mine_error_patterns(signals) if p["count"] >= min_count]
    return [{"asset_id": f"candidate:{p['skill_point_id']}:{p['error_type']}",
             "skill_point_id": p["skill_point_id"], "pattern": p["error_type"],
             "observed_count": p["count"], "status": "pending_expert_review",
             "proposed_action": p["update_action"]} for p in patterns]
