<template>
  <div class="auth">
    <section class="auth-card rise">
      <div class="auth-brand">
        <AppLogo />
        <div class="brand-line">定制师全流程实战训练系统</div>
      </div>

      <h2 class="auth-title">注册新账号</h2>
      <p class="auth-sub">注册后直接进入你的训练，我们会先给你一条专属的初始派单。</p>

      <div v-if="error" class="alert err"><SIcon name="warn" :size="15" /><span>{{ error }}</span></div>

      <form class="auth-form" @submit.prevent="submit">
        <label class="field">
          <span class="fl">用户名 <i class="req">登录用，创建后不可改</i></span>
          <input v-model="username" class="fi" type="text" name="username" autocomplete="username"
            placeholder="3–32 位字母 / 数字 / _ . -" :disabled="busy" @input="error = ''" />
          <span class="hint" :class="{ bad: username && !usernameOk }">
            {{ username && !usernameOk ? '只能使用字母、数字、下划线、点与短横线，长度 3–32' : '用户名是账号唯一标识' }}
          </span>
        </label>
        <label class="field">
          <span class="fl">显示名 <i class="req">可选</i></span>
          <input v-model="displayName" class="fi" type="text" name="display_name" autocomplete="nickname"
            placeholder="留空则使用用户名" :disabled="busy" />
        </label>
        <label class="field">
          <span class="fl">密码</span>
          <div class="fi-wrap">
            <input v-model="password" class="fi" :type="showPwd ? 'text' : 'password'" name="new-password"
              autocomplete="new-password" placeholder="至少 8 位" :disabled="busy" @input="error = ''" />
            <button type="button" class="eye" :title="showPwd ? '隐藏密码' : '显示密码'" @click="showPwd = !showPwd">
              <SIcon name="eye" :size="16" />
            </button>
          </div>
          <span class="hint" :class="{ bad: password && !passwordOk }">
            {{ password && !passwordOk ? '密码至少 8 位' : '密码只保存加密摘要，系统不保存明文' }}
          </span>
        </label>
        <label class="field">
          <span class="fl">确认密码</span>
          <input v-model="confirm" class="fi" :type="showPwd ? 'text' : 'password'" name="confirm-password"
            autocomplete="new-password" placeholder="再输入一次" :disabled="busy" @input="error = ''" />
          <span v-if="confirm" class="hint" :class="{ bad: !confirmOk }">{{ confirmOk ? '两次输入一致' : '两次输入不一致' }}</span>
        </label>

        <button class="submit" type="submit" :disabled="busy || !formOk">
          <SIcon v-if="busy" name="refresh" :size="15" class="spin" />
          <span>{{ busy ? '创建账号中…' : '注册并进入' }}</span>
        </button>
      </form>

      <div class="auth-foot">
        <span>已经有账号？</span>
        <router-link :to="loginTo" class="link">返回登录</router-link>
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
const displayName = ref('')
const password = ref('')
const confirm = ref('')
const showPwd = ref(false)
const busy = ref(false)
const error = ref('')

const redirect = computed(() => (typeof route.query.redirect === 'string' ? route.query.redirect : ''))
const loginTo = computed(() => (redirect.value ? { path: '/login', query: { redirect: redirect.value } } : '/login'))

/* 与后端 tripcraft/api/routers/auth.py::_validate_credentials 同规则，先在本地挡住明显非法输入 */
const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/
const usernameOk = computed(() => USERNAME_RE.test(username.value.trim()))
const passwordOk = computed(() => password.value.length >= 8)
const confirmOk = computed(() => confirm.value.length > 0 && confirm.value === password.value)
const formOk = computed(() => usernameOk.value && passwordOk.value && confirmOk.value)

function errorText(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string' && d.trim()) return d
  if (Array.isArray(d) && d.length) {
    const msg = d.map((x: any) => String(x?.msg || '')).filter(Boolean).join('；')
    if (msg) return msg
  }
  const status = e?.response?.status
  if (status === 409) return '该用户名已被注册，请换一个'
  if (status === 400) return '用户名或密码不符合规则：用户名 3–32 位字母/数字/_.-，密码至少 8 位'
  if (status === 503) return '暂时无法注册，请稍后重试'
  if (!e?.response) return '暂时无法连接，请稍后重试'
  return e?.message || '注册失败，请重试'
}

async function submit() {
  if (busy.value || !formOk.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await store.register({
      username: username.value,
      password: password.value,
      display_name: displayName.value,
    })
    if (res.signedIn) {
      await router.replace(redirect.value.startsWith('/') ? redirect.value : '/')
      return
    }
    // 服务端建号成功但没能签发会话：引导用新口令登录
    await router.replace({ path: '/login', query: { redirect: redirect.value || '/', notice: res.notice } })
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
.auth-card { width: 100%; max-width: 480px; background: #fff; border: 1px solid $color-border; border-radius: $radius-lg;
  box-shadow: $shadow-card; padding: 28px 32px 22px; }
@keyframes riseIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.rise { animation: riseIn .4s cubic-bezier(.34,1.2,.6,1) both; }

.auth-brand { display: flex; flex-direction: column; gap: 8px; }
.brand-line { font-size: $fs-meta; color: $color-text-muted; letter-spacing: .4px; }
.auth-title { margin: 20px 0 6px; font-size: 25px; font-weight: 800; }
.auth-sub { margin: 0 0 16px; font-size: $fs-meta; line-height: 1.7; color: $color-text-secondary; }

.alert { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border-radius: $radius-md;
  font-size: $fs-meta; line-height: 1.6; margin-bottom: 14px; }
.alert.err { color: #b32d2d; background: #fdecec; border: 1px solid #f7cfcf; }

.auth-form { display: flex; flex-direction: column; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.fl { font-size: $fs-meta; font-weight: 600; color: $color-text-secondary; }
.fl .req { font-style: normal; font-weight: 500; color: $color-text-muted; font-size: $fs-badge; margin-left: 6px; }
.fi { width: 100%; height: 42px; padding: 0 13px; font-size: $fs-body; color: $color-text; background: #fff;
  border: 1px solid $color-border-strong; border-radius: $radius-md; outline: none; transition: border-color .15s ease, box-shadow .15s ease; }
.fi:focus { border-color: $color-primary; box-shadow: 0 0 0 3px rgba(37,119,227,.12); }
.fi:disabled { background: #f7f8fa; color: $color-text-muted; }
.fi-wrap { position: relative; }
.fi-wrap .fi { padding-right: 44px; }
.eye { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center; border: none; background: transparent;
  color: $color-text-muted; cursor: pointer; border-radius: 8px; }
.eye:hover { color: $color-primary; background: $color-primary-softer; }
.hint { font-size: $fs-badge; color: $color-text-muted; }
.hint.bad { color: $color-danger; }

.submit { margin-top: 8px; height: 46px; display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  border: none; border-radius: $radius-md; cursor: pointer; color: #fff; font-size: $fs-body; font-weight: 700;
  background: linear-gradient(135deg, $color-primary, $color-primary-dark); box-shadow: 0 6px 16px rgba(37,119,227,.24);
  transition: transform .16s cubic-bezier(.34,1.4,.6,1), box-shadow .16s ease, filter .16s ease; }
.submit:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 10px 22px rgba(37,119,227,.3); filter: brightness(1.03); }
.submit:disabled { cursor: default; background: linear-gradient(135deg, #9dc0ee, #86aee6); box-shadow: none; }
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.auth-foot { margin-top: 14px; display: flex; align-items: center; gap: 6px; font-size: $fs-meta; color: $color-text-secondary; }
.link { color: $color-primary; font-weight: 700; }
.link:hover { text-decoration: underline; }

.scope-note { margin-top: 16px; padding: 11px 14px; border-radius: $radius-md; background: $color-bg;
  border: 1px solid $color-border; font-size: $fs-meta; line-height: 1.7; color: $color-text-secondary; }
.sn-tag { display: inline-block; margin-right: 6px; padding: 1px 8px; border-radius: 999px;
  background: $color-primary-soft; color: $color-primary; font-weight: 700; font-size: $fs-badge; }
.scope-note code { font-family: ui-monospace, monospace; font-size: $fs-meta; color: $color-text; background: #fff;
  border: 1px solid $color-border; border-radius: 4px; padding: 0 4px; }
</style>
