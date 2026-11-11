<template>
  <div class="auth">
    <section class="auth-card rise">
      <div class="auth-brand">
        <AppLogo />
        <div class="brand-line">定制师全流程实战训练系统</div>
      </div>

      <h2 class="auth-title">登录</h2>
      <p class="auth-sub">登录后继续你的训练，刷新页面无需重新登录。</p>

      <div v-if="notice" class="alert info"><SIcon name="check" :size="15" /><span>{{ notice }}</span></div>
      <div v-if="error" class="alert err"><SIcon name="warn" :size="15" /><span>{{ error }}</span></div>
      <div v-else-if="sessionError" class="alert err"><SIcon name="warn" :size="15" /><span>{{ sessionError }}</span></div>

      <form class="auth-form" @submit.prevent="submit">
        <label class="field">
          <span class="fl">用户名</span>
          <input v-model="username" class="fi" type="text" name="username" autocomplete="username"
            placeholder="3–32 位字母 / 数字 / _ . -" :disabled="busy" @input="error = ''" />
        </label>
        <label class="field">
          <span class="fl">密码</span>
          <div class="fi-wrap">
            <input v-model="password" class="fi" :type="showPwd ? 'text' : 'password'" name="password"
              autocomplete="current-password" placeholder="至少 8 位" :disabled="busy" @input="error = ''" />
            <button type="button" class="eye" :title="showPwd ? '隐藏密码' : '显示密码'" @click="showPwd = !showPwd">
              <SIcon name="eye" :size="16" />
            </button>
          </div>
        </label>

        <button class="submit" type="submit" :disabled="busy || !canSubmit">
          <SIcon v-if="busy" name="refresh" :size="15" class="spin" />
          <span>{{ busy ? '登录中…' : '登录' }}</span>
        </button>
      </form>

      <div class="auth-foot">
        <span>还没有账号？</span>
        <router-link :to="registerTo" class="link">注册新账号</router-link>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLogo from '@/components/AppLogo.vue'
import SIcon from '@/components/SIcon.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const username = ref('')
const password = ref('')
const showPwd = ref(false)
const busy = ref(false)
const error = ref('')

/** 登录成功后要回到的原目标（守卫在重定向时写入 ?redirect=） */
const redirect = computed(() => (typeof route.query.redirect === 'string' ? route.query.redirect : ''))
const registerTo = computed(() => (redirect.value ? { path: '/register', query: { redirect: redirect.value } } : '/register'))
const notice = computed(() => (typeof route.query.notice === 'string' ? route.query.notice : ''))
const sessionError = computed(() => store.sessionError)

const canSubmit = computed(() => username.value.trim().length > 0 && password.value.length > 0)

function errorText(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string' && d.trim()) return d
  if (Array.isArray(d) && d.length) {
    const msg = d.map((x: any) => String(x?.msg || '')).filter(Boolean).join('；')
    if (msg) return msg
  }
  const status = e?.response?.status
  if (status === 401) return '用户名或密码不正确'
  if (status === 400) return '请输入用户名与密码'
  if (status === 503) return '暂时无法登录，请稍后重试'
  if (!e?.response) return '暂时无法连接，请稍后重试'
  return e?.message || '登录失败，请重试'
}

async function submit() {
  if (busy.value || !canSubmit.value) return
  busy.value = true
  error.value = ''
  try {
    await store.login(username.value, password.value)
    const to = redirect.value.startsWith('/') ? redirect.value : '/'
    await router.replace(to)
  } catch (e: any) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.auth { width: 100%; min-height: calc(100vh - 140px); display: flex; align-items: center; justify-content: center; padding: 24px; }
.auth-card { width: 100%; max-width: 460px; background: #fff; border: 1px solid $color-border; border-radius: $radius-lg;
  box-shadow: $shadow-card; padding: 30px 32px 24px; }
@keyframes riseIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.rise { animation: riseIn .4s cubic-bezier(.34,1.2,.6,1) both; }

.auth-brand { display: flex; flex-direction: column; gap: 8px; }
.brand-line { font-size: $fs-meta; color: $color-text-muted; letter-spacing: .4px; }
.auth-title { margin: 22px 0 6px; font-size: 26px; font-weight: 800; }
.auth-sub { margin: 0 0 18px; font-size: $fs-meta; line-height: 1.7; color: $color-text-secondary; }

.alert { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border-radius: $radius-md;
  font-size: $fs-meta; line-height: 1.6; margin-bottom: 14px; }
.alert.err { color: #b32d2d; background: #fdecec; border: 1px solid #f7cfcf; }
.alert.info { color: #1a63c4; background: $color-primary-softer; border: 1px solid #d8e7fa; }

.auth-form { display: flex; flex-direction: column; gap: 14px; }
.field { display: flex; flex-direction: column; gap: 7px; }
.fl { font-size: $fs-meta; font-weight: 600; color: $color-text-secondary; }
.fi { width: 100%; height: 44px; padding: 0 13px; font-size: $fs-body; color: $color-text; background: #fff;
  border: 1px solid $color-border-strong; border-radius: $radius-md; outline: none; transition: border-color .15s ease, box-shadow .15s ease; }
.fi:focus { border-color: $color-primary; box-shadow: 0 0 0 3px rgba(37,119,227,.12); }
.fi:disabled { background: #f7f8fa; color: $color-text-muted; }
.fi-wrap { position: relative; }
.fi-wrap .fi { padding-right: 44px; }
.eye { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center; border: none; background: transparent;
  color: $color-text-muted; cursor: pointer; border-radius: 8px; }
.eye:hover { color: $color-primary; background: $color-primary-softer; }

.submit { margin-top: 6px; height: 46px; display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  border: none; border-radius: $radius-md; cursor: pointer; color: #fff; font-size: $fs-body; font-weight: 700;
  background: linear-gradient(135deg, $color-primary, $color-primary-dark); box-shadow: 0 6px 16px rgba(37,119,227,.24);
  transition: transform .16s cubic-bezier(.34,1.4,.6,1), box-shadow .16s ease, filter .16s ease; }
.submit:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 10px 22px rgba(37,119,227,.3); filter: brightness(1.03); }
.submit:disabled { cursor: default; background: linear-gradient(135deg, #9dc0ee, #86aee6); box-shadow: none; }
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.auth-foot { margin-top: 16px; display: flex; align-items: center; gap: 6px; font-size: $fs-meta; color: $color-text-secondary; }
.link { color: $color-primary; font-weight: 700; }
.link:hover { text-decoration: underline; }

.scope-note { margin-top: 18px; padding: 12px 14px; border-radius: $radius-md; background: $color-bg;
  border: 1px solid $color-border; font-size: $fs-meta; line-height: 1.75; color: $color-text-secondary; }
.sn-tag { display: inline-block; margin-right: 6px; padding: 1px 8px; border-radius: 999px;
  background: $color-primary-soft; color: $color-primary; font-weight: 700; font-size: $fs-badge; }
.scope-note code { font-family: ui-monospace, monospace; font-size: $fs-meta; color: $color-text; background: #fff;
  border: 1px solid $color-border; border-radius: 4px; padding: 0 4px; }
</style>
