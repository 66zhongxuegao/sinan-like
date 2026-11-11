<template>
  <div class="db" @pointermove="onPointerMove">
    <header class="db-topbar">
      <div class="db-topbar-inner">
        <div class="db-brand">
          <AppLogo />
          <span class="db-brand-divider" />
          <span class="db-brand-label">数据看板</span>
        </div>

        <nav class="db-seg" :data-idx="view === 'team' ? 0 : 1" aria-label="看板切换">
          <span class="db-seg-glider" />
          <button class="db-seg-btn" :class="{ on: view === 'team' }" type="button" @click="setView('team')">团队看板</button>
          <button class="db-seg-btn" :class="{ on: view === 'ops' }" type="button" @click="setView('ops')">运营看板</button>
        </nav>

        <div class="db-actions">
          <span class="db-live"><i class="db-dot-live" />实时 · 演示数据</span>
          <span class="db-clock">{{ clock }}</span>
          <button class="db-icon-btn" :class="{ spin: spinning }" type="button" title="重播动效" aria-label="重播动效" @click="replay">
            <SIcon name="refresh" :size="16" />
          </button>
          <button class="db-icon-btn" type="button" title="指标口径与埋点" aria-label="指标口径与埋点" @click="specOpen = true">
            <SIcon name="filetext" :size="16" />
          </button>
          <span class="db-actions-sep" />
          <button class="db-exit" type="button" @click="exitConsole">
            <SIcon name="back" :size="15" /><span>返回</span>
          </button>
        </div>
      </div>
    </header>

    <section class="db-hero">
      <svg class="db-hero-art" viewBox="0 0 1480 240" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <path d="M-40 210C180 180 260 60 470 96S760 220 960 120S1240 20 1520 60" fill="none"
          stroke="rgba(255,255,255,.32)" stroke-width="2" />
        <path d="M-40 244C220 214 340 124 560 152S900 252 1120 162S1360 70 1520 98" fill="none"
          stroke="rgba(255,255,255,.14)" stroke-width="1.5" />
        <circle cx="470" cy="96" r="4" fill="#fff" opacity=".85" />
        <circle cx="960" cy="120" r="3.5" fill="#fff" opacity=".7" />
        <circle cx="1240" cy="58" r="3" fill="#fff" opacity=".6" />
      </svg>

      <div class="db-hero-inner">
        <div class="db-hero-copy">
          <div class="db-eyebrow">TRAINING INTELLIGENCE · 司南礼客</div>
          <h1 class="db-title">{{ view === 'team' ? '团队训练看板' : '运营数据看板' }}</h1>
          <p class="db-sub">
            {{ view === 'team' ? '华东定制师训练营 · A 组 · 48 名学员' : '全平台学员 · 运营团队视角 · 2,846 名学员' }}
          </p>
        </div>

        <div class="db-hero-meta">
          <div class="db-hero-chip">
            <span>统计周期</span>
            <b>{{ view === 'team' ? '10/12 — 10/18' : '09/19 — 10/18' }}</b>
          </div>
          <div class="db-hero-chip">
            <span>数据更新</span>
            <b>{{ lastSync }}</b>
          </div>
          <div class="db-hero-note">演示聚合数据 · 全部指标可接埋点</div>
        </div>
      </div>
    </section>

    <main class="db-body">
      <transition name="board" mode="out-in">
        <TeamBoard v-if="view === 'team'" :key="`team-${renderKey}`" />
        <OpsBoard v-else :key="`ops-${renderKey}`" />
      </transition>
    </main>

    <Teleport to="body">
      <transition name="drawer">
        <div v-if="specOpen" class="db-mask" @click.self="specOpen = false">
          <aside class="db-drawer" role="dialog" aria-modal="true" aria-label="指标口径与埋点">
            <div class="db-drawer-hd">
              <div>
                <div class="db-drawer-title">指标口径与埋点</div>
                <div class="db-drawer-sub">每个数字都能追溯到事件；接入真实数据时按同一口径替换即可。</div>
              </div>
              <button class="db-icon-btn" type="button" aria-label="关闭" @click="specOpen = false">
                <SIcon name="x" :size="16" />
              </button>
            </div>
            <div class="db-drawer-body">
              <div v-for="s in metricSpecs" :key="s.metric" class="db-spec">
                <div class="db-spec-name">{{ s.metric }}</div>
                <div class="db-spec-formula">{{ s.formula }}</div>
                <code class="db-spec-events">{{ s.events }}</code>
              </div>
            </div>
            <div class="db-drawer-foot">
              当前页面为纯前端演示数据。正式接入时保留事件名与统计口径，将聚合结果替换为接口返回值即可，无需改动页面结构。
            </div>
          </aside>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLogo from '@/components/AppLogo.vue'
import SIcon from '@/components/SIcon.vue'
import TeamBoard from '@/views/dashboard/TeamBoard.vue'
import OpsBoard from '@/views/dashboard/OpsBoard.vue'
import { metricSpecs } from '@/data/dashboard'

const route = useRoute()
const router = useRouter()

const view = ref<'team' | 'ops'>(route.query.view === 'ops' ? 'ops' : 'team')
const specOpen = ref(false)
const renderKey = ref(0)
const spinning = ref(false)
const now = ref(new Date())
const lastSync = ref('10:45')

const clock = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }))

function setView(v: 'team' | 'ops') {
  if (view.value === v) return
  view.value = v
  void router.replace({ query: { ...route.query, view: v } })
}

function replay() {
  renderKey.value += 1
  lastSync.value = now.value.toLocaleTimeString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }).slice(0, 5)
  spinning.value = true
  window.setTimeout(() => { spinning.value = false }, 820)
}

function exitConsole() {
  if (window.history.length > 1) router.back()
  else void router.push('/')
}

function onPointerMove(e: PointerEvent) {
  const target = e.target as HTMLElement | null
  const card = target?.closest('.db-card') as HTMLElement | null
  if (!card) return
  const rect = card.getBoundingClientRect()
  card.style.setProperty('--mx', `${e.clientX - rect.left}px`)
  card.style.setProperty('--my', `${e.clientY - rect.top}px`)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') specOpen.value = false
}

const BASE_TITLE = 'TripCraft · 司南礼客 — 定制师全流程模拟实战系统'
let timer = 0
onMounted(() => {
  document.title = '训练数据看板 · 司南礼客'
  timer = window.setInterval(() => { now.value = new Date() }, 1000)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.title = BASE_TITLE
  window.clearInterval(timer)
  document.removeEventListener('keydown', onKey)
})

watch(() => route.query.view, (v) => {
  view.value = v === 'ops' ? 'ops' : 'team'
})
</script>

<style lang="scss">
@use '../../styles/dashboard.scss';
</style>

<style scoped>
.board-enter-active, .board-leave-active { transition: opacity .24s ease, transform .24s ease; }
.board-enter-from { opacity: 0; transform: translateY(10px); }
.board-leave-to { opacity: 0; transform: translateY(-6px); }
</style>