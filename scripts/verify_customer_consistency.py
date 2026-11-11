"""本地客户一致性验收：不读密钥、不连接模型、不启动软件。

python scripts/verify_customer_consistency.py [--source-db path]
可选从现有库读取最多 20 张订单，在临时库验证回填；原库保持只读。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP_ROOT = ROOT / ".dsh-run" / "customer-consistency-verify"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
from tripcraft.storage import Store
from tripcraft.services.customer_card import build_card, check_reply, extract_facts
from tripcraft.services.customer_context import customer_messages, guarded_reply
from tripcraft.services.call_service import CallService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.services.tools_service import ToolsService
from tripcraft.voice.bridge import VoiceBridge

QUESTIONS = {"party": "几个人出行？", "dates": "出行日期是什么？", "days": "玩几天？",
             "budget": "预算多少？", "hotel": "住宿有什么要求？", "documents": "证件准备情况？"}
SOURCE_DB = None


class FakeLLM:
    def __init__(self, text="喂，你好。", feedback=None):
        self.text = text
        self.feedback = feedback or {"reply": text, "sentiment": "满意", "asks": []}
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.text

    def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        return self.feedback


class Frames:
    def __init__(self):
        self.frames = []

    async def send_json(self, frame):
        self.frames.append(frame)


class Realtime:
    def __init__(self):
        self.retries = 0

    def update_instructions(self, text):
        self.instructions = text

    def ask_text(self, text):
        self.retries += 1


def order(store, oid="verify", **payload):
    store.upsert_order(oid, "verify-user", "验收客户", "云南", "正常", 0,
                       {"generated": True, "language": "中文", "party": "3 大 1 小", **payload})
    return store.order(oid)


def voice_reply(store, row, question, responses):
    ws, rt = Frames(), Realtime()
    bridge = VoiceBridge(ws, row, row["customer"], row["destination"], CallService(store=store), None)
    bridge.client = rt
    bridge._last_student_question = question
    async def drive():
        queue = asyncio.Queue()
        for index, text in enumerate(responses):
            for event in ({"type": "response.created"},
                          {"type": "response.audio.delta", "delta": f"AUDIO-{index}"},
                          {"type": "response.audio_transcript.done", "transcript": text},
                          {"type": "response.done"}):
                await queue.put(event)
        await queue.put(None)
        await bridge._pump(queue)
    asyncio.run(drive())
    replies = [f["text"] for f in ws.frames if f.get("type") == "transcript"]
    if not replies:
        raise AssertionError(f"语音未产生经过守卫的转写: {ws.frames}")
    return replies[-1], ws.frames, rt


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store._conn.close()

    def test_twenty_orders_six_facts_across_actual_channels(self):
        for index in range(20):
            oid = f"verify-{index}"
            row = order(self.store, oid)
            card = self.store.ensure_customer_card(oid)
            calls = CallService(store=self.store, llm=FakeLLM())
            session = calls.start_for_order(self.store, oid, "verify-user")
            im = SupplierService(self.store, llm=FakeLLM())
            for key, question in QUESTIONS.items():
                with self.subTest(order=index, fact=key):
                    text = calls.say(session.session_id, question, "verify-user")
                    im_text = im._customer_reply({}, row, question)["content"]
                    spoken, _, _ = voice_reply(self.store, row, question, [text])
                    self.assertEqual(text, im_text)
                    self.assertEqual(text, spoken)
                    self.assertFalse(check_reply(text, card, question=question))
                    if card["fields"][key]["state"] != "unknown":
                        self.assertEqual(extract_facts(text, card, question).get(key), card["fields"][key]["value"])
                    else:
                        self.assertIn("还没确定", text)
            calls.end(session.session_id)
            self.assertEqual(self.store.order(oid)["_customer_card"]["fields"]["budget"]["revealed"], True)

    def test_hidden_release_shared_persisted_and_audited(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = str(Path(directory) / "memory.sqlite")
            store = Store(path)
            order(store)
            before = store.ensure_customer_card("verify")
            self.assertFalse(before["fields"]["budget"]["revealed"])
            answer = guarded_reply(store, None, "verify", "text", QUESTIONS["budget"])["reply"]
            store._conn.close()
            store = Store(path)
            after = store.ensure_customer_card("verify")
            self.assertTrue(after["fields"]["budget"]["revealed"])
            self.assertEqual(answer, guarded_reply(store, None, "verify", "im", QUESTIONS["budget"])["reply"])
            self.assertEqual(len([e for e in store.customer_fact_events("verify") if e["kind"] == "released"]), 1)
            self.assertEqual(json.loads(store.order("verify")["payload"])["budget"], after["fields"]["budget"]["value"])
            store._conn.close()

    def test_conflicting_reply_retries_once_then_falls_back(self):
        order(self.store)
        llm = FakeLLM("我们两个人出行。")
        result = guarded_reply(self.store, llm, "verify", "im", "请介绍一下需求")
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(result["consistency"]["fallback"])
        self.assertNotIn("两个人", result["reply"])
        self.assertEqual(self.store.ensure_customer_card("verify")["fields"]["party"]["value"], "3 大 1 小")
        self.assertTrue(self.store.customer_fact_events("verify"))

    def test_voice_rejects_audio_before_playback(self):
        row = order(self.store)
        answer, frames, rt = voice_reply(self.store, row, QUESTIONS["party"], ["我们两个人出行。", "出行人数：3 大 1 小。"])
        self.assertEqual(rt.retries, 1)
        self.assertEqual([f["audio"] for f in frames if f.get("type") == "audio"], ["AUDIO-1"])
        self.assertEqual(answer, "出行人数：3 大 1 小。")
        answer, frames, rt = voice_reply(self.store, row, QUESTIONS["party"], ["我们两个人出行。"] * 2)
        self.assertEqual(rt.retries, 1)
        self.assertFalse([f for f in frames if f.get("type") == "audio"])
        self.assertIn("3 大 1 小", answer)

    def test_unknown_rejects_concrete_numbers_and_documents(self):
        row = order(self.store, generated=False, party="")
        card = self.store.ensure_customer_card(row["order_id"])
        for text in ("两个人", "十一月二十日出发", "预算八千元", "护照已经办好了"):
            self.assertTrue(check_reply(text, card, question="人数、日期、预算和证件？"), text)
        for channel in ("text", "im", "voice"):
            reply = guarded_reply(self.store, FakeLLM("预算八千元"), "verify", channel, "预算多少？")["reply"]
            self.assertIn("还没确定", reply)

    def test_confirmation_can_resolve_unknown_but_never_overwrite_fixed(self):
        order(self.store, generated=False)
        guarded_reply(self.store, FakeLLM("好的，预算8000元，确认。"), "verify", "im", "确认预算8000元，可以吗？")
        self.assertEqual(self.store.ensure_customer_card("verify")["fields"]["budget"]["value"], "预算8000元")
        self.store.observe_customer_facts("verify", {"party": "2人"}, "im", "conflict", confirmed=True)
        self.assertEqual(self.store.ensure_customer_card("verify")["fields"]["party"]["value"], "3 大 1 小")
        self.assertEqual(self.store.customer_fact_events("verify")[-1]["kind"], "conflict")
        result = guarded_reply(self.store, FakeLLM("好的，确认。"), "verify", "im", "确认人数2人，可以吗？")
        self.assertTrue(result["consistency"]["fallback"])
        self.assertIn("3 大 1 小", result["reply"])

    def test_dates_and_duration_are_coherent(self):
        row = order(self.store, dates="2026-11-20 至 2026-11-24", days="")
        self.assertEqual(self.store.ensure_customer_card(row["order_id"])["fields"]["days"]["value"], "5 天")
        row = order(self.store, "bad-old-dates", generated=False, dates="2026-11-20 至 2026-11-24", days="7 天")
        self.assertEqual(self.store.ensure_customer_card(row["order_id"])["fields"]["days"]["value"], "7 天")
        self.assertTrue(self.store.customer_fact_events(row["order_id"]))

    def test_plan_read_uses_shared_memory_and_persona(self):
        from tripcraft.services.plan_service import PlanService
        order(self.store, language="English", source_market="英国")
        llm = FakeLLM(feedback={"reply": "I have read your plan.", "sentiment": "满意", "asks": []})
        plans = PlanService(self.store, tools=ToolsService(llm=llm, store=self.store))
        plan = plans.create("verify", {"title": "Plan", "days": []})
        self.store.update_plan(plan["plan_id"], status="已发送", read_due_at="2020-01-01T00:00:00")
        result = plans._materialize_read(self.store.plan(plan["plan_id"]))
        self.assertEqual(result["feedback"], "I have read your plan.")
        self.assertTrue(any(t["channel"] == "plan" for t in self.store.conversation_turns("verify")))

    def test_offline_provider_uses_same_card(self):
        from tripcraft.services.scenario_service import ScenarioLLM, list_cases
        from tripcraft.services.customer_context import build_customer_system
        order(self.store)
        provider = ScenarioLLM(list_cases()[0])
        card = self.store.ensure_customer_card("verify")
        for question in QUESTIONS.values():
            messages = [{"role": "system", "content": build_customer_system("verify", "im", store=self.store)},
                        {"role": "user", "content": question}]
            response = provider.chat(messages)
            self.assertFalse(check_reply(response, card, question=question))
        from tripcraft.services.customer_context import GREETINGS
        for language, greeting in GREETINGS.items():
            oid = "greeting-" + language
            order(self.store, oid, language=language)
            response = provider.chat([{"role": "system", "content": build_customer_system(oid, "text", store=self.store)},
                                      {"role": "user", "content": "定制师刚打来电话"}])
            self.assertEqual(response, greeting)

    def test_history_includes_feedback_and_excludes_other_orders(self):
        order(self.store)
        order(self.store, "other")
        self.store.add_customer_turn("verify", "document", "customer", "请确认接送地点", "feedback-1")
        self.store.add_customer_turn("other", "document", "customer", "OTHER-ORDER-SECRET", "feedback-2")
        messages = customer_messages(self.store, "verify", "im", "刚才说了什么？")
        self.assertTrue(any(m["content"] == "请确认接送地点" for m in messages))
        self.assertNotIn("OTHER-ORDER-SECRET", json.dumps(messages, ensure_ascii=False))

    def test_document_feedback_uses_order_persona_and_language(self):
        order(self.store, language="English", source_market="英国", personality="PERSONA_SENTINEL")
        llm = FakeLLM(feedback={"reply": "您好，我们两个人。", "asks": ["预算多少？"]})
        result = ToolsService(llm=llm, store=self.store).deliverable_feedback("需求确认单", "Document", order_id="verify")
        self.assertEqual(len(llm.calls), 2)
        self.assertNotRegex(result["reply"], r"[\u3400-\u9fff]")
        system = llm.calls[0][0]["content"]
        self.assertIn("PERSONA_SENTINEL", system)
        self.assertIn("English", system)
        self.assertTrue(any(t["channel"] == "document" for t in self.store.conversation_turns("verify")))

    def test_existing_orders_backfill_without_inventing_answers(self):
        rows = []
        if SOURCE_DB:
            connection = sqlite3.connect(Path(SOURCE_DB).resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            rows = [dict(r) for r in connection.execute("SELECT * FROM biz_order ORDER BY created_at DESC LIMIT 20")]
            connection.close()
            self.assertTrue(rows, "源库没有订单")
        else:
            rows = [{"order_id": f"legacy-{i}", "user_id": "legacy", "customer": "旧客户", "destination": "云南", "payload": '{"party":"3人"}'} for i in range(20)]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = str(Path(directory) / "backfill.sqlite")
            store = Store(path)
            for row in rows:
                store.upsert_order(row["order_id"], row["user_id"], row["customer"], row["destination"], "正常", 0, json.loads(row["payload"] or "{}"))
            store._exec("DELETE FROM order_customer")
            store._conn.close()
            store = Store(path)
            for row in rows:
                card = store.ensure_customer_card(row["order_id"])
                expected = build_card(row, fill_hidden=False)
                self.assertEqual(card["fields"], expected["fields"])
                for key, fact in card["fields"].items():
                    if fact["state"] == "unknown":
                        self.assertEqual(fact["value"], "")
                # 旧单在三通道使用相同守卫；未知项不能从原先的空串生成新数字。
                if card["identity"]["language"] == "中文":
                    for question in QUESTIONS.values():
                        outputs = [guarded_reply(store, None, row["order_id"], channel, question)["reply"] for channel in ("text", "voice", "im")]
                        self.assertEqual(outputs[0], outputs[1])
                        self.assertEqual(outputs[0], outputs[2])
            store._conn.close()
        print(f"旧单临时库回填：{len(rows)} 单")


def run_checks(verbosity=2):
    return unittest.TextTestRunner(verbosity=verbosity).run(unittest.defaultTestLoader.loadTestsFromTestCase(ConsistencyTests))


if __name__ == "__main__":
    if "--source-db" in sys.argv:
        SOURCE_DB = sys.argv[sys.argv.index("--source-db") + 1]
    raise SystemExit(0 if run_checks().wasSuccessful() else 1)
