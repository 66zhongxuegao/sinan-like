<template>
  <div class="learn-page">
    <header class="learn-head">
      <div class="lh-copy">
        <span class="lh-kicker">LEARNING ATLAS</span>
        <h2>学习地图</h2>
        <p v-if="treeMode">技能树看全局结构，路线模式按你的画像和需求决定先学什么。</p>
      </div>
      <div class="mode-switch" role="group" aria-label="学习地图显示模式">
        <button type="button" :class="{ on: mode === 'tree' }" data-role="mode-tree" @click="setMode('tree')">
          <SIcon name="layers" :size="15" /> 技能树模式
        </button>
        <button type="button" :class="{ on: mode === 'route' }" data-role="mode-route" @click="setMode('route')">
          <SIcon name="route" :size="15" /> 路线模式
        </button>
      </div>
    </header>

    <section v-if="mode === 'route'" class="route-shell">
      <div v-if="routeLoading" class="route-state"><i class="loading-ring" />正在读取路线…</div>
      <div v-else-if="routeError" class="route-state error">
        {{ routeError }} <button class="mini" @click="loadRoute">重试</button>
      </div>
      <div v-else-if="!route" class="route-empty">
        <div class="re-icon"><SIcon name="compass" :size="22" /></div>
        <h3>路线还没有生成</h3>
        <p>可以不填需求，直接让管家按画像短板排；也可以说说这次最想补什么。</p>
        <textarea v-model="routeDemand" rows="2" placeholder="例如：下个月接亲子团，重点补报价、节奏和突发处理" />
        <div class="re-actions">
          <button class="tc-btn primary" :disabled="routeBusy" @click="generateRoute()">
            <SIcon name="sparkle" :size="14" /> {{ routeBusy ? '正在排路线…' : '直接生成推荐路线' }}
          </button>
          <button class="tc-btn ghost" @click="setMode('tree')">先看技能树</button>
        </div>
      </div>

      <template v-else>
        <article class="priority-hero">
          <div class="ph-actions">
            <button class="tc-btn ghost" data-role="route-adjust" @click="adjustOpen = true">
              <SIcon name="chat" :size="14" /> 调整路线
            </button>
            <button class="tc-btn ghost" :disabled="routeBusy" @click="generateRoute(true)">重新生成</button>
          </div>
          <div class="ph-number">01</div>
          <div class="ph-copy">
            <h1>
              <span>系统建议你目前应当优先学习</span>
              <strong>{{ priorityItem?.name }}</strong>
            </h1>
            <div v-if="priorityItem" class="ph-tags">
              <span>{{ priorityItem.id }}</span>
              <span>{{ priorityItem.dimension_name }}</span>
              <span>{{ priorityItem.stage_name }}</span>
            </div>
          </div>
          <div v-if="priorityItem" class="ph-score">
            <b>{{ priorityItem.score.toFixed(0) }}</b>
            <span>初始能力</span>
          </div>
          <button v-if="priorityItem" class="ph-start" @click="enter(priorityItem.id)">
            开始学习这一项 <SIcon name="right" :size="15" />
          </button>
        </article>

        <div class="route-stream">
          <div class="stream-title">
            <span>后续学习顺序</span>
            <b>{{ route.items.length - 1 }} 项</b>
          </div>
          <div class="route-lane">
            <section v-for="tier in remainingTiers" :key="tier.key" class="route-tier" :style="{ '--tier': tier.color }">
              <header class="tier-head">
                <i class="tier-dot" />
                <h4>{{ tier.label }}</h4>
                <span class="tier-count">{{ tier.items.length }}</span>
              </header>
              <div class="tier-items">
                <article v-for="item in tier.items" :key="item.id" class="route-item"
                  :style="{ '--delay': ((item.order - 2) * 0.035) + 's' }" @click="enter(item.id)">
                  <span class="ri-order">{{ String(item.order).padStart(2, '0') }}</span>
                  <div class="ri-main">
                    <h5>{{ item.name }}</h5>
                    <div class="ri-meta"><span class="ri-id">{{ item.id }}</span><span>{{ item.dimension_name }}</span></div>
                  </div>
                  <span class="ri-score">{{ item.score.toFixed(0) }}</span>
                  <SIcon name="right" :size="14" class="ri-arrow" />
                </article>
              </div>
            </section>
          </div>
        </div>

        <div v-if="adjustOpen" class="route-dialog-mask" @click.self="adjustOpen = false">
          <section class="route-dialog">
            <header>
              <div><span class="rd-kicker">路线管家</span><h3>和管家说说想怎么调整</h3></div>
              <button class="close-btn" @click="adjustOpen = false"><SIcon name="x" :size="16" /></button>
            </header>
            <div class="rd-log">
              <div v-for="(m, i) in route.messages || []" :key="i" class="rd-msg" :class="m.role">
                <span>{{ m.role === 'user' ? '你' : '管家' }}</span><p>{{ m.text }}</p>
              </div>
            </div>
            <textarea v-model="adjustText" rows="3" placeholder="例如：把跨文化沟通放到第一批，报价放后面；或者这周只有 3 小时" />
            <div class="rd-actions">
              <button class="tc-btn primary" data-role="route-revise" :disabled="routeBusy || !adjustText.trim()" @click="reviseRoute">
                {{ routeBusy ? '正在调整…' : '让管家调整路线' }}
              </button>
            </div>
          </section>
        </div>
      </template>
    </section>

    <div v-show="treeMode" class="map-wrap" ref="wrapRef" :class="{ dragging }" @mousedown="onDown">
      <div class="stage" :style="stageStyle" @click.self="tapCollapse">
        <div class="orbit orbit-a" />
        <div class="orbit orbit-b" />
        <svg class="links" :width="SIZE" :height="SIZE">
          <template v-if="!focused">
            <line v-for="d in dims" :key="'l-' + d.id" :x1="CX" :y1="CY"
              :x2="d.x" :y2="d.y" :stroke="d.color + '3d'" stroke-width="1.5" />
          </template>
          <template v-else>
            <line v-for="p in spNodes" :key="'sl-' + p.id" :x1="CX" :y1="CY"
              :x2="p.x" :y2="p.y" :stroke="focused.color + '52'" stroke-width="1.5" />
          </template>
        </svg>

        <div v-if="!focused" class="node center" :style="{ left: CX + 'px', top: CY + 'px' }" @click.stop="collapse">
          <div class="disc" />
          <svg class="rings" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="46" fill="none" stroke="#d3dce9" stroke-width="4" />
            <circle cx="50" cy="50" r="46" fill="none" stroke="#2577e3" stroke-width="4" stroke-linecap="round"
              :stroke-dasharray="C43" :stroke-dashoffset="off(46, overall.teach)" transform="rotate(-90 50 50)" />
            <circle cx="50" cy="50" r="37" fill="none" stroke="#d3dce9" stroke-width="3.5" />
            <circle cx="50" cy="50" r="37" fill="none" stroke="#e08a1e" stroke-width="3.5" stroke-linecap="round"
              :stroke-dasharray="C30" :stroke-dashoffset="off(37, overall.real)" transform="rotate(-90 50 50)" />
          </svg>
          <div class="txt center-txt">
            <div class="t-name">总掌握度</div>
            <div class="t-vals"><span class="tv teach">{{ overall.teach }}</span><span class="tv real">{{ overall.real }}</span></div>
          </div>
        </div>

        <div v-for="(d, i) in dims" :key="d.id" class="node dim"
          :class="{ on: focusedId === d.id, gone: focused && focusedId !== d.id }"
          :style="{ left: dimPos(d).x + 'px', top: dimPos(d).y + 'px', '--dim': d.color, animationDelay: (0.06 * (i + 1)) + 's' }"
          @click.stop="focusDim(d.id)">
          <div class="disc" />
          <svg class="rings" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="46" fill="none" stroke="#d3dce9" stroke-width="4" />
            <circle cx="50" cy="50" r="46" fill="none" stroke="#2577e3" stroke-width="4" stroke-linecap="round"
              :stroke-dasharray="C43" :stroke-dashoffset="off(46, d.teach)" transform="rotate(-90 50 50)" />
            <circle cx="50" cy="50" r="37" fill="none" stroke="#d3dce9" stroke-width="3.5" />
            <circle cx="50" cy="50" r="37" fill="none" stroke="#e08a1e" stroke-width="3.5" stroke-linecap="round"
              :stroke-dasharray="C30" :stroke-dashoffset="off(37, d.real)" transform="rotate(-90 50 50)" />
          </svg>
          <div class="txt dim-txt">
            <div class="t-name">{{ d.short }}</div>
            <div class="t-vals"><span class="tv teach">{{ d.teach }}</span><span class="tv real">{{ d.real }}</span></div>
          </div>
        </div>

        <transition-group name="pop">
          <div v-for="(s, i) in spNodes" :key="s.id" class="node sp"
            :style="{ left: s.x + 'px', top: s.y + 'px', '--dim': focused ? focused.color : '#2577e3', animationDelay: (0.045 * i) + 's' }"
            @click.stop="selectSp(s)">
            <div class="disc" />
            <svg class="rings" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="46" fill="none" stroke="#d3dce9" stroke-width="4" />
              <circle cx="50" cy="50" r="46" fill="none" stroke="#2577e3" stroke-width="4" stroke-linecap="round"
                :stroke-dasharray="C43" :stroke-dashoffset="off(46, s.teach)" transform="rotate(-90 50 50)" />
              <circle cx="50" cy="50" r="37" fill="none" stroke="#d3dce9" stroke-width="3.5" />
              <circle cx="50" cy="50" r="37" fill="none" stroke="#e08a1e" stroke-width="3.5" stroke-linecap="round"
                :stroke-dasharray="C30" :stroke-dashoffset="off(37, s.real)" transform="rotate(-90 50 50)" />
            </svg>
            <div class="txt sp-txt">
              <div class="spn">{{ s.label }}</div>
              <div class="spv"><span class="tv teach">{{ s.teach }}</span><span class="tv real">{{ s.real }}</span></div>
            </div>
          </div>
        </transition-group>

        <button class="reset-btn" @click.stop="resetView"><SIcon name="compass" :size="13" /> 复位</button>
        <div class="legend">
          <span class="lg"><i class="sw teach" />教学</span>
          <span class="lg"><i class="sw real" />实战</span>
        </div>

        <transition name="pop">
          <div v-if="focused" class="crumb" @click.stop="collapse">
            <span class="c-dot" :style="{ background: focused.color }" />{{ focused.id }} · {{ focused.name }}
            <span class="c-back">返回总览</span>
          </div>
        </transition>

        <transition name="pop">
          <div v-if="selected" class="pop-card" :style="popStyle" @click.stop>
            <div class="pc-head">
              <span class="pc-id">{{ selected.id }}</span>
              <span v-if="!selected.bridge" class="pc-cp" :class="selected.cp">{{ selected.cp === 'B' ? '问题应对' : '动作' }}</span>
            </div>
            <div class="pc-name">{{ selected.name }}</div>
            <div class="pc-rows">
              <template v-if="!selected.bridge">
                <div class="pc-row"><i class="sw teach" />教学掌握度<b>{{ selected.teach }}%</b></div>
                <div class="pc-row"><i class="sw real" />实战掌握度<b>{{ selected.real }}%</b></div>
              </template>
              <div v-else class="pc-desc">{{ selected.desc }}</div>
            </div>
            <div v-if="(selected.events || []).length" class="pc-events">
              <div class="pc-ev-title">涉及突发事件</div>
              <div v-for="e in selected.events" :key="e.code" class="pc-ev" :class="{ off: !e.unlocked }">
                <i class="ev-dot" /><span class="ev-name">{{ e.title }}</span>
                <span class="ev-tag">{{ e.unlocked ? '已解锁' : '未解锁' }}</span>
              </div>
              <div v-if="(selected.events || []).some((e: any) => !e.unlocked)" class="pc-ev-hint">
                教学掌握度达到 60% 后解锁对应事件。
              </div>
            </div>
            <div v-else class="pc-ev-none">本技能点不涉及突发事件</div>
            <div class="pc-acts">
              <router-link v-if="focused && focused.id === 'BRIDGE'" class="tc-btn pc-btn"
                :to="`/learn/thread/C8.2`">进入学习</router-link>
              <button v-else class="tc-btn pc-btn" @click.stop="enter(selected.id)">进入学习</button>
              <router-link v-if="selected.bridge" class="tc-btn ghost pc-btn"
                :to="`/learn/bridge/${selected.id}`">看内容</router-link>
            </div>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'
import SIcon from '@/components/SIcon.vue'

const router = useRouter()
const pageRoute = useRoute()
const SIZE = 1600
const CX = SIZE / 2
const CY = SIZE / 2

const raw = ref<any[]>([])
const userStore = useUserStore()
const focusedId = ref('')
const selected = ref<any>(null)
const mode = ref<'tree' | 'route'>(pageRoute.query.mode === 'tree' ? 'tree' : 'route')
const treeMode = computed(() => mode.value === 'tree')
const route = ref<any>(null)
const routeLoading = ref(false)
const routeBusy = ref(false)
const routeError = ref('')
const routeDemand = ref('')
const adjustOpen = ref(false)
const adjustText = ref('')
const priorityItem = computed<any>(() => route.value?.items?.[0] || null)
const remainingTiers = computed(() => (route.value?.tiers || []).map((tier: any) => ({
  ...tier,
  items: (tier.items || []).filter((item: any) => item.order > 1),
})).filter((tier: any) => tier.items.length))

async function loadRoute() {
  routeLoading.value = true
  routeError.value = ''
  try {
    const r = (await client.get(`/profiles/${userStore.userId}/learning-route`)).data
    route.value = r.route || null
    if (route.value?.demand) routeDemand.value = route.value.demand
  } catch (e: any) {
    routeError.value = e?.response?.data?.detail || '学习路线暂时无法读取'
  } finally { routeLoading.value = false }
}

async function generateRoute(force = false) {
  if (routeBusy.value) return
  if (!force && route.value) return
  routeBusy.value = true
  routeError.value = ''
  try {
    const r = (await client.post(`/profiles/${userStore.userId}/learning-route`, {
      demand: routeDemand.value.trim(),
    })).data
    route.value = r.route
    if (r.route?.demand) routeDemand.value = r.route.demand
  } catch (e: any) {
    routeError.value = e?.response?.data?.detail || '路线生成失败，请稍后重试'
  } finally { routeBusy.value = false }
}

async function reviseRoute() {
  const message = adjustText.value.trim()
  if (!message || routeBusy.value) return
  routeBusy.value = true
  routeError.value = ''
  try {
    const r = (await client.post(`/profiles/${userStore.userId}/learning-route/revise`, { message })).data
    route.value = r.route
    routeDemand.value = r.route?.demand || routeDemand.value
    adjustText.value = ''
  } catch (e: any) {
    routeError.value = e?.response?.data?.detail || '路线调整失败，请稍后重试'
  } finally { routeBusy.value = false }
}

function setMode(next: 'tree' | 'route') {
  mode.value = next
  router.replace({ path: pageRoute.path, query: { ...pageRoute.query, mode: next } })
  if (next === 'tree') nextTick(fitOverview)
  else void loadRoute()
}

const COLORS: Record<string, string> = {
  C1: '#2577e3', C2: '#12a76a', C3: '#7a5af8', C4: '#e08a1e',
  C5: '#e0567a', C6: '#0ea5b7', C7: '#64748b', C8: '#8b5cf6',
  BRIDGE: '#0ea5b7',
}
const SHORT: Record<string, string> = {
  C1: '沟通信任', C2: '需求洞察', C3: '方案能力', C4: '资源整合',
  C5: '报价利润', C6: '应急解决', C7: '合规效率', C8: '跨文化',
  BRIDGE: '文化桥',
}
/* 第二层：半径长短差异大 + 角度散 */
const RAD = [285, 545, 330, 585, 300, 555, 345, 575, 620]
const ANG = [-103, -27, -4, 49, 63, 129, 152, 213, 250]

const C43 = 2 * Math.PI * 46
const C30 = 2 * Math.PI * 37
function off(r: number, v: number) { return 2 * Math.PI * r * (1 - Math.max(0, Math.min(100, v)) / 100) }

function hash(id: string, salt: string) {
  let h = 0
  for (const ch of id + salt) h = (h * 31 + ch.charCodeAt(0)) % 100003
  return h
}
function v(id: string, kind: string) { return (kind === 'teach' ? 44 : 36) + (hash(id, kind) % 54) }
function avg(list: number[]) { return list.length ? Math.round(list.reduce((a, b) => a + b, 0) / list.length) : 0 }
function shortName(name: string) { return (name || '').split('（')[0].slice(0, 6) }

const dims = computed(() =>
  raw.value.map((d, i) => {
    const ang = ANG[i % ANG.length] * Math.PI / 180
    const r = RAD[i % RAD.length]
    return {
      ...d, color: COLORS[d.id] || '#2577e3', short: SHORT[d.id] || d.name,
      teach: d.teach, real: d.real,
      x: CX + r * Math.cos(ang), y: CY + r * Math.sin(ang),
    }
  })
)
const overall = ref({ teach: 0, real: 0 })
const focused = computed(() => dims.value.find((d) => d.id === focusedId.value) || null)

/** 第三层布局（纯计算，供渲染与「自动适配」共用） */
function spLayout(d: any) {
  const n = d.points.length
  const spread = (n >= 8 ? 322 : n >= 6 ? 285 : n >= 4 ? 215 : 155) * Math.PI / 180
  const start = -90 * Math.PI / 180
  return d.points.map((p: any, i: number) => {
    const tt = n === 1 ? 0.5 : i / (n - 1)
    const ang = start + (tt - 0.5) * spread
    const r = [420, 520, 470][i % 3]
    return {
      id: p.id, name: p.name, label: shortName(p.name), cp: p.checkpoint,
      teach: p.teach, real: p.real,
      x: CX + r * Math.cos(ang), y: CY + r * Math.sin(ang),
    }
  })
}
const spNodes = computed(() => (focused.value ? spLayout(focused.value) : []))

/* ── 视图：按「实际内容范围」自动适配 ── */
const wrapRef = ref<HTMLElement | null>(null)
const dragging = ref(false)
const view = ref({ x: 0, y: 0, s: 1 })
let sx = 0, sy = 0, vx0 = 0, vy0 = 0, moved = 0

const stageStyle = computed(() => ({
  width: SIZE + 'px', height: SIZE + 'px', transformOrigin: '0 0',
  transform: `translate(${view.value.x}px, ${view.value.y}px) scale(${view.value.s})`,
}))

/** 把给定节点集合（含留白）缩放到容器内，尽量占满 */
function fitTo(nodes: { x: number; y: number }[], pad = 120) {
  const wrap = wrapRef.value
  if (!wrap || !nodes.length) return
  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y)
  const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad
  const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad
  const w = maxX - minX, h = maxY - minY
  const vw = wrap.clientWidth || 900, vh = wrap.clientHeight || 640
  const s = Math.min(vw / w, vh / h) * 0.94
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
  view.value = { s, x: vw / 2 - cx * s, y: vh / 2 - cy * s }
}

function dimPos(d: any) {
  return focusedId.value === d.id ? { x: CX, y: CY } : { x: d.x, y: d.y }
}

function fitOverview() {
  fitTo([{ x: CX, y: CY }, ...dims.value.map((d: any) => ({ x: d.x, y: d.y }))])
}
function fitFocus(d: any) {
  fitTo([{ x: CX, y: CY }, ...spLayout(d).map((p: any) => ({ x: p.x, y: p.y }))], 100)
}
function resetView() { focusedId.value = ''; selected.value = null; nextTick(fitOverview) }

function onDown(e: MouseEvent) {
  const el = e.target as HTMLElement
  if (el.closest('.node, .pop-card, .crumb, .legend, .reset-btn')) return
  dragging.value = true; moved = 0
  sx = e.clientX; sy = e.clientY
  vx0 = view.value.x; vy0 = view.value.y
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  e.preventDefault()
}
function onMove(e: MouseEvent) {
  if (!dragging.value) return
  const dx = e.clientX - sx, dy = e.clientY - sy
  moved = Math.max(moved, Math.abs(dx) + Math.abs(dy))
  view.value = { ...view.value, x: vx0 + dx, y: vy0 + dy }
}
function onUp() {
  dragging.value = false
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
}
function onWheel(e: WheelEvent) {
  e.preventDefault()
  const wrap = wrapRef.value
  if (!wrap) return
  const rect = wrap.getBoundingClientRect()
  const mx = e.clientX - rect.left, my = e.clientY - rect.top
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
  const ns = Math.min(2.6, Math.max(0.25, view.value.s * factor))
  const k = ns / view.value.s
  view.value = { s: ns, x: mx - (mx - view.value.x) * k, y: my - (my - view.value.y) * k }
}
function tapCollapse() { if (moved > 6) { moved = 0; return } collapse() }

const popStyle = computed(() => {
  const s = selected.value
  if (!s) return {}
  return { left: Math.min(SIZE - 250, Math.max(12, s.x + 44)) + 'px', top: Math.min(SIZE - 200, Math.max(12, s.y - 40)) + 'px' }
})

function focusDim(id: string) {
  selected.value = null
  if (focusedId.value === id) { focusedId.value = ''; nextTick(fitOverview); return }
  focusedId.value = id
  const d = dims.value.find((x: any) => x.id === id)
  if (d) nextTick(() => fitFocus(d))
}
function collapse() { if (!focusedId.value) return; focusedId.value = ''; selected.value = null; nextTick(fitOverview) }
function selectSp(s: any) { selected.value = s }
function enter(id: string) {
  router.push(`/learn/thread/${id}`)
}

function onResize() { focused.value ? fitFocus(focused.value) : fitOverview() }

onMounted(async () => {
  try {
    const res = (await client.get('/learn/map', { params: { user_id: userStore.userId } })).data
    const dimList = res.dimensions || []
    try {
      const bridges = (await client.get('/learn/culture-bridges')).data as any[]
      if (bridges?.length) {
        dimList.push({
          id: 'BRIDGE', name: '文化桥', short: '文化桥',
          teach: 0, real: 0, bridge: true,
          points: bridges.map((b: any) => ({
            id: b.code, name: b.name, label: b.name, cp: 'B', bridge: true,
            teach: 0, real: 0, desc: b.summary, events: [],
          })),
        })
      }
    } catch { /* 文化桥拿不到不影响主图 */ }
    raw.value = dimList
    overall.value = res.overall || { teach: 0, real: 0 }
  } catch { raw.value = [] }
  await loadRoute()
  await nextTick()
  if (mode.value === 'tree') fitOverview()
  window.addEventListener('resize', onResize)
  wrapRef.value?.addEventListener('wheel', onWheel, { passive: false })
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  wrapRef.value?.removeEventListener('wheel', onWheel)
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.learn-page { display: flex; flex-direction: column; gap: 14px; width: 100%; }
.learn-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 4px 2px 2px; }
.lh-copy { min-width: 0; }
.lh-kicker { color: #7b91ae; font-size: 11px; font-weight: 800; letter-spacing: .16em; }
.lh-copy h2 { margin: 5px 0 2px; font-size: 28px; line-height: 1.2; color: #17243a; }
.lh-copy p { margin: 0; color: #74849a; font-size: 14px; line-height: 1.6; }
.mode-switch { flex-shrink: 0; display: inline-flex; padding: 4px; gap: 4px; border-radius: 12px; border: 1px solid #dbe5f1; background: #edf3fa; }
.mode-switch button { display: inline-flex; align-items: center; gap: 7px; height: 36px; padding: 0 14px; border: 1px solid transparent; border-radius: 9px;
  background: transparent; color: #687b93; font: inherit; font-size: 14px; cursor: pointer; white-space: nowrap; transition: all .16s ease; }
.mode-switch button:hover { color: #2577e3; }
.mode-switch button.on { background: #fff; color: #1f5fb8; border-color: #c5daf5; box-shadow: 0 3px 8px rgba(35,80,138,.09); font-weight: 700; }
.route-shell { min-height: calc(100vh - 300px); border: 1px solid #e3e9f1; border-radius: 16px; padding: 20px;
  background: linear-gradient(180deg, #f8fbfe 0%, #f2f6fb 100%); }
.route-state { min-height: 220px; display: flex; align-items: center; justify-content: center; gap: 9px; color: #73869e; font-size: 15px; }
.route-state.error { color: #b5473d; }
.loading-ring { width: 20px; height: 20px; border-radius: 50%; border: 2px solid #c9ddf5; border-top-color: #2577e3; animation: spin .8s linear infinite; }
.route-empty { max-width: 680px; margin: 72px auto; padding: 34px; text-align: center; border-radius: 16px; background: #fff; border: 1px solid #dee8f4; box-shadow: 0 16px 48px rgba(37,78,133,.08); }
.re-icon { width: 48px; height: 48px; margin: 0 auto 12px; display: grid; place-items: center; border-radius: 14px; color: #2577e3; background: #eaf3fe; }
.route-empty h3 { margin: 0 0 7px; font-size: 22px; color: #1c2e47; }
.route-empty p { margin: 0 0 16px; color: #788aa1; line-height: 1.7; }
.route-empty textarea { width: 100%; border: 1px solid #d5e0ed; border-radius: 10px; padding: 11px 13px; font: inherit; font-size: 15px; line-height: 1.6; resize: vertical; outline: none; }
.route-empty textarea:focus { border-color: #2577e3; box-shadow: 0 0 0 3px rgba(37,119,227,.1); }
.re-actions { display: flex; justify-content: center; gap: 9px; margin-top: 12px; flex-wrap: wrap; }
.tc-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; padding: 0 15px; border: 1px solid transparent; border-radius: 8px; font: inherit; font-size: 14px; cursor: pointer; }
.tc-btn.primary { color: #fff; background: #2577e3; box-shadow: 0 5px 14px rgba(37,119,227,.22); }
.tc-btn.primary:hover:not(:disabled) { background: #1a63c4; }
.tc-btn.ghost { color: #3f5c7d; background: #fff; border-color: #d8e2ee; }
.tc-btn.ghost:hover:not(:disabled) { color: #2577e3; border-color: #a9cafa; }
.tc-btn:disabled { opacity: .5; cursor: default; }
.mini { border: 1px solid #d9e3ef; background: #fff; color: #3f5c7d; border-radius: 7px; padding: 5px 10px; font: inherit; font-size: 13px; cursor: pointer; }
.priority-hero { position: relative; isolation: isolate; overflow: hidden; min-height: 330px; display: grid; grid-template-columns: 108px minmax(0,1fr) 140px; grid-template-rows: auto 1fr auto; gap: 12px 20px; padding: 28px 32px 26px; border-radius: 22px;
  border: 1px solid #f0d9b9; background: linear-gradient(125deg, #fffdf8 0%, #fff8ed 42%, #edf5ff 100%); box-shadow: 0 22px 60px rgba(48,88,140,.13), inset 0 1px 0 #fff;
  animation: heroIn .55s cubic-bezier(.2,.8,.2,1) both; }
.priority-hero::before { content: ''; position: absolute; z-index: -1; width: 380px; height: 380px; right: -100px; top: -145px; border-radius: 50%; background: radial-gradient(circle, rgba(224,138,30,.22), rgba(224,138,30,0) 68%); animation: glowBreath 6s ease-in-out infinite alternate; }
.priority-hero::after { content: ''; position: absolute; inset: 0; z-index: -1; background: linear-gradient(105deg, transparent 30%, rgba(255,255,255,.55) 46%, transparent 62%); transform: translateX(-110%); animation: sheen 6.5s ease-in-out 1.1s infinite; }
.ph-actions { grid-column: 3; grid-row: 1; display: flex; justify-content: flex-end; align-items: flex-start; gap: 8px; flex-wrap: wrap; position: relative; z-index: 2; }
.ph-actions .tc-btn { background: rgba(255,255,255,.78); backdrop-filter: blur(6px); }
.ph-number { grid-column: 1; grid-row: 1 / 4; align-self: center; color: #e08a1e; font-size: 76px; line-height: 1; font-weight: 900; letter-spacing: -.08em; text-shadow: 0 8px 28px rgba(224,138,30,.15); animation: numberIn .7s .08s cubic-bezier(.2,.8,.2,1) both; }
.ph-copy { grid-column: 2; grid-row: 1 / 3; align-self: center; min-width: 0; position: relative; z-index: 2; }
.ph-copy h1 { margin: 0; max-width: 920px; color: #162a44; }
.ph-copy h1 span { display: block; font-size: 19px; line-height: 1.5; font-weight: 650; color: #b46b10; letter-spacing: .01em; }
.ph-copy h1 strong { display: block; margin-top: 9px; font-size: clamp(34px, 4vw, 54px); line-height: 1.18; letter-spacing: -.035em; color: #172a44; }
.ph-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 18px; }
.ph-tags span { border-radius: 999px; padding: 6px 12px; font-size: 14px; font-weight: 650; color: #36506d; background: rgba(255,255,255,.75); border: 1px solid rgba(183,202,225,.75); }
.ph-tags span:first-child { color: #b4690e; border-color: #efcf9e; background: #fff7e9; font-family: ui-monospace, Consolas, monospace; }
.ph-score { grid-column: 3; grid-row: 2; align-self: center; justify-self: end; width: 120px; height: 120px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #a85f08; background: radial-gradient(circle at 35% 28%, #fff, #fff4df 58%, #ffe6bd); border: 1px solid #f2d3a2; box-shadow: 0 14px 30px rgba(209,130,25,.16); position: relative; z-index: 2; animation: scoreIn .65s .16s cubic-bezier(.2,.8,.2,1) both; }
.ph-score b { font-size: 39px; line-height: 1; font-weight: 900; letter-spacing: -.05em; }
.ph-score span { margin-top: 7px; font-size: 14px; font-weight: 700; }
.ph-start { grid-column: 2 / 4; grid-row: 3; justify-self: start; display: inline-flex; align-items: center; gap: 10px; margin-top: 10px; padding: 12px 20px; border: 0; border-radius: 11px; cursor: pointer; color: #fff; background: linear-gradient(135deg, #f0a02f, #d97908); font: inherit; font-size: 16px; font-weight: 800; box-shadow: 0 10px 24px rgba(217,121,8,.26); transition: transform .16s ease, box-shadow .16s ease; animation: startIn .55s .24s cubic-bezier(.2,.8,.2,1) both; }
.ph-start:hover { transform: translateY(-2px); box-shadow: 0 14px 30px rgba(217,121,8,.34); }
.route-stream { margin-top: 26px; animation: streamIn .45s .18s cubic-bezier(.2,.8,.2,1) both; }
.stream-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 6px 13px; color: #243a57; font-size: 21px; font-weight: 800; }
.stream-title b { color: #2577e3; font-size: 15px; border-radius: 999px; background: #eef5ff; padding: 5px 11px; }
.route-lane { position: relative; padding-left: 14px; }
.route-lane::before { content: ''; position: absolute; left: 24px; top: 20px; bottom: 24px; width: 3px; border-radius: 99px; background: linear-gradient(#e08a1e, #2577e3 36%, #12a76a 68%, #aebbc9); transform-origin: top; animation: lineGrow .8s .25s cubic-bezier(.25,.8,.25,1) both; }
.route-tier { position: relative; margin-bottom: 26px; }
.tier-head { display: flex; align-items: center; gap: 10px; margin: 0 0 10px; padding-left: 4px; }
.tier-dot { width: 14px; height: 14px; flex-shrink: 0; border-radius: 50%; background: var(--tier); box-shadow: 0 0 0 5px color-mix(in srgb, var(--tier) 14%, white); }
.tier-head h4 { margin: 0; color: #26384f; font-size: 17px; }
.tier-count { margin-left: auto; color: var(--tier); border: 1px solid color-mix(in srgb, var(--tier) 30%, white); background: color-mix(in srgb, var(--tier) 8%, white); border-radius: 999px; padding: 3px 10px; font-size: 13px; font-weight: 800; }
.tier-items { display: flex; flex-direction: column; gap: 9px; padding-left: 32px; }
.route-item { position: relative; display: grid; grid-template-columns: 46px minmax(0,1fr) 54px 18px; gap: 14px; align-items: center; padding: 14px 16px 14px 12px; border-radius: 14px; border: 1px solid #e1e8f1; background: #fff; cursor: pointer; transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease; animation: itemIn .4s var(--delay) cubic-bezier(.2,.8,.2,1) both; }
.route-item::before { content: ''; position: absolute; left: -28px; top: 50%; width: 20px; border-top: 1px dashed color-mix(in srgb, var(--tier) 58%, #d9e1eb); }
.route-item:hover { transform: translateX(4px); border-color: color-mix(in srgb, var(--tier) 52%, #d8e2ed); box-shadow: 0 10px 24px rgba(37,72,120,.09); }
.ri-order { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; background: color-mix(in srgb, var(--tier) 10%, white); color: var(--tier); font-size: 15px; font-weight: 900; font-variant-numeric: tabular-nums; }
.ri-main { min-width: 0; }
.ri-meta { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 6px; color: #5f7894; font-size: 13px; font-weight: 600; }
.ri-id { color: var(--tier); font-family: ui-monospace, Consolas, monospace; font-weight: 800; background: color-mix(in srgb, var(--tier) 8%, white); border-radius: 6px; padding: 2px 7px; }
.ri-main h5 { margin: 0; color: #1f3149; font-size: 17px; line-height: 1.4; }
.ri-score { justify-self: end; color: #263b57; font-size: 22px; font-weight: 900; line-height: 1; font-variant-numeric: tabular-nums; }
.ri-arrow { color: #a9b7c8; transition: color .16s ease, transform .16s ease; }
.route-item:hover .ri-arrow { color: var(--tier); transform: translateX(2px); }
@keyframes heroIn { from { opacity: 0; transform: translateY(18px) scale(.985); } to { opacity: 1; transform: none; } }
@keyframes numberIn { from { opacity: 0; transform: translateX(-16px); } to { opacity: 1; transform: none; } }
@keyframes scoreIn { from { opacity: 0; transform: scale(.7) rotate(-8deg); } to { opacity: 1; transform: none; } }
@keyframes startIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes streamIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes lineGrow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@keyframes itemIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes glowBreath { from { transform: scale(.94); opacity: .72; } to { transform: scale(1.08); opacity: 1; } }
@keyframes sheen { 0%, 45% { transform: translateX(-110%); } 62%, 100% { transform: translateX(110%); } }
.route-dialog-mask { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 20px; background: rgba(16,29,47,.44); backdrop-filter: blur(3px); }
.route-dialog { width: min(640px, 100%); max-height: 82vh; display: flex; flex-direction: column; border-radius: 16px; background: #fff; box-shadow: 0 28px 80px rgba(14,34,60,.3); overflow: hidden; }
.route-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 20px 22px 14px; border-bottom: 1px solid #e7edf5; }
.rd-kicker { color: #2577e3; font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.route-dialog h3 { margin: 4px 0 0; font-size: 21px; color: #1d304a; }
.close-btn { border: 0; background: none; color: #8d9cae; cursor: pointer; padding: 2px; }
.rd-log { flex: 1; min-height: 150px; max-height: 320px; overflow-y: auto; padding: 16px 22px; display: flex; flex-direction: column; gap: 10px; background: #fafcff; }
.rd-msg { max-width: 86%; border-radius: 12px; padding: 10px 12px; background: #edf4fd; }
.rd-msg.user { align-self: flex-end; background: #fff3e3; }
.rd-msg > span { color: #8899ad; font-size: 11px; font-weight: 700; }
.rd-msg p { margin: 4px 0 0; color: #344a64; font-size: 14px; line-height: 1.65; }
.route-dialog > textarea { margin: 14px 22px 0; min-height: 88px; resize: vertical; border: 1px solid #d5e0ed; border-radius: 10px; padding: 11px 13px; font: inherit; font-size: 14px; line-height: 1.6; outline: none; }
.route-dialog > textarea:focus { border-color: #2577e3; box-shadow: 0 0 0 3px rgba(37,119,227,.1); }
.rd-actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 22px 20px; color: #93a0b2; font-size: 12px; }
.map-wrap {
  overflow: hidden; border-radius: $radius-lg; cursor: grab; position: relative;
  height: calc(100vh - 302px); min-height: 520px;
  background:
    radial-gradient(circle at 50% 50%, rgba(37,119,227,0.09), transparent 52%),
    radial-gradient(circle at 50% 50%, #f8fbfe, #edf2f9);
}
.map-wrap.dragging { cursor: grabbing; }
.map-wrap.dragging .node { pointer-events: none; }
.stage { position: absolute; left: 0; top: 0; transition: transform .5s cubic-bezier(.34,1.08,.36,1); }
.map-wrap.dragging .stage { transition: none; }
.orbit { position: absolute; left: 50%; top: 50%; border-radius: 50%; border: 1px dashed rgba(37,119,227,0.13); transform: translate(-50%,-50%); pointer-events: none; }
.orbit-a { width: 620px; height: 620px; will-change: transform; backface-visibility: hidden; animation: spin 110s linear infinite; }
.orbit-b { width: 900px; height: 900px; border-style: dotted; will-change: transform; backface-visibility: hidden; animation: spin-r 170s linear infinite; }
@keyframes spin { to { transform: translate(-50%,-50%) rotate(360deg); } }
@keyframes spin-r { to { transform: translate(-50%,-50%) rotate(-360deg); } }

.links { position: absolute; inset: 0; pointer-events: none; }

.node { position: absolute; transform: translate(-50%,-50%); cursor: pointer; transition: left .55s cubic-bezier(.34,1.12,.36,1), top .55s cubic-bezier(.34,1.12,.36,1), opacity .3s ease, filter .2s ease; animation: nodeIn .5s cubic-bezier(.34,1.35,.4,1) backwards; }
@keyframes nodeIn { from { opacity: 0; transform: translate(-50%,-50%) scale(.35); } to { opacity: 1; transform: translate(-50%,-50%) scale(1); } }
.node:hover { filter: drop-shadow(0 8px 20px rgba(37,119,227,0.30)); }
.node.gone { opacity: 0; visibility: hidden; pointer-events: none; }
.disc { position: absolute; inset: 0; border-radius: 50%; background: #fff; border: 1px solid #d6e0ed; box-shadow: 0 4px 14px rgba(37,119,227,0.14); }
.rings { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }

.center { width: 249px; height: 249px; z-index: 3; }
.dim { width: 165px; height: 165px; z-index: 2; }
.dim.on { width: 243px; height: 243px; z-index: 6; }
.sp { width: 183px; height: 183px; z-index: 5; }

.txt { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 0 10px; }
.t-name { font-size: 20px; font-weight: 700; color: $color-text; letter-spacing: .2px; }
.center-txt .t-name, .dim.on .t-name { font-size: 24px; }
.t-vals, .spv { display: flex; gap: 6px; margin-top: 2px; }
.tv { font-size: 20px; font-weight: 800; }
.center-txt .tv, .dim.on .tv { font-size: 24px; }
.tv.teach { color: #2577e3; }
.tv.real { color: #e08a1e; }
.sp-txt { padding: 0 14px; }
/* 三级节点比二级小，名称最多 6 字：字号与行距收到刚好内切于内环 */
.spn { font-size: 18px; font-weight: 700; color: $color-text; line-height: 1.25; text-align: center; }
.sp-txt .tv { font-size: 18px; }
.sp-txt .spv { margin-top: 1px; }

.legend { position: absolute; right: 20px; top: 20px; display: flex; gap: 16px; background: rgba(255,255,255,0.94); border: 1px solid $color-border; border-radius: 999px; padding: 7px 16px; font-size: 15.5px; box-shadow: $shadow-card; z-index: 9; }
.lg { display: inline-flex; align-items: center; gap: 6px; color: $color-text-secondary; }
.sw { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.sw.teach { background: #2577e3; }
.sw.real { background: #e08a1e; }

.reset-btn { position: absolute; right: 20px; top: 62px; display: inline-flex; align-items: center; gap: 5px; background: rgba(255,255,255,0.94); border: 1px solid $color-border; border-radius: 999px; padding: 7px 15px; font-size: 15.5px; color: $color-primary; cursor: pointer; box-shadow: $shadow-card; z-index: 9; }
.crumb { position: absolute; left: 20px; top: 20px; display: flex; align-items: center; gap: 8px; background: #fff; border: 1px solid $color-border; border-radius: 999px; padding: 8px 16px; font-size: 15px; cursor: pointer; box-shadow: $shadow-card; z-index: 9; }
.c-dot { width: 8px; height: 8px; border-radius: 50%; }
.c-back { color: $color-primary; margin-left: 6px; }

.pc-events { margin-top: 10px; border-top: 1px dashed $color-border; padding-top: 8px; }
.pc-ev-title { font-size: 15.5px; color: $color-text-muted; margin-bottom: 5px; }
.pc-ev { display: flex; align-items: center; gap: 6px; font-size: 15.5px; padding: 3px 0; }
.ev-dot { width: 6px; height: 6px; border-radius: 50%; background: #12a76a; flex-shrink: 0; }
.pc-ev.off .ev-dot { background: #c3ccd8; }
.pc-ev.off .ev-name { color: $color-text-muted; }
.ev-name { flex: 1; }
.ev-tag { font-size: 15.5px; color: #12a76a; }
.pc-ev.off .ev-tag { color: $color-text-muted; }
.pc-ev-hint { font-size: 15.5px; color: $color-text-muted; margin-top: 6px; line-height: 1.5; }
.pc-ev-none { margin-top: 10px; font-size: 15.5px; color: $color-text-muted; border-top: 1px dashed $color-border; padding-top: 8px; }
.pc-desc { margin: 8px 0 10px; font-size: 13px; line-height: 1.6; color: $color-text-secondary; }
.pop-card { position: absolute; width: 600px; background: #fff; border: 1px solid $color-border; border-radius: 18px; padding: 30px; box-shadow: 0 28px 70px rgba(16,32,56,0.3); z-index: 20; }
.pc-head { display: flex; align-items: center; justify-content: space-between; }
.pc-id { font-family: ui-monospace, monospace; font-size: 16.5px; color: $color-primary; background: $color-primary-soft; padding: 2px 8px; border-radius: 5px; }
.pc-cp { font-size: 15px; padding: 1px 8px; border-radius: 999px; background: #eef1f5; color: $color-text-muted; }
.pc-cp.B { background: #fff3e0; color: #b8741a; }
.pc-name { font-size: 26px; font-weight: 800; margin: 14px 0 14px; line-height: 1.4; }
.pc-rows { display: flex; flex-direction: column; gap: 6px; }
.pc-row { display: flex; align-items: center; gap: 8px; font-size: 18px; color: $color-text-secondary; }
.pc-row b { margin-left: auto; color: $color-text; }
.pc-acts { display: flex; gap: 10px; margin-top: 12px; }
.pc-btn { flex: 1; justify-content: center; }
.pc-btn.ghost { background: #fff; }

.pop-enter-active { transition: opacity .2s ease, transform .2s ease; }
.pop-enter-from { opacity: 0; transform: scale(.86); }
/* 离开要"干脆"：短时长 + 缩小，且锁死位移过渡，避免与节点自身的 left/top 过渡打架 */
.pop-leave-active {
  transition: opacity .12s ease, transform .12s ease !important;
  z-index: 7;
}
.pop-leave-to { opacity: 0; transform: translate(-50%, -50%) scale(.45); }
</style>
<style scoped lang="scss">
@media (max-width: 760px) {
  .learn-head { align-items: flex-start; flex-direction: column; }
  .mode-switch { width: 100%; }
  .mode-switch button { flex: 1; justify-content: center; }
  .route-shell { padding: 12px; }
  .priority-hero { min-height: 0; grid-template-columns: 62px minmax(0,1fr) 72px; padding: 20px 17px 18px; gap: 10px 12px; border-radius: 17px; }
  .ph-actions { grid-column: 1 / -1; grid-row: 1; justify-content: flex-start; position: static; }
  .ph-number { grid-column: 1; grid-row: 2 / 4; font-size: 50px; }
  .ph-copy { grid-column: 2 / 4; grid-row: 2; }
  .ph-copy h1 span { font-size: 15px; }
  .ph-copy h1 strong { font-size: 30px; margin-top: 6px; }
  .ph-tags { margin-top: 12px; gap: 6px; }
  .ph-tags span { padding: 4px 8px; font-size: 12px; }
  .ph-score { grid-column: 2; grid-row: 3; justify-self: start; width: 74px; height: 74px; }
  .ph-score b { font-size: 26px; }
  .ph-score span { font-size: 11px; margin-top: 3px; }
  .ph-start { grid-column: 2 / 4; grid-row: 4; justify-self: stretch; justify-content: center; align-self: center; margin-top: 2px; padding: 11px 12px; font-size: 14px; white-space: nowrap; }
  .stream-title { font-size: 18px; }
  .route-item { grid-template-columns: 38px minmax(0,1fr) 36px 14px; gap: 9px; padding: 12px 10px; }
  .ri-order { width: 34px; height: 34px; border-radius: 10px; }
  .ri-main h5 { font-size: 15px; }
  .ri-score { font-size: 18px; }
  .rd-actions { align-items: flex-start; flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  .priority-hero, .priority-hero::before, .priority-hero::after, .ph-number, .ph-score, .ph-start,
  .route-stream, .route-lane::before, .route-item { animation: none !important; }
}
</style>
