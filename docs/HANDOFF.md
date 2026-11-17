# 司南礼客现有系统功能与 Agent 交接说明

> 更新日期：2026-11-17  
> 适用目录：`D:\司南礼客项目`  
> 当前基线提交：`5a39cf2 feat: group orders messages and chat under practice hub`

本文用于让新的开发 Agent 在不重新猜测项目结构的情况下接手工作。内容以当前源码和实际启动结果为准。

---

## 1. 项目定位

**项目名称**：司南礼客  
**英文/代码名**：TripCraft  
**定位**：面向入境游定制师培训的个性化生成与多智能体协同决策系统。

系统把“学习、训练、实战、证据、评分、画像、复盘”连接成一条训练闭环：

```text
注册/登录
  → 初始测评
  → 学情画像
  → 个性化学习路线
  → AI 教师讲解/练习/资源生成
  → 画像驱动的实战派单
  → 抢单/首呼/IM/资源询价
  → 交付物生成与投递
  → 成本结算
  → 评分与证据核验
  → 画像更新与下一单难度调整
```

---

## 2. 技术栈与运行形态

### 后端

- Python 3.11+
- FastAPI
- Pydantic v2
- Uvicorn
- 标准库 SQLite
- HTTP/WebSocket
- DeepSeek/OpenAI 兼容大模型接口
- 阿里云 Qwen Realtime WebSocket
- 高德地图 API

### 前端

- Vue 3
- TypeScript
- Vite
- Pinia
- Vue Router（Hash 模式）
- Element Plus
- ECharts / vue-echarts
- Electron
- SCSS

### 当前部署

```text
Cloudflare
  → Named Tunnel: sinan-like
  → Vite 前端: 127.0.0.1:25190
  → FastAPI 后端: 127.0.0.1:28020
```

- 公网域名：`https://sinanlike.com`
- 备用域名：`https://www.sinanlike.com`
- Cloudflare 部署详情：`docs/CLOUDFLARE_DEPLOYMENT.md`
- **注意**：当前公网部署仍以本机为源站，电脑关机或休眠后网站会离线。

---

## 3. 快速启动

### 3.1 普通训练模式

```powershell
cd D:\司南礼客项目
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desktop_launch.ps1 -Mode Normal
```

等价的桌面入口：

```text
司南礼客桌面版.bat
```

端口：

- 前端：`http://127.0.0.1:25190`
- 后端：`http://127.0.0.1:28020`
- 数据库：`.dsh-run\normal\preview.sqlite`

### 3.2 只启动 Web 服务

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desktop_launch.ps1 -Mode Normal -WebOnly
```

### 3.3 固定案例演示模式

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\启动标准演示.ps1
```

端口：

- 前端：`http://127.0.0.1:25191`
- 后端：`http://127.0.0.1:28930`
- 数据库：`.dsh-run\codex-review\preview.sqlite`

### 3.4 依赖

```powershell
cd D:\司南礼客项目
python -m pip install -e ".[dev]"

cd .\frontend
npm ci
```

### 3.5 本地构建

```powershell
cd D:\司南礼客项目\frontend
npm run build
```

### 3.6 后端测试

```powershell
cd D:\司南礼客项目
pytest -q
```

最近一次完整后端测试记录：**412 passed**。当前日期之后的修改若涉及后端，应重新执行。

---

## 4. 配置与环境变量

本地密钥文件：

```text
D:\司南礼客项目\local.env
```

该文件被 `.gitignore` 排除，不能提交 Git。

主要变量：

```text
DEEPSEEK_API_KEY
LLM_BASE_URL
LLM_MODEL
DASHSCOPE_API_KEY
QWEN_OMNI_WS_URL
QWEN_OMNI_MODEL
AMAP_API_KEY
OPEN_METEO_BASE
```

其他运行变量：

```text
TRIPCRAFT_DB                     # 指定 SQLite 路径
SERVE_WEB=1                      # 让 FastAPI 托管 frontend/dist
TRIPCRAFT_SCENARIO_MODE=offline  # 固定案例离线 provider
TRIPCRAFT_DEMO_TOURIST=on        # 演示实例固定游客
TRIPCRAFT_BOOTSTRAP_ORDERS=1     # 注册后生成初始派单
TRIPCRAFT_SEED_DEMO=1            # 可选旧版 u-demo 种子
```

启动脚本中还固定写了本机路径：

```text
D:\python\python.exe
D:\nodejs\node.exe
```

换机时需要先运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\首次安装与适配.ps1
```

---

## 5. 仓库目录

```text
tripcraft/
  api/                 FastAPI 组合根、中间件、认证、路由
  agents/              LLM 客户端与教学/派单/评分/画像 Agent
  orchestration/       Conductor、Agent 注册表与编排协议
  services/            业务服务层
  contracts/           技能点、Rubric、阶段、交付物等契约
  engine/              状态机与门禁
  storage/             SQLite Store 与 schema
  tools/               外部工具封装
  voice/               实时语音桥接
  mcp/                 MCP Server

frontend/
  src/App.vue          桌面与移动应用壳
  src/router/          路由与登录守卫
  src/stores/          Pinia 用户/训练状态
  src/api/             Axios 客户端
  src/components/      通用组件
  src/views/           页面
  electron/            Electron 主进程与 preload

data/                  知识库、Rubric、标准案例
tests/                 后端测试
scripts/               启动、验收、演示、维护脚本
docs/                  设计、状态、部署与交接文档
_交接文档/              安装、演示和验收材料
```

---

## 6. 后端总体架构

### 6.1 组合根

后端入口：

```text
tripcraft/api/app.py
```

职责：

1. 创建 FastAPI
2. 构造 `AppContext`
3. 注册访问监控中间件
4. 注册各业务路由
5. 安装认证中间件
6. 可选托管 `frontend/dist`

### 6.2 AppContext

文件：

```text
tripcraft/api/context.py
```

`AppContext` 是单实例服务容器，持有：

- SQLite `Store`
- `PracticeService`
- `ToolsService`
- `GuardService`
- `DirectorService`
- `CallService`
- `SupplierService`
- `FinanceService`
- `DeliverableService`
- `PlanService`
- `ConversationService`
- `Conductor`

LLM 与线程服务惰性初始化。路由不得自行 `new` 服务，避免同进程出现两套状态。

### 6.3 路由域

路由注册表：

```text
tripcraft/api/routers/__init__.py
```

当前模块：

- `core`
- `auth`
- `runs`
- `practice`
- `deliverables`
- `calls`
- `growth`
- `scenario`
- `platform`
- `competition`

---

## 7. 认证、会话与数据隔离

文件：

```text
tripcraft/api/security.py
tripcraft/services/auth_service.py
tripcraft/api/routers/auth.py
frontend/src/stores/user.ts
```

### 功能

- 注册
- 登录
- 退出
- 会话恢复
- 个人资料读取
- 个人资料修改
- 登录账号候选列表

### 认证规则

- 服务端会话是唯一可信身份来源
- Bearer token 优先，其次 HttpOnly Cookie `tc_token`
- 非公开 API 默认 fail-closed
- `user_id` 不允许从前端伪造
- 订单归属执行 `own_order` 校验

### 前端身份态

- `localStorage` 保存 `tc-token`
- `GET /auth/session` 换取公开资料
- API 请求自动带 Bearer token
- 401 自动回登录页
- 公开资料不包含密码哈希

### 数据口径

- `users.kind=demo`：标准案例/演示数据
- `users.kind=real`：真实训练数据

---

## 8. 后端功能模块

## 8.1 通用与契约

路由：`tripcraft/api/routers/core.py`

功能：

- 健康检查 `/`
- 文化桥列表与详情
- 文本翻译
- 阶段
- 能力维度
- 61 个技能点
- Rubric
- 客源市场

主要接口：

```text
GET  /
GET  /learn/culture-bridges
GET  /learn/culture-bridges/{code}
POST /learn/translate
GET  /contracts/steps
GET  /contracts/dimensions
GET  /contracts/skill-points
GET  /contracts/skill-points/{skill_point_id}
GET  /contracts/rubric/{skill_point_id}
GET  /contracts/markets
```

## 8.2 学习地图、AI 教师、题目与画像

路由：`tripcraft/api/routers/growth.py`  
服务：`tripcraft/services/thread_service.py`  
服务：`tripcraft/services/learning_route.py`  
服务：`tripcraft/services/adaptive_diagnosis.py`

功能：

- 学习地图
- 文化桥对话工作台
- AI 教师问答
- 知识检索
- 个性资源生成
- 讲义、实操指南、学习报告、错题本
- AI 出题
- 选择题/简答题
- 答题判分
- 掌握度 M1-M5
- BKT 参数更新
- 初始测评
- 学习路线生成与修改
- 学情雷达
- 历史快照
- 趋势数据
- 画像刷新

关键流程：

```text
画像 + Rubric + 历史答题 + 实战证据
  → LLM 判断掌握度 M1-M5
  → 映射题目难度 L1-L5
  → LLM 生成题目
  → 服务端保存答案
  → 学员作答
  → 选择题规则判分 / 简答题 LLM 判分
  → BKT 更新 teach
  → 重新计算下一题难度
```

主要接口：

```text
GET  /learn/map
GET  /threads/{sp}
POST /threads/{sp}/messages
POST /threads/{sp}/assets
POST /threads/{sp}/quiz
POST /threads/{sp}/quiz/answer
GET  /profiles/{user_id}
GET  /profiles/{user_id}/trend
POST /profiles/{user_id}/abilities
GET  /profiles/{user_id}/radar
GET  /profiles/{user_id}/radar/history
GET  /profiles/{user_id}/radar/history/{snapshot_id}
GET  /profile/quiz
GET  /profiles/{user_id}/learning-route
POST /profiles/{user_id}/learning-route
POST /profiles/{user_id}/learning-route/revise
GET  /profiles/{user_id}/intake
POST /profile/assessment
GET  /profiles/{user_id}/report
POST /profiles/{user_id}/refresh
```

当前难度控制事实：

- 题目由 AI 动态生成，不是固定题库抽题
- `M1→L1`、`M2→L2`、`M3→L3`、`M4→L4`、`M5→L5`
- 难度主要是 Prompt 中的定性描述
- 后端覆盖模型返回的 difficulty，但尚未自动校验题目实际复杂度
- 已知契约不一致：`DifficultyLevel` 枚举当前只定义 L1-L4，而教学题使用 L1-L5

## 8.3 派单、抢单与订单

路由：`tripcraft/api/routers/practice.py`  
服务：`tripcraft/services/practice_service.py`  
服务：`tripcraft/services/learner_brief.py`  
生成器：`tripcraft/agents/scenario.py`  
时限：`tripcraft/services/dispatch_service.py`

功能：

- 按学员画像生成派单
- 学习者简报
- 目标技能点选择
- 单量/压力旋钮
- 待接单列表
- 抢单窗口
- 竞争人数
- 竞争者接走时间
- 首呼时限
- 方案时限
- 订单列表
- 订单详情
- Journey/阶段进度
- 订单 action
- 事件目录
- 事件注入
- 覆盖校验
- 评分复核

目标技能点选择：

1. 上一单未覆盖的补考点优先
2. 未评估技能点优先
3. 分数最低的薄弱技能点优先

整单分支：

```text
最弱主考点 <60     → 补救
60-69             → 加压一档
70-79             → 加压二档
80-89             → 加压三档
≥90               → 加压四档
```

压力旋钮：

- 客源/语言复杂度
- 需求模糊度
- 派单信息残缺度
- 首呼时限
- 预算紧度
- 资源冲突
- 客户情绪强度

主要接口：

```text
GET  /practice/stages
GET  /practice/steps
GET  /practice/orders
GET  /practice/orders/{order_id}
GET  /practice/orders/available
GET  /practice/dispatch/brief
POST /practice/dispatch/generate
GET  /practice/orders/{order_id}/journey
GET  /practice/orders/{order_id}/steps
GET  /practice/orders/{order_id}/contacts
GET  /practice/orders/{order_id}/gates
POST /practice/orders/{order_id}/grab
POST /practice/orders/{order_id}/actions
GET  /practice/orders/{order_id}/actions
GET  /practice/orders/{order_id}/flow
GET  /practice/orders/{order_id}/dispatch
GET  /practice/orders/{order_id}/timeline
GET  /practice/orders/{order_id}/coverage
GET  /practice/orders/{order_id}/reviews
POST /practice/orders/{order_id}/reviews/{sp}
```

## 8.4 电话、IM、资源协作与财务

路由：`tripcraft/api/routers/calls.py`  
服务：`tripcraft/services/call_service.py`  
服务：`tripcraft/services/supplier_service.py`  
服务：`tripcraft/services/finance_service.py`  
语音：`tripcraft/voice/`

功能：

- 发起客户首呼
- 实时语音会话
- 文字模拟通话
- 通话记录
- 实时转写
- 角色人设
- 语言/音色
- IM 会话列表
- 联系人
- 添加联系人
- 改备注
- 拉群
- 邀请成员
- 客户/地接/酒店/车队/导游群聊
- 资源方自动回应
- 资源报价进入成本台账
- 财务损失定责
- 结账留档

主要接口：

```text
POST /practice/orders/{order_id}/call
GET  /practice/call/{sid}
POST /practice/call/{sid}/messages
POST /practice/call/{sid}/end
POST /practice/im/sessions/{sid}/messages
GET  /practice/im/sessions
GET  /practice/im/contacts
PATCH /practice/im/contacts/{contact_id}
POST /practice/im/contacts
POST /practice/im/sessions/{sid}/rename
POST /practice/im/sessions/{sid}/members
GET  /practice/orders/{order_id}/finance
POST /practice/orders/{order_id}/finance/entries/{entry_id}/decide
POST /practice/orders/{order_id}/finance/settle
POST /practice/im/sessions
```

## 8.5 交付物、方案与 PDF

路由：`tripcraft/api/routers/deliverables.py`  
服务：`tripcraft/services/deliverable_service.py`  
服务：`tripcraft/services/plan_service.py`  
服务：`tripcraft/services/pdf_service.py`

功能：

- 交付物规格
- 按订单列交付物
- 导入模板
- 草稿保存
- 文档预览
- 客户版/内部版
- 证据闸门
- 语义校验
- 提交并投递
- PDF 导出
- 文件上传与下载
- 行程方案版本
- 方案发送
- 客户阅读/反馈
- 客户确认
- 文档模板保存/删除

主要接口：

```text
GET  /deliverables/specs
GET  /practice/orders/{order_id}/deliverables
POST /practice/orders/{order_id}/deliverables/import-template
GET  /practice/orders/{order_id}/deliverables/{did}
POST /practice/orders/{order_id}/deliverables/{did}/preview
POST /practice/orders/{order_id}/deliverables/{did}/export.pdf
POST /practice/orders/{order_id}/deliverables/{did}
GET  /practice/orders/{order_id}/plans
POST /practice/orders/{order_id}/plans
PUT  /practice/orders/{order_id}/plans/{plan_id}
POST /practice/orders/{order_id}/plans/{plan_id}/send
POST /practice/orders/{order_id}/plans/{plan_id}/confirm
GET  /practice/doc-templates
POST /practice/doc-templates
DELETE /practice/doc-templates/{template_id}
POST /deliverables/files
GET  /deliverables/files/{file_id}
```

## 8.6 评分、证据与画像写回

路由：`tripcraft/api/routers/growth.py`  
服务：`tripcraft/services/evidence_verifier.py`  
服务：`tripcraft/services/source_registry.py`  
Agent：`tripcraft/agents/scorer.py`

功能：

- 从通话、IM、交付物收集证据
- 按 Rubric 评分
- M1-M5 判档
- 低置信度进入人工复核
- Claim/Evidence 溯源
- 官方来源注册和快照
- 写回能力画像
- 更新订单目标和覆盖状态
- 生成下一单难度建议

主要接口：

```text
POST /practice/orders/{order_id}/score
GET  /practice/orders/{order_id}/evidence
GET  /practice/orders/{order_id}/scores
GET  /practice/orders/{order_id}/reviews
POST /practice/orders/{order_id}/reviews/{sp}
POST /evidence/snapshots
GET  /evidence/snapshots/{snapshot_id}
POST /evidence/verify
GET  /diagnosis/next
GET  /feedback/candidates
```

## 8.7 标准案例与离线演示

路由：`tripcraft/api/routers/scenario.py`  
服务：`tripcraft/services/scenario_service.py`

功能：

- 标准案例目录
- 案例详情
- 演示状态
- 导入案例
- 重置案例
- 演示账号状态
- 订单演示状态
- 离线 provider
- Live provider
- 案例校准

主要接口：

```text
GET  /scenario/cases
GET  /scenario/cases/{case_id}
GET  /scenario/status
POST /scenario/cases/{case_id}/import
POST /scenario/cases/{case_id}/reset
GET  /scenario/account
GET  /scenario/orders/{order_id}/state
POST /scenario/provider/offline
POST /scenario/provider/live
POST /scenario/cases/{case_id}/calibrate
```

## 8.8 工具、MCP、校准与比赛接口

路由：`tripcraft/api/routers/platform.py`  
路由：`tripcraft/api/routers/competition.py`  
路由：`tripcraft/api/routers/runs.py`

功能：

- 校准数据与运行
- Agent 注册表
- MCP tools/list
- MCP tools/call
- Guard check
- 订单 Guard
- 天气
- 路线规划
- POI
- 地图
- 行程核验
- 汇率
- 资源方状态与询价
- 交付物生成工具
- Skill Graph
- Evidence Snapshot
- Diagnosis Next
- Feedback Candidates
- Run 状态机
- S2 会话

关键接口：

```text
GET  /calibration
GET  /calibration/samples
POST /calibration/run
GET  /orchestration/agents
POST /mcp
GET  /mcp/tools
POST /guard/check
POST /practice/orders/{order_id}/guard
GET  /tools/weather
GET  /tools/route
GET  /tools/poi/tips
GET  /tools/map
POST /tools/itinerary/check
GET  /tools/fx
GET  /tools/supplier/state
POST /tools/supplier/state
POST /tools/supplier
POST /tools/deliverable
GET  /skill-graph/summary
GET  /skill-graph/{skill_point_id}
GET  /overview
POST /runs
GET  /runs/{run_id}
POST /runs/{run_id}/advance
POST /runs/{run_id}/rollback
POST /runs/{run_id}/flags
POST /runs/{run_id}/deliverables
POST /s2/sessions
POST /s2/sessions/{sid}/messages
POST /s2/sessions/{sid}/finish
GET  /s2/sessions/{sid}
GET  /runs/debug/status
```

### 8.9 MCP 工具清单

文件：

```text
tripcraft/mcp/server.py
```

当前 MCP 工具：

- `weather.get`
- `route.plan`
- `itinerary.check`
- `fx.rates`
- `supplier.inquire`
- `deliverable.push`
- `guard.check`
- `director.emit`
- `order.status`
- `practice.coverage`
- `knowledge.lookup`

提供：

- HTTP JSON-RPC：`POST /mcp`
- tools/list
- tools/call

### 8.10 访问监控

文件：

```text
tripcraft/services/visit_monitor.py
```

功能：

- 读取 Cloudflare 真实客户端头
- 记录访问日志
- 后台异步做 IP 归属地查询
- 输出 `logs/visits.jsonl` 和 `logs/visits.log`
- 本地/内网地址默认忽略

---

## 9. 多智能体编排

目录：

```text
tripcraft/orchestration/
```

核心类：

- `Conductor`
- `AgentRegistry`
- `AgentTask`
- `Plan`
- `Blackboard`
- `AgentResult`

教学对话采用动态 Plan：

```text
teaching.router
  → teaching.retrieval
  → teaching.context
  → optional teaching.profile
  → teaching.teacher
```

评分、资源生成、供应商沟通、客户反馈等也共享 Agent 基础能力。

---

## 10. SQLite 数据层

文件：

```text
tripcraft/storage/db.py
```

默认库：

```text
tripcraft.sqlite
```

实际启动时由 launcher 指定为：

- `.dsh-run\normal\preview.sqlite`
- `.dsh-run\codex-review\preview.sqlite`

核心表：

- `users`
- `sessions`
- `profile_baseline`
- `profile_snapshot`
- `quiz_question`
- `profile`
- `ability`
- `thread`
- `thread_message`
- `asset`
- `quiz_attempt`
- `memory`
- `biz_order`
- `im_session`
- `contact`
- `supplier_quote`
- `im_message`
- `order_contact`
- `notice`
- `finance_entry`
- `doc_template`
- `plan_version`
- `order_settlement`
- `supplier_state`
- `order_evidence`
- `order_score`
- `call_session`
- `call_line`
- `order_target`
- `director_event`
- `deliverable_doc`
- `deliverable_draft`
- `deliverable_file`
- `order_action`
- `calibration_run`
- `incident`
- `order_customer`
- `customer_fact_event`
- `customer_feedback_turn`
- `source_snapshot`

视图：

- `conversation_turn`

---

## 11. 前端应用结构

### 11.1 应用壳

文件：

```text
frontend/src/App.vue
```

桌面端：

- 左侧栏
- 顶部页标题
- 连接状态
- 用户菜单
- 主内容区
- 训练进度悬浮按钮

移动端：

- 顶部品牌与页标题
- 连接状态
- 用户头像
- 底部主导航
- 安全区适配

移动端底部主导航固定为：

```text
首页 / 学习 / 实战 / 我的
```

“消息”和“聊天”不再是一级导航，而是“实战”内部的功能。

### 11.2 路由

文件：

```text
frontend/src/router/index.ts
```

公开路由：

- `/`：首页、登录/注册

需要登录：

- `/learn`
- `/learn/thread/:sp`
- `/learn/bridge/:code`
- `/practice`
- `/practice/messages`
- `/practice/im`
- `/practice/orders/:id`
- `/practice/orders/:id/call`
- `/practice/orders/:id/score`
- `/practice/orders/:id/deliverables`
- `/practice/orders/:id/finance`
- `/practice/orders/:id/plan/new`
- `/profile`
- `/profile/quiz`
- `/toolbox`
- `/system`
- `/demo`
- `/dashboard`

### 11.3 移动端实战结构

`/practice` 当前是实战中心，移动端内部有三个 Tab：

- 订单
- 消息/抢单
- 聊天

查询参数：

```text
/practice?tab=messages
/practice?tab=chat
```

抢单成功后自动回订单页：

```text
/practice?grabbed={order_id}
```

### 11.4 前端状态

`frontend/src/stores/user.ts`：

- token
- 会话恢复
- 当前用户
- 登录
- 注册
- 退出
- 更新资料
- 数据口径 real/demo

`frontend/src/stores/practice.ts`：

- 当前订单
- 实战页共享状态

### 11.5 API 客户端

文件：

```text
frontend/src/api/client.ts
```

```ts
axios.create({ baseURL: '/api', timeout: 300000 })
```

本地开发和当前 Cloudflare Tunnel 都通过 Vite `/api` 代理到 FastAPI。

### 11.6 Electron

文件：

```text
frontend/electron/main.cjs
frontend/electron/preload.cjs
```

功能：

- 单实例窗口
- 后端/前端服务复用
- 服务未就绪时显示错误页
- 独立 userData
- 窗口图标
- 复用模式不关闭外部服务

---

## 12. 前端页面功能

### 首页

文件：`frontend/src/views/HomeView.vue`

- 登录
- 注册
- 成长路径
- 开始测评
- 登录后进入训练

### 学习地图

文件：`frontend/src/views/learn/LearnMapView.vue`

- 技能树模式
- 路线模式
- 路线生成
- 路线管家
- 技能点弹卡
- 掌握度展示
- 事件解锁状态

### 教学对话

文件：`frontend/src/views/learn/ThreadView.vue`

- AI 教师聊天
- 快捷动作
- 讲义/指南/报告/错题本
- 做题
- 题目卡
- 作答
- 得分/解析
- 来源溯源
- 翻译
- 掌握度
- 难度曲线
- 个性资源

### 文化桥

文件：`frontend/src/views/learn/CultureBridgeView.vue`

- 十大客源国文化桥
- 中外对比
- 使用建议
- 常见误区

### 实战中心

文件：`frontend/src/views/practice/PracticeView.vue`

移动端内部：

- 订单列表
- 消息/抢单
- 聊天

订单列表：

- 进行中/已完成/已取消
- 订单阶段进度
- 评分复盘
- 进入订单

### 消息中心/抢单

文件：`frontend/src/views/vbooking/MessagesView.vue`

- 重要通知
- 待接单通知
- 订单通知
- 产品/财务/营销/其他通知
- 客源语言筛选
- 刷新派单
- 抢单卡片
- 倒计时
- 竞争人数
- 抢单

### 聊天

文件：`frontend/src/views/practice/ImView.vue`

- 会话列表
- 通讯录
- 单聊/群聊
- 客户/地接/酒店/车队/导游
- 添加联系人
- 改备注
- 拉群
- 邀请成员
- 文本消息
- 文件
- 交付物卡片
- 语音输入

### 订单详情

文件：`frontend/src/views/vbooking/OrderDetailView.vue`

- 订单基本信息
- 客户
- 目的地
- 首呼/方案倒计时
- 六阶段/步骤
- 当前唯一下一步
- 文件夹入口
- 评分复盘入口
- 订单状态
- 方案版本
- 后续联系记录

### 电话训练

文件：`frontend/src/views/practice/CallView.vue`

- 语音模式
- 文字模式
- 拨打
- 麦克风
- 挂断
- 实时转写
- 通话计时

### 交付物工作台

文件：`frontend/src/views/practice/DeliverableWorkbenchView.vue`

- 文件选择
- 模板导入
- 分节表单
- 动态明细行
- 实时预览
- 客户版/内部版
- 必填校验
- Guard
- 语义核验
- 提交并投递
- PDF
- 下一步

### 行程方案

文件：`frontend/src/views/vbooking/PlanNewView.vue`

- 基本信息
- 逐日行程
- 六要素
- 方案小节
- 模板
- 交付要件
- 保存草稿
- 导入模板
- 发送
- PDF
- 客户反馈

### 评分复盘

文件：`frontend/src/views/practice/OrderScoreView.vue`

- 本单状态
- 覆盖校验
- 未覆盖项
- 人工复核
- 分维度结果
- 证据
- 下一单难度
- 写回画像

### 成本与结算

文件：`frontend/src/views/practice/FinanceView.vue`

- 收入
- 成本
- 损失
- 毛利
- 成本明细
- 赔付台账
- 责任归属
- 结账留档
- 完成条件

### 学情画像

文件：`frontend/src/views/ProfileView.vue`

- 学习/实战掌握度
- 技能点统计
- 雷达图
- 历史快照
- 趋势
- 画像记忆
- 长板
- 学习建议

### 初始画像测评

文件：`frontend/src/views/ProfileQuizView.vue`

- 12 题测评
- 进度
- 上一题/下一题
- 分析动画
- 初始画像
- 当前能力对比
- 分数趋势
- 维度点评
- 学习建议
- 学习路线入口

### 工具台

文件：`frontend/src/views/ToolboxView.vue`

- 路线规划
- 天气
- 汇率
- 行程折返核验

### 数据看板

文件：`frontend/src/views/dashboard/DashboardView.vue`

- 团队视角
- 运营视角
- KPI
- 趋势
- 漏斗
- 热力图
- 留存

### 标准案例

文件：`frontend/src/views/DemoCaseView.vue`

- 演示状态
- 案例目录
- 导入
- 重置
- 真实依赖状态
- 开发诊断

---

## 13. 前端设计系统

主题变量：

```text
frontend/src/styles/tokens.scss
```

当前主色：

- 深蓝：`#133450`
- 深色：`#0d283f`
- 浅蓝：`#3f6e91`
- 浅蓝底：`#e7eef4`

品牌图标：

```text
frontend/src/assets/logo-sinan-like.png
frontend/src/assets/logo-sinan-like.webp
frontend/src/assets/app.ico
```

移动端要求：

- 最大内容宽度跟随视口
- 单列布局
- 16px 左右内容边距
- 主要按钮和输入框不小于约 42–44px
- 底部导航含安全区
- 320px 与 390px 已验证无页面级横向滚动

---

## 14. 当前已验证项目

### 内容替换与仓库

- [x] “旅鸢”已替换为“司南礼客”
- [x] 文本与文件名中无“旅鸢”残留
- [x] GitHub 仓库：`https://github.com/66zhongxuegao/sinan-like`
- [x] 仓库为 public

### 前端

- [x] 深蓝主题
- [x] 新品牌图标
- [x] 桌面端应用壳
- [x] 移动端 4 Tab
- [x] 实战内“订单/消息/聊天”
- [x] 320/390 宽度无页面级横向溢出
- [x] `npm run build` 成功

### 后端

- [x] FastAPI 服务正常
- [x] AI 教师真实模型调用恢复
- [x] `/threads/{sp}/messages` 已验证 200
- [x] 本地密钥已恢复到 `local.env`

### 部署

- [x] Cloudflare Named Tunnel
- [x] `sinanlike.com` HTTPS 200
- [x] `/api/docs` 200
- [x] 线上移动端已验证

---

## 15. 已知问题与技术债

- [ ] 公网当前依赖本机运行，电脑关机后离线
- [ ] Cloudflare 源站使用 Vite 开发入口，不是长期生产级 Web Server
- [ ] `local.env` 不进入 Git，换机必须手动恢复
- [ ] 启动脚本包含本机 Python/Node 绝对路径
- [ ] 题目难度主要靠 Prompt 控制，缺少结构化 DifficultySpec 与出题校验器
- [ ] `DifficultyLevel` 只定义 L1-L4，但教学题已使用 L1-L5
- [ ] 小部分旧路由/旧页面仍在目录中但不在当前主路由
- [ ] `PracticeService`、`SupplierService`、`DeliverableWorkbenchView`、`ImView` 等文件较大
- [ ] 前端主包存在 >1MB 大 chunk
- [ ] 当前没有完整自动化前端 E2E 回归套件
- [ ] 公网部署流量日志、打点统计仍需单独审视

---

## 16. 下一个 Agent 的推荐阅读顺序

1. `README.md`
2. `docs/HANDOFF.md`（本文）
3. `docs/CLOUDFLARE_DEPLOYMENT.md`
4. `tripcraft/api/app.py`
5. `tripcraft/api/context.py`
6. `tripcraft/api/routers/__init__.py`
7. `frontend/src/router/index.ts`
8. `frontend/src/App.vue`
9. 目标功能对应的 router/service/view

---

## 17. 修改前检查清单

```powershell
cd D:\司南礼客项目
git status --short --branch
git log -5 --oneline
```

确认：

- 当前是否有人正在改同一文件
- 后端实例是否在运行
- 前端端口是否被占用
- 是否误碰 `.dsh-run` 用户数据
- 是否把 `local.env` 加入 Git
- 是否保持用户身份和订单归属校验

---

## 18. 修改后验收清单

```powershell
cd D:\司南礼客项目
python -m compileall -q tripcraft tests scripts
pytest -q

cd .\frontend
npm run build
```

浏览器验收：

```text
http://127.0.0.1:25190/#/
http://127.0.0.1:25190/api/docs
```

关键人工流程：

1. 注册/登录
2. 初始测评
3. 学习路线
4. AI 教师提问
5. AI 出题并作答
6. 生成派单
7. 消息中心抢单
8. 订单详情下一步
9. 电话/IM
10. 交付物保存与提交
11. 评分复盘
12. 画像更新

移动端重点检查：

- 底部导航四项
- 实战内部三项
- 抢单按钮
- 聊天窗口
- 输入框键盘弹起
- 320/390/430 宽度

---

## 19. 变更记录

### 2026-11-17

- 新增本交接文档
- 当前移动端主导航为：首页、学习、实战、我的
- 消息/抢单/聊天收进“实战”
- 已完成 AI 教师缺失密钥修复
- `sinanlike.com` 通过 Cloudflare Tunnel 上线
