import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import client from '@/api/client'
import router from '@/router'

/**
 * 身份与学习数据归属（R08/R11/R12/R14）。
 *
 * 唯一可信身份来源是服务端会话：
 *   - localStorage 只保存会话 token（键 `tc-token`），**不保存也不读取任何 user_id**；
 *   - 启动时用 GET /auth/session 把 token 换成公开个人资料，恢复不了就当作未登录；
 *   - 所有请求经 axios 请求拦截器带 `Authorization: Bearer <token>`，401 统一跳登录页。
 *
 * 旧版「从 localStorage 任选 user_id 切换用户」的路径已经移除：
 * tc-user / tc-users 两个键在启动时即被清除，switchUser() 只接受当前会话账号。
 */

export interface SessionUser {
  user_id: string
  username: string
  display_name: string
  company: string
  phone: string
  email: string
  bio: string
  kind: string
  created_at: string
  updated_at: string
  last_login_at: string
}

export interface ProfilePatch {
  display_name?: string
  company?: string
  phone?: string
  email?: string
  bio?: string
}

export interface RegisterResult {
  signedIn: boolean
  user: SessionUser | null
  notice: string
  bootstrap: Record<string, unknown> | null
}

/** token 存储键（与旧身份键区分：旧键只存过 user_id） */
const LS_TOKEN = 'tc-token'
/** 旧版身份键：只可能存「任选他人 user_id」，启动即清除，杜绝越权入口 */
const LEGACY_IDENTITY_KEYS = ['tc-user', 'tc-users']

/** 这些端点的 401 由调用方自己反馈（登录失败 / 会话探测），不触发跳转 */
const NO_REDIRECT_401 = ['/auth/login', '/auth/register', '/auth/session']

function readToken(): string {
  try { return localStorage.getItem(LS_TOKEN) || '' } catch { return '' }
}

function persistToken(token: string): void {
  try {
    if (token) localStorage.setItem(LS_TOKEN, token)
    else localStorage.removeItem(LS_TOKEN)
  } catch { /* 无痕模式 / 无存储环境：仅内存会话 */ }
}

/** 清除旧版身份键：它们记录的是「谁都能改的 user_id」，不属于本版契约。 */
export function purgeLegacyIdentity(): void {
  try { for (const k of LEGACY_IDENTITY_KEYS) localStorage.removeItem(k) } catch { /* 忽略 */ }
}

function normalizeUser(raw: any): SessionUser {
  const u = raw || {}
  return {
    user_id: String(u.user_id || ''),
    username: String(u.username || ''),
    display_name: String(u.display_name || ''),
    company: String(u.company || ''),
    phone: String(u.phone || ''),
    email: String(u.email || ''),
    bio: String(u.bio || ''),
    kind: String(u.kind || 'real'),
    created_at: String(u.created_at || ''),
    updated_at: String(u.updated_at || ''),
    last_login_at: String(u.last_login_at || ''),
  }
}

/** 拦截器按「模块 + axios 实例」只装一次：多个 Pinia 实例/热更新下也不会重复堆积 */
let interceptorsInstalled = false
/**
 * 拦截器要作用在「当前活的」store 实例上（热更新或重建 Pinia 后，闭包里的旧 ref 已经不是
 * 页面正在用的那一份）。store 每次 setup 时把自己的读写能力登记到这里。
 */
const live: { token: () => string; clear: () => void } = { token: () => '', clear: () => {} }

export const useUserStore = defineStore('user', () => {
  // ── 会话态 ──
  const token = ref<string>(readToken())
  const profile = ref<SessionUser | null>(null)
  /** 是否已经向服务端确认过会话（成功或失败）——守卫据此决定要不要等 */
  const sessionReady = ref(false)
  const restoring = ref(false)
  /** 恢复会话的失败原因（网络错误等），供登录页提示 */
  const sessionError = ref('')

  // ── 派生身份（其他页面只读这些）──
  const userId = computed(() => profile.value?.user_id || '')
  const isAuthenticated = computed(() => !!token.value && !!profile.value)
  const displayName = computed(() => profile.value?.display_name || profile.value?.username || '')
  const username = computed(() => profile.value?.username || '')
  /**
   * 数据口径只认服务端 `users.kind`（与后端 growth.py::_data_scope 同一口径）：
   * kind === 'demo' → 标准案例 / 示例数据；其余一律真实训练数据。
   *
   * 这里**不做用户名前缀匹配**：那会误伤真实用户名（例如真有人叫 u-demo123 就会被错标），
   * 也会与后端不一致。前缀只在**注册那一刻**由服务端写进 kind，之后读取只认 kind。
   * 展示上的权威口径请优先使用 `/profiles/{id}/trend` 返回的 `data_scope.label`。
   */
  const isDemo = computed(() => profile.value?.kind === 'demo')
  /** 与 tripcraft/api/routers/growth.py::_data_scope 的 label 保持一致 */
  const dataScopeLabel = computed(() => (isDemo.value ? '标准案例 / 演示数据' : '真实训练数据'))

  // ── 兼容旧调用点（不再具备切换身份的能力）──
  /** @deprecated 身份由服务端会话决定；该列表恒为当前账号一项 */
  const users = computed(() => (profile.value
    ? [{ id: userId.value, name: displayName.value || userId.value }]
    : []))
  const consultantName = computed(() => profile.value?.display_name || profile.value?.username || '定制师')
  const companyName = computed(() => profile.value?.company || '')

  /**
   * @deprecated 旧版「切换用户」：任何非当前账号的 id 都拒绝。
   * 换账号请走登录页（真实服务端会话）。
   */
  function switchUser(id: string): boolean {
    if (id && id === userId.value) return true
    console.warn('[identity] 切换用户已下线：身份只由服务端会话决定，请使用 登录 / 退出登录。')
    return false
  }

  /** @deprecated 新建用户改为注册页（POST /auth/register） */
  function addUser(): string {
    console.warn('[identity] 新建用户已下线：请使用注册页创建真实账号。')
    return ''
  }

  // ── axios 认证头 + 401 跳登录 ──
  function installInterceptors(): void {
    if (interceptorsInstalled) return
    interceptorsInstalled = true
    client.interceptors.request.use((config) => {
      const t = live.token()
      if (t) config.headers.set('Authorization', `Bearer ${t}`)
      else config.headers.delete('Authorization')
      return config
    })
    client.interceptors.response.use(
      (resp) => resp,
      (error) => {
        const status = error?.response?.status
        const url = String(error?.config?.url || '')
        const skip = NO_REDIRECT_401.some((p) => url.startsWith(p))
        if (status === 401 && !skip) {
          // 会话失效（被退出 / 过期）：清本地态并送回登录页，登录后回到原目标
          live.clear()
          redirectToLogin('')
        }
        return Promise.reject(error)
      },
    )
  }

  function redirectToLogin(fallback: string): void {
    const cur = router.currentRoute.value
    if (cur.path === '/login' || cur.path === '/register') return
    const target = fallback && fallback.startsWith('/') ? fallback : cur.fullPath
    void router.push({
      path: '/',
      query: target && target !== '/' ? { mode: 'login', redirect: target } : { mode: 'login' },
    })
  }

  function setSession(next: string): void {
    token.value = next
    persistToken(next)
  }

  function clearLocalSession(): void {
    token.value = ''
    profile.value = null
    persistToken('')
    // 会话切换时不要保留上一个账号的订单进度条。
    try { sessionStorage.removeItem('tc-active-order') } catch { /* 忽略 */ }
  }

  // 登记为「当前活的会话」：请求头与 401 处理都从这里读，避免闭包指向失效实例
  live.token = () => token.value
  live.clear = clearLocalSession

  // ── 会话读写 ──
  async function fetchSession(): Promise<SessionUser> {
    const resp = await client.get('/auth/session')
    const u = normalizeUser(resp.data)
    profile.value = u
    return u
  }

  let inflightRestore: Promise<boolean> | null = null

  async function doRestore(): Promise<boolean> {
    restoring.value = true
    purgeLegacyIdentity()
    sessionError.value = ''
    try {
      const t = readToken()
      if (!t) {
        clearLocalSession()
        return false
      }
      setSession(t)
      await fetchSession()
      return true
    } catch (e: any) {
      profile.value = null
      if (e?.response?.status === 401) {
        clearLocalSession()
      } else {
        sessionError.value = e?.response ? `会话恢复失败（HTTP ${e.response.status}）` : '无法连接服务器，会话未能恢复'
      }
      return false
    } finally {
      restoring.value = false
      sessionReady.value = true
    }
  }

  /**
   * 启动 / 守卫调用：用本地 token 换会话资料。
   * 401 → 视为未登录（清除 token）；网络错误 → 保留 token 但本次视为未登录。
   * 并发调用共享同一次请求，避免守卫与页面各发一遍 /auth/session。
   */
  async function restore(force = false): Promise<boolean> {
    if (sessionReady.value && !force) return !!profile.value
    if (inflightRestore) return inflightRestore
    inflightRestore = doRestore()
    try {
      return await inflightRestore
    } finally {
      inflightRestore = null
    }
  }

  /** 登录：POST /auth/login → 存 token → 取公开资料 */
  async function login(name: string, password: string): Promise<SessionUser> {
    const resp = await client.post('/auth/login', { username: name.trim(), password })
    const data: any = resp.data || {}
    const t = String(data.token || '')
    if (!t) throw new Error('服务端未返回会话令牌')
    setSession(t)
    const u = data.user ? normalizeUser(data.user) : await fetchSession()
    profile.value = u
    sessionReady.value = true
    sessionError.value = ''
    return u
  }

  /**
   * 注册：POST /auth/register（注册即登录）。
   * 服务端若只创建了账号没能签发会话（token 为空），返回 signedIn=false，由页面引导去登录。
   */
  async function register(payload: {
    username: string
    password: string
    display_name?: string
  }): Promise<RegisterResult> {
    const body = {
      username: payload.username.trim(),
      password: payload.password,
      display_name: (payload.display_name || '').trim(),
    }
    const resp = await client.post('/auth/register', body)
    const data: any = resp.data || {}
    const t = String(data.token || '')
    if (!t) {
      return {
        signedIn: false,
        user: null,
        notice: String(data.login_error || '账号已创建，请用刚刚的用户名与口令登录'),
        bootstrap: (data.bootstrap as Record<string, unknown>) || null,
      }
    }
    setSession(t)
    profile.value = normalizeUser(data)
    sessionReady.value = true
    sessionError.value = ''
    return {
      signedIn: true,
      user: profile.value,
      notice: '',
      bootstrap: (data.bootstrap as Record<string, unknown>) || null,
    }
  }

  /** 退出：先让服务端吊销会话，再清本地 token（顺序不能反） */
  async function logout(): Promise<void> {
    try {
      if (token.value) await client.post('/auth/logout')
    } catch { /* 幂等：服务端登出失败也必须清掉本地会话 */ }
    clearLocalSession()
    purgeLegacyIdentity()
    sessionReady.value = true
    if (router.currentRoute.value.path !== '/') {
      await router.push({ path: '/', query: { mode: 'login' } })
    } else if (router.currentRoute.value.query.mode !== 'login') {
      await router.replace({ path: '/', query: { mode: 'login' } })
    }
  }

  /** 个人资料：PATCH /auth/profile（后端白名单 display_name/company/phone/email/bio） */
  async function updateProfile(fields: ProfilePatch): Promise<SessionUser> {
    const resp = await client.patch('/auth/profile', fields)
    const u = normalizeUser(resp.data)
    profile.value = u
    return u
  }

  /** @deprecated 保留旧签名；改为写服务端资料 */
  async function setProfile(name: string, company = ''): Promise<void> {
    await updateProfile({ display_name: name, company })
  }

  /** 主动刷新会话资料（例如更新画像后） */
  async function refreshProfile(): Promise<SessionUser | null> {
    if (!token.value) return null
    try { return await fetchSession() } catch { return null }
  }

  installInterceptors()

  return {
    // 会话态
    token, profile, sessionReady, restoring, sessionError,
    // 派生
    userId, username, displayName, isAuthenticated, isDemo, dataScopeLabel,
    consultantName, companyName, users,
    // 动作
    restore, login, register, logout, updateProfile, setProfile, refreshProfile,
    redirectToLogin,
    // 兼容旧调用点（已失效，保留签名以免旧页面编译失败）
    switchUser, addUser,
  }
})

export default useUserStore
