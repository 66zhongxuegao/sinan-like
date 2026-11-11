# R07 · 模型调用上下文边界清单（conversation 域）

生成时间：本次重构（2026-10-16 会话）
覆盖范围：训练老师 / 测评 / 客户 / 供应商 / 评分 五类模型调用入口。
核对方式：逐条 `read` 源码确认「实际传进 `llm.chat/chat_json` 的 messages 与参数」，
不是看函数签名推断。行号对应当前工作区版本（有改动后会漂移，只作为定位锚点）。

约定：
- **user_id**：这条入口的身份从哪来（API 层一律 `Depends(current_user)`，
  服务层从订单行 `store.order(order_id)["user_id"]` 取；不接受请求体里的 `user_id` 当身份）。
- **order_id**：是否带订单上下文。
- **role**：提示词里定义的角色（system prompt 的角色定位）。
- **scene**：随请求变化、进入提示词的情境数据。
- 「只传需要的字段」= 该入口**没有**把无关域的数据（隐藏人设 / 评分答案 / 系统提示 / 成本底牌）喂进去。

---

## 0. 客户事实单一来源（本域本次新增，所有客户类入口的共同上游）

`tripcraft/services/customer_order_facts.py`

| 函数 | 作用 |
| --- | --- |
| `facts_for_order_id(store, order_id)` | 唯一入口：订单行 → `CustomerFacts` |
| `CustomerFacts.model_facts()` | 模型可见事实（party/dates/days/budget/transport/hotel/special/decision/documents），**空值保留** |
| `CustomerFacts.persona_for()` | 按同一份事实组装 `CustomerPersona`（文本/语音/IM 共用） |
| `CustomerFacts.public_facts()` | 前端可见白名单（不含预算/特殊需求/隐藏诉求） |
| `CustomerFacts.persona_view()` | 提示词素材视图（含 hidden/preferences/quirks） |

三条客户通道都调用 `persona_for(*args, facts=model_facts)`，因此订单事实只有一份口径。
实证：`scripts/verify_channel_context.py`（捕获真实 prompt 后逐字段比对）。

---

## 1. 训练老师（教学问答 / 讲义 / 判档 / 出题 / 判分）

文件：`tripcraft/services/thread_service.py`
身份来源：`user_id` 参数由路由层 `growth.py` 传入（**待办**：identity 域收口 `Depends(current_user)`）。

| 入口 | 行号 | user_id | order_id | role | scene（进提示词的内容） | 只传需要的字段？ |
| --- | --- | --- | --- | --- | --- | --- |
| `_plan()` 调度 | 271-283 | 无（只用 message） | 无 | 核心调度器 | 学员这句话前 200 字 | ✅ 只有一句话 |
| `_profile_advice()` | 285-295 | 有（取 ability） | 无 | 画像顾问 | 当前技能点掌握度 + 答题数 | ✅ 只有该技能点统计 |
| `reply()` 教师讲解 | 354-381 | 有 | 无 | 「司南」带教老师 | `ThreadContext.render()`：本技能点 Rubric + 知识点召回 + 本线程历史(6条) + 答题情况 + 掌握度 + 实战证据(3条) | ⚠️ 含 Rubric（教学场景需要，非评分答案） |
| `generate_asset()` | 385-417 | 有 | 无 | 教研生成 | 同上 + 答题/掌握度 | ⚠️ 含 Rubric |
| `judge_mastery()` | 421-435 | 有 | 无 | 掌握度判档 | 同上 | ⚠️ 输出 M1-M5 档位，仅落在服务端 |
| `pick_question()` | 437-449 | 有 | 无 | 实战出题老师 | 同上 | ⚠️ 生成 `answer`/`reference` 在**响应**里（见 R08 待办） |
| `submit_answer()` 简答判分 | 451-464 | 有 | 无 | 实战评判老师 | 题干 + 参考答案 + 学员答案 | ✅ 只有本题 |

**隔离性**：教学线程没有订单上下文，不会读到实战订单的隐藏人设或成本底牌。

---

## 2. 测评（初始画像 / 动态刷新）

文件：`tripcraft/agents/profiler.py`

| 入口 | 行号 | user_id | order_id | role | scene | 只传需要的字段？ |
| --- | --- | --- | --- | --- | --- | --- |
| `ProfileAgent.assess()` | 311-321（`_ask(ASSESS_SYSTEM…)` 319） | 路由层 `body.user_id`（**待办**：改 `Depends(current_user)`） | 无 | 画像 Agent | 答题摘要 `answer_digest` + 各维度分数 | ✅ 只有测评答案与分数 |
| `ProfileAgent.refresh()` | 343（`_ask(REFRESH_SYSTEM…)`） | 同上 | 无 | 画像 Agent | 维度分 + 能力表 + 近期订单评分摘要 + 答题 + 上一版报告 | ⚠️ 含订单评分摘要（结论级，不含原始转写） |

**隔离性**：测评不接触通话转写原文，也不接触资源方成本口径。

---

## 3. 客户（文本通话 / 实时语音 / IM 群聊）—— 本次重点

| 通道 | 入口与行号 | user_id | order_id | role | scene | 只传需要的字段？ |
| --- | --- | --- | --- | --- | --- | --- |
| 文本通话 | `call_service.py` `CallSession._ensure_agent()` 57-66 → `CustomerAgent.opening/reply`（`agents/customer.py` 88-102） | ✅ 真实登录用户（`AgentContext.user_id`，原为写死 `u-demo`，**已修**） | ✅ 订单号进 persona 派生 | 客户（不出戏） | 人设 + 订单事实 facts + 历史对话 + 追加 R06 硬约束 | ✅ 只有客户侧数据 |
| 实时语音 | `voice/bridge.py` `VoiceBridge.run()` 172-183 → `voice/realtime_qwen.py` `build_scene_voice_instructions()` 66-137 | ✅ `websocket_user()` 解析后传入 `CallSession`/`AgentContext` | ✅ `order_id` query + `facts_from_order_row` | 客户（游客） | 人设 + 订单事实 + 场景（opening/objective/situation）+ R06 规则 | ✅ 只有客户侧；**隐藏诉求只进提示词，不下发前端** |
| IM / 群聊 | `supplier_service.py` `_customer_reply()` 805-828（`CUSTOMER_SYSTEM_IM` 320-341） | ✅ 会话 `user_id`（路由层已改 `Depends(current_user)`） | ✅ 会话自带的 order_id | 客户 | 人设 + 订单事实 + 本单资源事实 `facts_text` + 事件 + 阶段 | ✅ 客户侧 + 本单客观事实 |

**本次改动**：
1. 三条通道统一经 `customer_order_facts` 取事实，`persona_for(..., facts=model_facts)`；
2. 语音通道修掉 `source_market` 空串兜底成「中国」的口径漂移；
3. 文本/语音的 `AgentContext.user_id` 不再写死演示账号；
4. 语音 `ready` 帧与通话快照改走 `api/public_dto.public_customer`（不含 hidden/traits/quirks）。

**实测证据**：`output/acceptance/evidence/conv-channel-context.md`

---

## 4. 供应商 / 资源方 / 导游

文件：`tripcraft/services/supplier_service.py`、`tripcraft/services/tools_service.py`

| 入口 | 行号 | user_id | order_id | role | scene | 只传需要的字段？ |
| --- | --- | --- | --- | --- | --- | --- |
| `_supplier_reply()` 资源方应答 | `supplier_service.py` 766-780（`ROLE_SYSTEM` 269） | 归属从订单行 `episode_owner`（**已修**硬编码 `u-demo`） | ✅ | 地接/酒店/车队/票务 | 本单资源口径、可用性、回复时限、阶段 | ⚠️ 含本单成本口径（供应商角色需要，非学员底牌） |
| `_guide_reply()` 司导应答 | 同上 782-803（`GUIDE_SYSTEM` 305） | 同上 | ✅ | 导游/司机 | 本单资源事实 + 事件 + 阶段 | ⚠️ 同上 |
| `ask()` 一次性询价 | 753-765 | 从订单行取 | ✅ | 资源方 | 同资源方应答 | 同上 |
| `tools_service.supplier()` | `tools_service.py` `SUPPLIER_SYSTEM` 26 / 调用约 192 | `supplier_states(user_id)` 需显式 user_id（**已修**，不再默认 `u-demo`） | 经 `order_id` 参数 | 资源方 | 情景状态 + 提问 | ✅ |
| `tools_service.deliverable_feedback()` | `CUSTOMER_SYSTEM` 60 / 调用约 205 | 由订单归属 | ✅ | 客户 | 交付物正文 | ✅ |

**本次改动**：`supplier_service.py` 的 7 处 `or "u-demo"` 兜底全部改为
「取不到归属就明确失败 / 告警并退回基准档」，逐条见本文件第 5 节。

---

## 5. R02/R07 硬编码用户整改清单（改前 → 改后）

| # | 位置（改前） | 改前行为 | 改后 |
| --- | --- | --- | --- |
| 1 | `call_service.py` `_ensure_agent()` `AgentContext(user_id="u-demo")` | 所有用户共享同一上下文身份 | `AgentContext(user_id=self.user_id)`（真实登录用户） |
| 2 | `call_service.py` `open_session()` `save_call_session(..., "u-demo", ...)` | 落库归属全写演示账号 | `save_call_session(..., owner, ...)`，owner = 调用方 user_id |
| 3 | `supplier_service.py:178` `_state()` `row.get("user_id") or "u-demo"` | 无归属时读演示账号的订单级资源约束 | `episode_owner()` 取不到 → 只读基准档 + `RuntimeWarning` |
| 4 | `supplier_service.py:389` `_user()` | 同上 | 返回空串（调用方判断） |
| 5 | `supplier_service.py:438→465` `rename_contact()` `ensure_hub(fresh.get("user_id") or "u-demo")` | 备注改名会把群挂到演示账号 | 有归属才刷新 hub；无归属告警跳过 |
| 6 | `supplier_service.py:532→559` `add_contact()` `user = row.get("user_id") or "u-demo"` | 联系人挂到演示账号 | 无归属 → `ValueError`（明确失败） |
| 7 | `supplier_service.py:627→664` `apply_fact()` | 事件约束落到演示账号 | 无归属 → `ValueError`（明确失败） |
| 8 | `supplier_service.py:664→705` `respond()` `user = sess.get("user_id") or "u-demo"` | 自建群按演示账号归属 | 会话/订单双取，取不到走 `_hub_reply` 的明确失败分支 |
| 9 | `supplier_service.py:691→732` `_hub_reply()` `user = sess.get("user_id") or "u-demo"` | 大群回复可能用的是别人的单 | 无归属 → 返回「会话缺少归属信息，请重新登录」 |
| 10 | `tripcraft/api/routers/calls.py` `im_sessions(user_id="u-demo")` | 任意查询参数当身份 | `Depends(current_user)`，列表只按当前用户过滤 |
| 11 | `tripcraft/api/routers/calls.py` `im_contacts(user_id="u-demo")` | 同上 | `Depends(current_user)` + `own_order` |
| 12 | `tripcraft/api/routers/calls.py` `im_send()` `sess.get("user_id") or "u-demo"` | 大群证据可能挂到别人的单 | 会话归属校验 + 订单归属校验 |
| 13 | `tripcraft/api/routers/calls.py` 各通话路由无归属校验 | 凭 sid 任意读写他人通话 | `get_for_user` / `own_order`，越权 403/404 |
| 14 | `/voice/realtime` 无认证 | 匿名可进、可对任意订单发起语音 | `websocket_user` + `own_order`，4401/4403 关闭 |
| 15 | `tools_service.supplier_states()/set_supplier_state()`（Lead 已修） | 默认 `u-demo` | 显式 `user_id`，空归属报错 |

---

## 6. 结论

- **已核实**：五类入口的 role / scene 边界清晰，互不混用；客户三通道共用同一份订单事实
  （真实 prompt 实证）；通话与 IM 的对象归属已收紧到登录用户。
- **未核实（无实时依赖）**：真实模型在收到越权提问时是否真的回避（无 DEEPSEEK/DASHSCOPE 凭据）。
- **待办（不属本域写范围）**：
  1. `growth.py` 的 `/threads/*` 与 `/profile/*` 仍用 `body.user_id` 当身份 → 交 identity 域改
     `Depends(current_user)` + `require_self`；
  2. `thread_service.snapshot()` 的题卡 payload 里含 `answer`/`reference` → 交 identity 域剥离
     （本域已提供 `public_dto.public_quiz_card()` 可直接用）；
  3. `journey` 域的订单详情 `persona` 字段 → 可改用 `api/public_dto.public_customer(facts)`。
