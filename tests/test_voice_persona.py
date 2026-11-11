"""客户人设一致性：语言 / 音色 / 文本 / 群聊同源（离线，不联网）。"""

from tripcraft.agents.customer import build_customer_system, persona_for, stable_gender_age
from tripcraft.services.call_service import CallService
from tripcraft.voice.bridge import build_persona, lang_code, pick_voice


class CaptureLLM:
    """只记录 system prompt 的假 LLM。"""

    def __init__(self):
        self.systems: list[str] = []

    def chat(self, messages, **kwargs):
        self.systems.append(messages[0]["content"] if messages else "")
        return "ok"


# ---------------- 人设 ----------------

def test_persona_is_stable_per_order_and_varies_across_orders():
    a1 = persona_for("客户 A", "江苏", "香港", "中文", "9000000000000001")
    a2 = persona_for("客户 A", "江苏", "香港", "中文", "9000000000000001")
    assert (a1.gender, a1.age) == (a2.gender, a2.age), "同一单必须每次都是同一个人"

    seen = {(persona_for("客户", "云南", "美国", "English", f"order-{i}").gender,
             persona_for("客户", "云南", "美国", "English", f"order-{i}").age) for i in range(40)}
    assert len(seen) > 4, f"不同订单应该换人，实际只有 {seen}"


def test_gender_and_age_are_balanced_enough():
    genders = [stable_gender_age(f"order-{i}")[0] for i in range(400)]
    assert 120 < genders.count("男") < 280, "性别不能一边倒"


def test_persona_carries_order_language_and_prompt_pins_it():
    p = persona_for("客户 E", "四川", "美国", "English", "9000000000000005")
    assert p.language == "English"
    assert any("只说English" in t for t in p.traits)
    system = build_customer_system(p)
    assert "你只会说English" in system, "文本通话的系统提示必须写死语言"
    assert "不要翻译成中文" in system

    zh = persona_for("客户 A", "江苏", "香港", "中文", "9000000000000001")
    assert zh.language == "中文"
    assert "你只会说中文" in build_customer_system(zh)


# ---------------- 语音：人设 → 音色 / 提示词 同源 ----------------

def test_voice_persona_is_the_same_object_as_text_persona():
    p = persona_for("客户 E", "四川", "美国", "English", "9000000000000005", "说话直接")
    v = build_persona("客户 E", "四川", "English", "美国", "9000000000000005", "说话直接")
    assert v["gender"] == p.gender and v["age"] == p.age
    assert v["language"] == p.language


def test_voice_follows_persona_gender():
    males, females = set(), set()
    for i in range(60):
        oid = f"order-{i}"
        p = persona_for("客户", "云南", "美国", "English", oid)
        voice = pick_voice(lang_code(p.language), p.gender)
        (males if p.gender == "男" else females).add(voice)
    assert males and females, "男女都要出现，否则等于没换声"
    assert males.isdisjoint(females), "同一门语言下男女音色不应重叠"


def test_language_maps_to_a_real_voice_for_every_supported_language():
    from tripcraft.agents.scenario import LANGUAGES
    from tripcraft.voice.language_profiles import VOICE_LANG
    for label in LANGUAGES:
        code = lang_code(label)
        assert code in VOICE_LANG, label
        for gender in ("男", "女"):
            assert pick_voice(code, gender)


# ---------------- 文本通话：真的把语言发给了模型 ----------------

def test_text_call_sends_language_rule_to_model():
    llm = CaptureLLM()
    svc = CallService(llm=llm)
    svc.start("9000000000000005", "客户 E", "四川", "美国", "English")
    assert llm.systems, "客户 Agent 应该收到 system prompt"
    assert "你只会说English" in llm.systems[0]

    llm2 = CaptureLLM()
    svc2 = CallService(llm=llm2)
    svc2.start("9000000000000001", "客户 A", "江苏", "香港", "中文")
    assert "你只会说中文" in llm2.systems[0]


def test_session_keeps_language_and_personality():
    svc = CallService(llm=CaptureLLM())
    sess = svc.start("9000000000000005", "客户 E", "四川", "美国", "English", "语气冲，赶时间")
    snap = sess.snapshot()
    assert snap["language"] == "English"
    assert sess.personality == "语气冲，赶时间"
    assert sess.persona().personality == "语气冲，赶时间"
