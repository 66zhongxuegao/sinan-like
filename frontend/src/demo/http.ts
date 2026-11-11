import axios from 'axios'

/* 标准案例页的 HTTP 层。
 *
 * 【反例边界，必须保持】这里**没有** axios 请求/响应拦截器：
 *   - 不做全局 `client.interceptors.response.use(...)`（旧 frontend/src/demo/fixtures.ts 就是
 *     用拦截器把后端响应改写成写死的剧本，属于伪造链路，已删除）。
 *   - 不把失败吞掉后继续走下一步：任何非 2xx、或网络层错误（无 response），
 *     都在这里抛成 `DemoHttpError`，由调用方负责停住并显示。
 *
 * 会话：token 与 identity 域 store 用同一份状态（localStorage `tc-token`）；
 * 本页不另立会话、不伪造身份。未登录时 /scenario/* 由后端 401（直接打开 /demo 也会被
 * router/index.ts 的全局守卫先送去 /login）。
 */

/** 会话 token 的存储键：与 identity 域 stores/user.ts 的 `LS_TOKEN` 是同一个键。 */
const LS_TOKEN = 'tc-token'

/**
 * 读当前会话 token。
 * identity 域的 store 把 token 写在这里并由其请求拦截器加到所有 axios 请求上；
 * 本页显式再带一次，是为了让「未带 token → 401」这条失败路径在页面层面可验证
 * （而不是被别处的全局拦截器掩盖）。
 */
export function readSessionToken(): string {
  try {
    return localStorage.getItem(LS_TOKEN) || ''
  } catch {
    return ''
  }
}

/** 统一的失败类型：HTTP 错误与网络错误都必须是显式错误，不许静默。 */
export class DemoHttpError extends Error {
  /** 后端返回的 HTTP 状态码；网络层失败（连接不上/超时）时为 0。 */
  readonly code: number
  readonly method: string
  readonly url: string
  readonly detail: string
  /** 后端原始响应体（用于在页面上展示真实回执，不做二次加工）。 */
  readonly payload: unknown

  constructor(init: { code: number; method: string; url: string; detail: string; payload?: unknown }) {
    super(`[${init.code || 'NETWORK'}] ${init.method} ${init.url} → ${init.detail}`)
    this.name = 'DemoHttpError'
    this.code = init.code
    this.method = init.method
    this.url = init.url
    this.detail = init.detail
    this.payload = init.payload
  }

  /** 未登录 / 会话失效：页面据此提示去 /login，不静默重试。 */
  get isUnauthorized(): boolean {
    return this.code === 401
  }

  /** 后端显式拒绝（如非演示实例的 provider 开关返回 409），原样透出给用户。 */
  get isForbidden(): boolean {
    return this.code === 403 || this.code === 409
  }
}

function detailOf(data: unknown, fallback: string): string {
  if (typeof data === 'string' && data.trim()) return data.trim()
  if (data && typeof data === 'object') {
    const d = (data as { detail?: unknown }).detail
    if (typeof d === 'string' && d.trim()) return d.trim()
    if (Array.isArray(d) && d.length) {
      // FastAPI 校验错误是数组，逐条取 msg，避免整段 JSON 糊在页面上
      const msgs = d
        .map((x) => (x && typeof x === 'object' ? String((x as { msg?: unknown }).msg || JSON.stringify(x)) : String(x)))
        .filter(Boolean)
      if (msgs.length) return msgs.join('；')
    }
    try {
      return JSON.stringify(data)
    } catch {
      return fallback
    }
  }
  return fallback
}

function qs(query?: Record<string, string | number | boolean>): string {
  if (!query) return ''
  const parts = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

interface RequestOptions {
  method: 'GET' | 'POST'
  query?: Record<string, string | number | boolean>
  body?: unknown
  /** 显式指定 token；不传则每次从 store 的同一份会话状态里取。 */
  token?: string
}

/**
 * 唯一出网口。不注册任何拦截器；axios 返回非 2xx 会 reject，这里统一转成 DemoHttpError。
 */
async function request<T>(path: string, opts: RequestOptions): Promise<T> {
  const url = `/api${path}${qs(opts.query)}`
  const token = opts.token !== undefined ? opts.token : readSessionToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    const res = await axios.request<T>({
      url,
      method: opts.method,
      data: opts.body,
      headers,
      // 显式：不隐藏 4xx/5xx，让它们作为异常冒出来
      validateStatus: (s) => s >= 200 && s < 300,
    })
    return res.data
  } catch (err) {
    if (axios.isAxiosError(err)) {
      // 有响应 → 后端明确的 HTTP 拒绝；无响应 → 网络层失败。两者都不放过。
      const code = err.response?.status ?? 0
      const detail = err.response
        ? detailOf(err.response.data, `HTTP ${code}`)
        : `${err.code || 'NETWORK_ERROR'} ${err.message || '请求未到达后端'}`
      throw new DemoHttpError({
        code,
        method: opts.method,
        url,
        detail,
        payload: err.response?.data,
      })
    }
    throw new DemoHttpError({
      code: 0,
      method: opts.method,
      url,
      detail: err instanceof Error ? err.message : String(err),
    })
  }
}

export const demoHttp = {
  get: <T>(path: string, query?: Record<string, string | number | boolean>, token?: string) =>
    request<T>(path, { method: 'GET', query, token }),
  post: <T>(path: string, body?: unknown, query?: Record<string, string | number | boolean>, token?: string) =>
    request<T>(path, { method: 'POST', body, query, token }),
}

/** 把任意异常转成可展示文本（页面只显示真实错误，不替换成好听的文案）。 */
export function errorText(err: unknown): string {
  if (err instanceof DemoHttpError) return err.message
  if (err instanceof Error) return `${err.name}: ${err.message}`
  return String(err)
}
