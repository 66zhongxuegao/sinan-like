<template>
  <div class="ddonut">
    <div class="ddonut-ring" :style="{ width: `${size}px`, height: `${size}px` }">
      <svg :viewBox="`0 0 ${size} ${size}`">
        <circle :cx="half" :cy="half" :r="radius" fill="none" stroke="#eef3fa" :stroke-width="thickness" />
        <circle v-for="(s, i) in segments" :key="s.label" :cx="half" :cy="half" :r="radius" fill="none"
          :stroke="s.color" :stroke-width="thickness" stroke-linecap="round"
          :stroke-dasharray="`${Math.max(0, s.len - 3)} ${C}`" :stroke-dashoffset="s.offset"
          class="ddonut-seg" :style="{ '--from': C, '--to': s.offset, animationDelay: `${0.15 + i * 0.13}s` }" />
      </svg>
      <div class="ddonut-center">
        <b>{{ total.toLocaleString('zh-CN') }}</b>
        <span>{{ centerLabel }}</span>
      </div>
    </div>
    <div class="ddonut-legend">
      <div v-for="s in segments" :key="`l-${s.label}`" class="ddonut-leg">
        <i :style="{ background: s.color }" />
        <span>{{ s.label }}</span>
        <b>{{ pct(s.value) }}%</b>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DonutItem } from '@/data/dashboard'

const props = withDefaults(defineProps<{
  items: DonutItem[]
  size?: number
  thickness?: number
  centerLabel?: string
}>(), { size: 152, thickness: 15, centerLabel: '学员' })

const half = computed(() => props.size / 2)
const radius = computed(() => props.size / 2 - props.thickness / 2 - 2)
const C = computed(() => 2 * Math.PI * radius.value)
const total = computed(() => props.items.reduce((a, b) => a + b.value, 0))

const segments = computed(() => {
  let acc = 0
  return props.items.map((it) => {
    const len = total.value ? (it.value / total.value) * C.value : 0
    const seg = { ...it, len, offset: -acc }
    acc += len
    return seg
  })
})

function pct(v: number): string {
  if (!total.value) return '0'
  return ((v / total.value) * 100).toFixed(0)
}
</script>

<style scoped>
.ddonut { display: flex; align-items: center; gap: 18px; }
.ddonut-ring { position: relative; flex-shrink: 0; }
.ddonut-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); overflow: visible; }
.ddonut-seg { animation: donutIn 1.05s cubic-bezier(.22, 1, .36, 1) both; }
.ddonut-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; }
.ddonut-center b { font-family: 'Bahnschrift', 'Microsoft YaHei', sans-serif; font-size: 22px; letter-spacing: -.4px; color: #16223a; }
.ddonut-center span { font-size: 10.5px; color: #8a9bb2; letter-spacing: 1px; }
.ddonut-legend { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 9px; }
.ddonut-leg { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #5c6f8a; }
.ddonut-leg i { width: 8px; height: 8px; border-radius: 3px; flex-shrink: 0; }
.ddonut-leg b { margin-left: auto; color: #16223a; font-family: 'Bahnschrift', sans-serif; font-size: 13px; }
@keyframes donutIn { from { stroke-dashoffset: var(--from); opacity: .2; } to { stroke-dashoffset: var(--to); opacity: 1; } }
@media (max-width: 1280px) {
  .ddonut { flex-direction: column; align-items: flex-start; gap: 12px; }
  .ddonut-legend { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 7px 14px; }
}
@media (prefers-reduced-motion: reduce) {
  .ddonut-seg { animation: none; }
}
</style>