# Multi-Agent Orchestra 架构

2026-10-18

## 定义

项目采用**确定性编排的 Multi-Agent Orchestra**：

- **Conductor**：后端编排层，负责任务顺序、依赖、黑板合并和 Trace。
- **Score**：Rubric、订单事实、六类教学资料，是每个 Agent 的输入边界。
- **Sections**：教学声部与实战声部，各自只完成受控任务。
- **Blackboard**：一次编排内的共享状态，Agent 不直接互相调用。
- **Trace**：记录每次角色调用、耗时、证据和失败原因。

Conductor 不生成业务内容，不直接调用模型。主讲 Agent 也不是总指挥，只负责汇总输出。

## 目录

```text
tripcraft/orchestration/
  contracts.py    AgentSpec / AgentTask / AgentResult / Plan / TraceEvent / Blackboard
  catalog.py      角色目录：teaching.* / practice.*
  registry.py     角色契约与实现绑定
  conductor.py    顺序执行、依赖校验、动态 Plan、Trace
```

## 教学链路

```text
teaching.router
  → teaching.retrieval
  → teaching.context
  → teaching.profile（可选）
  → teaching.teacher
```

- `router` 只判断本轮需要哪些协作者，不作答。
- `retrieval` 返回知识点基座命中与来源。
- `context` 是**确定性代码节点，不调用 LLM**，装配 Rubric、知识、线程历史、答题记录、画像、实战证据。
- `profile` 读取掌握度给建议，失败时可选跳过。
- `teacher` 汇总黑板，生成一次带来源的讲解。

对应实现：`tripcraft/services/thread_service.py`。

## 实战链路

```text
session / order
  → practice.hub / practice.customer / practice.supplier / practice.guide
  → 结构化回复
```

电话：

```text
practice.phone_customer
  → 同一份客户人设 + 订单事实
```

对应实现：`tripcraft/services/supplier_service.py`、`tripcraft/services/call_service.py`。

## 共享执行入口

`AppContext` 持有一个共享 `Conductor`，教学、IM 和电话服务把各自的角色绑定到同一个注册表：

```text
AppContext.conductor
  ├─ ThreadService       → teaching.*
  ├─ SupplierService     → practice.customer / supplier / guide / hub
  └─ CallService         → practice.phone_customer
```

## 调试面

启用 `TRIPCRAFT_DEBUG_PLATFORM=1` 后：

```text
GET /orchestration/agents
```

返回角色目录、所属声部、能力和是否已绑定实现。

## 边界

- Agent 之间不直接调用。
- 所有输入由 Blackboard 提供，所有输出由 Conductor 合并。
- 失败角色默认阻断必选任务；可选角色失败不会阻断主讲汇总。
- 评分、校准、资源事实和流程门控仍由既有领域服务控制，不由 LLM 自由决定。

## IM / 订单 / 画像边界（2026-10-18）

IM 不是一组靠群名识别的聊天框，而是四个明确对象：

- `Conversation`：`hub / dm / group`，成员从会话参与者读取；
- `Participant`：学员、客户、酒店、车队、地接、票务、司导；
- `Order anchor`：会话订单、联系人订单或显式 `order_id`，资源大群多单并行时必须显式选择；
- `Route`：`conversation_id + order_id + target_role + agent_id`，由代码生成，不交给模型猜。

路由顺序固定为：

```text
校验会话归属
  → 绑定订单锚点
  → 解析目标角色
  → Conductor 选择 Agent
  → 读本单订单事实
  → 落消息与 evidence
```

导演事件只改写当前订单的事实，再投递到受影响会话；IM、电话、交付物都写同一份 evidence，评分通过覆盖率、置信度和校准闸门后写回同一份画像（教学掌握 `teach`、实战掌握 `real_v`）。实现见 `tripcraft/services/conversation_service.py`、`tripcraft/services/supplier_service.py`、`tripcraft/services/director_service.py` 与 `tripcraft/api/routers/calls.py`。

演示页：`output/im-order-profile-architecture.html`；口播稿：`output/im-order-profile-narration.md`。
