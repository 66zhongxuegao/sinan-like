"""资源方数据 → 证据链 → 评分 Agent 的贯通测试（离线，不联网）。

回答两个问题：
1. 学员在资源方群里的对话，会不会进证据链？（会，且落点按群类型对齐内部步骤）
2. 评分 Agent 看不看得到资源方的客观口径？（看得到，但只作核对参照，不算学员证据）

迁移说明（Lead 收口，2026-10）：
- 旧版用 `monkeypatch.setattr(app_mod, "DeepSeekClient", NoKey)`，假设路由还挂在
  `tripcraft/api/app.py` 上。拆分后 app.py 不再持有 DeepSeekClient，该写法必然 AttributeError。
- 新版：模型离线由 `tests/conftest.py` 的 autouse fixture 统一保证
  （chat/chat_json 直接抛 LLMError，并移除 DEEPSEEK_API_KEY），所以这里不再需要自建 NoKey。
- 认证：API 默认 fail-closed，所有请求走 conftest 的 `auth_client`；
  演示种子数据按**当前登录账号**注入（`practice.seed(user_id)`），
  因此订单归属校验自然通过——这是按新认证迁移，不是绕过安全控制。
"""

from __future__ import annotations

import os
import tempfile
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient  # noqa: F401  (类型注解用)
from tripcraft.agents.scorer import ScoringAgent
from tripcraft.services.practice_service import GROUP_STEP, PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.storage import Store

ORDER = "9000000000000004"      # 种子数据里的浙江单 · 平台阶段 4


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    """每个用例一个独立库文件。

    必要性：种子订单的 order_id 是固定的，而 `seed()` 现在有归属保护
    （不会把已属于他人的种子单改归自己）。若整个会话共用一个库，
    第二个用例的账号就 seed 不到任何单，后续归属校验必然 403。
    这里在 test 级 autouse 里先换库，保证先于 client/auth_client fixture 生效。

    注意：库文件放在**已存在**的系统临时目录里，不新建目录
    （沙箱下新建目录不可访问，见 tests/conftest.py 说明）。
    """
    monkeypatch.setenv("TRIPCRAFT_DB", os.path.join(
        tempfile.gettempdir(), f"ev_{uuid4().hex}.sqlite"))


class CaptureLLM:
    """不联网的假模型：只记录它收到的提示词。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        return "收到"

    def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        return {"scores": []}


def _seed_for_current_account(c, headers) -> str:
    """给当前登录账号注入种子订单，返回其 user_id。

    只 seed 这一个账号（seed 现在有归属保护，不会抢别人的单）。
    """
    uid = c.get("/auth/session", headers=headers).json()["user_id"]
    PracticeService(Store()).seed(uid)
    return uid


def _add(c, headers, order_id, *kinds):
    """按真实顺序加联系人（新规则：没加联系人的群不能发言）。"""
    for k in kinds:
        r = c.post("/practice/im/contacts", headers=headers,
                   json={"order_id": order_id, "kind": k})
        assert r.status_code == 200, r.text


def _room(c, headers, kind):
    """新模型：没有自动建的"酒店沟通群"，只有加了好友之后的单聊。"""
    groups = c.get("/practice/im/sessions", headers=headers,
                   params={"order_id": ORDER}).json()
    return next(g for g in groups if g["code"] == f"dm-{kind}")


def test_group_chat_becomes_evidence(auth_client):
    c, headers = auth_client
    _seed_for_current_account(c, headers)

    groups = c.get("/practice/im/sessions", headers=headers,
                   params={"order_id": ORDER}).json()
    codes = {g["code"] for g in groups}
    # 订单就绪后系统会预建资源大群、票务窗并自动指派地接；测试只关心
    # 这些会话存在，不把“入口会话数量”锁死成某个旧版本常量。
    assert "hub" in codes

    _add(c, headers, ORDER, "地接社", "酒店")
    hotel = _room(c, headers, "酒店")
    assert hotel["name"] and hotel["kind"] == "酒店"
    c.post(f"/practice/im/sessions/{hotel['session_id']}/messages", headers=headers,
           json={"sender": "我", "role": "me", "content": "这三天四星房什么价？"})

    ev = Store().evidence(ORDER)
    kinds = [(e["kind"], e["step"]) for e in ev]
    assert ("im", "S4") in kinds                     # 酒店群 → S4 资源询价
    last = ev[-1]
    assert "开元销售陈" in last["text"] or "酒店" in last["text"]
    assert "我：" in last["text"] and "540" in last["text"]   # 学员原话 + 资源方口径

    # 非学员消息（系统/对方）不进证据，避免自说自话
    before = len(Store().evidence(ORDER))
    c.post(f"/practice/im/sessions/{hotel['session_id']}/messages", headers=headers,
           json={"sender": "酒店·李", "role": "other", "content": "好的"})
    assert len(Store().evidence(ORDER)) == before


def test_group_step_map_covers_the_new_session_kinds(auth_client):
    """聊天的内部步骤落点要覆盖新模型的会话类型（大群 / 单聊 / 自建群）。"""
    c, headers = auth_client
    _seed_for_current_account(c, headers)
    _add(c, headers, ORDER, "地接社", "酒店", "客户")

    groups = c.get("/practice/im/sessions", headers=headers,
                   params={"order_id": ORDER}).json()
    codes = {g["code"] for g in groups}
    assert "hub" in codes and "dm-酒店" in codes and "dm-客户" in codes
    for code in codes:
        assert GROUP_STEP[code].startswith("S"), code


def test_toolbox_quote_uses_same_facts_as_group(auth_client):
    c, headers = auth_client
    _seed_for_current_account(c, headers)

    svc = SupplierService(Store())
    via_ask = svc.ask(ORDER, "酒店", "四星什么价？")
    assert via_ask["quote"]["summary"] == svc.facts(ORDER, "酒店")["summary"]
    assert "540" in via_ask["content"]


def test_scoring_agent_receives_resource_facts():
    """纯服务层：评分提示词里必须带资源方口径，且标注不能单独作为给分依据。"""
    llm = CaptureLLM()
    agent = ScoringAgent(llm)
    from tripcraft.contracts.rubric import RUBRICS
    agent.score("【call】学员：您好", [RUBRICS["C1.1"]],
                facts="酒店：四星 540/间/晚（可用性 紧张）")
    payload = llm.calls[0][1]["content"]
    assert "resource_facts" in payload and "540" in payload
    assert "不是学员证据" in payload or "不能单独作为给分依据" in payload


def test_score_order_passes_facts_into_prompt(auth_client):
    c, headers = auth_client
    _seed_for_current_account(c, headers)
    _add(c, headers, ORDER, "地接社", "酒店")
    hotel = _room(c, headers, "酒店")
    c.post(f"/practice/im/sessions/{hotel['session_id']}/messages", headers=headers,
           json={"sender": "我", "role": "me", "content": "四星和用车什么价？"})

    store = Store()
    practice = PracticeService(store)
    # 本单目标技能点要先被覆盖才进评分：A 型补交付物证据，B 型补触发 + 反应
    for sp_id in practice.build_plan(ORDER):
        t = store.target(ORDER, sp_id)
        if not t:
            continue
        if t["checkpoint"] == "B":
            practice.mark_trigger(ORDER, sp_id, t["step"])
            practice.mark_reacted(ORDER, sp_id)
        else:
            practice.record_evidence(ORDER, "行程方案", f"覆盖 {sp_id}", step=t["step"])

    facts = practice.supplier_facts_text(ORDER)
    assert "酒店：" in facts and "540" in facts       # 本单资源方口径

    llm = CaptureLLM()
    practice.score_order(ORDER, llm)
    assert llm.calls                                  # 确实把材料送进了评分模型
    payload = llm.calls[0][1]["content"]
    assert "resource_facts" in payload and "540" in payload


def test_incident_shows_up_in_scoring_facts(auth_client):
    c, headers = auth_client
    _seed_for_current_account(c, headers)

    store = Store()
    practice = PracticeService(store)
    from tripcraft.services.director_service import DirectorService
    from tripcraft.services.supplier_service import SupplierService
    sup = SupplierService(store, practice=practice)
    sup.add_contact(ORDER, "地接社")
    sup.add_contact(ORDER, "导游")          # 司导单聊得先在，事件才有地方落
    fired = DirectorService(store, practice=practice, llm=None).emit(ORDER, "pre_trip")
    assert fired and fired["injected"], "已经加了导游，车辆故障事件应该注入"
    facts = practice.supplier_facts_text(ORDER)
    assert "事件·车辆故障" in facts and "换车" in facts
