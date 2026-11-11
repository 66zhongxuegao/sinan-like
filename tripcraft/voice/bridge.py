"""浏览器 ⇄ DashScope Qwen-Omni-Realtime 的语音中继（FastAPI WebSocket）。

职责：
  1. 浏览器只连本服务，DashScope 密钥留在后端（不落到前端）；
  2. 上行：浏览器麦克风 PCM16/16k -> input_audio_buffer.append；
  3. 下行：模型 24k PCM 音频增量 + 双方转写文本 -> 浏览器；
  4. 通话结束后：把转写写回 call_session/call_line，并登记为本单实战证据。

协议（JSON 文本帧）：
  浏览器 -> 服务端
    {"type":"audio","audio":"<base64 pcm16 16k>"}
    {"type":"commit"}                     # 手动提交一轮（默认由服务端 VAD 自动提交）
    {"type":"text","text":"..."}          # 无麦/调试：用文本触发一轮
    {"type":"stop"}                       # 主动结束
  服务端 -> 浏览器
    {"type":"ready"}
    {"type":"audio","audio":"<base64 pcm16 24k>"}
    {"type":"transcript","who":"agent|student","text":"...","final":bool}
    {"type":"state","value":"listening|thinking|speaking|idle"}
    {"type":"error","message":"..."}
    {"type":"closed"}
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agents.customer import CustomerPersona
from ..agents.customer import persona_for, trip_intent
from ..services.customer_order_facts import facts_from_order_row, facts_for_order_id
from .language_profiles import LANG_COUNTRIES, VOICE_LANG

ROOT = Path(__file__).resolve().parents[2]
TRACE_FILE = ROOT / "logs" / "voice_trace.jsonl"
from .realtime_qwen import (
    INPUT_RATE,
    OUTPUT_RATE,
    QwenRealtimeClient,
    build_scene_voice_instructions,
    resolve_env,
)

# 展示用语言名 -> 语言码
LANG_CODES = {
    "中文": "zh", "汉语": "zh", "简体中文": "zh",
    "English": "en", "英语": "en",
    "日本語": "ja", "日语": "ja", "한국어": "ko", "韩语": "ko",
    "Français": "fr", "法语": "fr", "Deutsch": "de", "德语": "de",
    "Español": "es", "西班牙语": "es", "Русский": "ru", "俄语": "ru",
    "العربية": "ar", "阿拉伯语": "ar", "Italiano": "it", "意大利语": "it",
    "Português": "pt", "葡萄牙语": "pt", "Tiếng Việt": "vi", "越南语": "vi",
    "Bahasa Indonesia": "id", "印尼语": "id", "ไทย": "th", "泰语": "th",
    "Türkçe": "tr", "土耳其语": "tr",
}


def lang_code(label: str) -> str:
    return LANG_CODES.get((label or "").strip(), "zh")


def pick_voice(lang: str, gender: str) -> str:
    table = VOICE_LANG.get(lang) or VOICE_LANG["zh"]
    return table["male"] if gender == "男" else table["female"]


def build_scene(order_customer: str, destination: str, stage_name: str, source_market: str = "", facts: dict | None = None) -> dict[str, Any]:
    return {
        "opening": "电话刚接通，由你先自然地接听一句；然后根据定制师说明的来意，沟通你自己的旅行安排。",
        "trip_hint": trip_intent(destination, source_market, facts),
        "location": "电话沟通",
        "stage_title": stage_name or "首呼与需求挖掘",
        "objective": "希望定制师理解自己的出行意向与实际限制，提供合适的行程建议，并商量后续联系安排",
        "situation": (
            "你正以客户身份咨询旅行安排，按自己的资料回答问题；"
            "尚未确定的事项可以请对方给建议。语气、耐心与预算表达遵循具体人设及已知事实。"
        ),
    }


def build_persona(customer_name: str, destination: str, lang_label: str,
                  source_market: str = "", order_id: str = "", personality: str = "") -> dict:
    """语音提示词用的人设 —— 直接取自订单级人设（agents/customer.py），
    和文本通话、群聊是同一份，避免同一个客人换条链路就换个人。"""
    p = persona_for(customer_name, destination, source_market, lang_label, order_id, personality)
    return p.voice_profile()


def persona_view_from_order(order: dict | None) -> dict:
    """语音通道的人设视图：唯一从订单行派生（R02）。

    修复前这里传的是 `self.order.get("source_market", "")`——空客源地会让
    `persona_for` 兜底成“中国”，与文本/IM 通道的“香港”默认口径不一致。
    现在统一走 `services.customer_order_facts`。
    """
    return facts_from_order_row(order).persona_view()


def load_order_facts(store, order_id: str):
    """按订单号加载客户事实（语音入口用；避免调用方各自取字段）。"""
    return facts_for_order_id(store, order_id)


def map_event(ev: dict) -> dict | None:
    """DashScope 事件 -> 浏览器事件（None = 不转发）。"""
    t = ev.get("type", "")
    if t == "session.updated":
        return {"type": "ready"}
    if t == "response.audio.delta":
        delta = ev.get("delta") or ev.get("audio")
        return {"type": "audio", "audio": delta} if delta else None
    if t == "response.audio_transcript.delta":
        return {"type": "transcript", "who": "agent", "text": ev.get("delta", ""), "final": False}
    if t == "response.audio_transcript.done":
        return {"type": "transcript", "who": "agent", "text": ev.get("transcript", ""), "final": True}
    if t in ("conversation.item.input_audio_transcription.completed",
             "conversation.item.input_audio_transcription.done"):
        return {"type": "transcript", "who": "student", "text": ev.get("transcript", ""), "final": True}
    if t == "input_audio_buffer.speech_started":
        return {"type": "state", "value": "listening"}
    if t == "input_audio_buffer.speech_stopped":
        return {"type": "state", "value": "thinking"}
    if t == "response.created":
        return {"type": "state", "value": "speaking"}
    if t == "response.done":
        return {"type": "state", "value": "listening"}
    if t in ("error", "ws_error"):
        return {"type": "error", "message": json.dumps(ev, ensure_ascii=False)[:400]}
    if t == "closed":
        return {"type": "closed"}
    return None


class VoiceBridge:
    """一次语音通话的中继会话，接收含 payload 的数据库原始订单行。"""

    def __init__(self, ws, order: dict, customer_name: str, destination: str,
                 call_svc, practice, user_id: str = "") -> None:
        if "payload" not in order:
            raise ValueError("语音通话缺少完整订单资料，请重新加载订单后拨打")
        self.ws = ws
        self.order = order
        self.customer_name = customer_name
        self.destination = destination
        self.call_svc = call_svc
        self.practice = practice
        self.store = getattr(call_svc, "_store", None) or getattr(practice, "_store", None)
        # 真实登录用户：写进 call_session.user_id / AgentContext，不再写死演示账号
        self.user_id = user_id or ""
        self.client: QwenRealtimeClient | None = None
        self.lines: list[dict] = []
        self._agent_buf = ""
        self._pending = ""
        self.session_id = ""
        # ---- 通话埋点：上游到底有没有就绪、双方各发了多少音频 ----
        self.started_at = time.time()
        self.ready_ok = False
        self.ready_ms: int | None = None
        self.audio_in_frames = 0
        self.audio_in_bytes = 0
        self.audio_out_frames = 0
        self.audio_out_bytes = 0

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(ev: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        # 客户事实唯一来源：订单行 → CustomerFacts（与文本/IM 同一套默认值、同一份订单事实）
        facts = facts_for_order_id(self.store, self.order["order_id"])
        label = facts.language
        lang = lang_code(label)
        p = facts.persona_for()
        from ..services.customer_context import GREETINGS, build_customer_system
        instructions = build_customer_system(facts.order_id, "voice", store=self.store,
                                             history=self.store.conversation_turns(facts.order_id, 10))

        try:
            api_key, ws_url, model = resolve_env()
        except RuntimeError as exc:
            await self._send({"type": "error", "message": str(exc)})
            return

        sess = self.call_svc.open_session(facts.order_id or self.order.get("order_id", ""),
                                          facts.customer, facts.destination, mode="voice",
                                          source_market=facts.source_market,
                                          language=facts.language,
                                          personality=facts.personality,
                                          user_id=self.user_id,
                                          facts=facts.model_facts())
        self.session_id = sess.session_id

        voice = pick_voice(lang, p.gender)
        client = QwenRealtimeClient(
            api_key, ws_url, model, instructions,
            voice=voice, on_event=on_event)
        self.client = client
        client.connect()
        if not await asyncio.to_thread(client.wait_ready, 20):
            await self._send({"type": "error", "message": "语音服务连接超时（未收到 session.updated）"})
            client.close()
            self._trace("ready_timeout")
            return

        # ready 里带上语言与人设：前端要显示「这通电话对方说什么语言」，也便于演示时讲解。
        # 这里**只发公开字段**（public_dto.public_customer），隐藏诉求/性格细节一律不下发。
        from ..api.public_dto import public_customer

        await self._send({"type": "ready", "session_id": self.session_id,
                          "lang": lang, "language": label, "voice": voice,
                          "persona": public_customer(facts),
                          "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE})

        self.ready_ok = True
        self.ready_ms = int((time.time() - self.started_at) * 1000)
        self._mark_dialed()

        sender = asyncio.create_task(self._pump(queue))
        recv = asyncio.create_task(self._receive())
        try:
            # 电话接通后由客户先开口；否则模型会一直等学员先说话，前端看起来像“对方不说话”。
            client.ask_text(GREETINGS.get(label, "Hello?"))
            while True:
                done, _pending = await asyncio.wait(
                    {sender, recv}, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        raise exc
                if sender in done:
                    break          # 上游事件泵结束/断开 → 收口落库
        except Exception:
            pass
        finally:
            recv.cancel()
            sender.cancel()
            client.close()
            await self._finalize()

    async def _receive(self) -> None:
        """接收浏览器上行帧；断开或 stop 时返回（让 run() 收口落库）。"""
        while True:
            raw = await self.ws.receive_text()
            if not await self._handle(raw):
                return

    async def _pump(self, queue: asyncio.Queue) -> None:
        from ..services.customer_card import check_reply
        from ..services.customer_context import build_customer_system, fallback_reply
        frames, transcript, deltas, byte_count, retry = [], "", "", 0, 0
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    return
                event_type = ev.get("type", "")
                if event_type == "session.updated":
                    continue
                if event_type == "response.created":
                    frames, transcript, deltas, byte_count = [], "", "", 0
                    await self._send({"type": "state", "value": "thinking"})
                    continue
                if event_type == "response.audio.delta":
                    frame = map_event(ev)
                    if frame:
                        byte_count += len(frame.get("audio") or "")
                        if byte_count <= 16 * 1024 * 1024:
                            frames.append(frame)
                    continue
                if event_type == "response.audio_transcript.delta":
                    deltas += str(ev.get("delta") or "")
                    continue
                if event_type == "response.audio_transcript.done":
                    transcript += str(ev.get("transcript") or "")
                    continue
                if event_type == "response.done":
                    transcript = (transcript or deltas).strip()
                    card = self.store.ensure_customer_card(self.order["order_id"])
                    question = getattr(self, "_last_student_question", "")
                    issues = check_reply(transcript, card, question=question)
                    if not transcript or byte_count > 16 * 1024 * 1024:
                        issues.append({"key": "voice", "reason": "unverifiable_audio"})
                    if issues:
                        for issue in issues:
                            self.store.record_customer_conflict(self.order["order_id"], issue, "voice",
                                                               f"{self.session_id}:{len(self.lines)}:{retry}")
                        if retry == 0 and self.client is not None:
                            retry = 1
                            correction = build_customer_system(self.order["order_id"], "voice", store=self.store)
                            correction += "\n上一条回复已被拦截，未播放。请保持出游客户身份，按事实卡重新回答原问题；表达自己的需求或请定制师给建议，不采集定制师的旅行需求，不替对方提供服务。纠正：" + json.dumps(issues, ensure_ascii=False)
                            self.client.update_instructions(correction)
                            self.client.ask_text("请重新回答定制师的原话：" + question)
                            frames, transcript, deltas, byte_count = [], "", "", 0
                            continue
                        # 不播放冲突音频；再次失败时用同一事实卡模板显示文字。
                        transcript = fallback_reply(card, question)
                        frames = []
                    retry = 0
                    await self._send({"type": "state", "value": "speaking"})
                    self._agent(transcript)
                    for frame in frames:
                        self.audio_out_frames += 1
                        self.audio_out_bytes += len(frame.get("audio") or "") * 3 // 4
                        await self._send(frame)
                    await self._send({"type": "transcript", "who": "agent", "text": transcript, "final": True})
                    if issues:
                        await self._send({"type": "state", "value": "idle", "message": "本轮已切换为文字回复"})
                    await self._send({"type": "state", "value": "listening"})
                    if self.client is not None:
                        self.client.update_instructions(build_customer_system(
                            self.order["order_id"], "voice", store=self.store,
                            history=self.store.conversation_turns(self.order["order_id"], 10)))
                    frames, transcript, deltas, byte_count = [], "", "", 0
                    continue
                line = transcript_line(ev)
                if line is not None:
                    who, text = line
                    if who == "agent":
                        self._agent(text)
                    else:
                        self._student(text)
                mapped = map_event(ev)
                if mapped is None:
                    continue
                if mapped.get("type") == "audio":
                    b64 = mapped.get("audio") or ""
                    if b64:
                        self.audio_out_frames += 1
                        self.audio_out_bytes += len(b64) * 3 // 4
                await self._send(mapped)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._trace("consistency_error")
            await self._send({"type": "error", "message": "本轮语音处理未完成，请重新发起通话。"})

    async def _handle(self, raw: str) -> bool:
        try:
            msg = json.loads(raw)
        except Exception:
            return True
        t = msg.get("type")
        if t == "stop":
            return False
        if self.client is None:
            return True
        if t == "audio":
            b64 = msg.get("audio") or ""
            if b64:
                self.audio_in_frames += 1
                try:
                    raw = base64.b64decode(b64)
                    self.audio_in_bytes += len(raw)
                    self.client.append_audio(raw)
                except Exception:
                    pass
        elif t == "commit":
            try:
                self.client.commit()
            except Exception:
                pass
        elif t == "text":
            text = (msg.get("text") or "").strip()
            if text:
                self._student(text)
                try:
                    self.client.ask_text(text)
                except Exception:
                    pass
        return True

    # ---- 转写落库 ----

    def _student(self, text: str) -> None:
        self._last_student_question = text
        if self.lines and self.lines[-1]["who"] == "student" and self.lines[-1]["text"] == text:
            return
        self.lines.append({"who": "student", "text": text})
        if self.call_svc is not None and self.session_id:
            sess = self.call_svc.get(self.session_id)
            if sess is not None:
                self.call_svc.record_line(sess, "student", text)

    def _agent(self, text: str) -> None:
        from ..services.customer_context import observe_reply
        store = getattr(self, "store", None)
        order_id = str((getattr(self, "order", None) or {}).get("order_id") or "")
        if store is not None and order_id:
            observe_reply(store, order_id, text, "voice",
                          f"{self.session_id}:voice:{len(self.lines)}",
                          getattr(self, "_last_student_question", ""))
        if self.lines and self.lines[-1]["who"] == "agent" and self.lines[-1]["text"] == text:
            return
        self.lines.append({"who": "agent", "text": text})
        if self.call_svc is not None and self.session_id:
            sess = self.call_svc.get(self.session_id)
            if sess is not None:
                self.call_svc.record_line(sess, "agent", text)

    def _mark_dialed(self) -> None:
        """拨通即算「发起首呼」。
        门槛只管有没有真的发起这一通电话，聊得好不好交给评分 Agent（有证据链可查）。
        record_action 本身幂等，重复调用不会写两条。
        """
        if self.practice is None or not self.order:
            return
        try:
            self.practice.record_action(
                self.order["order_id"], "first_call",
                {"session_id": self.session_id, "mode": "voice", "stage": "dialed"},
            )
        except Exception:
            pass

    def _trace(self, reason: str) -> None:
        """把这一通的关键数字记到 logs/voice_trace.jsonl。

        ready_ok / ready_ms 回答「语音模型到底连上没有」，
        audio_in_* 是浏览器送上来的音频，audio_out_* 是模型返回的音频。
        """
        rec = {
            "ts": time.time(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session_id": self.session_id,
            "order_id": (self.order or {}).get("order_id", ""),
            "customer": self.customer_name,
            "reason": reason,
            "ready_ok": self.ready_ok,
            "ready_ms": self.ready_ms,
            "duration_s": round(time.time() - self.started_at, 1),
            "audio_in_frames": self.audio_in_frames,
            "audio_in_bytes": self.audio_in_bytes,
            "audio_out_frames": self.audio_out_frames,
            "audio_out_bytes": self.audio_out_bytes,
            "turns": sum(1 for l in self.lines if l["who"] == "student"),
        }
        try:
            TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with TRACE_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def _send(self, payload: dict) -> None:
        try:
            await self.ws.send_json(payload)
        except Exception:
            pass

    async def _finalize(self) -> None:
        if not self.session_id:
            return
        try:
            self.call_svc.end(self.session_id)
        except Exception:
            pass
        turns = sum(1 for l in self.lines if l["who"] == "student")
        # 首呼已在「拨通」（收到 ready）时登记，这里只统计轮数，不再重复登记。
        self._trace("closed")
        await self._send({"type": "closed", "turns": turns,
                          "evidence": len(self.practice.evidence(self.order["order_id"]))
                          if self.practice is not None else 0})


def transcript_line(ev: dict) -> tuple[str, str] | None:
    """把上游事件里的「最终转写」取出来，用于落库。

    中间的分片（delta）不落库，只落 done / completed，避免同一句话被拆成十几条。
    """
    t = ev.get("type")
    if t == "response.audio_transcript.done":
        who = "agent"
    elif t in ("conversation.item.input_audio_transcription.completed",
               "conversation.item.input_audio_transcription.done"):
        who = "student"
    else:
        return None
    text = (ev.get("transcript") or "").strip()
    return (who, text) if text else None


def collect_transcript(ev: dict, buf: dict) -> None:
    """（可选）供离线复用的转写累加器。"""
    if ev.get("type") == "response.audio_transcript.done":
        buf["agent"] = ev.get("transcript", "")
