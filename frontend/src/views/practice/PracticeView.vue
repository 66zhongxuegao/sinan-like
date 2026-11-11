<template>
  <div class="prac">
    <header class="page-head">
      <div class="title-wrap">
        <h2>我的订单</h2>
        <span class="count-badge">{{ list.length }}</span>
      </div>
      <div class="filters" role="tablist" aria-label="订单分类">
        <button v-for="t in TABS" :key="t" type="button" role="tab" class="filter"
          :aria-selected="tab === t" :class="{ active: tab === t }" @click="tab = t">{{ t }}</button>
      </div>
    </header>

    <div v-if="ordersLoading" class="state-card">
      <span class="loader-dot" /><span class="loader-dot" /><span class="loader-dot" />
    </div>
    <div v-else-if="ordersError" class="state-card error-state">
      <span>{{ ordersError }}</span>
      <button class="retry" type="button" @click="loadOrders">重试</button>
    </div>
    <div v-else-if="!list.length" class="state-card empty-state">
      <span>{{ cards.length ? '该分类下暂无订单' : '暂无订单' }}</span>
      <RouterLink v-if="!cards.length" class="empty-link" to="/practice/messages">前往抢单</RouterLink>
    </div>

    <TransitionGroup v-else name="card-list" tag="div" class="orders">
      <article v-for="(c, index) in list" :key="c.order.order_id" class="order"
        :class="{ highlighted: c.order.order_id === highlighted, urgent: c.order.urgent }"
        :style="{ '--i': index }" tabindex="0" @click="open(c)" @keydown.enter="open(c)">
        <span v-if="hasNew(c)" class="new-mark" aria-hidden="true" />

        <div class="order-head">
          <div class="person">
            <span class="avatar">{{ initialOf(c.order.customer) }}</span>
            <div class="person-copy">
              <strong class="customer">{{ c.order.customer }}</strong>
              <span class="destination"><span class="dest-label">目的地</span>{{ c.order.destination }}</span>
            </div>
          </div>

          <div class="statuses">
            <span v-if="c.order.urgent" class="urgent-badge"><i />优先处理</span>
            <span v-if="c.order.status !== '正常'" class="status-badge bad">{{ c.order.status }}</span>
          </div>
        </div>

        <div class="order-body">
          <span class="order-id"><SIcon name="layers" :size="16" />{{ c.order.order_id }}</span>

          <div class="progress-line" :class="{ pending: !c.j.stages.value.length }"
            tabindex="0" :aria-label="`当前阶段：${currentNameOf(c)}`"
            @mouseenter="hoveredTrack = c.order.order_id"
            @mouseleave="hoveredTrack = ''"
            @focus="hoveredTrack = c.order.order_id"
            @blur="hoveredTrack = ''">
            <span class="line-segments">
              <i v-for="(segment, si) in stagesOf(c)" :key="segment.id" class="line-segment"
                :class="segment.state" :style="{ '--seg': si }" />
            </span>
            <Transition name="stage-tip">
              <span v-if="hoveredTrack === c.order.order_id" class="stage-tip">当前 · {{ currentNameOf(c) }}</span>
            </Transition>
          </div>

          <div class="order-actions">
            <button class="action ghost" type="button" @click.stop="goto(c.order, 'score')">
              <SIcon name="chart" :size="18" />评分复盘
            </button>
            <button class="action primary" type="button" @click.stop="open(c)">
              进入订单<SIcon name="right" :size="18" />
            </button>
          </div>
        </div>
      </article>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { computed, effectScope, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'
import { useJourney } from '@/composables/useJourney'
import { usePracticeStore } from '@/stores/practice'

const router = useRouter()
const route = useRoute()
const practice = usePracticeStore()

const TABS = ['进行中', '已完成', '已取消'] as const
const tab = ref<string>('进行中')
const ordersLoading = ref(false)
const ordersError = ref('')

interface Card { order: any; j: ReturnType<typeof useJourney> }
const cards = shallowRef<Card[]>([])
const cardScope = effectScope(true)
onUnmounted(() => cardScope.stop())

function isCancelled(o: any) { return o.status === '禁用' }
function isComplete(c: Card) {
  const j = c.j.journey.value
  if (j) return !j.next_action
  return Number(c.order.stage_index || 0) >= 7
}

const list = computed(() => cards.value.filter((c) => {
  if (tab.value === '已取消') return isCancelled(c.order)
  if (isCancelled(c.order)) return false
  if (tab.value === '已完成') return isComplete(c)
  return !isComplete(c)
}))

const hoveredTrack = ref('')

function stagesOf(c: Card) {
  const rows = c.j.stages.value
  if (rows.length) return rows
  return Array.from({ length: 6 }, (_, i) => ({ id: `pending-${i}`, state: 'todo' as const }))
}

function currentNameOf(c: Card) {
  const rows = c.j.stages.value
  if (!rows.length) return '加载中'
  const current = rows.find((stage) => stage.state === 'current')
  if (current) return current.name
  const last = rows[rows.length - 1]
  return last?.state === 'done' ? '已完成' : '待开始'
}

function initialOf(name: unknown) {
  const text = String(name || '').trim()
  return text ? text.slice(0, 1) : '客'
}

async function loadOrders() {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const rows = (await client.get('/practice/orders')).data as any[]
    cardScope.run(() => {
      cards.value = rows.filter((o) => o.claimed === true)
        .map((o) => ({ order: o, j: useJourney(String(o.order_id)) }))
    })
  } catch (e: any) {
    ordersError.value = e?.response?.data?.detail || '订单加载失败，请重试'
    cards.value = []
  } finally {
    ordersLoading.value = false
  }
}

const highlighted = computed(() => String(route.query.grabbed || ''))

function seenKey(id: string) { return 'order_seen_' + id }
function stamp(c: Card) {
  return `${c.order.stage_index}|${c.order.status}|${c.order.urgent ? 1 : 0}|${c.j.currentStageId.value}`
}
function hasNew(c: Card) {
  const seen = localStorage.getItem(seenKey(c.order.order_id))
  return !!seen && seen !== stamp(c)
}
function open(c: Card) {
  localStorage.setItem(seenKey(c.order.order_id), stamp(c))
  practice.setActiveOrder(c.order.order_id)
  router.push(`/practice/orders/${c.order.order_id}`)
}
function goto(o: any, tabName: string) {
  practice.setActiveOrder(o.order_id)
  router.push(`/practice/orders/${o.order_id}/${tabName}`)
}

onMounted(loadOrders)
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.prac {
  width: 100%;
  max-width: 1100px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 28px;
  color: $color-text;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 22px;
  animation: head-in .42s cubic-bezier(.2,.8,.2,1) both;
}
.title-wrap { display: flex; align-items: center; gap: 12px; }
h2 { margin: 0; font-size: 30px; line-height: 1.2; font-weight: 800; letter-spacing: .02em; }
.count-badge {
  min-width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 10px;
  border-radius: 999px;
  background: #e9f3ff;
  color: #0060d6;
  font-size: 17px;
  font-weight: 800;
}
.filters {
  display: flex;
  gap: 5px;
  padding: 5px;
  border-radius: 999px;
  background: #edf4fc;
}
.filter {
  height: 38px;
  padding: 0 17px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #31577f;
  font: inherit;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  transition: background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.filter:hover { color: #005fd8; transform: translateY(-1px); }
.filter.active { background: #fff; color: #005fd8; box-shadow: 0 5px 14px rgba(25, 89, 180, .12); }

.orders { display: flex; flex-direction: column; gap: 14px; }
.order {
  position: relative;
  overflow: hidden;
  padding: 21px 22px 19px;
  border: 1px solid #dbe9f9;
  border-radius: 22px;
  background:
    radial-gradient(circle at 92% 8%, rgba(0,102,255,.055), transparent 29%),
    #fff;
  box-shadow: 0 8px 26px rgba(29, 79, 145, .065);
  cursor: pointer;
  animation: card-in .48s cubic-bezier(.2,.8,.2,1) both;
  animation-delay: calc(var(--i) * 55ms);
  transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
}
.order::before {
  content: "";
  position: absolute;
  left: 0;
  top: 22px;
  bottom: 22px;
  width: 4px;
  border-radius: 0 4px 4px 0;
  background: linear-gradient(180deg, #2a8cff, #0066ff);
  transform: scaleY(.35);
  transform-origin: center;
  opacity: .55;
  transition: transform .24s ease, opacity .24s ease;
}
.order::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(105deg, transparent 35%, rgba(255,255,255,.68) 48%, transparent 61%);
  transform: translateX(-120%);
}
.order:hover {
  transform: translateY(-4px);
  border-color: #8ec1ff;
  box-shadow: 0 17px 38px rgba(16, 88, 184, .14);
}
.order:hover::before { transform: scaleY(1); opacity: 1; }
.order:hover::after { animation: card-shine .7s ease; }
.order.highlighted { border-color: #0066ff; box-shadow: 0 0 0 4px rgba(0,102,255,.1), 0 17px 38px rgba(16,88,184,.13); }
.order:focus-visible { outline: 3px solid #0066ff; outline-offset: 3px; }

.new-mark {
  position: absolute;
  top: 18px;
  left: 18px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #1685ff;
  box-shadow: 0 0 0 0 rgba(22,133,255,.32);
  animation: new-pulse 2.2s ease-out infinite;
}

.order-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.person { display: flex; align-items: center; min-width: 0; gap: 14px; }
.avatar {
  width: 48px;
  height: 48px;
  flex: 0 0 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: linear-gradient(145deg, #e8f4ff, #d7ebff);
  color: #0060d6;
  font-size: 21px;
  font-weight: 800;
  box-shadow: inset 0 0 0 1px rgba(0,102,255,.08);
}
.person-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.customer { color: #12375f; font-size: 21px; line-height: 1.25; font-weight: 800; }
.destination { display: inline-flex; align-items: center; gap: 8px; color: #1e6fc4; font-size: 16px; font-weight: 700; }
.dest-label { padding: 2px 7px; border-radius: 6px; background: #eaf4ff; color: #0a61c5; font-size: 14px; font-weight: 800; }
.statuses { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.status-badge { padding: 5px 11px; border-radius: 999px; font-size: 15px; font-weight: 750; }
.status-badge.ok { color: #087b50; background: #e7f8ef; }
.status-badge.bad { color: #bc3232; background: #ffeded; }
.urgent-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 999px;
  color: #c42e2e;
  background: #fff0f0;
  font-size: 15px;
  font-weight: 800;
}
.urgent-badge i { width: 7px; height: 7px; border-radius: 50%; background: #e14545; animation: urgent-pulse 1.7s ease-in-out infinite; }

.order-body { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 16px 0 0 62px; }
.order-id {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #24547f;
  font-size: 16px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: .01em;
}
.order-id :deep(svg) { color: #5d94cf; }

.progress-line {
  position: relative;
  flex: 1 1 auto;
  min-width: 150px;
  min-height: 46px;
  display: flex;
  align-items: center;
  padding: 8px 2px;
  outline: none;
  cursor: default;
}
.line-segments { display: flex; align-items: center; gap: 7px; width: 100%; }
.line-segment {
  display: block;
  flex: 1 1 0;
  height: 8px;
  border-radius: 999px;
  background: #dceafb;
  transform-origin: left;
  animation: segment-in .42s cubic-bezier(.2,.8,.2,1) both;
  animation-delay: calc(var(--seg) * 38ms);
  transition: background .22s ease, transform .18s ease, box-shadow .22s ease;
}
.line-segment.done { background: linear-gradient(90deg, #0066ff, #2f93ff); }
.line-segment.current {
  background: linear-gradient(90deg, #0d79ff, #49b6ff);
  box-shadow: 0 0 0 3px rgba(22,133,255,.1), 0 3px 10px rgba(22,133,255,.22);
  animation: segment-in .42s cubic-bezier(.2,.8,.2,1) both, segment-glow 1.9s ease-in-out infinite .5s;
}
.progress-line:hover .line-segment,
.progress-line:focus-visible .line-segment { transform: scaleY(1.28); }
.progress-line.pending .line-segment { opacity: .55; }
.stage-tip {
  position: absolute;
  z-index: 4;
  top: -32px;
  left: 50%;
  transform: translateX(-50%);
  padding: 8px 13px;
  border-radius: 10px;
  background: #0a3f78;
  color: #fff;
  font-size: 15px;
  line-height: 1;
  font-weight: 750;
  white-space: nowrap;
  box-shadow: 0 8px 20px rgba(4,52,104,.22);
}
.stage-tip::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -5px;
  width: 10px;
  height: 10px;
  background: #0a3f78;
  transform: translateX(-50%) rotate(45deg);
}
.stage-tip-enter-active, .stage-tip-leave-active { transition: opacity .16s ease, transform .16s ease; }
.stage-tip-enter-from, .stage-tip-leave-to { opacity: 0; transform: translate(-50%, 4px); }

.order-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex: 0 0 auto; }
.action {
  height: 46px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 20px;
  border-radius: 13px;
  font: inherit;
  font-size: 17px;
  font-weight: 750;
  cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease;
}
.action:hover { transform: translateY(-2px); }
.action.ghost { border: 1px solid #b9d7f7; background: #f6fbff; color: #075fc5; }
.action.ghost:hover { border-color: #5da6f7; background: #edf7ff; }
.action.primary {
  border: 1px solid #0066ff;
  background: linear-gradient(135deg, #0066ff, #2b8fff);
  color: #fff;
  box-shadow: 0 8px 18px rgba(0,102,255,.2);
}
.action.primary:hover { box-shadow: 0 12px 24px rgba(0,102,255,.28); }

.state-card {
  min-height: 150px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border: 1px solid #dbe9f9;
  border-radius: 22px;
  background: #fff;
  color: #24547f;
  font-size: 18px;
  font-weight: 700;
}
.loader-dot { width: 9px; height: 9px; border-radius: 50%; background: #1685ff; animation: loader-bounce 1s ease-in-out infinite; }
.loader-dot:nth-child(2) { animation-delay: .13s; }
.loader-dot:nth-child(3) { animation-delay: .26s; }
.error-state, .empty-state { flex-direction: column; }
.retry, .empty-link {
  border: 0;
  border-radius: 999px;
  background: #e8f3ff;
  color: #005fd8;
  padding: 9px 18px;
  font: inherit;
  font-size: 16px;
  font-weight: 750;
  text-decoration: none;
  cursor: pointer;
}
.retry:hover, .empty-link:hover { background: #d9ebff; }

.card-list-enter-active, .card-list-leave-active { transition: opacity .22s ease, transform .22s ease; }
.card-list-enter-from, .card-list-leave-to { opacity: 0; transform: translateY(12px) scale(.985); }
.card-list-leave-active { position: absolute; }
.card-list-move { transition: transform .28s ease; }

@keyframes head-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
@keyframes card-in { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@keyframes segment-in { from { opacity: 0; transform: scaleX(.15); } to { opacity: 1; transform: scaleX(1); } }
@keyframes segment-glow { 0%, 100% { box-shadow: 0 0 0 3px rgba(22,133,255,.1), 0 3px 10px rgba(22,133,255,.22); } 50% { box-shadow: 0 0 0 5px rgba(22,133,255,.16), 0 4px 14px rgba(22,133,255,.3); } }
@keyframes card-shine { from { transform: translateX(-120%); } to { transform: translateX(120%); } }
@keyframes new-pulse { 0% { box-shadow: 0 0 0 0 rgba(22,133,255,.32); } 70% { box-shadow: 0 0 0 8px rgba(22,133,255,0); } 100% { box-shadow: 0 0 0 0 rgba(22,133,255,0); } }
@keyframes urgent-pulse { 0%,100% { transform: scale(1); opacity: .8; } 50% { transform: scale(1.45); opacity: 1; } }
@keyframes loader-bounce { 0%,80%,100% { transform: translateY(0); opacity: .35; } 40% { transform: translateY(-7px); opacity: 1; } }

@media (max-width: 760px) {
  .prac { gap: 16px; }
  .page-head { align-items: flex-start; }
  h2 { font-size: 26px; }
  .count-badge { height: 30px; min-width: 30px; font-size: 15px; }
  .filters { padding: 4px; }
  .filter { height: 35px; padding: 0 13px; font-size: 15px; }
  .order { padding: 18px 17px 17px; border-radius: 20px; }
  .avatar { width: 44px; height: 44px; flex-basis: 44px; border-radius: 14px; font-size: 19px; }
  .customer { font-size: 19px; }
  .destination { font-size: 15px; }
  .order-body { flex-direction: column; align-items: stretch; gap: 10px; margin: 14px 0 0 58px; }
  .order-actions { width: 100%; justify-content: stretch; }
  .progress-line { width: 100%; min-height: 34px; padding: 4px 0 8px; }
  .order-id { font-size: 14px; overflow-wrap: anywhere; }
  .action { flex: 1; height: 44px; padding: 0 12px; font-size: 16px; }
}

@media (max-width: 480px) {
  .page-head { flex-direction: column; gap: 14px; }
  .filters { width: 100%; }
  .filter { flex: 1; }
  .order-head { gap: 10px; }
  .statuses { flex-direction: column; align-items: flex-end; gap: 6px; }
  .status-badge, .urgent-badge { padding: 4px 9px; font-size: 14px; }
  .order-body { margin-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .page-head, .order, .new-mark, .urgent-badge i, .loader-dot, .line-segment { animation: none; }
  .order, .order::before, .order::after, .action, .filter, .line-segment, .stage-tip-enter-active, .stage-tip-leave-active { transition: none; }
  .order:hover { transform: none; }
  .order:hover::after { animation: none; }
}
</style>
