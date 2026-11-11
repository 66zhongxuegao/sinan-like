<template>
  <!-- 首页与实战页共用的同一套流程标准：六阶段，数据全部来自 props（R09/R10） -->
  <nav class="stage-nav" :class="{ dense }" aria-label="实战流程阶段">
    <button
      v-for="(s, i) in stages"
      :key="s.id"
      class="sn-item"
      :class="[stateOf(s.id), { on: s.id === current }]"
      type="button"
      :title="s.focus"
      @click="$emit('pick', s.id)"
    >
      <span class="sn-dot">
        <SIcon v-if="stateOf(s.id) === 'done'" name="check" :size="12" />
        <template v-else>{{ i + 1 }}</template>
      </span>
      <span class="sn-mid">
        <span class="sn-name">{{ s.name }}</span>
        <span v-if="!dense && s.focus" class="sn-focus">{{ s.focus }}</span>
      </span>
      <span v-if="i < stages.length - 1" class="sn-line" />
    </button>
  </nav>
</template>

<script setup lang="ts">
import SIcon from '@/components/SIcon.vue'
import type { StageDef } from '@/composables/useStages'

const props = withDefaults(
  defineProps<{
    stages: StageDef[]
    current?: string
    /** 各阶段状态覆盖；不传时只有 current 高亮，其余按顺序推断为 done/todo */
    states?: Record<string, 'done' | 'current' | 'todo'>
    /** 紧凑模式：隐藏 focus 说明，适合放在卡片里 */
    dense?: boolean
  }>(),
  { current: '', states: () => ({}), dense: false },
)

defineEmits<{ pick: [stageId: string] }>()

function stateOf(id: string): 'done' | 'current' | 'todo' {
  const explicit = props.states?.[id]
  if (explicit) return explicit
  const ci = props.stages.findIndex((s) => s.id === props.current)
  const i = props.stages.findIndex((s) => s.id === id)
  if (ci < 0 || i < 0) return 'todo'
  if (i < ci) return 'done'
  return i === ci ? 'current' : 'todo'
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.stage-nav { display: flex; align-items: stretch; gap: 0; flex-wrap: wrap;
  background: #fff; border: 1px solid $color-border; border-radius: $radius-md; padding: 6px; }

.sn-item { position: relative; display: flex; align-items: center; gap: 9px; flex: 1 1 190px; min-width: 0;
  text-align: left; padding: 10px 12px; border: none; background: transparent; border-radius: $radius-sm;
  font-family: inherit; cursor: pointer; transition: background .16s ease, color .16s ease; }
.sn-item:hover { background: $color-primary-softer; }
.sn-item.on { background: $color-primary-soft; }

.sn-dot { width: 24px; height: 24px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; font-size: 14px; font-weight: 700;
  background: #eef1f5; color: $color-text-muted; }
.sn-item.done .sn-dot { background: #e8f7ee; color: #12a76a; }
.sn-item.on .sn-dot { background: $color-primary; color: #fff; }

.sn-mid { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.sn-name { font-size: 15px; color: $color-text-secondary; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.sn-item.done .sn-name { color: $color-text-secondary; }
.sn-item.on .sn-name { color: $color-primary; font-weight: 700; }
.sn-focus { font-size: 13px; line-height: 1.45; color: $color-text-muted; }

.sn-line { position: absolute; right: -1px; top: 50%; width: 1px; height: 22px;
  background: $color-border; transform: translateY(-50%); }

.dense .sn-item { flex-basis: 130px; padding: 8px 10px; }
.dense .sn-name { font-size: 14.5px; }
</style>
