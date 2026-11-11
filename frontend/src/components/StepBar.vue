<template>
  <!--
    六阶段进度条（R09）：本组件**不再**平铺 13 个内部状态 S0–S12。
    阶段口径只来自两处：外部传入的 `stages`（props）或 `useStages()`（GET /practice/stages，
    即 tripcraft/contracts/stages.py 的投影）。接口不可用时显示错误态 + 重试，不用硬编码兜底。
    渲染统一走 StageNav，保证首页 / 实战页 / 订单详情看到的是同一个流程标准。
  -->
  <div class="stepbar-wrap">
    <div v-if="showState && loading" class="sb-state">流程阶段加载中…</div>
    <div v-else-if="showState && error" class="sb-state err">
      <span class="sb-err">{{ error }}</span>
      <button class="sb-retry" type="button" @click="retry">重试</button>
    </div>
    <div v-else-if="showState" class="sb-state err">
      <span class="sb-err">暂时没加载出来</span>
      <button class="sb-retry" type="button" @click="retry">重试</button>
    </div>
    <StageNav
      v-else
      :stages="stageList"
      :current="current"
      :states="states"
      :dense="dense"
      @pick="$emit('pick', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import StageNav from '@/components/StageNav.vue'
import { useStages, type StageDef } from '@/composables/useStages'

const props = withDefaults(
  defineProps<{
    /** 当前阶段 id（六阶段契约里的 stage id，例如 pre2_plan），不是 S0–S12 内部步骤号 */
    current?: string
    /** 外部直接传入阶段定义时优先用它（例如订单卡片用 journey 的阶段） */
    stages?: StageDef[]
    /** 各阶段状态覆盖：done / current / todo */
    states?: Record<string, 'done' | 'current' | 'todo'>
    /** 紧凑模式（卡片内） */
    dense?: boolean
  }>(),
  { current: '', states: () => ({}), dense: false },
)

defineEmits<{ pick: [stageId: string] }>()

const { stages: apiStages, loading, error, load } = useStages()

// 只在没拿到外部阶段时请求接口，避免每张订单卡片都打一次 /practice/stages
onMounted(() => {
  if (!props.stages || !props.stages.length) load()
})

const stageList = computed<StageDef[]>(() => {
  const fromProps = props.stages || []
  return fromProps.length ? fromProps : apiStages.value
})

/** 加载 / 错误 / 空三态只在「既没有外部阶段、又拿不到接口」时占用版面 */
const showState = computed(() => stageList.value.length === 0)

function retry() {
  load(true)
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.stepbar-wrap { display: block; }
.sb-state { display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid $color-border;
  border-radius: $radius-md; padding: 14px 16px; font-size: 15px; color: $color-text-muted; }
.sb-state.err { color: $color-text-secondary; }
.sb-err { flex: 1; }
.sb-retry { flex-shrink: 0; height: 28px; padding: 0 12px; border-radius: 7px; border: 1px solid $color-primary;
  background: $color-primary-softer; color: $color-primary; font-size: 14px; font-family: inherit;
  font-weight: 600; cursor: pointer; }
.sb-retry:hover { background: $color-primary; color: #fff; }
</style>
