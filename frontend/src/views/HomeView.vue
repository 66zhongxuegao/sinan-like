<template>
  <div class="home" :class="{ 'signed-in': isAuthed }">
    <section class="hero" aria-labelledby="home-title">
      <div class="sky" aria-hidden="true">
        <svg class="cloud cloud-back" viewBox="0 0 600 260"><path d="M70 230C-15 230-15 130 64 125C42 44 152 10 191 82C224-32 394-12 402 107C497 58 572 123 548 177C625 207 577 254 524 249H70Z" fill="currentColor"/></svg>
        <svg class="cloud cloud-mid" viewBox="0 0 600 260"><path d="M70 230C-15 230-15 130 64 125C42 44 152 10 191 82C224-32 394-12 402 107C497 58 572 123 548 177C625 207 577 254 524 249H70Z" fill="currentColor"/></svg>
        <svg class="cloud cloud-front" viewBox="0 0 600 260"><path d="M70 230C-15 230-15 130 64 125C42 44 152 10 191 82C224-32 394-12 402 107C497 58 572 123 548 177C625 207 577 254 524 249H70Z" fill="currentColor"/></svg>
        <svg class="flight-line" viewBox="0 0 800 420" preserveAspectRatio="none">
          <path d="M-30 360C110 325 150 225 290 248S455 360 590 255S725 92 845 72"/>
        </svg>
        <svg class="birds" viewBox="0 0 180 90">
          <path d="M8 53c9-9 16-9 25 0 9-9 16-9 25 0"/>
          <path d="M68 31c5-5 9-5 14 0 5-5 9-5 14 0"/>
          <path d="M92 20c6-6 11-6 17 0 6-6 11-6 17 0"/>
          <path d="M126 62c5-5 9-5 14 0 5-5 9-5 14 0"/>
          <path d="M149 82c4-4 7-4 11 0 4-4 7-4 11 0"/>
        </svg>
      </div>

      <div class="hero-layout" :class="{ guest: !isAuthed }">
        <div class="hero-copy">
          <div class="home-brand">
            <img src="@/assets/logo-tripcraft.webp" alt="" />
            <h1 id="home-title">司南礼客</h1>
          </div>

          <button v-if="isAuthed" class="tc-btn cta" data-testid="primary-action"
            :disabled="primary.disabled" @click="runPrimary">
            <span>{{ primary.label }}</span>
            <SIcon name="right" :size="23" :stroke-width="2.4" />
          </button>
        </div>

        <form v-if="!isAuthed" class="auth-card" @submit.prevent="submitAuth">
          <h2 class="sr-only">{{ authMode === 'login' ? '登录' : '注册' }}</h2>
          <div class="auth-tabs" role="tablist">
            <button type="button" role="tab" :aria-selected="authMode === 'login'"
              :class="{ active: authMode === 'login' }" @click="setAuthMode('login')">登录</button>
            <button type="button" role="tab" :aria-selected="authMode === 'register'"
              :class="{ active: authMode === 'register' }" @click="setAuthMode('register')">注册</button>
          </div>

          <div v-if="authNotice" class="auth-alert info"><SIcon name="check" :size="17" /><span>{{ authNotice }}</span></div>
          <div v-if="authError" class="auth-alert error"><SIcon name="warn" :size="17" /><span>{{ authError }}</span></div>

          <div class="auth-fields">
            <select v-if="authMode === 'login'" v-model="authUsername" class="auth-input account-select"
              name="username" aria-label="选择登录账户" :disabled="authBusy || !loginAccounts.length"
              @change="selectLoginAccount">
              <option v-if="!loginAccounts.length" value="">正在读取账户…</option>
              <option v-for="a in loginAccounts" :key="a.username" :value="a.username">{{ a.label }}</option>
            </select>
            <input v-else v-model.trim="authUsername" class="auth-input" type="text" name="username"
              autocomplete="username" placeholder="用户名" aria-label="用户名" :disabled="authBusy" @input="clearAuthMessages" />
            <div class="password-wrap">
              <input v-model="authPassword" class="auth-input" :type="showPwd ? 'text' : 'password'"
                name="password" :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'"
                :placeholder="authMode === 'login' ? '密码' : '密码（至少 8 位）'" aria-label="密码"
                :disabled="authBusy" @input="clearAuthMessages" />
              <button type="button" class="auth-eye" :title="showPwd ? '隐藏密码' : '显示密码'" @click="showPwd = !showPwd">
                <SIcon name="eye" :size="18" />
              </button>
            </div>
            <input v-if="authMode === 'register'" v-model="authConfirm" class="auth-input"
              :type="showPwd ? 'text' : 'password'" name="confirm-password" autocomplete="new-password"
              placeholder="确认密码" aria-label="确认密码" :disabled="authBusy" @input="clearAuthMessages" />
          </div>

          <button class="auth-submit" type="submit" :disabled="authBusy || !authFormReady">
            <SIcon v-if="authBusy" name="refresh" :size="18" class="spin" />
            <span>{{ authBusy ? '请稍候' : authMode === 'login' ? '登录' : '注册' }}</span>
            <SIcon v-if="!authBusy" name="right" :size="20" :stroke-width="2.4" />
          </button>

        </form>
      </div>
    </section>

    <section class="journey" aria-labelledby="journey-title">
      <h2 id="journey-title" class="journey-title">成长路径</h2>

      <div class="track">
        <button v-for="(step, i) in TRACK" :key="step.id" type="button" class="step"
          :class="{ on: i === stepIndex, done: i < stepIndex, open: openStepId === step.id }"
          :aria-expanded="openStepId === step.id" @click="toggleStep(step.id)">
          <span class="step-dot"><SIcon :name="step.icon" :size="29" :stroke-width="1.9" /></span>
          <span class="step-name">{{ step.title }}</span>
        </button>
      </div>

      <transition name="detail-pop">
        <div v-if="activeStep" class="step-detail">
          <span v-for="item in activeStep.items" :key="item" class="step-tag">{{ item }}</span>
        </div>
      </transition>
    </section>

    <p v-if="dataWarn" class="warn">
      <span>{{ dataWarn }}</span>
      <button class="retry" type="button" @click="reloadData">重试</button>
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'

type AuthMode = 'login' | 'register'
type StepState = { id: string; title: string; icon: string; items: string[] }

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const isAuthed = computed(() => store.isAuthenticated)
const loaded = ref(false)
const canAssess = ref(false)
const availableCount = ref(0)
const myOrders = ref<any[]>([])
const ordersError = ref('')

const authMode = ref<AuthMode>(route.query.mode === 'register' ? 'register' : 'login')
const loginAccounts = ref<any[]>([])
const authUsername = ref('')
const authPassword = ref('')
const authConfirm = ref('')
const showPwd = ref(false)
const authBusy = ref(false)
const authError = ref('')
const authNotice = ref('')

const redirectTo = computed(() => {
  const value = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  return value.startsWith('/') && value !== '/' ? value : ''
})

const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/
const authFormReady = computed(() => {
  if (!authUsername.value || !authPassword.value) return false
  if (authMode.value === 'login') return true
  return USERNAME_RE.test(authUsername.value) && authPassword.value.length >= 8 &&
    authConfirm.value.length > 0 && authConfirm.value === authPassword.value
})

function setAuthMode(mode: AuthMode) {
  if (authBusy.value) return
  authMode.value = mode
  showPwd.value = false
  clearAuthMessages()
  if (mode === 'register') {
    authUsername.value = ''
    authPassword.value = ''
    authConfirm.value = ''
  } else if (loginAccounts.value.length) {
    selectLoginAccount()
  }
}

function clearAuthMessages() {
  authError.value = ''
  authNotice.value = ''
}

function selectLoginAccount() {
  const account = loginAccounts.value.find((a) => a.username === authUsername.value)
  authPassword.value = account?.password || ''
  clearAuthMessages()
}

async function loadLoginAccounts() {
  try {
    const r = (await client.get('/auth/login-accounts')).data
    loginAccounts.value = r.accounts || []
    if (!authUsername.value && loginAccounts.value.length) {
      authUsername.value = loginAccounts.value[0].username
      authPassword.value = loginAccounts.value[0].password || ''
    }
  } catch {
    loginAccounts.value = []
  }
}

function errorText(e: any): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length) {
    const msg = detail.map((x: any) => String(x?.msg || '')).filter(Boolean).join('；')
    if (msg) return msg
  }
  const status = e?.response?.status
  if (status === 401) return '用户名或密码不正确'
  if (status === 409) return '用户名已存在'
  if (status === 400) return '请检查输入内容'
  if (status === 503) return '暂时无法登录，请稍后重试'
  if (!e?.response) return '暂时无法连接，请稍后重试'
  return e?.message || '操作失败，请重试'
}

async function submitAuth() {
  if (authBusy.value || !authFormReady.value) return
  authBusy.value = true
  clearAuthMessages()
  try {
    if (authMode.value === 'login') {
      await store.login(authUsername.value, authPassword.value)
    } else {
      const result = await store.register({
        username: authUsername.value,
        password: authPassword.value,
      })
      if (!result.signedIn) {
        authMode.value = 'login'
        authPassword.value = ''
        authConfirm.value = ''
        authNotice.value = result.notice
        return
      }
    }
    if (redirectTo.value) {
      await router.replace(redirectTo.value)
      return
    }
    await loadWorkspace()
  } catch (e: any) {
    authError.value = errorText(e)
  } finally {
    authBusy.value = false
  }
}

interface Primary { label: string; to: string; disabled: boolean }
const primary = computed<Primary>(() => {
  if (!loaded.value) return { label: '正在加载', to: '', disabled: true }
  if (canAssess.value) return { label: '开始测评', to: '/profile/quiz', disabled: false }
  if (availableCount.value > 0) return { label: '去接单', to: '/practice/messages', disabled: false }
  if (myOrders.value.length) return { label: '继续训练', to: '/practice', disabled: false }
  return { label: '开始学习', to: '/learn', disabled: false }
})

function runPrimary() {
  if (!primary.value.disabled && primary.value.to) router.push(primary.value.to)
}

const TRACK: StepState[] = [
  { id: 'assess', title: '自测', icon: 'target', items: ['初始测评', '能力画像', '学习建议'] },
  { id: 'learn', title: '学习', icon: 'book', items: ['学习地图', '技能训练', '专项复盘'] },
  { id: 'practice', title: '实战', icon: 'compass', items: ['接单沟通', '方案交付', '实战评分'] },
]

const stepIndex = computed(() => {
  if (!isAuthed.value || !loaded.value) return 0
  if (canAssess.value) return 0
  if (availableCount.value || myOrders.value.length) return 2
  return 1
})

const openStepId = ref('')
const activeStep = computed(() => TRACK.find((step) => step.id === openStepId.value))
function toggleStep(id: string) {
  openStepId.value = openStepId.value === id ? '' : id
}

const dataWarn = computed(() => ordersError.value ? '订单进度暂时没加载出来。' : '')

async function loadWorkState() {
  ordersError.value = ''
  try {
    const rows = (await client.get('/practice/orders/available')).data as any[]
    availableCount.value = Array.isArray(rows) ? rows.length : 0
  } catch { availableCount.value = 0 }
  try {
    const mine = (await client.get('/practice/orders')).data as any[]
    myOrders.value = Array.isArray(mine) ? mine : []
  } catch {
    myOrders.value = []
    ordersError.value = '1'
  }
}

async function loadWorkspace() {
  loaded.value = false
  await loadWorkState()
  try {
    const uid = store.userId
    if (uid) {
      const response = await client.get(`/profiles/${uid}/intake`)
      canAssess.value = !!response.data.can_assess
    } else {
      canAssess.value = false
    }
  } catch { canAssess.value = false }
  loaded.value = true
}

function reloadData() {
  if (isAuthed.value) void loadWorkspace()
}

watch(isAuthed, (authed) => {
  if (authed) {
    // 登录后同一路由不会重新 onMounted；必须主动刷新首页数据，
    // 否则退出重置后再登录仍可能看到上一个会话的空/旧状态。
    void loadWorkspace()
    return
  }
  loaded.value = true
  canAssess.value = false
  availableCount.value = 0
  myOrders.value = []
  ordersError.value = ''
  openStepId.value = ''
  authMode.value = 'login'
  // 退出后重新拉取账户列表：外部新增/删除账号（如空白演示账号）不应等整页刷新才出现。
  void loadLoginAccounts()
})

onMounted(async () => {
  await loadLoginAccounts()
  if (!store.sessionReady) await store.restore()
  if (isAuthed.value) {
    await loadWorkspace()
  } else {
    authError.value = store.sessionError || ''
    loaded.value = true
  }
})
</script>

<style scoped lang="scss">
.home {
  --blue: #0066ff;
  --ink: #12375f;
  display: flex;
  flex-direction: column;
  gap: 24px;
  width: 100%;
  max-width: 1320px;
  min-height: calc(100vh - 40px);
  margin: 0 auto;
  padding-bottom: 18px;
  color: var(--ink);
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}
.home.signed-in { min-height: calc(100vh - 106px); }

.hero {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  flex: 1 1 auto;
  min-height: 560px;
  display: flex;
  align-items: center;
  padding: 58px 68px;
  border-radius: 34px;
  color: #fff;
  background: linear-gradient(116deg, #0052df 0%, #0878ff 48%, #5bb4ff 100%);
  background-size: 150% 150%;
  box-shadow: 0 26px 76px rgba(0, 82, 210, .2);
  animation: sky-shift 20s ease-in-out infinite alternate;
}
.sky { position: absolute; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; }
.sky::before {
  content: "";
  position: absolute;
  width: 820px;
  height: 820px;
  right: -270px;
  top: -430px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255,255,255,.2) 0%, rgba(255,255,255,0) 67%);
  animation: glow-drift 18s ease-in-out infinite alternate;
}
.sky::after {
  content: "";
  position: absolute;
  left: -10%;
  right: -10%;
  bottom: -235px;
  height: 400px;
  border-radius: 50% 50% 0 0;
  background: rgba(255,255,255,.09);
  animation: horizon-breathe 22s ease-in-out infinite alternate;
}
.cloud { position: absolute; height: auto; color: #fff; will-change: transform; }
.cloud-back { width: 660px; right: 70px; top: -205px; opacity: .13; animation: cloud-back-drift 34s ease-in-out infinite alternate; }
.cloud-mid { width: 470px; left: 43%; top: 49%; opacity: .07; animation: cloud-back-drift 28s ease-in-out -9s infinite alternate-reverse; }
.cloud-front { width: 780px; right: -235px; bottom: -245px; opacity: .19; animation: cloud-front-drift 29s ease-in-out infinite alternate; }
.flight-line {
  position: absolute;
  right: -2%;
  bottom: 0;
  width: 65%;
  height: 100%;
  fill: none;
  stroke: rgba(255,255,255,.2);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-dasharray: 5 17;
  animation: trail-flow 16s linear infinite;
}
.birds {
  position: absolute;
  width: 230px;
  height: 115px;
  right: 105px;
  top: 116px;
  fill: none;
  stroke: rgba(255,255,255,.72);
  stroke-width: 2.4;
  stroke-linecap: round;
  animation: birds-float 9s ease-in-out infinite alternate;
}
@keyframes sky-shift { from { background-position: 0% 42%; } to { background-position: 100% 58%; } }
@keyframes glow-drift { from { transform: translate3d(0,0,0) scale(1); opacity: .8; } to { transform: translate3d(-85px,48px,0) scale(1.12); opacity: 1; } }
@keyframes horizon-breathe { from { transform: scaleX(.96) translateY(8px); opacity: .72; } to { transform: scaleX(1.04) translateY(-4px); opacity: 1; } }
@keyframes cloud-back-drift { from { transform: translate3d(-30px,10px,0) scale(.98); } to { transform: translate3d(36px,-14px,0) scale(1.03); } }
@keyframes cloud-front-drift { from { transform: translate3d(-24px,7px,0) scale(.99); } to { transform: translate3d(32px,-12px,0) scale(1.02); } }
@keyframes trail-flow { to { stroke-dashoffset: -220; } }
@keyframes birds-float { from { transform: translate3d(-4px,5px,0); } to { transform: translate3d(18px,-8px,0); } }

.hero-layout { position: relative; z-index: 1; width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 72px; }
.hero-layout.guest { align-items: center; }
.hero-copy { display: flex; flex: 1 1 auto; flex-direction: column; align-items: flex-start; gap: 44px; min-width: 0; }
.home-brand { display: flex; align-items: center; gap: 22px; }
.home-brand img {
  width: 78px;
  height: 78px;
  object-fit: contain;
  border-radius: 22px;
  background: rgba(255,255,255,.96);
  box-shadow: 0 10px 26px rgba(0, 35, 105, .15);
}
.home-brand h1 {
  margin: 0;
  font-size: clamp(68px, 7.2vw, 96px);
  line-height: 1;
  font-weight: 750;
  letter-spacing: .08em;
}

.home .cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 40px;
  min-height: 70px;
  padding: 0 29px 0 32px;
  border: 0;
  border-radius: 999px;
  background: #fff;
  color: #0057d9;
  font: inherit;
  font-size: 26px;
  font-weight: 750;
  cursor: pointer;
  box-shadow: 0 12px 28px rgba(0, 34, 105, .2);
  transition: transform .2s ease, box-shadow .2s ease;
}
.home .cta :deep(svg) { transition: transform .2s ease; }
.home .cta:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 16px 34px rgba(0, 34, 105, .24); }
.home .cta:hover:not(:disabled) :deep(svg) { transform: translateX(3px); }
.home .cta:disabled { cursor: wait; opacity: .72; }

.auth-card {
  flex: 0 0 424px;
  width: 424px;
  padding: 25px 27px 27px;
  border-radius: 27px;
  background: rgba(255,255,255,.98);
  color: var(--ink);
  box-shadow: 0 22px 54px rgba(0, 36, 110, .22);
}
.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 5px;
  margin-bottom: 20px;
  border-radius: 15px;
  background: #edf6ff;
}
.auth-tabs button {
  height: 48px;
  border: 0;
  border-radius: 11px;
  background: transparent;
  color: #31577f;
  font: inherit;
  font-size: 20px;
  font-weight: 700;
  cursor: pointer;
  transition: background .16s ease, color .16s ease, box-shadow .16s ease;
}
.auth-tabs button.active { background: #fff; color: #0057d9; box-shadow: 0 4px 13px rgba(20, 70, 140, .11); }
.auth-alert { display: flex; align-items: flex-start; gap: 9px; margin-bottom: 13px; padding: 10px 12px; border-radius: 11px; font-size: 16px; line-height: 1.55; }
.auth-alert.info { background: #eef7ff; color: #0c5fc8; }
.auth-alert.error { background: #fff0f0; color: #b52f2f; }
.auth-fields { display: flex; flex-direction: column; gap: 11px; }
.auth-input {
  width: 100%;
  height: 56px;
  padding: 0 16px;
  border: 1px solid #d6e5f5;
  border-radius: 13px;
  outline: none;
  background: #f7fbff;
  color: var(--ink);
  font: inherit;
  font-size: 19px;
  transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
}
.auth-input::placeholder { color: #6d8198; }
.auth-input:focus { border-color: #2f89ff; background: #fff; box-shadow: 0 0 0 4px rgba(0,102,255,.1); }
.auth-input:disabled { opacity: .65; cursor: wait; }
.password-wrap { position: relative; }
.password-wrap .auth-input { padding-right: 52px; }
.auth-eye {
  position: absolute;
  right: 7px;
  top: 50%;
  width: 40px;
  height: 40px;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #486987;
  cursor: pointer;
}
.auth-eye:hover { background: #e8f3ff; color: #0057d9; }
.account-select { appearance: auto; cursor: pointer; padding-right: 38px; }
.auth-submit {
  width: 100%;
  height: 58px;
  margin-top: 17px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 30px;
  border: 0;
  border-radius: 14px;
  background: linear-gradient(135deg, #0066ff, #167dff);
  color: #fff;
  font: inherit;
  font-size: 21px;
  font-weight: 750;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(0, 86, 220, .24);
  transition: transform .16s ease, box-shadow .16s ease, opacity .16s ease;
}
.auth-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 14px 28px rgba(0, 86, 220, .3); }
.auth-submit:disabled { opacity: .55; cursor: default; box-shadow: none; }
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }

.journey {
  padding: 29px 42px 31px;
  border: 1px solid #dfedfc;
  border-radius: 28px;
  background: rgba(255,255,255,.95);
  box-shadow: 0 14px 40px rgba(20, 72, 140, .06);
}
.journey-title { margin: 0 0 26px; font-size: 30px; font-weight: 750; }
.track { position: relative; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; }
.track::before {
  content: "";
  position: absolute;
  left: 16.67%;
  right: 16.67%;
  top: 39px;
  height: 2px;
  background: #d4e7fb;
}
.step {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 0 12px;
  border: 0;
  background: transparent;
  color: var(--ink);
  font: inherit;
  cursor: pointer;
}
.step-dot {
  width: 80px;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid #cfe3fa;
  border-radius: 50%;
  background: #fff;
  color: #5c7c9c;
  box-shadow: 0 0 0 8px #fff;
  transition: transform .18s ease, color .18s ease, background .18s ease, border-color .18s ease, box-shadow .18s ease;
}
.step:hover .step-dot { transform: translateY(-3px); border-color: #7cb6ff; color: #0066ff; }
.step.done .step-dot { border-color: #86bbff; background: #eaf5ff; color: #0066ff; }
.step.on .step-dot {
  border-color: #0066ff;
  background: linear-gradient(145deg, #0066ff, #2b91ff);
  color: #fff;
  box-shadow: 0 0 0 8px #fff, 0 9px 22px rgba(0,102,255,.24);
}
.step-name { font-size: 27px; line-height: 1.2; font-weight: 750; }
.step.on .step-name { color: #0057d9; }
.step.open .step-dot { transform: translateY(-3px); }
.step:focus-visible { outline: 3px solid #0047b3; outline-offset: 4px; border-radius: 18px; }

.step-detail { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px 12px; margin-top: 24px; padding-top: 22px; border-top: 1px solid #e2eefc; }
.step-tag { padding: 10px 18px; border-radius: 999px; background: #edf6ff; color: #095abf; font-size: 18px; line-height: 1; font-weight: 700; }
.detail-pop-enter-active, .detail-pop-leave-active { transition: opacity .16s ease, transform .16s ease; }
.detail-pop-enter-from, .detail-pop-leave-to { opacity: 0; transform: translateY(-5px); }

.warn { display: flex; align-items: center; flex-wrap: wrap; gap: 15px; margin: 0; padding: 15px 18px; border-radius: 14px; background: #fff6e8; color: #8a5215; font-size: 19px; }
.retry { border: 0; border-radius: 999px; background: #e8f3ff; color: #0057d9; padding: 9px 18px; font: inherit; font-size: 17px; font-weight: 700; cursor: pointer; }
.home .cta:focus-visible, .auth-card button:focus-visible { outline: 3px solid #0047b3; outline-offset: 4px; }
.home .cta:focus-visible { outline-color: #fff; outline-offset: 5px; }

@media (max-width: 1000px) {
  .home { max-width: 760px; }
  .hero { flex-basis: auto; min-height: 0; padding: 42px 38px; }
  .hero-layout, .hero-layout.guest { flex-direction: column; align-items: flex-start; gap: 34px; }
  .hero-copy { flex: 0 0 auto; gap: 30px; }
  .auth-card { width: 100%; flex-basis: auto; max-width: 520px; }
  .birds { right: 54px; top: 88px; }
  .flight-line { width: 78%; opacity: .75; }
}

@media (max-width: 600px) {
  .home { gap: 18px; min-height: 0; padding-bottom: 12px; }
  .hero { padding: 30px 22px 28px; border-radius: 27px; }
  .hero-layout, .hero-layout.guest { gap: 28px; }
  .hero-copy { gap: 24px; }
  .home-brand { gap: 16px; }
  .home-brand img { width: 60px; height: 60px; border-radius: 17px; }
  .home-brand h1 { font-size: clamp(56px, 15.5vw, 66px); letter-spacing: .04em; }
  .home .cta { min-height: 60px; padding: 0 22px 0 25px; gap: 28px; font-size: 22px; }
  .auth-card { padding: 22px 21px 23px; border-radius: 22px; }
  .auth-tabs { margin-bottom: 17px; }
  .auth-input { height: 53px; font-size: 18px; }
  .auth-submit { height: 55px; }
  .cloud-front { width: 460px; right: -205px; bottom: -120px; }
  .cloud-back { width: 330px; right: 4px; top: -112px; }
  .cloud-mid { width: 260px; left: 42%; top: 53%; }
  .birds { width: 145px; height: 73px; right: 10px; top: 71px; stroke-width: 2.6; }
  .flight-line { width: 95%; right: -8%; bottom: -10px; opacity: .6; }
  .journey { padding: 24px 20px 26px; border-radius: 24px; }
  .journey-title { margin-bottom: 23px; font-size: 27px; }
  .step { gap: 13px; padding: 0 6px; }
  .step-dot { width: 62px; height: 62px; box-shadow: 0 0 0 6px #fff; }
  .step-dot :deep(svg) { width: 24px; height: 24px; }
  .step-name { font-size: 23px; }
  .track::before { top: 30px; }
  .step-detail { margin-top: 20px; padding-top: 18px; }
  .step-tag { padding: 9px 14px; font-size: 17px; }
}

@media (prefers-reduced-motion: reduce) {
  .hero, .sky::before, .sky::after, .cloud, .birds, .flight-line { animation: none; }
  .home .cta, .step-dot, .detail-pop-enter-active, .detail-pop-leave-active { transition: none; }
}
</style>
