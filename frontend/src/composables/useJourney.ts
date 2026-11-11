/**
 * 单订单的六阶段旅程投影（journey 域共享，冻结 v1）。
 *
 * 消费 `GET /practice/orders/{id}/journey`：阶段状态、子步骤状态、唯一下一步动作。
 * 失败时**保留上一次成功值**（只有切换订单才清空），避免页面闪空导致学员以为进度丢了。
 */
import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import client from '@/api/client'

export type NextActionKind = 'deliverable' | 'call' | 'plan' | 'action' | 'im' | 'score' | 'done'

export interface NextAction {
  kind: NextActionKind
  stage: string
  substep: string
  deliverable: string
  label: string
  detail: string
  route: string
}

export interface JourneySubstep {
  id: string
  name: string
  hint: string
  step: string
  deliverable: string
  state: 'done' | 'current' | 'todo'
  done: boolean
}

export interface JourneyStage {
  id: string
  name: string
  short: string
  order: number
  focus: string
  primary_deliverable: string
  state: 'done' | 'current' | 'todo'
  done_count: number
  total_count: number
  substeps: JourneySubstep[]
  deliverables: Array<{ code: string; title: string; submitted: boolean; version: number }>
  next_action: NextAction | null
}

export function useJourney(orderId: Ref<string> | string): {
  journey: Ref<any | null>
  loading: Ref<boolean>
  error: Ref<string>
  stages: ComputedRef<JourneyStage[]>
  currentStageId: ComputedRef<string>
  currentStage: ComputedRef<JourneyStage | null>
  nextAction: ComputedRef<NextAction | null>
  stageStates: ComputedRef<Record<string, 'done' | 'current' | 'todo'>>
  refresh: () => Promise<void>
} {
  const idRef: Ref<string> = typeof orderId === 'string' ? ref(orderId) : orderId
  const journey = ref<any | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function refresh(): Promise<void> {
    const id = String(idRef.value || '')
    if (!id) {
      journey.value = null
      return
    }
    loading.value = true
    error.value = ''
    try {
      journey.value = (await client.get(`/practice/orders/${id}/journey`)).data
    } catch (e: any) {
      // 保留上一次成功值：接口抖动不应把已显示的进度清空
      error.value = e?.response?.data?.detail || '流程进度加载失败'
    } finally {
      loading.value = false
    }
  }

  watch(
    idRef,
    (next, prev) => {
      if (next !== prev) journey.value = null
      refresh()
    },
    { immediate: true },
  )

  const stages = computed<JourneyStage[]>(() => journey.value?.stages || [])
  const currentStageId = computed<string>(() => journey.value?.current_stage || '')
  const currentStage = computed<JourneyStage | null>(
    () => stages.value.find((s) => s.id === currentStageId.value) || null,
  )
  const nextAction = computed<NextAction | null>(() => journey.value?.next_action || null)
  const stageStates = computed<Record<string, 'done' | 'current' | 'todo'>>(() => {
    const out: Record<string, 'done' | 'current' | 'todo'> = {}
    for (const s of stages.value) out[s.id] = s.state
    return out
  })

  return {
    journey,
    loading,
    error,
    stages,
    currentStageId,
    currentStage,
    nextAction,
    stageStates,
    refresh,
  }
}
