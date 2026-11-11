<template>
  <div class="demo-case">
    <!-- ① 页面显著标识：标准案例 / 演示数据 + 当前模式（面向用户的话，技术字段折叠在下面） -->
    <section class="banner" :class="modeKey">
      <div class="banner-main">
        <span class="mark">标准案例/演示数据</span>
        <span class="sep" />
        <span class="mode" :class="modeKey">
          <i class="dot" />
          {{ modeLabel }}
        </span>
      </div>
      <div class="banner-sub">{{ modeNote }}</div>
      <div v-if="status" class="banner-deps">
        <span class="dep" :class="liveModelClass">实时模型：{{ liveModelText }}</span>
        <span class="dep" :class="voiceStatusClass">真实语音：{{ voiceStatusText }}</span>
        <span class="dep">案例资料校验码 {{ shortDigest }}</span>
      </div>

      <!-- 技术细节默认收起：面向用户的正文不出现实现术语 -->
      <details class="dev">
        <summary>开发者 / 诊断详情（默认收起）</summary>
        <div v-if="status" class="dev-body">
          <div class="kv mono">mode = {{ status.mode }} · scope = {{ status.scope || '—' }}
            · demo_instance = {{ (status.demo_instance as any)?.enabled ? 'true' : 'false' }}
            · scenario_mode_env = {{ status.scenario_mode_env || '(unset)' }}</div>
          <div class="kv mono">llm_key_present = {{ status.deps.llm_key_present }}
            · llm_key_source = {{ status.deps.llm_key_source || '—' }}
            · llm_connectivity_verified = {{ status.deps.llm_connectivity_verified }}
            · llm_not_verified_reason = {{ status.deps.llm_not_verified_reason || '—' }}</div>
          <div class="kv mono">voice_key_present = {{ status.deps.voice_key_present }}
            · voice_key_source = {{ status.deps.voice_key_source || '—' }}
            · voice_connectivity_verified = {{ status.deps.voice_connectivity_verified }}
            · voice_not_verified_reason = {{ status.deps.voice_not_verified_reason || '—' }}</div>
          <div class="kv mono">auth_mode = {{ status.deps.auth_mode }} · DB = {{ status.deps.db_path }}</div>
          <div v-if="status.switch_policy" class="kv">{{ status.switch_policy }}</div>
          <ul v-if="status.honest_notes?.length" class="honest">
            <li v-for="(n, i) in status.honest_notes" :key="i">{{ n }}</li>
          </ul>
        </div>
        <div v-else class="kv">尚未取到状态（目录接口失败时不会显示占位数据）。</div>
      </details>
    </section>

    <!-- ② 任何一步失败：原样显示后端错误并停住，不继续往下走 -->
    <section v-if="loadError" class="card err-card">
      <div class="err-title">加载失败，页面已停住（不做静默兜底）</div>
      <pre class="err-body">{{ loadError }}</pre>
      <div class="err-actions">
        <button class="tc-btn ghost" :disabled="loading" @click="reload">
          {{ loading ? '重试中…' : '重新加载' }}
        </button>
        <span class="err-hint">/scenario/* 需要登录：未登录会返回 401「未登录或会话已失效」。</span>
      </div>
    </section>

    <template v-else>
      <!-- ③ 会话（真实会话由 identity 域 store 持有；本页只展示，不另立登录态） -->
      <section class="card sec">
        <div class="sec-title title-rule"><span>当前会话</span></div>
        <div v-if="user.profile" class="row">
          <span class="kv"><b>{{ user.profile.display_name || user.profile.username }}</b></span>
          <span class="kv" :class="user.isDemo ? 'ok' : 'bad'">
            {{ user.isDemo ? '标准案例演示账号' : '非演示账号（kind=' + (user.profile.kind || 'real') + '）' }}
          </span>
          <span class="kv">{{ user.dataScopeLabel }}</span>
          <router-link class="tc-btn ghost" to="/login">切换账号（/login）</router-link>
        </div>
        <div v-else class="login">
          <p class="hint">
            当前没有服务端会话：标准案例接口会返回 401（后端强制认证，未登录不放行）。
            请到登录页用标准案例演示账号登录（本页不替用户注册或伪造身份）。
          </p>
          <div class="row">
            <router-link class="tc-btn" to="/login">去登录页</router-link>
            <button class="tc-btn ghost" :disabled="loading" @click="reload">重新检查会话</button>
          </div>
        </div>
        <p v-if="user.sessionError" class="inline-err">会话恢复失败：{{ user.sessionError }}</p>
        <p v-if="actionError" class="inline-err">{{ actionError }}</p>
        <details class="dev">
          <summary>开发者 / 诊断详情</summary>
          <div class="row">
            <span class="kv">user_id <b class="mono">{{ user.profile?.user_id || '（无会话）' }}</b></span>
            <span class="kv">演示账号用户名：<b class="mono">{{ DEMO_ACCOUNT.username }}</b>（{{ DEMO_ACCOUNT.label }}）</span>
            <span class="kv">账号口径：<code>data/scenario/standard_case.json · isolation</code></span>
          </div>
        </details>
      </section>

      <!-- ④ 案例概览：普通视图只留客人/日期/人数/预算/目的地；标识与固定资料进开发详情 -->
      <section class="card sec">
        <div class="sec-title title-rule"><span>标准案例（演示数据）</span></div>
        <details class="dev">
          <summary>开发者 / 诊断详情</summary>
          <div class="row">
            <button class="tc-btn ghost" :disabled="loading" @click="reload">重新拉取案例目录</button>
            <span v-if="loadedAt" class="kv">最近一次成功：{{ loadedAt }}</span>
            <span v-if="catalog" class="kv">目录 digest <b class="mono">{{ shortDigest }}</b></span>
          </div>
        </details>
        <div v-if="catalog && !catalog.cases.length" class="inline-err">
          目录里没有案例：后端返回 cases=[]，页面不会用本地写死的案例冒充。
        </div>
        <div v-for="c in cases" :key="c.case_id" class="case">
          <div class="case-hd">
            <span class="case-title">{{ c.title }}</span>
            <span class="tag" :class="c.demo_data ? 'tag-demo' : 'tag-real'">
              {{ c.demo_data ? (c.demo_label || '标准案例/演示数据') : '真实数据' }}
            </span>
          </div>
          <div class="case-grid">
            <div><span class="g-k">客人</span><span class="g-v">{{ c.customer }}</span></div>
            <div><span class="g-k">目的地 / 天数</span><span class="g-v">{{ c.destination }} · {{ c.days }} 天</span></div>
            <div><span class="g-k">日期</span><span class="g-v">{{ dateText(c.dates) }}</span></div>
            <div><span class="g-k">人数</span><span class="g-v">{{ partyText(c.party) }}</span></div>
            <div><span class="g-k">预算</span><span class="g-v">{{ recordText(c.budget) }}</span></div>
          </div>

          <details class="dev">
            <summary>开发者 / 诊断详情：案例标识与固定资料</summary>
            <div class="dev-body">
              <div class="row">
                <span class="kv">case_id <b class="mono">{{ c.case_id }}</b></span>
                <span class="kv">演示账号 <b class="mono">{{ c.demo_account }}</b></span>
                <span class="kv">客源 / 语言 {{ c.source_market }} · {{ c.language }}</span>
                <span class="kv">酒店 {{ recordText(c.hotel) }}</span>
                <span class="kv">用车 {{ recordText(c.transport) }}</span>
                <span class="kv">阶段 id <b class="mono">{{ c.stage_ids.join(' → ') }}</b></span>
              </div>
              <div class="case-sub">固定资源约束（导入时由服务端注入 {{ c.resource_constraints.length }} 条）</div>
              <div class="tbl-scroll">
                <table class="tbl">
                  <thead><tr><th>资源方</th><th>库存 / 档期</th><th>价格系数</th><th>说明</th></tr></thead>
                  <tbody>
                    <tr v-for="(r, i) in c.resource_constraints" :key="i">
                      <td>{{ r.kind }}</td><td>{{ r.availability || '—' }}</td>
                      <td>{{ r.price_factor ?? '—' }}</td><td>{{ r.note || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="case-sub">实时依赖（如实标注，未验收就写未验收）</div>
              <div class="tbl-scroll">
                <table class="tbl">
                  <thead><tr><th>依赖</th><th>用途</th><th>离线替代</th><th>验收状态</th></tr></thead>
                  <tbody>
                    <tr v-for="(d, key) in c.realtime_dependencies" :key="key">
                      <td class="mono">{{ key }}</td>
                      <td>{{ (d.needed_for || []).join('、') }}</td>
                      <td>{{ d.offline_substitute || '无（不做离线替代）' }}</td>
                      <td>{{ d.verification_status || '未标注' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </details>
        </div>
      </section>

      <!-- ⑤ 开始 / 继续 / 重置（真实接口；回执只留一句话，明细收进开发详情） -->
      <section class="card sec">
        <div class="sec-title title-rule"><span>开始 / 继续 / 重置</span></div>
        <div class="row">
          <label class="fld"><span>案例</span>
            <select v-model="selectedCaseId" class="ipt">
              <option v-for="c in cases" :key="c.case_id" :value="c.case_id">{{ c.title }}</option>
            </select>
          </label>
          <button class="tc-btn" :disabled="!selectedCaseId || busy" @click="doImport">
            {{ imp.status === 'running' ? '导入中…' : '导入标准案例（开始）' }}
          </button>
          <router-link v-if="continueOrderId" class="tc-btn ghost"
                       :to="`/practice/orders/${continueOrderId}`">继续（打开订单）</router-link>
          <label class="chk"><input v-model="includeProfile" type="checkbox" /> 重置时连同学习/画像数据</label>
          <button class="tc-btn ghost" :disabled="!selectedCaseId || busy" @click="doReset">
            {{ rst.status === 'running' ? '重置中…' : '重置标准案例' }}
          </button>
        </div>

        <p v-if="imp.status === 'ok' && imp.receipt" class="kv ok-line">
          标准案例已导入：订单号 {{ imp.receipt.order_id }}。
          <span v-if="imp.receipt.missing_fields.length">首呼时记得补齐 {{ imp.receipt.missing_fields.length }} 项待确认信息。</span>
        </p>
        <pre v-else-if="imp.status === 'fail'" class="op-err">{{ imp.error }}</pre>
        <span v-else-if="imp.status === 'running'" class="kv">导入中，请稍候…</span>

        <p v-if="rst.status === 'ok' && rst.receipt" class="kv ok-line">
          已重置当前账号的标准案例数据（命中 {{ rst.receipt.orders_targeted.length }} 单，只影响本账号）。
        </p>
        <pre v-else-if="rst.status === 'fail'" class="op-err">{{ rst.error }}</pre>
        <span v-else-if="rst.status === 'running'" class="kv">重置中，请稍候…</span>

        <p v-if="imp.status === 'idle' && rst.status === 'idle'" class="hint">
          按钮只调用真实后端，不在本地造单、不写假进度；重置只删当前登录账号的数据。
        </p>

        <details class="dev">
          <summary>开发者 / 诊断详情：导入与重置回执</summary>
          <div class="dev-body">
            <div class="op" :class="imp.status">
              <div class="op-hd"><b>导入回执</b>
                <span v-if="imp.status === 'running'" class="op-tag run">提交中…</span>
                <span v-else-if="imp.status === 'ok'" class="op-tag ok">成功</span>
                <span v-else-if="imp.status === 'fail'" class="op-tag bad">失败</span>
                <span v-else class="op-tag idle">未提交</span>
                <span v-if="imp.at" class="op-at">{{ imp.at }}</span>
              </div>
              <div v-if="imp.status === 'ok' && imp.receipt" class="op-body">
                <div class="row">
                  <span class="kv">order_id <b class="mono">{{ imp.receipt.order_id }}</b></span>
                  <span class="kv">stage_index {{ imp.receipt.stage_index }}</span>
                  <span class="kv">标识 {{ imp.receipt.demo_label }}</span>
                  <span class="kv">demo_data {{ imp.receipt.demo_data ? 'true' : 'false' }}</span>
                  <span class="kv">归属 user_id {{ imp.receipt.user_id }}</span>
                </div>
                <div class="kv">scenario_marker：{{ JSON.stringify(imp.receipt.scenario_marker) }}</div>
                <div class="kv">注入资源：{{ injectedKinds || '无' }}</div>
                <div class="kv">缺失字段：{{ imp.receipt.missing_fields.length ? imp.receipt.missing_fields.join('、') : '无' }}</div>
                <div class="kv">服务端下一步提示：{{ imp.receipt.next_action }}</div>
              </div>
              <div v-else-if="imp.status === 'idle'" class="op-hint">尚未提交。</div>
            </div>
            <div class="op" :class="rst.status">
              <div class="op-hd"><b>重置回执</b>
                <span v-if="rst.status === 'running'" class="op-tag run">提交中…</span>
                <span v-else-if="rst.status === 'ok'" class="op-tag ok">成功</span>
                <span v-else-if="rst.status === 'fail'" class="op-tag bad">失败</span>
                <span v-else class="op-tag idle">未提交</span>
                <span v-if="rst.at" class="op-at">{{ rst.at }}</span>
              </div>
              <div v-if="rst.status === 'ok' && rst.receipt" class="op-body">
                <div class="kv">重置范围：{{ rst.receipt.scope }}</div>
                <div class="kv">命中的订单：{{ rst.receipt.orders_targeted.join('、') || '（无：本账号没有该案例订单）' }}</div>
                <div class="kv">删除清单：{{ recordText(rst.receipt.deleted) }}</div>
                <div class="kv">计数 before：{{ countsText(rst.receipt.before) }}</div>
                <div class="kv">计数 after：{{ countsText(rst.receipt.after) }}</div>
                <div class="kv">{{ rst.receipt.isolation_note }}</div>
              </div>
              <div v-else-if="rst.status === 'idle'" class="op-hint">尚未提交。</div>
            </div>
            <div class="row">
              <button class="tc-btn ghost" :disabled="loading" @click="refreshAccount">刷新账号计数</button>
              <span v-if="account" class="kv">
                订单 {{ account.orders }}（标准案例 {{ account.scenario_orders }}）· 证据 {{ account.evidence }} ·
                交付物 {{ account.deliverables }} · 画像行 {{ account.ability_rows }} · 线程 {{ account.threads }} ·
                通知 {{ account.notices }}
              </span>
              <span v-if="accountError" class="inline-err">{{ accountError }}</span>
            </div>
          </div>
        </details>
      </section>

      <!-- ⑥ 六阶段进度与操作指引（状态只用后端真实数据：stage_plan + order.stage_id，不写假进度） -->
      <section v-if="catalog" class="card sec">
        <div class="sec-title title-rule"><span>六阶段进度与操作指引</span></div>
        <p v-if="!order" class="hint">
          还没有选中案例订单：先在上一节「导入标准案例（开始）」，或点「继续（打开订单）」。
        </p>
        <div class="tbl-scroll">
          <table class="tbl stage">
            <thead><tr>
              <th style="width:180px">阶段</th><th>这一阶段要做什么</th>
              <th style="width:120px">当前状态</th><th style="width:96px">入口</th>
            </tr></thead>
            <tbody>
              <tr v-for="s in stageRows" :key="s.id" :class="{ now: s.state === '进行中' }">
                <td><b>{{ s.name }}</b></td>
                <td>{{ s.focus }}</td>
                <td><span class="tag" :class="s.state === '已完成' ? 'tag-real' : 'tag-demo'">{{ s.state }}</span></td>
                <td><router-link class="go" :to="s.route">去做</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="order" class="kv">
          当前进行到：<b>{{ order.stage_name }}</b>（后面的阶段还没开始；每一步明细在下方折叠区里）。
        </p>
        <p v-else class="hint">六个阶段都会显示在这里；导入后开始第一个阶段。</p>

        <!-- 后端出现契约里没有的阶段 id：显式报错，不静默兜底 -->
        <div v-if="guideMissingStages.length" class="stage-error">
          <b>阶段入口未登记，已停住并有阶段未展示。</b>
          后端返回了契约里没有的阶段 id，页面不会用默认入口文案冒充；请对照
          <code>tripcraft/contracts/stages.py</code> 的六个阶段修复映射。
        </div>

        <details class="dev">
          <summary>操作步骤明细（{{ guide.length }} 步，来自后端 stage_plan）</summary>
          <p class="hint">
            清单由 <code>GET /scenario/cases</code> 的 stage_plan 生成；每步的服务端判定由
            <code>GET /scenario/orders/{'{id}'}/state</code> 的 gate.checks 原样透出。
            本页不做自动点击、不做模拟：点「去这一步」进入真实产品页面操作。
          </p>
          <div class="tbl-scroll">
            <table class="tbl guide">
              <thead><tr>
                <th style="width:64px">步骤</th><th>做什么</th><th>在哪个页面</th><th>服务端取证接口</th><th style="width:96px">入口</th>
              </tr></thead>
              <tbody>
                <tr v-for="g in guide" :key="g.id">
                  <td class="mono">{{ g.step }}</td>
                  <td>
                    <div class="g-title">{{ g.title }}</div>
                    <div class="g-hint">{{ g.hint }}</div>
                    <div v-if="g.deliverable" class="g-deliv">交付物：{{ g.deliverable }}</div>
                  </td>
                  <td>{{ g.page }}</td>
                  <td class="mono small">{{ g.server }}</td>
                  <td><router-link class="go" :to="g.route">去这一步</router-link></td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>

        <details class="dev block-toggle">
          <summary>开发者 / 诊断详情：每步服务端状态</summary>
          <div class="dev-body">
            <div class="row">
              <label class="fld"><span>订单</span>
                <select v-model="trackedOrderId" class="ipt">
                  <option value="" disabled hidden>请选择订单</option>
                  <option v-for="oid in knownOrderIds" :key="oid" :value="oid">{{ oid }}</option>
                </select>
              </label>
              <button class="tc-btn ghost" :disabled="!trackedOrderId || busy" @click="refreshOrderState">
                刷新订单状态
              </button>
              <span v-if="orderAt" class="kv">最近一次成功：{{ orderAt }}</span>
            </div>
            <p v-if="orderError" class="inline-err">订单状态读取失败：{{ orderError }}</p>
            <div v-if="order" class="op-body">
              <div class="row">
                <span class="kv">status {{ order.status }}</span>
                <span class="kv">阶段 {{ order.stage_index }} · {{ order.stage_name }}</span>
                <span class="kv">阶段 id {{ order.stage_id }}</span>
                <span class="kv">内部步骤 {{ order.internal_step }}</span>
                <span class="kv">gate {{ order.gate.done }}/{{ order.gate.total }}{{ order.gate.passed ? ' 已通过' : ' 未通过' }}</span>
                <span class="kv">标识 {{ order.demo_label }}（demo_data {{ order.demo_data ? 'true' : 'false' }}）</span>
              </div>
              <div class="kv">证据 {{ order.evidence_count }} 条 · 交付物 {{ order.deliverables.join('、') || '无' }} ·
                评分 {{ order.scores.evaluated }} 条（待复核 {{ order.scores.pending_review }}，均值 {{ order.scores.average ?? '—' }}）
              </div>
              <div class="kv">行中事件：{{ order.incidents.length ? order.incidents.map((i) => `${i.title}（${i.channel}）`).join('、') : '无' }}</div>
              <div class="kv">已写回画像：{{ Object.keys(order.ability_written).length ? recordText(order.ability_written) : '暂无' }}</div>
              <div class="tbl-scroll">
                <table class="tbl">
                  <thead><tr><th>动作</th><th>判定</th><th>在哪儿做</th><th>服务端原因</th></tr></thead>
                  <tbody>
                    <tr v-for="g in gates" :key="g.action">
                      <td class="mono">{{ g.action }}</td>
                      <td><span class="tag" :class="g.ok ? 'tag-real' : 'tag-demo'">{{ g.ok ? '已完成' : '待完成' }}</span></td>
                      <td>{{ g.where }}</td>
                      <td>{{ g.reason }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="order.gate.next" class="next">
                服务端下一步：{{ order.gate.next.label || order.gate.next.action }} —— {{ order.gate.next.hint }}
                <template v-if="order.gate.next.where">（{{ order.gate.next.where }}）</template>
              </div>
            </div>
            <div v-else-if="!orderError" class="op-hint">先导入标准案例拿到 order_id，再选订单查看服务端逐步状态。</div>
          </div>
        </details>

        <details class="dev">
          <summary>开发者 / 诊断详情：阶段契约与闸门来源</summary>
          <div class="dev-body row">
            <span class="kv">阶段闸门来源：contracts/stages.py（契约版本见订单状态）</span>
            <span class="kv">阶段数 {{ catalog.stage_plan.length }}</span>
            <span v-if="order" class="kv">服务端 gate {{ order.gate.done }}/{{ order.gate.total }} ·
              stage_id <b class="mono">{{ order.stage_id }}</b> · 内部步骤
              <b class="mono">{{ order.internal_step }}</b></span>
          </div>
        </details>
      </section>

      <!-- ⑦ 逐步操作说明已并入上一节「六阶段进度与操作指引」的折叠明细，避免首屏重复铺开 -->

      <!-- ⑧ 模式与实时依赖：默认收起的诊断详情（用户可见的模式文案在顶部横幅里） -->
      <details class="dev block-toggle">
        <summary>开发者 / 诊断详情：模式与实时依赖</summary>
        <div class="dev-body">
          <div class="row">
            <button class="tc-btn ghost" :disabled="busy" @click="probeDependencies">
              {{ busy ? '核验中…' : '核验实时模型是否真的可用' }}
            </button>
            <span v-if="probeResult" class="kv">{{ probeResult }}</span>
            <span v-if="providerError" class="inline-err">{{ providerError }}</span>
          </div>
          <p class="hint">
            确定性离线模式由实例启动参数决定，运行期不提供全局切换；本页只如实显示当前实例的状态。
          </p>
          <div class="kv mono">provider_model = {{ status?.provider_model || '(未启用)' }}
            · provider_calls = {{ status?.provider_audit && status.provider_audit.calls !== undefined ? status.provider_audit.calls : '(未启用)' }}
            · confidence_cap = {{ status?.confidence_cap }}</div>
          <div v-if="status?.session_state" class="kv">{{ status.session_state }}</div>
          <div v-if="status?.switch_policy" class="kv">{{ status.switch_policy }}</div>
        </div>
      </details>
    </template>
  </div>
</template>

<script setup lang="ts">
/* 标准案例入口：只调真实后端接口（/scenario/* 与既有业务接口 /practice/messages）。
 *
 * 硬边界（对应验收条件）：
 *   1. 全站唯一出网口是 @/demo/http.ts：**没有** axios 请求/响应拦截器，不做响应改写。
 *   2. 任何接口失败都停住并显示真实错误（DemoHttpError 带状态码与后端 detail）；
 *      没有 try{}catch{} 之后继续走下一步的静默分支。
 *   3. 页面显著标识「标准案例/演示数据」，并显示当前模式（offline 确定性 / live 实时）与依赖实测状态。
 *   4. 导入/重置按钮有提交中 / 成功回执 / 失败错误三种状态，回执字段原样展示。
 *   5. 逐步说明来自后端 stage_plan，每步服务端状态来自 gate.checks；本地不写死案例与步骤。
 */

import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorText } from '@/demo/http'
import {
  scenarioApi,
  modeText,
  DEMO_ACCOUNT,
  type AccountCounts,
  type AccountCounts as Counts,
  type ImportReceipt,
  type OrderState,
  type ResetReceipt,
  type ScenarioCatalog,
} from '@/demo/scenarioApi'
import { buildGuide, gateRows } from '@/demo/guide'
import { useUserStore } from '@/stores/user'

type Phase = 'idle' | 'running' | 'ok' | 'fail'
interface OpState<T> {
  status: Phase
  error: string
  receipt: T | null
  at: string
}

/** 会话由 identity 域 store 持有（同一份 tc-token）；本页只读不写，不另立登录态。 */
const user = useUserStore()
const router = useRouter()

const loading = ref(false)
const loadError = ref('')
const actionError = ref('')
const busy = ref(false)
const loadedAt = ref('')

const catalog = ref<ScenarioCatalog | null>(null)
const selectedCaseId = ref('')
const account = ref<AccountCounts | null>(null)
const accountError = ref('')
const includeProfile = ref(true)
const order = ref<OrderState | null>(null)
const trackedOrderId = ref('')
const orderError = ref('')
const orderAt = ref('')
const probeResult = ref('')
const providerError = ref('')

const imp = reactive<OpState<ImportReceipt>>({ status: 'idle', error: '', receipt: null, at: '' })
const rst = reactive<OpState<ResetReceipt>>({ status: 'idle', error: '', receipt: null, at: '' })

const cases = computed(() => catalog.value?.cases || [])
const status = computed(() => catalog.value?.status || null)
const modeKey = computed(() => modeText(status.value?.mode || '').key)
const modeLabel = computed(() => modeText(status.value?.mode || '').label)
const modeNote = computed(() => modeText(status.value?.mode || '').note)
const shortDigest = computed(() => {
  const d = String(catalog.value?.digest || status.value?.case_digest || '')
  return d ? `${d.slice(0, 12)}…` : '（未取到）'
})
const isDemoAccount = computed(() => user.profile?.username === DEMO_ACCOUNT.username)

/* 面向用户的实时依赖文案：把「配置了 key」与「真实连通已核验」分开说，不暗示已验收。 */
const liveModelText = computed(() => {
  const d = status.value?.deps
  if (!d) return '状态未知'
  if (!d.llm_key_present) return '未配置（当前无法调用实时模型）'
  if (d.llm_connectivity_verified) return '已核验可用'
  return '已配置，未核验可用'
})
const liveModelClass = computed(() => {
  const d = status.value?.deps
  if (!d) return 'bad'
  if (d.llm_connectivity_verified) return 'ok'
  return d.llm_key_present ? 'warn' : 'bad'
})
const voiceStatusText = computed(() => {
  const d = status.value?.deps
  if (!d) return '状态未知'
  if (d.voice_connectivity_verified) return '已核验可用'
  return `未验收（${d.voice_key_present ? '需浏览器麦克风实测' : '缺少语音密钥，且需浏览器麦克风实测'}）`
})
const voiceStatusClass = computed(() => (status.value?.deps.voice_connectivity_verified ? 'ok' : 'warn'))
/** 导入回执里的固定资源约束类型（原样列出，不在前端加工）。 */
const injectedKinds = computed(() =>
  (imp.receipt?.resources_injected || [])
    .map((r) => String(r.kind || ''))
    .filter(Boolean)
    .join('、'),
)
const guideBuild = computed(() => buildGuide(catalog.value?.stage_plan || [], order.value))
const guide = computed(() => guideBuild.value.entries)
const guideMissingStages = computed(() => guideBuild.value.missingStageIds)
const gates = computed(() => gateRows(order.value))
/** 「继续」：优先用已导入/已跟踪的订单，其次是账号下已有的标准案例订单。 */
const continueOrderId = computed(() =>
  trackedOrderId.value || imp.receipt?.order_id || (account.value?.scenario_order_ids || [])[0] || '')
/**
 * 六阶段概览：阶段列表来自后端 stage_plan；「当前/已完成」只用服务端给的 order.stage_id
 * 与阶段 order 比较得出，没有订单就如实显示「未导入」，不在前端编造进度。
 */
const stageRows = computed(() => {
  const plan = catalog.value?.stage_plan || []
  const currentId = order.value?.stage_id || ''
  const current = currentId ? plan.find((s) => s.id === currentId) : undefined
  return plan.map((s) => {
    let state = '未导入'
    if (order.value) {
      const cur = current?.order ?? s.order
      state = cur > s.order ? '已完成' : cur === s.order ? '进行中' : '未开始'
    }
    const first = guide.value.find((g) => (s.steps || []).includes(g.step))
    return { id: s.id, name: s.name, focus: s.focus, state, route: first?.route || '/practice' }
  })
})
const knownOrderIds = computed(() => {
  const ids = new Set<string>()
  if (imp.receipt?.order_id) ids.add(imp.receipt.order_id)
  for (const id of account.value?.scenario_order_ids || []) ids.add(id)
  return Array.from(ids)
})

function nowText(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function dateText(dates: unknown): string {
  if (!dates) return '—'
  if (typeof dates === 'string') return dates
  const d = dates as { start?: string; end?: string }
  return [d.start, d.end].filter(Boolean).join(' → ') || JSON.stringify(dates)
}

function partyText(party: Record<string, number | string> | string | undefined | null): string {
  if (!party) return '—'
  if (typeof party === 'string') return party
  return Object.entries(party)
    .map(([k, v]) => `${k} ${v}`)
    .join(' · ')
}

function recordText(o: unknown): string {
  if (o === null || o === undefined) return '—'
  if (typeof o === 'number' || typeof o === 'string' || typeof o === 'boolean') return String(o)
  if (Array.isArray(o)) return o.length ? o.join('、') : '—'
  const rec = o as Record<string, unknown>
  const keys = Object.keys(rec)
  if (!keys.length) return '—'
  return keys
    .map((k) => {
      const v = rec[k]
      if (v && typeof v === 'object') return `${k}=${recordText(v)}`
      return `${k}=${v}`
    })
    .join(' · ')
}

function countsText(c: Counts): string {
  return `订单 ${c.orders}（标准案例 ${c.scenario_orders}）· 证据 ${c.evidence} · 交付物 ${c.deliverables} · 画像 ${c.ability_rows} · 测评 ${c.quiz_attempts} · 线程 ${c.threads} · 通知 ${c.notices}`
}

/** 读会话 + 案例目录。任何失败写进 loadError 并让页面停住；没有静默兜底。 */
async function reload() {
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    // 会话以 identity 域 store 为准（同一份 tc-token）；本页不自己判登录态。
    try {
      await user.restore(true)
    } catch {
      // restore 内部已把失败原因写进 sessionError；这里不吞掉后续的接口错误
    }
    const st = await scenarioApi.status(false)
    // 内部排查页只在**显式内部演示实例**可见：普通实例直接回首页，不暴露导入入口。
    if (!(st as any)?.demo_instance?.enabled) {
      router.replace('/')
      return
    }
    const data = await scenarioApi.catalog()
    catalog.value = data
    if (!selectedCaseId.value && data.cases.length) selectedCaseId.value = data.cases[0].case_id
    loadedAt.value = nowText()
    await refreshAccount()
  } catch (err) {
    catalog.value = null
    loadError.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function refreshAccount() {
  accountError.value = ''
  try {
    account.value = await scenarioApi.account(selectedCaseId.value)
  } catch (err) {
    account.value = null
    accountError.value = errorText(err)
  }
}

async function refreshOrderState() {
  if (!trackedOrderId.value) {
    orderError.value = '未选择订单：请先导入标准案例或从账号计数里选一个 order_id'
    return
  }
  busy.value = true
  orderError.value = ''
  try {
    order.value = await scenarioApi.orderState(trackedOrderId.value)
    orderAt.value = nowText()
  } catch (err) {
    order.value = null
    orderError.value = errorText(err)
  } finally {
    busy.value = false
  }
}

async function doImport() {
  imp.status = 'running'
  imp.error = ''
  imp.receipt = null
  imp.at = ''
  busy.value = true
  try {
    const receipt = await scenarioApi.importCase(selectedCaseId.value)
    imp.receipt = receipt
    imp.status = 'ok'
    imp.at = nowText()
    if (receipt.order_id) {
      trackedOrderId.value = receipt.order_id
      await refreshOrderState()
    }
    await refreshAccount()
  } catch (err) {
    imp.status = 'fail'
    imp.error = errorText(err)
    imp.at = nowText()
  } finally {
    busy.value = false
  }
}

async function doReset() {
  rst.status = 'running'
  rst.error = ''
  rst.receipt = null
  rst.at = ''
  busy.value = true
  try {
    const receipt = await scenarioApi.resetCase(selectedCaseId.value, includeProfile.value)
    rst.receipt = receipt
    rst.status = 'ok'
    rst.at = nowText()
    order.value = null
    orderError.value = ''
    await refreshAccount()
  } catch (err) {
    rst.status = 'fail'
    rst.error = errorText(err)
    rst.at = nowText()
  } finally {
    busy.value = false
  }
}

/** 真实连通核验：后端 probe=true 会真发一次最小 LLM 请求，结果如实写回状态。 */
async function probeDependencies() {
  busy.value = true
  providerError.value = ''
  probeResult.value = ''
  try {
    const st = await scenarioApi.status(true)
    probeResult.value = st.deps.llm_connectivity_verified
      ? `LLM 连通已核验${st.deps.llm_probe_model ? '（模型 ' + st.deps.llm_probe_model + '）' : ''}`
      : `LLM 连通未核验：${st.deps.llm_not_verified_reason || '后端未给出原因'}`
    // 状态变了：重新拉目录，让标识条跟着后端走
    catalog.value = await scenarioApi.catalog()
  } catch (err) {
    providerError.value = errorText(err)
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.demo-case { width: 100%; max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.sec { padding: 16px 18px; }
.sec-title { font-size: $fs-section; font-weight: 800; margin-bottom: 10px; }
.hint { font-size: $fs-meta; color: $color-text-secondary; line-height: 1.8; margin-bottom: 10px; }
.mono { font-family: ui-monospace, monospace; }
.small { font-size: $fs-meta; }
.row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.kv { font-size: $fs-meta; color: $color-text-secondary; }
.kv.ok { color: $color-success; }
.kv.bad { color: $color-danger; }
code { font-family: ui-monospace, monospace; font-size: $fs-badge; background: $color-primary-softer; padding: 1px 5px; border-radius: 4px; }

/* 标识条 */
.banner { padding: 14px 18px; border-radius: $radius-md; border: 1px solid $color-border; background: $color-primary-softer; }
.banner.live { background: #f2fbf6; border-color: #cbeadb; }
.banner.unknown { background: #fff6e8; border-color: #f2dcc0; }
.banner-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mark { font-size: $fs-card-title; font-weight: 800; color: $color-primary; letter-spacing: .4px; }
.sep { width: 1px; height: 18px; background: $color-border-strong; }
.mode { display: inline-flex; align-items: center; gap: 7px; font-size: $fs-meta; font-weight: 700; border-radius: 999px; padding: 3px 12px; background: #fff; border: 1px solid $color-border; }
.mode .dot { width: 8px; height: 8px; border-radius: 50%; background: $color-warning; }
.mode.live .dot { background: $color-success; }
.mode.unknown .dot { background: $color-danger; }
.scope { font-size: $fs-badge; color: $color-text-secondary; }
.banner-sub { margin-top: 7px; font-size: $fs-meta; color: $color-text; }
.banner-deps { margin-top: 9px; display: flex; flex-wrap: wrap; gap: 8px; }
.dep { font-size: $fs-badge; background: #fff; border: 1px solid $color-border; border-radius: 999px; padding: 3px 10px; color: $color-text-secondary; }
.dep.ok { color: $color-success; border-color: #cbeadb; }
.dep.bad { color: $color-danger; border-color: #f4c9c9; }
.dep.warn { color: #a3620c; border-color: #f2dcc0; }

/* 折叠的技术细节与窄屏容器 */
.dev { margin-top: 10px; }
.dev summary { cursor: pointer; font-size: $fs-meta; color: $color-text-secondary; }
.dev-body { margin-top: 8px; display: flex; flex-direction: column; gap: 4px;
  background: #fff; border: 1px solid $color-border; border-radius: 6px; padding: 9px 11px; word-break: break-all; }
.guide-wrap { margin: 4px 0 8px; }
.guide-sum { cursor: pointer; font-size: $fs-meta; color: $color-text-secondary; margin-bottom: 6px; }
.tbl-scroll { overflow-x: auto; max-width: 100%; }
.stage-error { margin: 8px 0; font-size: $fs-meta; line-height: 1.9; color: #8f2b2b;
  background: #fdf4f4; border: 1px solid #f4c9c9; border-radius: 6px; padding: 9px 11px; word-break: break-all; }
.banner-note { margin-top: 8px; font-size: $fs-badge; color: $color-text-secondary; line-height: 1.8; }
.honest { margin: 8px 0 0 18px; font-size: $fs-badge; color: $color-text-secondary; line-height: 1.9; }
.banner-warn { margin-top: 8px; font-size: $fs-meta; color: #a3620c; background: #fff6e8; border-radius: 6px; padding: 7px 10px; }

/* 失败卡片 */
.err-card { padding: 16px 18px; border-color: #f4c9c9; background: #fdf4f4; }
.err-title { font-size: $fs-list; font-weight: 700; color: $color-danger; margin-bottom: 8px; }
.err-body, .op-err { font-family: ui-monospace, monospace; font-size: $fs-badge; white-space: pre-wrap; word-break: break-all;
  background: #fff; border: 1px solid #f4c9c9; border-radius: 6px; padding: 9px 11px; color: #8f2b2b; }
.err-actions { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.err-hint { font-size: $fs-badge; color: $color-text-secondary; }
.inline-err { font-size: $fs-meta; color: $color-danger; }

/* 表单 */
.fld { display: inline-flex; flex-direction: column; gap: 4px; font-size: $fs-badge; color: $color-text-muted; }
.ipt { height: 38px; min-width: 190px; border: 1px solid $color-border; border-radius: 6px; padding: 0 11px; font-size: $fs-body; outline: none; background: #fff; }
.ipt:focus { border-color: $color-primary; }
.chk { display: inline-flex; align-items: center; gap: 6px; font-size: $fs-meta; color: $color-text-secondary; }
.login .row { margin-top: 10px; }

/* 案例 */
.case { margin-top: 14px; border-top: 1px dashed $color-border; padding-top: 14px; }
.case-hd { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.case-title { font-size: $fs-card-title; font-weight: 800; }
.case-id { font-size: $fs-badge; color: $color-text-muted; }
.tag { font-size: $fs-badge; border-radius: 999px; padding: 2px 10px; }
.tag-demo { background: $color-primary-soft; color: $color-primary; font-weight: 700; }
.tag-real { background: #e8f7ee; color: #0d8a55; font-weight: 700; }
.case-grid { margin-top: 10px; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 7px 18px; }
.case-grid > div { display: flex; gap: 8px; font-size: $fs-meta; }
.g-k { color: $color-text-muted; min-width: 84px; flex-shrink: 0; }
.g-v { color: $color-text; word-break: break-all; }
.case-sub { margin-top: 12px; font-size: $fs-meta; font-weight: 700; color: $color-text-secondary; }

.tbl { width: 100%; border-collapse: collapse; font-size: $fs-meta; margin-top: 6px; }
.tbl th { text-align: left; padding: 7px 9px; color: $color-text-secondary; font-weight: 600; border-bottom: 1px solid $color-border; white-space: nowrap; }
.tbl td { padding: 7px 9px; border-bottom: 1px solid #f1f3f5; vertical-align: top; }

/* 回执 */
.op { margin-top: 12px; border: 1px solid $color-border; border-radius: 8px; padding: 11px 13px; background: #fcfdff; }
.op.ok { border-color: #cbeadb; background: #f6fdf9; }
.op.fail { border-color: #f4c9c9; background: #fdf6f6; }
.op.running { border-color: $color-primary-light; background: $color-primary-softer; }
.op-hd { display: flex; align-items: center; gap: 10px; font-size: $fs-meta; margin-bottom: 7px; }
.op-tag { font-size: $fs-badge; border-radius: 999px; padding: 2px 9px; }
.op-tag.run { background: $color-primary-soft; color: $color-primary; }
.op-tag.ok { background: #e8f7ee; color: #0d8a55; }
.op-tag.bad { background: #fdeceb; color: #c0392b; }
.op-tag.idle { background: $color-bg; color: $color-text-muted; }
.op-at { font-size: $fs-badge; color: $color-text-muted; margin-left: auto; }
.op-body { display: flex; flex-direction: column; gap: 5px; }
.op-hint { font-size: $fs-badge; color: $color-text-secondary; }

.next { margin-top: 10px; font-size: $fs-meta; background: $color-primary-soft; border-radius: 6px; padding: 8px 11px; color: $color-text; }
.ok-line { color: #1f7a3d; }
.tbl.stage tr.now td { background: rgba(0, 0, 0, 0.035); }
.guide .g-title { font-weight: 700; color: $color-text; }
.guide .g-hint { font-size: $fs-badge; color: $color-text-secondary; margin-top: 2px; }
.guide .g-deliv { font-size: $fs-badge; color: $color-primary; margin-top: 2px; }
.go { font-size: $fs-badge; font-weight: 700; white-space: nowrap; }
</style>
