# frontend/src/demo/ —— 标准案例（演示数据）前端模块

页面入口：`frontend/src/views/DemoCaseView.vue`（路由 `/demo`，已由 identity 域注册在 `router/index.ts`）。
本模块**只调真实后端接口**，不做任何响应改写、不静默跳过失败。

## 目录（就这三个文件）

| 文件 | 职责 |
| --- | --- |
| `http.ts` | 唯一出网口。`DemoHttpError` 统一承载 HTTP/网络失败；**没有** axios 拦截器；token 与 identity 域共用 `localStorage: tc-token` |
| `scenarioApi.ts` | `/scenario/*` 与既有业务接口的类型化封装（字段名逐字对齐后端）；导出 `DEMO_ACCOUNT`、`modeText()` |
| `guide.ts` | 由后端 `stage_plan` 组装逐步说明；`gateRows()` 原样透出后端 `gate.checks`；只登记「契约阶段 id → 入口页面」，未登记 id 显式报错（不静默兜底） |

### 阶段 id 口径（唯一来源：`tripcraft/contracts/stages.py` v1）

`STAGE_ENTRY` 的 key 只能是这六个，前端不写第二套阶段定义：

```
pre1_requirement  pre2_plan  pre3_quote  pre4_notice  on_trip  post_trip
```

后端 `stage_plan` 出现这六个之外的 id 时，`buildGuide()` 返回 `missingStageIds`，
页面显示可见错误「阶段入口未登记，已停住并有步骤未展示」并列出 id，不会用默认文案冒充。
（`guide.ts` 里没有旧草案的 `in1_execute / in2_incident / post1_settle / post2_review`。）

### 面向用户 vs 开发者文案

- 正文只说人话：「演示数据 · 确定性离线」「实时模型：已配置，未核验可用 / 已核验可用 / 未配置」
  「真实语音：未验收（缺少语音密钥，且需浏览器麦克风实测）」。
- `llm_key_present / llm_connectivity_verified / llm_not_verified_reason / voice_* / scope /
  scenario_mode_env / auth_mode / db_path / provider_*` 全部收进两处
  `<details>`「开发者 / 诊断详情（默认收起）」，正文不出现。
- 窄屏：步骤清单整体包在 `<details>` 里（可收起）+ `.tbl-scroll{overflow-x:auto}` 横向滚动，
  表格不会撑破布局。

## 旧 demo 反例清理记录（本次删除）

| 已删除 | 反例性质 |
| --- | --- |
| `fixtures.ts` | 注册 `client.interceptors.response.use(...)`，把后端响应**改写**成写死的剧本（伪造链路），并用 `try{}catch{}` + `console.warn` 吞掉改写异常 |
| `beats.ts` | 自动播放剧本：每一步 `d.clickText([...], { optional: true })`，找不到元素只打印警告就继续下一步 |
| `driver.ts` | 配合上面的 optional 静默跳过（`if (!opt?.optional) console.warn(...)`），并在产品页面上模拟鼠标点击 |
| `store.ts` / `DemoBar.vue` / `DemoCursor.vue` | 旧演示账户自动播放的 UI 与 store（含假鼠标指针）；identity 域已把 `App.vue` 里对它们的引用整体删除，本模块不再需要兼容层 |

现在 `frontend/src/` 里：

```powershell
# 无 axios 拦截器（demo 模块 0 处；stores/user.ts 的拦截器属 identity 域，只加认证头并跳登录，不改写响应）
Select-String -Path (Get-ChildItem frontend/src -Recurse -Include *.ts,*.vue).FullName -Pattern 'interceptors'
# 无 optional 静默跳过（命中项只在 guide.ts 的注释里说明旧反例）
Select-String -Path (Get-ChildItem frontend/src -Recurse -Include *.ts,*.vue).FullName -Pattern 'optional\s*:'
# 三个反例文件均已不存在
Test-Path frontend/src/demo/fixtures.ts, frontend/src/demo/beats.ts, frontend/src/demo/driver.ts
```

## 页面读的后端契约（都以页面实际发出的请求为准）

| 方法与路径 | 页面用途 | 关键字段 |
| --- | --- | --- |
| `GET /scenario/cases` | 案例目录 + 模式状态 | `cases[]`、`digest`、`stage_plan[].substeps[]`、`status.mode`、`status.deps.*` |
| `GET /scenario/status?probe=true` | 「真实连通核验」按钮 | `deps.llm_connectivity_verified` / `llm_not_verified_reason` |
| `GET /scenario/account?case_id=` | 账号计数（重置前后对比） | `scenario_orders`、`scenario_order_ids` 等 |
| `POST /scenario/cases/{id}/import` | 一键导入（真实落单） | `order_id`、`scenario_marker`、`resources_injected`、`next_action` |
| `GET /scenario/orders/{id}/state` | 每步服务端状态 | `gate.checks[]`、`stage_id`、`internal_step`、`scores` |
| `POST /scenario/cases/{id}/reset` | 一键重置（只清当前账号） | `scope`、`orders_targeted`、`deleted`、`before/after` |
| `POST /scenario/provider/offline|live` | 实例模式开关；非演示实例后端返回 **409**，页面原样展示 | `detail` |
| `GET /practice/messages` | 既有业务接口（操作指路） | `groups` |

模式口径（`modeText()`）：`offline` = 确定性演示数据（不是实时模型）；`live` = 实时模型链路，
其可用性由 `deps.*_connectivity_verified` 实测决定，页面**不把「配置了 key」当成「连通可用」**。

## 复跑验收（两条命令）

```powershell
# ① 接口契约核对：进程内起真实 app（随机端口）+ 真实 HTTP，逐字段核对页面用到的响应字段
python -X utf8 scripts/acceptance_demo_case_ui.py
#    证据：output/acceptance/evidence/scenario-demo-ui/api-contract.json（135 项全 OK）

# ② 真实前端模块端到端：类型剥离后直接跑 src/demo/*.ts，node:http 适配器真实出网到 127.0.0.1:18010
#    （首次需要把 frontend/node_modules 以 junction 挂到 demo-modules-tmp 下）
node output/acceptance/logs/demo-modules-e2e.cjs
#    证据：output/acceptance/evidence/scenario-demo-ui/modules-e2e.json（40 项全 OK）
```

`demo-modules-e2e.cjs` 覆盖：未登录 401 → 真实登录 → 目录/模式/deps → 逐步说明（24 步，
含「STAGE_ENTRY 的 key 就是契约六阶段」与「未登记阶段 id → 显式报错」两条口径断言）→
导入回执 → 订单服务端状态 → 账号计数 → 消息接口 → 重置回执（命中并清零）→
未知案例 400 / 坏 token 401 / 非演示实例 409 三条失败路径。

## 已知限制（未做假的替代）

- `npm run build` 在本机沙箱里**进不到源码分析阶段**就失败：Vite 加载自身配置时 esbuild 需要
  以管道 stdio 起服务进程，被沙箱拒绝（`Error: spawn EPERM`，`esbuild/lib/main.js:ensureServiceIsRunning`）。
  该失败发生在 `loadConfigFromFile(vite.config.ts)` 阶段，与 `src/**` 无关；同一沙箱下
  `npx vue-tsc --noEmit`（`npm run build` 的第一个环节）退出码 0。
- 真实浏览器点击路径**未能在本沙箱完成**：headless Edge 在这台机器上起不来
  （crashpad/网络沙箱被拒 + CDP 端口不监听），`vite dev` 同样受上面的 EPERM 阻塞。
  因此「页面渲染 + 按钮点击」的替代证据是：`vue-tsc` 通过（含 `DemoCaseView.vue` 模板类型检查）
  + 真实模块端到端（`modules-e2e.json`）。在有图形会话的机器上可用
  `npm run dev` 打开 `#/demo` 复核。
- `gate.checks` 是中文标签、`stage_plan` 的交付物是英文 id，两者无可靠对应关系，
  所以逐步说明里不显示「第几步 = 哪条 gate check」，服务端判定统一在订单状态表里原样列出。
