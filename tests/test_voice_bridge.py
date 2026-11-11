"""语音中继的转写落库：上游事件 → 通话记录。

背景：语音通话里 AI 说的话、学生说的话都来自上游实时转写事件，
必须由事件泵回写；漏了这一步，「说过话才算首呼」就永远不成立，
订单会被误判超时。
"""

from tripcraft.voice.bridge import VoiceBridge, transcript_line


def test_transcript_line_agent_final():
    ev = {"type": "response.audio_transcript.done", "transcript": "喂，你好，我是陈先生。"}
    assert transcript_line(ev) == ("agent", "喂，你好，我是陈先生。")


def test_transcript_line_student_final():
    for t in ("conversation.item.input_audio_transcription.completed",
              "conversation.item.input_audio_transcription.done"):
        ev = {"type": t, "transcript": "您好，请问是陈先生吗"}
        assert transcript_line(ev) == ("student", "您好，请问是陈先生吗")


def test_transcript_line_ignores_deltas_and_empty():
    assert transcript_line({"type": "response.audio_transcript.delta", "delta": "喂"}) is None
    assert transcript_line({"type": "response.audio_transcript.done", "transcript": "   "}) is None
    assert transcript_line({"type": "response.audio.delta", "delta": "xxxx"}) is None


def _bare_bridge() -> VoiceBridge:
    b = object.__new__(VoiceBridge)
    b.lines = []
    b.call_svc = None
    b.session_id = ""
    return b


def test_turns_count_student_lines():
    b = _bare_bridge()
    b._agent("喂，你好")
    b._student("您好，我是定制师")
    b._agent("我想去广西")
    turns = sum(1 for l in b.lines if l["who"] == "student")
    assert turns == 1 and len(b.lines) == 3


def test_consecutive_duplicates_are_ignored():
    b = _bare_bridge()
    b._agent("喂，你好")
    b._agent("喂，你好")
    b._student("您好")
    b._student("您好")
    assert [l["who"] for l in b.lines] == ["agent", "student"]
# ---------------- 拨通即算首呼 + 通话埋点 ----------------

class _FakePractice:
    def __init__(self):
        self.calls = []

    def record_action(self, order_id, action, payload=None):
        self.calls.append((order_id, action, payload))


def _bridge_for_call() -> VoiceBridge:
    b = object.__new__(VoiceBridge)
    b.lines = []
    b.call_svc = None
    b.session_id = "call-9000000000000009-1"
    b.order = {"order_id": "9000000000000009"}
    b.customer_name = "客户 X"
    b.practice = _FakePractice()
    b.started_at = 0.0
    b.ready_ok = False
    b.ready_ms = None
    b.audio_in_frames = 0
    b.audio_in_bytes = 0
    b.audio_out_frames = 0
    b.audio_out_bytes = 0
    return b


def test_ready_marks_first_call_even_without_speaking():
    """拨通（收到 ready）就算发起首呼——门槛管有没有做，评分管做得好不好。"""
    b = _bridge_for_call()
    b._mark_dialed()
    assert len(b.practice.calls) == 1
    order_id, action, payload = b.practice.calls[0]
    assert (order_id, action) == ("9000000000000009", "first_call")
    assert payload["mode"] == "voice" and payload["stage"] == "dialed"


def test_trace_writes_ready_and_audio_counters(monkeypatch, tmp_path):
    import json as _json
    from tripcraft.voice import bridge as br

    trace = tmp_path / "voice_trace.jsonl"
    monkeypatch.setattr(br, "TRACE_FILE", trace)
    b = _bridge_for_call()
    b.ready_ok = True
    b.ready_ms = 4200
    b.audio_in_frames = 12
    b.audio_in_bytes = 48000
    b.audio_out_frames = 30
    b.audio_out_bytes = 96000
    b._agent("喂，你好")
    b._student("您好")
    b._trace("closed")
    rec = _json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
    assert rec["ready_ok"] is True and rec["ready_ms"] == 4200
    assert rec["audio_in_frames"] == 12 and rec["audio_out_frames"] == 30
    assert rec["turns"] == 1 and rec["reason"] == "closed"
    assert rec["order_id"] == "9000000000000009"