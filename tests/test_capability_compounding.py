"""反馈回流：学习信号落库、错误模式聚合和候选资产。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.capability_compounding import (
    capability_candidates, compile_learning_signal, load_learning_signals,
    mine_error_patterns, persist_learning_signal,
)
from tripcraft.storage import Store


def test_feedback_is_persisted_and_turns_into_candidate():
    store = Store(os.path.join(tempfile.gettempdir(), f"feedback-{uuid4().hex}.sqlite"))
    try:
        for _ in range(2):
            signal = compile_learning_signal(
                "u1", "C2.2", False, 35, ["quiz:q1"], context="预算题", source="quiz")
            persist_learning_signal(store, signal)
        signals = load_learning_signals(store, "u1")
        assert len(signals) == 2
        patterns = mine_error_patterns(signals)
        assert patterns[0]["skill_point_id"] == "C2.2"
        assert patterns[0]["count"] == 2
        candidates = capability_candidates(signals, min_count=2)
        assert candidates[0]["status"] == "pending_expert_review"
    finally:
        store.close()
