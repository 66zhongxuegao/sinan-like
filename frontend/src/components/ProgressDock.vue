<template>
  <div class="dock">
    <transition name="panel">
      <div v-if="open" class="panel card">
        <div class="p-order">
          <span class="po-label">当前订单</span>
          <select ref="selEl" class="po-sel" :value="oid" @change="pickOrder">
            <option v-for="o in orderList" :key="o.id" :value="o.order_id">
              {{ o.customer }} · {{ o.order_id.slice(-4) }} · {{ o.destination }}
            </option>
          </select>
        </div>

        <div class="p-tabs">
          <button class="p-tab" :class="{ on: tab === 'stages' }" @click="tab = 'stages'">流程进度</button>
          <button class="p-tab" :class="{ on: tab === 'gates' }" @click="tab = 'gates'">完成条件</button>
        </div>

        <!-- 流程进度：六个阶段 + 状态全部来自 GET /practice/orders/{id}/journey；
             该接口不可用时退回 GET /practice/stages 只显示阶段名，进度显示「—」。 -->
        <div v-if="tab === 'stages'" class="p-body">
          <div v-if="loading && !stageRows.length" class="p-state">流程进度加载中…</div>
          <div v-else-if="journeyError && !stageRows.length" class="p-state err">
            <span class="ps-msg">{{ journeyError }}</span>
            <button class="ps-retry" type="button" @click="reload">重试</button>
          </div>
          <div v-else-if="!stageRows.length" class="p-state">该订单暂无流程数据</div>

          <template v-else>
            <button v-if="nextAction" class="p-next" type="button" @click="goNext">
              <span class="pn-k">下一步</span>
              <span class="pn-mid">
                <span class="pn-label">{{ nextAction.label }}</span>
                <span v-if="nextAction.detail" class="pn-detail">{{ nextAction.detail }}</span>
              </span>
              <span class="pn-go">继续 ›</span>
            </button>
            <div v-else-if="progressKnown" class="p-alldone">六阶段已全部完成</div>

            <div v-for="(s, i) in stageRows" :key="s.id" class="s-row"
              :class="{ done: s.state === 'done', cur: s.state === 'current' }">
              <span class="s-dot">{{ i + 1 }}</span>
              <span class="s-name">
                {{ s.name }}
                <span v-if="s.known && s.total_count" class="s-cnt">
                  {{ s.done_count }}/{{ s.total_count }} 项
                </span>
                <span v-for="sub in currentSubs(s)" :key="sub.id" class="s-sub"
                  :class="{ ok: sub.done }" :title="sub.approx ? '按已出团与证据近似判定' : sub.hint">
                  {{ sub.approx ? '≈' : (sub.done ? '✓' : '·') }} {{ sub.name }}
                </span>
              </span>
              <span class="s-st">{{ stateLabel(s) }}</span>
            </div>
          </template>
        </div>

        <!-- 完成条件：门槛判定仍来自 /gates；阶段名优先用六阶段口径 -->
        <div v-else class="p-body">
          <div v-if="gatesError" class="p-state err">
            <span class="ps-msg">{{ gatesError }}</span>
            <button class="ps-retry" type="button" @click="reload">重试</button>
          </div>
          <div v-else-if="!gateTotal && !gates.length" class="p-state">该订单暂无完成条件</div>
          <template v-else>
            <div class="g-head">
              <span class="g-stage">{{ currentStageName || gateStageName || '当前阶段' }}</span>
              <span class="g-cnt">{{ gateDone }}/{{ gates.length }}</span>
            </div>
            <div class="g-bar"><i :style="{ width: gatePct + '%' }" /></div>
            <div v-if="stepEvidence" class="g-where">
              <span class="gw-label">本步产出在哪里</span>{{ stepEvidence }}
            </div>
            <div v-for="g in gates" :key="g.label" class="g-row" :class="{ ok: g.ok }">
              <i class="gk" />
              <span class="g-mid">
                <span class="g-label">{{ g.label }}</span>
                <span v-if="!g.ok && g.where" class="g-where-line">去哪做：{{ g.where }}</span>
              </span>
              <button v-if="!g.ok && g.manual" class="g-do" :disabled="!!confirming" @click="confirmGate(g)">
                {{ confirming === g.action ? '登记中…' : '标记完成' }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </transition>

    <button class="fab" @click="toggle" :class="{ on: open }">
      <span class="fab-halo" />
      <svg class="fab-ring" viewBox="0 0 88 88">
        <circle cx="44" cy="44" r="37" fill="none" stroke="rgba(255,255,255,0.28)" stroke-width="6" />
        <circle cx="44" cy="44" r="37" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"
          :stroke-dasharray="C" :stroke-dashoffset="offset" transform="rotate(-90 44 44)" />
      </svg>
      <span class="fab-txt">{{ progressKnown ? currentIndex + 1 : '—' }}<i v-if="progressKnown">/{{ stageRows.length }}</i></span>
      <span class="fab-sub">流程进度</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import client from '@/api/client'
import { usePracticeStore } from '@/stores/practice'
import { useJourney } from '@/composables/useJourney'
import { useStages } from '@/composables/useStages'

const props = defineProps<{ orderId?: string }>()
const practice = usePracticeStore()
const router = useRouter()

const open = ref(false)
const tab = ref<'stages' | 'gates'>('stages')
const orderList = ref<any[]>([])
const selEl = ref<HTMLSelectElement | null>(null)

const oid = computed(() => props.orderId || practice.activeOrderId)

/** 进度主口径：/practice/orders/{id}/journey */
const {
  stages: journeyStages,
  currentStageId,
  nextAction,
  loading: journeyLoading,
  error: journeyError,
  refresh: refreshJourney,
} = useJourney(oid)

/** 名称兜底：/practice/stages（同一份六阶段契约，前端不内置阶段表） */
const {
  stages: apiStages,
  loading: stagesLoading,
  error: stagesError,
  load: loadStages,
} = useStages()

const loading = computed(() => journeyLoading.value || stagesLoading.value)
/** 只有 journey 到位时才知道真实进度；否则只显示阶段名，进度一律「—」 */
const progressKnown = computed(() => journeyStages.value.length > 0)

interface Row {
  id: string
  name: string
  state: 'done' | 'current' | 'todo'
  done_count: number
  total_count: number
  substeps: Array<{ id: string; name: string; hint: string; done: boolean; state: string; approx?: boolean }>
  known: boolean
}

const stageRows = computed<Row[]>(() => {
  if (journeyStages.value.length) {
    return journeyStages.value.map((s) => ({
      id: s.id, name: s.name, state: s.state,
      done_count: s.done_count, total_count: s.total_count,
      substeps: (s.substeps || []) as Row['substeps'], known: true,
    }))
  }
  return apiStages.value.map((s) => ({
    id: s.id, name: s.name, state: 'todo' as const,
    done_count: 0, total_count: s.substeps.length, substeps: [], known: false,
  }))
})

const currentIndex = computed(() => {
  const i = stageRows.value.findIndex((s) => s.id === currentStageId.value)
  return i < 0 ? 0 : i
})
const currentStageName = computed(() => {
  const row = stageRows.value.find((s) => s.id === currentStageId.value)
  if (row) return row.name
  return apiStages.value.find((s) => s.id === currentStageId.value)?.name || ''
})

/** 当前阶段的子步骤（未开始/已完成的阶段不铺开，免得面板太长） */
function currentSubs(row: Row) {
  return row.known && (row.state === 'current' || row.state === 'done') ? row.substeps : []
}

function stateLabel(row: Row): string {
  if (!row.known) return '—'
  return row.state === 'done' ? '已完成' : row.state === 'current' ? '进行中' : '未开始'
}

// 圆环进度按「已完成子步骤 / 全部子步骤」算，来自 journey 的 done_count / total_count
const C = 2 * Math.PI * 37
const doneSubs = computed(() => journeyStages.value.reduce((a, s) => a + (s.done_count || 0), 0))
const allSubs = computed(() => journeyStages.value.reduce((a, s) => a + (s.total_count || 0), 0))
const offset = computed(() => (allSubs.value ? C * (1 - doneSubs.value / allSubs.value) : C))

// ---------------- 完成条件（/gates） ----------------
const gates = ref<{ action: string; label: string; ok: boolean; where?: string; manual?: boolean }[]>([])
const stepEvidence = ref('')
const gateDone = ref(0)
const gatesError = ref('')
const gateStageName = ref('')
const gateTotal = computed(() => gates.value.length)
const gatePct = computed(() => (gateTotal.value ? Math.round((gateDone.value / gateTotal.value) * 100) : 0))
const confirming = ref('')

async function loadGates() {
  const id = oid.value
  if (!id) { gates.value = []; gateDone.value = 0; stepEvidence.value = ''; gateStageName.value = ''; return }
  try {
    const g = (await client.get(`/practice/orders/${id}/gates`)).data
    gates.value = g.checks || []
    gateDone.value = g.done || 0
    stepEvidence.value = g.step_evidence || ''      // 本步产出该交在哪
    gateStageName.value = g.stage_name || ''
    gatesError.value = ''
  } catch (e: any) {
    gatesError.value = e?.response?.data?.detail || '暂时没加载出来，点这里重试'
  }
}

async function loadOrders() {
  try { orderList.value = (await client.get('/practice/orders')).data } catch { orderList.value = [] }
}

function reload() {
  refreshJourney()
  loadGates()
}

watch(oid, () => { reload(); loadOrders() }, { immediate: true })

// 订单列表是异步来的：列表到位后要把 select 的显示值补上（否则看起来没选订单）
watch([oid, orderList, open], () => {
  const el = selEl.value
  if (!el || !oid.value) return
  if (Array.from(el.options).some((o) => o.value === oid.value)) el.value = oid.value
}, { flush: 'post' })

// 学员每做完一件事（投递、加好友、推进阶段），门控就变了：
// 光在挂载时读一次会一直显示旧进度，所以打开面板时刷新 + 平时每 6 秒轮询一次。
let dockTimer = 0
function refresh() {
  if (document.visibilityState !== 'hidden') reload()
}
onMounted(() => {
  loadStages()
  window.addEventListener('hashchange', refresh)
  dockTimer = window.setInterval(refresh, 6000)
})
onUnmounted(() => {
  window.removeEventListener('hashchange', refresh)
  if (dockTimer) clearInterval(dockTimer)
})

/** 人工确认类门槛：客户认可、客户回签、定金到账、尾款结清——学员确认后才推进平台状态 */
async function confirmGate(g: { action: string }) {
  if (confirming.value || !oid.value) return
  confirming.value = g.action
  try {
    await client.post(`/practice/orders/${oid.value}/actions`, { action: g.action })
    reload()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '登记失败')
  } finally {
    confirming.value = ''
  }
}

function goNext() {
  const route = nextAction.value?.route
  if (route) { practice.setActiveOrder(oid.value); router.push(route) }
}
function pickOrder(e: Event) {
  practice.setActiveOrder((e.target as HTMLSelectElement).value)
}
function toggle() {
  open.value = !open.value
  if (open.value) {
    reload()          // 打开就拉一次，别让学员看到旧门控
    loadOrders()      // 订单列表同理：抢到的新单必须马上出现在下拉框里
  }
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.dock { position: fixed; right: 24px; bottom: 24px; z-index: 60; display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: 14px; box-shadow: 0 18px 44px rgba(16,32,56,0.18); }

.panel { width: 360px; max-height: 500px; display: flex; flex-direction: column; overflow: hidden; }
.p-order { display: flex; align-items: center; gap: 9px; padding: 12px 12px 8px; }
.po-label { font-size: 15px; color: $color-text-muted; flex-shrink: 0; }
.po-sel { flex: 1; height: 36px; border: 1px solid $color-border; border-radius: 6px; padding: 0 10px; font-size: 15.5px; color: $color-text; background: #fff; outline: none; }
.po-sel:focus { border-color: $color-primary; }
.p-tabs { display: flex; gap: 4px; padding: 8px 8px 0; border-bottom: 1px solid $color-border; }
.p-tab { border: none; background: transparent; padding: 10px 15px; font-size: 16px; color: $color-text-secondary; cursor: pointer; border-bottom: 2px solid transparent; }
.p-tab.on { color: $color-primary; font-weight: 700; border-bottom-color: $color-primary; }
.p-body { padding: 10px 12px 14px; overflow-y: auto; }

.p-state { display: flex; align-items: center; gap: 10px; padding: 14px 4px; font-size: 15px; color: $color-text-muted; }
.p-state.err { color: $color-text-secondary; }
.ps-msg { flex: 1; }
.ps-retry { flex-shrink: 0; height: 28px; padding: 0 11px; border-radius: 7px; border: 1px solid $color-primary;
  background: $color-primary-softer; color: $color-primary; font-size: 14px; font-family: inherit; font-weight: 600; cursor: pointer; }
.ps-retry:hover { background: $color-primary; color: #fff; }

.p-next { display: flex; align-items: center; gap: 9px; width: 100%; text-align: left; padding: 10px 11px;
  margin-bottom: 10px; border: 1px solid $color-primary; border-radius: 9px; background: $color-primary-softer;
  font-family: inherit; cursor: pointer; transition: background .16s ease; }
.p-next:hover { background: $color-primary-soft; }
.pn-k { flex-shrink: 0; font-size: 13px; font-weight: 700; color: #fff; background: $color-primary;
  border-radius: 5px; padding: 2px 6px; }
.pn-mid { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pn-label { font-size: 15.5px; font-weight: 700; color: $color-primary; }
.pn-detail { font-size: 14px; color: $color-text-secondary; }
.pn-go { flex-shrink: 0; font-size: 14px; font-weight: 700; color: $color-primary; }
.p-alldone { font-size: 15px; color: $color-success; background: #e8f7ee; border-radius: 8px;
  padding: 8px 10px; margin-bottom: 10px; }

.s-row { display: flex; align-items: flex-start; gap: 10px; padding: 9px 8px; border-radius: 7px; font-size: 15.5px; color: $color-text-muted; }
.s-row.done { color: $color-text-secondary; }
.s-row.cur { background: $color-primary-soft; color: $color-primary; font-weight: 700; }
.s-dot { width: 20px; height: 20px; border-radius: 50%; background: #eef1f5; color: $color-text-muted; font-size: 13px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.s-row.done .s-dot { background: #e8f7ee; color: #12a76a; }
.s-row.cur .s-dot { background: $color-primary; color: #fff; }
.s-name { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.s-cnt { font-size: 14px; font-weight: 400; color: $color-text-muted; }
.s-sub { font-size: 14px; font-weight: 400; color: $color-text-secondary; }
.s-sub.ok { color: #12a76a; }
.s-st { font-size: 14.5px; flex-shrink: 0; }

.g-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.g-stage { font-size: 17px; font-weight: 700; }
.g-cnt { margin-left: auto; font-size: 16px; color: $color-primary; font-weight: 700; }
.g-bar { height: 5px; border-radius: 3px; background: #eef2f7; overflow: hidden; margin-bottom: 10px; }
.g-bar i { display: block; height: 100%; background: linear-gradient(90deg,#2577e3,#4a94ec); border-radius: 3px; transition: width .4s ease; }
.g-row { display: flex; align-items: flex-start; gap: 9px; font-size: 15.5px; color: $color-text-muted; padding: 5px 0; }
.g-mid { display: flex; flex-direction: column; gap: 2px; }
.g-label { color: $color-text-secondary; }
.g-where-line { font-size: 14.5px; color: $color-text-muted; }
.g-do { flex-shrink: 0; align-self: center; height: 28px; padding: 0 11px; border-radius: 7px;
  border: 1px solid $color-primary; background: $color-primary-softer; color: $color-primary;
  font-size: 14px; font-family: inherit; font-weight: 600; cursor: pointer; transition: all .16s ease; }
.g-do:hover:not(:disabled) { background: $color-primary; color: #fff; }
.g-do:disabled { opacity: .55; cursor: default; }
.g-where { font-size: 15px; color: $color-primary; background: $color-primary-softer; border-radius: 7px; padding: 6px 9px; margin-bottom: 8px; }
.gw-label { font-weight: 700; margin-right: 6px; }
.gk { width: 13px; height: 13px; border-radius: 4px; border: 1.5px solid #cfd9e6; flex-shrink: 0; margin-top: 3px; }
.g-row.ok { color: $color-text; }
.g-row.ok .gk { background: #12a76a; border-color: #12a76a; position: relative; }
.g-row.ok .gk::after { content: ''; position: absolute; left: 4px; top: 1px; width: 3px; height: 6px; border: solid #fff; border-width: 0 1.5px 1.5px 0; transform: rotate(45deg); }

.fab {
  position: relative; width: 116px; height: 116px; border-radius: 50%; border: none; cursor: pointer;
  background: linear-gradient(135deg, #2f86ff, #1a63c4);
  box-shadow: 0 14px 34px rgba(37,119,227,0.5), 0 0 0 6px rgba(37,119,227,0.10);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
  transition: transform .16s ease, box-shadow .2s ease;
}
.fab:hover { transform: translateY(-3px) scale(1.03); box-shadow: 0 18px 40px rgba(37,119,227,0.58), 0 0 0 8px rgba(37,119,227,0.14); }
.fab.on { background: linear-gradient(135deg, #1a63c4, #154f9e); }
.fab-halo {
  position: absolute; inset: -8px; border-radius: 50%;
  border: 2px solid rgba(37,119,227,0.35);
  will-change: transform, opacity;
  animation: halo 2.4s ease-in-out infinite;
}
@keyframes halo { 0%,100% { transform: scale(1); opacity: .55; } 50% { transform: scale(1.1); opacity: .15; } }
.fab-ring { position: absolute; inset: 0; width: 116px; height: 116px; }
.fab-txt { position: relative; color: #fff; font-size: 27px; font-weight: 800; line-height: 1; }
.fab-txt i { font-size: 15px; font-style: normal; opacity: .88; }
.fab-sub { position: relative; margin-top: 2px; font-size: 15px; color: rgba(255,255,255,0.9); }

.panel-enter-active { transition: all .2s ease; }
.panel-enter-from { opacity: 0; transform: translateY(10px) scale(.96); }
.panel-leave-active { transition: all .14s ease; }
.panel-leave-to { opacity: 0; transform: translateY(8px) scale(.96); }

/* 窄屏：面板与浮球都不许把页面撑开（390px 视口不能横向溢出） */
@media (max-width: 560px) {
  .dock { right: 10px; bottom: 10px; gap: 8px; }
  .panel { width: min(360px, calc(100vw - 20px)); max-height: min(500px, 68vh); }
  .fab { width: 88px; height: 88px; box-shadow: 0 10px 24px rgba(37,119,227,0.45), 0 0 0 4px rgba(37,119,227,0.10); }
  .fab-ring { width: 88px; height: 88px; }
  .fab-txt { font-size: 21px; }
  .fab-txt i { font-size: 13px; }
  .fab-sub { font-size: 12.5px; }
  .fab-halo { inset: -5px; }
}
</style>
