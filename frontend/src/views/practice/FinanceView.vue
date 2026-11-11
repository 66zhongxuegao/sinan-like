<template>
  <div class="fin">
    <div class="head">
      <div class="h-l">
        <button class="back" @click="goBack"><SIcon name="back" :size="13" /></button>
        <h2 class="h-title">成本与结算 · {{ order.customer || '' }} · {{ order.destination || '' }}</h2>
      </div>
      <div class="h-r">
        <span class="stage">{{ order.stage_name || '' }}</span>
        <button class="tc-btn" :disabled="busy" @click="settle">
          <SIcon name="check" :size="13" /> {{ settled ? '重新结账留档' : '结账并留档' }}
        </button>
      </div>
    </div>

    <div v-if="summary" class="kpis">
      <div class="kpi">
        <span class="k-label">客户确认收入</span>
        <span class="k-val">{{ money(summary.revenue) }}</span>
        <span class="k-sub">{{ summary.revenue ? '取自分项报价单' : '未提交分项报价' }}</span>
      </div>
      <div class="kpi">
        <span class="k-label">按资源方报价的成本</span>
        <span class="k-val">{{ money(summary.cost) }}</span>
        <span class="k-sub">{{ summary.cost_source }}<template v-if="summary.cost_estimated"> · {{ summary.cost_note }}</template></span>
      </div>
      <div class="kpi">
        <span class="k-label">我方承担损失</span>
        <span class="k-val" :class="{ bad: summary.loss > 0 }">{{ money(summary.loss) }}</span>
        <span class="k-sub">{{ summary.entries.length }} 笔台账 · {{ summary.pending }} 笔待定责</span>
      </div>
      <div class="kpi hl">
        <span class="k-label">实际毛利</span>
        <span class="k-val" :class="profitClass">{{ hasRevenue ? money(summary.profit) : '—' }}</span>
        <span class="k-sub">
          <span class="grade" :class="gradeClass">{{ summary.grade }}</span>
          <template v-if="hasRevenue">毛利率 {{ pct(summary.margin) }}</template>
          <template v-else>暂无收入数据，请先提交分项报价</template>
        </span>
      </div>
    </div>

    <section class="card sec">
      <div class="sec-title"><SIcon name="calc" :size="14" /><span>成本明细</span>
        <span class="sec-tag">{{ summary?.people || 0 }} 人 · {{ summary?.days || 0 }} 天 · {{ summary?.rooms || 0 }} 间</span>
      </div>
      <table class="tbl">
        <thead><tr><th>项目</th><th>数量</th><th class="num">金额</th></tr></thead>
        <tbody>
          <tr v-for="(it, i) in summary?.cost_items || []" :key="i">
            <td>{{ it.name }}</td><td class="muted">{{ it.qty }}</td><td class="num">{{ money(it.amount) }}</td>
          </tr>
          <tr v-if="!(summary?.cost_items || []).length"><td colspan="3" class="empty">尚未向资源方询价，还没有成本数据</td></tr>
        </tbody>
        <tfoot v-if="(summary?.cost_items || []).length">
          <tr><td>合计</td><td class="muted">{{ summary?.cost_source }}</td><td class="num strong">{{ money(summary?.cost) }}</td></tr>
        </tfoot>
      </table>
    </section>

    <section class="card sec">
      <div class="sec-title"><SIcon name="warn" :size="14" /><span>损失与赔付台账</span>
        <span class="sec-tag">未定责的损失默认由我方承担</span>
      </div>
      <div v-if="!(summary?.entries || []).length" class="empty">本单暂无损失或赔付记录</div>
      <div v-for="e in summary?.entries || []" :key="e.entry_id" class="entry">
        <div class="e-main">
          <span class="e-label">{{ e.label }}</span>
          <span class="e-src">{{ e.source === 'incident' ? '突发事件' : '台账登记' }}<template v-if="e.supplier_kind"> · {{ e.supplier_kind }}</template></span>
        </div>
        <div class="e-amt">{{ money(e.amount) }}</div>
        <div class="e-bearer">
          <template v-if="e.status === '待处理'">
            <button class="mini" :disabled="busy" @click="decide(e, '我方')">我方承担</button>
            <button class="mini" :disabled="busy" @click="decide(e, '资源方')">向资源方追偿</button>
            <button class="mini" :disabled="busy" @click="decide(e, '客户')">协商转嫁客户</button>
          </template>
          <template v-else>
            <span class="bearer">{{ e.bearer }}</span>
            <span class="mine">我方 {{ money(e.ours) }}</span>
          </template>
        </div>
      </div>
      <div v-if="toast" class="toast" :class="toastBad ? 'bad' : ''">{{ toast }}</div>
    </section>

    <section v-if="(summary?.gaps || []).length" class="card sec">
      <div class="sec-title"><SIcon name="chart" :size="14" /><span>自己登记的成本 vs 实际账目</span></div>
      <table class="tbl">
        <thead><tr><th>项目</th><th class="num">自报</th><th class="num">实际</th><th class="num">差异</th></tr></thead>
        <tbody>
          <tr v-for="(g, i) in summary?.gaps || []" :key="i">
            <td>{{ g.name }}</td>
            <td class="num">{{ money(g.declared) }}</td>
            <td class="num">{{ money(g.actual) }}</td>
            <td class="num" :class="g.diff < 0 ? 'bad' : 'ok'">{{ money(g.diff) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card sec">
      <div class="sec-title"><SIcon name="target" :size="14" /><span>本阶段完成条件</span>
        <span class="sec-tag">{{ gateDone }}/{{ gateTotal }}</span>
      </div>
      <div v-for="c in gateChecks" :key="c.action" class="g-row" :class="{ ok: c.ok }">
        <SIcon :name="c.ok ? 'check' : 'circle'" :size="13" />
        <div class="g-mid">
          <span class="g-label">{{ c.label }}</span>
          <span class="g-hint">{{ c.hint }}</span>
        </div>
      </div>
      <button class="link-btn" :disabled="!settlementCode" @click="openDeliverables">
        <SIcon name="filetext" :size="13" />
        {{ settlementCode ? `去填写「${settlementTitle}」` : '文档清单还在加载，请稍候' }}
      </button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'
import { useStages } from '@/composables/useStages'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))

const order = ref<any>({})
const summary = ref<any>(null)
const gate = ref<any>({ checks: [], done: 0, total: 0 })
const busy = ref(false)
const toast = ref('')
const toastBad = ref(false)
const settled = ref(false)

const hasRevenue = computed(() => Number(summary.value?.revenue || 0) > 0)
const gateChecks = computed(() => gate.value.checks || [])
const gateDone = computed(() => gate.value.done || 0)
const gateTotal = computed(() => gate.value.total || 0)

// 结算交付物按契约定位（tripcraft/contracts/stages.py 的 deliverable_stage），
// 跳转用 code 而不是中文标题，工作台按 code 打开对应文档。
const SETTLEMENT_CODE = 'settlement'
const { stages: stageDefs, load: loadStages } = useStages()
const settlementCode = computed(() => {
  const stage = stageDefs.value.find((s) => (s.deliverables || []).includes(SETTLEMENT_CODE))
  return stage ? SETTLEMENT_CODE : ''
})
const settlementTitle = computed(() => (settlementCode.value ? '地接结算核对单' : '结算交付物'))

const gradeClass = computed(() => {
  const g = summary.value?.grade || ''
  if (g === '优秀') return 'ok'
  if (g === '达标') return 'ok-soft'
  if (g === '偏低') return 'warn'
  if (g === '亏损') return 'bad'
  return 'muted'
})
const profitClass = computed(() => {
  const p = summary.value?.profit
  if (p === undefined || p === null) return ''
  return p < 0 ? 'bad' : p > 0 ? 'ok' : ''
})

function money(v: any) {
  const n = Number(v || 0)
  return '¥' + n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}
function pct(v: any) {
  return (Number(v || 0) * 100).toFixed(1) + '%'
}
function goBack() { router.push(`/practice/orders/${orderId.value}`) }
function openDeliverables() {
  if (!settlementCode.value) return
  router.push(`/practice/orders/${orderId.value}/deliverables?code=${settlementCode.value}`)
}

async function load() {
  if (!orderId.value) return
  try {
    const [o, s, g] = await Promise.all([
      client.get(`/practice/orders/${orderId.value}`),
      client.get(`/practice/orders/${orderId.value}/finance`),
      client.get(`/practice/orders/${orderId.value}/gates`),
    ])
    order.value = o.data
    summary.value = s.data
    gate.value = g.data || { checks: [], done: 0, total: 0 }
    settled.value = !!(s.data?.entries || []).length && (s.data?.pending || 0) === 0
  } catch (e: any) {
    toast.value = e?.response?.data?.detail || '加载失败'
    toastBad.value = true
  }
}

async function decide(e: any, bearer: string) {
  busy.value = true
  try {
    const r = (await client.post(
      `/practice/orders/${orderId.value}/finance/entries/${e.entry_id}/decide`, { bearer })).data
    summary.value = r.summary
    toast.value = r.message
    toastBad.value = !!(r.entry?.ours)
    settled.value = (r.summary?.pending || 0) === 0
  } catch (err: any) {
    toast.value = err?.response?.data?.detail || '定责失败'
    toastBad.value = true
  } finally { busy.value = false }
}

async function settle() {
  busy.value = true
  try {
    const r = (await client.post(`/practice/orders/${orderId.value}/finance/settle`)).data
    const hadRevenue = Number(summary.value?.revenue || 0) > 0
    summary.value = r
    settled.value = true
    toast.value = hadRevenue
      ? `已结账留档：实际毛利 ${money(r.profit)}，毛利率 ${pct(r.margin)}（已写入 S11 结算证据）`
      : '未提交分项报价，本次仅记录成本'
    toastBad.value = Number(r.profit) < 0
  } catch (err: any) {
    toast.value = err?.response?.data?.detail || '结账失败'
    toastBad.value = true
  } finally { busy.value = false }
}

onMounted(() => { load(); loadStages() })
watch(orderId, load)
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.fin { max-width: 1080px; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; box-shadow: $shadow-card; }
.head { display: flex; align-items: center; justify-content: space-between; }
.h-l { display: flex; align-items: center; gap: 10px; }
.h-title { font-size: 24px; font-weight: 800; }
.back { width: 28px; height: 28px; border-radius: 8px; border: 1px solid $color-border; background: #fff; color: $color-text-secondary; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.back:hover { border-color: $color-primary; color: $color-primary; }
.h-r { display: flex; align-items: center; gap: 10px; }
.stage { font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 3px 10px; }

.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.kpi { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
.kpi.hl { border-color: $color-primary; background: linear-gradient(180deg, #f7fbff, #fff); }
.k-label { font-size: 15.5px; color: $color-text-secondary; }
.k-val { font-size: 22px; font-weight: 800; letter-spacing: -0.4px; }
.k-val.ok { color: $color-success; }
.k-val.bad { color: $color-danger; }
.k-sub { font-size: 15px; color: $color-text-muted; }
.grade { display: inline-block; border-radius: 4px; padding: 0 6px; margin-right: 4px; font-weight: 600; }
.grade.ok { background: #e8f7ee; color: $color-success; }
.grade.ok-soft { background: #eef6ff; color: $color-primary; }
.grade.warn { background: #fdf3e6; color: $color-warning; }
.grade.bad { background: #fdeceb; color: $color-danger; }
.grade.muted { background: #f2f4f7; color: $color-text-muted; }

.sec { padding: 15px 18px; }
.sec-title { display: flex; align-items: center; gap: 7px; font-size: 16px; font-weight: 700; color: $color-text; margin-bottom: 10px; }
.sec-tag { margin-left: auto; font-size: 15px; color: $color-text-muted; font-weight: 400; }

.tbl { width: 100%; border-collapse: collapse; font-size: 15px; }
.tbl th { text-align: left; font-weight: 600; color: $color-text-secondary; font-size: 15.5px; padding: 7px 8px; border-bottom: 1px solid $color-border; }
.tbl td { padding: 9px 8px; border-bottom: 1px solid #f2f4f7; }
.tbl .num { text-align: right; font-variant-numeric: tabular-nums; }
.tbl .muted, .muted { color: $color-text-muted; }
.tbl .strong { font-weight: 800; }
.num.ok { color: $color-success; }
.num.bad { color: $color-danger; }

.entry { display: flex; align-items: center; gap: 12px; padding: 11px 2px; border-bottom: 1px solid #f2f4f7; }
.entry:last-of-type { border-bottom: none; }
.e-main { flex: 1; display: flex; flex-direction: column; gap: 3px; }
.e-label { font-size: 15.5px; font-weight: 600; }
.e-src { font-size: 15px; color: $color-text-muted; }
.e-amt { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; min-width: 90px; text-align: right; }
.e-bearer { display: flex; align-items: center; gap: 6px; min-width: 250px; justify-content: flex-end; }
.mini { font-size: 15.5px; border: 1px solid $color-border; background: #fff; color: $color-text-secondary; border-radius: 6px; padding: 4px 9px; cursor: pointer; }
.mini:hover { border-color: $color-primary; color: $color-primary; }
.mini:disabled { opacity: .5; cursor: default; }
.bearer { font-size: 15.5px; font-weight: 700; color: $color-primary; }
.mine { font-size: 15.5px; color: $color-text-secondary; }

.g-row { display: flex; align-items: flex-start; gap: 8px; padding: 8px 2px; color: $color-text-secondary; }
.g-row.ok { color: $color-success; }
.g-mid { display: flex; flex-direction: column; gap: 2px; }
.g-label { font-size: 15px; font-weight: 600; }
.g-hint { font-size: 15px; color: $color-text-muted; }
.link-btn { margin-top: 6px; display: inline-flex; align-items: center; gap: 6px; font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border: none; border-radius: 8px; padding: 7px 12px; cursor: pointer; }
.link-btn:disabled { opacity: .55; cursor: not-allowed; }

.toast { margin-top: 10px; font-size: 15.5px; color: $color-primary; background: $color-primary-softer; border-radius: 8px; padding: 9px 12px; }
.toast.bad { color: $color-danger; background: #fdf1f0; }
.empty { padding: 16px; text-align: center; color: $color-text-muted; font-size: 15.5px; }

@media (max-width: 1180px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
}
</style>
