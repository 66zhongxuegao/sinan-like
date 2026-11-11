<template>
  <div class="sys">
    <section class="card sec">
      <div class="sec-title title-rule"><span>订单客户事实卡</span></div>
      <div class="row">
        <select v-model="factOrderId" class="ipt" style="max-width:420px" @change="loadCustomerCard">
          <option value="" disabled hidden>请选择订单</option>
          <option v-for="o in factOrders" :key="o.order_id" :value="o.order_id">{{ o.customer }} · {{ o.destination }} · {{ o.order_id }}</option>
        </select>
        <button class="tc-btn ghost" :disabled="!factOrderId || factLoading" @click="loadCustomerCard">{{ factLoading ? '读取中…' : '查看事实卡' }}</button>
      </div>
      <p v-if="factError">{{ factError }}</p>
      <template v-if="factData">
        <div class="sec-sub">{{ factData.card.identity.customer }} · {{ factData.card.identity.language }} · 版本 {{ factData.card.version }}</div>
        <table class="tbl">
          <thead><tr><th>字段</th><th>客户答案</th><th>状态</th><th>已告知</th></tr></thead>
          <tbody><tr v-for="(f, key) in factData.card.fields" :key="key">
            <td>{{ FACT_LABELS[key] || key }}</td><td>{{ f.value || '尚未确定' }}</td>
            <td>{{ FACT_STATES[f.state] || f.state }}</td><td>{{ f.revealed ? '是' : '否' }}</td>
          </tr></tbody>
        </table>
        <details v-if="factData.conflicts.length">
          <summary>被拦截的冲突（{{ factData.conflicts.length }}）</summary>
          <table class="tbl"><thead><tr><th>字段</th><th>候选值</th><th>规范值</th><th>通道</th></tr></thead>
            <tbody><tr v-for="e in factData.conflicts" :key="e.event_id"><td>{{ FACT_LABELS[e.fact_key] || e.fact_key }}</td><td>{{ e.value }}</td><td>{{ e.expected || '未定' }}</td><td>{{ e.source_channel }}</td></tr></tbody>
          </table>
        </details>
      </template>
    </section>
    <!-- ① 导演规则表（只读） -->
    <section class="card sec">
      <div class="sec-title title-rule"><span>导演规则表 · 按 13 步注入事件型考点</span></div>
      <div class="sec-sub">
        学员动作自动进入事件总线，导演按画像难度决定注入的事件数量与强度。
        补救档给出明确线索（{{ 'explicit' }}），加压档更为隐蔽（{{ 'implicit' }}）。
      </div>
      <table class="tbl">
        <thead><tr>
          <th style="width:120px">代码</th><th style="width:64px">步骤</th><th style="width:120px">触发动作</th>
          <th style="width:120px">注入到</th><th>事件</th><th style="width:150px">考的技能点</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in rules" :key="r.code">
            <td class="mono">{{ r.code }}</td>
            <td>{{ r.step }}</td>
            <td class="mono small">{{ r.trigger.join(' / ') }}</td>
            <td>{{ r.channel }}</td>
            <td>{{ r.title }}</td>
            <td class="mono small">{{ r.skill_points.join(' ') }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ② 情景约束（导演设定） -->
    <section class="card sec">
      <div class="sec-title title-rule"><span>情景约束 · 资源方客观条件</span></div>
      <div class="sec-sub">设定后，对应资源方 Agent 的报价与档期反馈须遵守该条件。</div>
      <table class="ctl">
        <thead><tr><th style="width:100px">资源方</th><th style="width:150px">库存 / 档期</th>
          <th style="width:130px">价格系数</th><th>补充说明</th><th style="width:80px"></th></tr></thead>
        <tbody>
          <tr v-for="k in KINDS" :key="k">
            <td class="t-kind">{{ k }}</td>
            <td><select v-model="forms[k].availability" class="ipt sm">
              <option value="">默认</option>
              <option v-for="a in AVAILABILITY" :key="a" :value="a">{{ a }}</option>
            </select></td>
            <td><input v-model.number="forms[k].price_factor" type="number" step="0.05" min="0" class="ipt sm" placeholder="1.0" /></td>
            <td><input v-model="forms[k].note" class="ipt" placeholder="如：返程高峰，票源紧张" /></td>
            <td><button class="tc-btn ghost" @click="saveState(k)">应用</button></td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ③ 评分公信力 -->
    <section class="card sec">
      <div class="sec-title title-rule"><span>评分公信力 · 人工校准集</span></div>
      <div class="sec-sub">用人工标注 M 档、标出证据坐标的样本定期测验评分 Agent，并据此标定低置信度阈值。</div>
      <div v-if="cal.dataset" class="ds">
        <span class="ds-item">技能点 {{ cal.dataset.skill_points }} 个</span>
        <span class="ds-item">难例 {{ cal.dataset.hard_cases }} 条</span>
        <span class="ds-item">客源 {{ Object.keys(cal.dataset.markets || {}).length }} 个</span>
        <span class="ds-item">语言 {{ Object.keys(cal.dataset.languages || {}).join(' / ') }}</span>
        <span class="ds-item">档位 {{ levelText }}</span>
        <span class="ds-badge" :class="cal.dataset.passed ? 'ok' : 'bad'">
          {{ cal.dataset.passed ? '结构无缺口' : '有缺口：' + (cal.dataset.gaps || []).join('；') }}
        </span>
      </div>
      <div class="row">
        <span class="out">样本 {{ cal.samples }} 条</span>
        <span v-if="cal.latest" class="out">最近一次 {{ (cal.latest.created_at || '').slice(0, 19) }}</span>
        <span v-if="cal.latest" class="cg" :class="cal.latest.passed ? 'ok' : 'bad'">
          {{ cal.latest.passed ? '通过' : '未达标' }}
        </span>
        <button class="tc-btn ghost" :disabled="calRunning" @click="runCalibration(1)">
          {{ calRunning ? '评测中…' : '跑校准（1 轮）' }}
        </button>
        <button class="tc-btn ghost" :disabled="calRunning" @click="runCalibration(2)">跑校准（2 轮·测稳定性）</button>
      </div>
      <div v-if="cal.latest" class="cal-grid">
        <div class="cal-cell"><span class="cc-k">M 档一致率</span><span class="cc-v">{{ (cal.latest.agreement * 100).toFixed(1) }}%</span></div>
        <div class="cal-cell"><span class="cc-k">证据准确率</span><span class="cc-v">{{ (cal.latest.evidence_accuracy * 100).toFixed(1) }}%</span></div>
        <div class="cal-cell"><span class="cc-k">稳定性</span><span class="cc-v">{{ (cal.latest.stability * 100).toFixed(0) }}%</span></div>
        <div class="cal-cell"><span class="cc-k">标定阈值</span><span class="cc-v">置信 {{ cal.latest.threshold_confidence }} / 边界 ±{{ cal.latest.threshold_delta }}</span></div>
      </div>
      <div v-if="cal.gate" class="cal-gate" :class="cal.gate.passed ? 'ok' : 'bad'">
        <span class="cg-tag">主链准入</span>
        <span v-if="cal.gate.passed">评分 Agent 已通过校准，可正常写回画像</span>
        <span v-else-if="cal.gate.baseline">未达标：画像只下调、不上调</span>
        <span v-else>无校准基线：评分 Agent 未经校准集验证，本次不写画像</span>
      </div>
      <div v-if="calReport" class="result">
        <div class="r-line">本次一致率 {{ (calReport.agreement * 100).toFixed(1) }}% ／
          证据准确率 {{ (calReport.evidence_accuracy * 100).toFixed(1) }}% ／
          稳定性 {{ (calReport.stability * 100).toFixed(0) }}%</div>
        <div class="r-sub">标定阈值：置信度 ≥ {{ calReport.threshold.confidence }}，档位边界 ±{{ calReport.threshold.boundary_delta }} 分
          （该阈值下一致率 {{ calReport.threshold.accuracy_at }}，保留 {{ calReport.threshold.kept }} 条）</div>
      </div>
    </section>

    <!-- ④ MCP 契约 -->
    <section class="card sec">
      <div class="sec-title title-rule"><span>MCP 接口契约</span></div>
      <div class="sec-sub">外部数据与资源方能力均按 MCP 工具契约暴露，更换实现不需要改契约。</div>
      <div class="row">
        <span class="out">{{ mcp.protocolVersion }} · {{ mcp.transport }}</span>
        <span class="out">{{ mcp.tools?.length || 0 }} 个工具</span>
        <button class="tc-btn ghost" @click="loadMcp">刷新</button>
      </div>
      <div class="mcp-list">
        <div v-for="t in mcp.tools" :key="t.name" class="mcp-row">
          <span class="mcp-name">{{ t.name }}</span>
          <span class="mcp-desc">{{ t.description }}</span>
          <span class="mcp-req">{{ t.required?.length ? t.required.join(', ') : '—' }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import client from '@/api/client'

const KINDS = ['地接社', '酒店', '车队', '票务']
const AVAILABILITY = ['有货', '紧张', '无货', '无档期']
const FACT_LABELS: Record<string, string> = { party: '人数', dates: '日期', days: '天数', budget: '预算', transport: '交通', hotel: '住宿', special: '特殊需求', decision: '决策人', documents: '证件' }
const FACT_STATES: Record<string, string> = { fixed: '明确事实', canonical_hidden: '确定但尚未主动告知', unknown: '尚未确定' }
const factOrders = ref<any[]>([])
const factOrderId = ref('')
const factData = ref<any>(null)
const factError = ref('')
const factLoading = ref(false)
async function loadFactOrders() {
  try { const data = (await client.get('/practice/orders')).data; factOrders.value = (Array.isArray(data) ? data : data.orders || []).filter((o: any) => o.claimed === true) } catch { factError.value = '订单读取失败' }
}
async function loadCustomerCard() {
  if (!factOrderId.value) return
  factLoading.value = true; factError.value = ''; factData.value = null
  try { factData.value = (await client.get(`/practice/orders/${encodeURIComponent(factOrderId.value)}/customer-card`)).data }
  catch { factError.value = '事实卡读取失败' }
  finally { factLoading.value = false }
}

const rules = ref<any[]>([])
const cal = ref<any>({ samples: 0, latest: null, gate: null })
const calReport = ref<any>(null)
const calRunning = ref(false)
const mcp = ref<any>({ tools: [] })
const forms = reactive<Record<string, any>>(
  Object.fromEntries(KINDS.map((k) => [k, { availability: '', price_factor: null, note: '' }])),
)

const levelText = computed(() => {
  const lv = cal.value?.dataset?.levels || {}
  return Object.keys(lv).map((k) => `${k} ${lv[k]}`).join(' · ')
})

async function loadRules() {
  try { rules.value = (await client.get('/practice/director/catalog')).data.rules } catch { rules.value = [] }
}
async function loadCalibration() {
  try { cal.value = (await client.get('/calibration')).data } catch {}
}
async function loadMcp() {
  try { mcp.value = (await client.get('/mcp/tools')).data } catch {}
}
async function loadStates() {
  try {
    const { states } = (await client.get('/tools/supplier/state')).data
    for (const k of KINDS) {
      const s = states?.[k]
      if (s) Object.assign(forms[k], { availability: s.availability || '', price_factor: s.price_factor || null, note: s.note || '' })
    }
  } catch {}
}
async function saveState(k: string) {
  try {
    await client.post('/tools/supplier/state', {
      kind: k, availability: forms[k].availability || '',
      price_factor: Number(forms[k].price_factor) || 0, note: forms[k].note || '',
    })
  } catch {}
}
async function runCalibration(repeats: number) {
  calRunning.value = true
  calReport.value = null
  try {
    calReport.value = (await client.post('/calibration/run', { repeats })).data
    await loadCalibration()
  } catch (e: any) {
    calReport.value = { agreement: 0, evidence_accuracy: 0, stability: 0,
      threshold: { confidence: '-', boundary_delta: '-' } }
  } finally { calRunning.value = false }
}

onMounted(() => { loadRules(); loadCalibration(); loadMcp(); loadStates(); loadFactOrders() })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.sys { width: 100%; max-width: 1160px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.sec { padding: 16px 18px; }
.sec-title { font-size: 22px; font-weight: 800; margin-bottom: 8px; }
.sec-sub { font-size: 16px; color: $color-text-secondary; line-height: 1.8; margin-bottom: 14px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 15.5px; }
.tbl th { text-align: left; padding: 7px 9px; font-size: 15.5px; color: $color-text-secondary; font-weight: 600; border-bottom: 1px solid $color-border; white-space: nowrap; }
.tbl td { padding: 7px 9px; border-bottom: 1px solid #f1f3f5; }
.mono { font-family: ui-monospace, monospace; }
.small { font-size: 15.5px; }

.ctl { width: 100%; border-collapse: collapse; font-size: 15px; }
.ctl th { text-align: left; padding: 7px 10px; font-size: 15.5px; color: $color-text-secondary; font-weight: 600; border-bottom: 1px solid $color-border; }
.ctl td { padding: 7px 10px; border-bottom: 1px solid #f1f3f5; }
.t-kind { font-weight: 700; }
.ipt { height: 34px; border: 1px solid $color-border; border-radius: 6px; padding: 0 11px; font-size: 15px; outline: none; width: 100%; }
.ipt:focus { border-color: $color-primary; }
.ipt.sm { height: 30px; }
.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.out { font-size: 15.5px; color: $color-text-secondary; }
.ds { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
.ds-item { font-size: 15.5px; background: $color-primary-softer; border-radius: 999px; padding: 3px 11px; color: $color-text-secondary; }
.ds-badge { font-size: 15.5px; border-radius: 999px; padding: 3px 11px; }
.ds-badge.ok { background: #e8f7ee; color: #0d8a55; }
.ds-badge.bad { background: #fdeceb; color: #c0392b; }
.cg { font-size: 15px; border-radius: 999px; padding: 2px 10px; }
.cg.ok { background: #e8f7ee; color: #0d8a55; }
.cg.bad { background: #fdeceb; color: #c0392b; }
.cal-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.cal-cell { display: flex; flex-direction: column; gap: 2px; background: $color-primary-softer; border-radius: 8px; padding: 7px 14px; min-width: 108px; }
.cc-k { font-size: 15px; color: $color-text-muted; }
.cc-v { font-size: 15.5px; font-weight: 700; }
.cal-gate { margin-top: 9px; display: flex; align-items: center; gap: 9px; font-size: 15.5px; padding: 9px 12px; border-radius: 8px; }
.cal-gate.ok { background: #e8f7ee; color: #0d8a55; }
.cal-gate.bad { background: #fff6e8; color: #a3620c; }
.cg-tag { font-size: 14.5px; background: rgba(255,255,255,0.7); border-radius: 4px; padding: 1px 7px; }
.result { margin-top: 8px; background: $color-primary-softer; border-radius: 8px; padding: 11px 13px; }
.r-line { font-size: 15px; line-height: 1.8; }
.r-sub { font-size: 15.5px; color: $color-text-secondary; line-height: 1.9; }
.mcp-list { margin-top: 8px; display: flex; flex-direction: column; }
.mcp-row { display: flex; align-items: center; gap: 12px; padding: 7px 0; border-bottom: 1px dashed #f1f3f5; font-size: 15.5px; }
.mcp-name { font-family: ui-monospace, monospace; color: $color-primary; font-weight: 600; width: 150px; flex-shrink: 0; }
.mcp-desc { flex: 1; color: $color-text-secondary; }
.mcp-req { font-family: ui-monospace, monospace; font-size: 15px; color: $color-text-muted; }
</style>
