/**
 * 六阶段契约前端唯一入口（journey 域共享，冻结 v1）。
 *
 * 口径来源：后端 `GET /practice/stages`（= tripcraft/contracts/stages.py 的 as_payload()）。
 * 这里**不**内置第二份阶段表：接口不可用时暴露 error 让页面显示重试，
 * 避免前端出现与契约不同步的硬编码阶段（R09 的反例就是旧 StepBar 平铺 S0–S12）。
 */
import { ref, type Ref } from 'vue'
import client from '@/api/client'

export interface SubstepDef {
  id: string
  name: string
  hint: string
  step: string
  deliverable: string
}

export interface StageDef {
  id: string
  name: string
  short: string
  order: number
  steps: string[]
  deliverables: string[]
  focus: string
  primary_deliverable: string
  substeps: SubstepDef[]
}

export interface StagesPayload {
  version: number
  stages: StageDef[]
  step_names: Record<string, string>
  stage_of_step: Record<string, string>
  stage_of_deliverable: Record<string, string>
}

// 模块级单例：首页 / 订单列表 / 订单详情 / 工作台共用一次请求
const stages = ref<StageDef[]>([])
const stepNames = ref<Record<string, string>>({})
const stageOfDeliverable = ref<Record<string, string>>({})
const loading = ref(false)
const error = ref('')
let loaded = false
let inflight: Promise<void> | null = null

export function useStages(): {
  stages: Ref<StageDef[]>
  stepNames: Ref<Record<string, string>>
  stageOfDeliverable: Ref<Record<string, string>>
  loading: Ref<boolean>
  error: Ref<string>
  load: (force?: boolean) => Promise<void>
  stageById: (id: string) => StageDef | undefined
  stageOfCode: (code: string) => StageDef | undefined
} {
  async function load(force = false): Promise<void> {
    if (loaded && !force) return
    if (inflight) return inflight
    loading.value = true
    error.value = ''
    inflight = client
      .get<StagesPayload>('/practice/stages')
      .then((r) => {
        stages.value = r.data?.stages || []
        stepNames.value = r.data?.step_names || {}
        stageOfDeliverable.value = r.data?.stage_of_deliverable || {}
        loaded = stages.value.length > 0
      })
      .catch((e: any) => {
        error.value = e?.response?.data?.detail || '流程阶段加载失败，请检查登录状态后重试'
      })
      .finally(() => {
        loading.value = false
        inflight = null
      })
    return inflight
  }

  function stageById(id: string): StageDef | undefined {
    return stages.value.find((s) => s.id === id)
  }

  function stageOfCode(code: string): StageDef | undefined {
    const sid = stageOfDeliverable.value[code] || ''
    return sid ? stageById(sid) : undefined
  }

  return { stages, stepNames, stageOfDeliverable, loading, error, load, stageById, stageOfCode }
}
