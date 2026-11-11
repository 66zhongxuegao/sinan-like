/* 标准案例（演示数据）接口的**类型化封装**：只调真实后端，一个字段都不改写。
 *
 * 对应后端（owner: scenario 域）：
 *   GET  /scenario/cases                      → 目录（含 stage_plan 与模式状态）
 *   GET  /scenario/cases/{case_id}            → 单案例展开（文档/计划/首呼口径/行中事件/验收）
 *   GET  /scenario/status?probe=               → 当前模式（offline 确定性 / live 实时）与依赖实测状态
 *   GET  /scenario/account?case_id=           → 当前账号的标准案例数据计数
 *   POST /scenario/cases/{case_id}/import     → 真实 spawn_order 落单
 *   POST /scenario/cases/{case_id}/reset      → 只清当前账号（返回 before/after 与删除清单）
 *   GET  /scenario/orders/{order_id}/state    → 每步服务端状态（六阶段闸门 + 计数）
 *   POST /scenario/provider/offline|live      → 实例模式开关（非演示实例返回 409，原样透出）
 * 以及既有业务接口 GET /practice/messages（消息中心拉单用）。
 *
 * 所有失败都由 http.ts 抛 DemoHttpError：调用方要么呈现错误并停住，要么不调用。
 */

import { demoHttp, readSessionToken } from './http'

/** 每次调用都从会话状态取 token，避免把 token 缓存在模块里过期不更新。 */
function auth(): string | undefined {
  return readSessionToken() || undefined
}

/**
 * 标准案例演示账号（来源：data/scenario/standard_case.json 的 cases[].isolation）。
 * 仅供页面提示用户「该用哪个账号登录」；本页不替用户注册、不伪造身份。
 */
export const DEMO_ACCOUNT = {
  username: 'demo-lvyuan',
  label: '标准案例演示账号',
  source: 'data/scenario/standard_case.json · isolation.demo_account_username',
} as const

export interface RealtimeDependency {
  needed_for?: string[]
  offline_substitute?: string
  verification_status?: string
}

export interface CaseSummary {
  case_id: string
  title: string
  demo_label: string
  demo_data: boolean
  customer: string
  source_market: string
  language: string
  destination: string
  party: Record<string, number | string>
  dates: { start?: string; end?: string } | string
  days: number
  budget: Record<string, number | string>
  hotel: Record<string, unknown>
  transport: Record<string, unknown>
  special: unknown
  resource_constraints: Array<{
    kind?: string
    availability?: string
    price_factor?: number
    note?: string
  }>
  demo_account: string
  stage_ids: string[]
  realtime_dependencies: Record<string, RealtimeDependency>
}

export interface StageSubstep {
  id: string
  name: string
  hint: string
  step: string
  deliverable: string
}

export interface StageEntry {
  id: string
  name: string
  short: string
  order: number
  steps: string[]
  deliverables: string[]
  focus: string
  substeps: StageSubstep[]
}

/**
 * 依赖实测状态：**区分「配置存在」与「真实连通已核验」**（后端口径，前者不得当后者用）。
 * 字段名与 tripcraft/services/scenario_service.py:dependency_status() 逐字对应。
 */
export interface DependencyStatus {
  llm_key_present: boolean
  llm_key_source: string
  llm_connectivity_verified: boolean
  llm_not_verified_reason: string
  llm_probe_model?: string
  voice_key_present: boolean
  voice_key_source: string
  voice_connectivity_verified: boolean
  voice_not_verified_reason: string
  db_path: string
  auth_mode: string
  scenario_mode_env: string
}

export interface ScenarioStatus {
  mode: string
  /** scope=instance：模式由**本实例启动参数**决定，不提供运行期全局切换。 */
  scope?: string
  /** 实例级内部演示开关（启动期后台配置）：enabled=true 才会把随机游客替换成固定案例。 */
  demo_instance?: { enabled: boolean; case_id: string; mode: string; reason: string } | boolean
  scenario_mode_env?: string
  switch_policy?: string
  instance_note?: string
  session_state?: string
  scenario_llm_active: boolean
  provider_model: string
  provider_audit: { calls?: number; by_handler?: Record<string, number> } | Record<string, never>
  demo_label: string
  case_digest: string
  confidence_cap: number
  deps: DependencyStatus
  honest_notes: string[]
}

export interface ScenarioCatalog {
  cases: CaseSummary[]
  digest: string
  stage_plan: StageEntry[]
  demo_label: string
  status: ScenarioStatus
}

export interface ScenarioCaseDetail extends CaseSummary {
  stage_plan: StageEntry[]
  documents: Record<string, unknown>
  plan: Record<string, unknown>
  first_call: Record<string, unknown>
  incident: Record<string, unknown>
  acceptance: Record<string, unknown>
  replay: Record<string, unknown>
}

/** POST /scenario/cases/{id}/import 的真实回执（scenario_service.import_case 的返回）。 */
export interface ImportReceipt {
  order_id: string
  case_id: string
  demo_label: string
  demo_data: boolean
  user_id: string
  customer: string
  destination: string
  stage_index: number
  scenario_marker: { scenario_id: string; scenario_label: string; demo_data: boolean }
  fixed_fields: Record<string, unknown>
  missing_fields: string[]
  resources_injected: Array<{ kind: string; state: unknown }>
  next_action: string
}

export interface AccountCounts {
  user_id: string
  orders: number
  scenario_orders: number
  scenario_order_ids: string[]
  evidence: number
  deliverables: number
  ability_rows: number
  quiz_attempts: number
  threads: number
  notices: number
  calibration_runs: number
}

/** POST /scenario/cases/{id}/reset 的真实回执。 */
export interface ResetReceipt {
  ok: boolean
  user_id: string
  case_id: string
  scope: string
  orders_targeted: string[]
  deleted: Record<string, number>
  before: AccountCounts
  after: AccountCounts
  isolation_note: string
}

/** GET /scenario/orders/{order_id}/state —— 每步服务端状态（不是前端推断）。 */
export interface OrderGateCheck {
  action: string
  label: string
  hint: string
  where: string
  ok: boolean
  reason: string
  manual: boolean
}

export interface OrderState {
  order_id: string
  scenario_id: string
  demo_label: string
  demo_data: boolean
  status: string
  stage_index: number
  stage_name: string
  stage_id: string
  stage_of_step_contract_version: number
  internal_step: string
  gate: {
    order_id?: string
    stage_index?: number
    stage_name?: string
    stage_hint?: string
    step?: string
    step_evidence?: string
    checks?: OrderGateCheck[]
    done?: number
    total?: number
    passed?: boolean
    next?: { action?: string; label?: string; hint?: string; where?: string }
  }
  actions: string[]
  evidence_count: number
  deliverables: string[]
  incidents: Array<{ code: string; title: string; channel: string }>
  scores: { evaluated: number; pending_review: number; average: number | null }
  ability_written: Record<string, { real_v: number | null; teach: number | null }>
}

export interface PracticeMessageGroup {
  key: string
  label: string
  count: number
  children: Array<{ key: string; label: string; count: number; star?: boolean }>
}

export interface PracticeMessages {
  groups: PracticeMessageGroup[]
  messages: Array<Record<string, unknown>>
}

export const scenarioApi = {
  catalog: () => demoHttp.get<ScenarioCatalog>('/scenario/cases', undefined, auth()),
  caseDetail: (caseId: string) => demoHttp.get<ScenarioCaseDetail>(`/scenario/cases/${caseId}`, undefined, auth()),
  /** probe=true 时后端会**真发一次最小 LLM 请求**核验连通性（并如实记录失败原因）。 */
  status: (probe = false) =>
    demoHttp.get<ScenarioStatus>('/scenario/status', probe ? { probe: true } : undefined, auth()),
  account: (caseId = '') => demoHttp.get<AccountCounts>('/scenario/account', caseId ? { case_id: caseId } : undefined, auth()),
  importCase: (caseId: string) => demoHttp.post<ImportReceipt>(`/scenario/cases/${caseId}/import`, undefined, undefined, auth()),
  resetCase: (caseId: string, includeProfile = true) =>
    demoHttp.post<ResetReceipt>(`/scenario/cases/${caseId}/reset`, undefined, { include_profile: includeProfile }, auth()),
  orderState: (orderId: string) => demoHttp.get<OrderState>(`/scenario/orders/${orderId}/state`, undefined, auth()),
  practiceMessages: () => demoHttp.get<PracticeMessages>('/practice/messages', undefined, auth()),
  /** 实例模式开关：只在以 TRIPCRAFT_SCENARIO_MODE=offline 启动的演示实例上生效，否则后端 409。 */
  providerOffline: () => demoHttp.post<Record<string, unknown>>('/scenario/provider/offline', undefined, undefined, auth()),
  providerLive: () => demoHttp.post<Record<string, unknown>>('/scenario/provider/live', undefined, undefined, auth()),
}

/** 模式口径：offline = 确定性演示数据，live = 实时模型。两者都不是「前端模拟」。 */
export function modeText(mode: string): { key: string; label: string; note: string } {
  const m = String(mode || '').toLowerCase()
  if (m === 'offline') {
    return {
      key: 'offline',
      label: '演示数据 · 确定性离线',
      note: '回答来自标准案例资料（客户对话 / 训练老师 / 评分 / 画像刷新），不是实时模型生成。',
    }
  }
  if (m === 'live') {
    return {
      key: 'live',
      label: '实时模型',
      note: '模型调用走真实服务；是否真的可用见下面的「实时模型」状态（已配置 ≠ 已核验可用）。',
    }
  }
  return { key: 'unknown', label: `未知模式（${mode || '空'}）`, note: '后端返回了预期之外的 mode 值，按未知处理' }
}
