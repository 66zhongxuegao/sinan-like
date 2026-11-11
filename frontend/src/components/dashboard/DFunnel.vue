<template>
  <div class="dfunnel">
    <div v-for="(s, i) in steps" :key="s.label" class="dfunnel-row" :style="{ '--i': i }">
      <span class="dfunnel-name">{{ s.short }}</span>
      <div class="dfunnel-track">
        <div class="dfunnel-bar" :style="{ width: `${pct(i)}%`, background: s.color }" />
      </div>
      <span class="dfunnel-val">{{ fmt(s.value) }}</span>
      <span v-if="i > 0" class="dfunnel-conv" :class="{ warn: conv(i) < 80 }">→{{ conv(i).toFixed(0) }}%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { FunnelStep } from '@/data/dashboard'

const props = withDefaults(defineProps<{
  steps: FunnelStep[]
  showConversion?: boolean
}>(), { showConversion: true })

function pct(i: number): number {
  const top = props.steps[0]?.value || 1
  return Math.max(4, (props.steps[i].value / top) * 100)
}
function conv(i: number): number {
  const prev = props.steps[i - 1]?.value || 1
  return (props.steps[i].value / prev) * 100
}
function fmt(v: number): string {
  return v.toLocaleString('zh-CN')
}
</script>

<style scoped>
.dfunnel { display: flex; flex-direction: column; gap: 9px; padding-top: 2px; }
.dfunnel-row { display: grid; grid-template-columns: 46px minmax(0, 1fr) 56px 48px; align-items: center; gap: 9px;
  animation: funnelRow .55s cubic-bezier(.22, 1, .36, 1) both; animation-delay: calc(var(--i) * 70ms); }
.dfunnel-name { font-size: 12px; color: #5c6f8a; white-space: nowrap; }
.dfunnel-track { height: 9px; border-radius: 999px; background: #eef3fa; overflow: hidden; }
.dfunnel-bar { position: relative; height: 100%; border-radius: 999px; overflow: hidden;
  box-shadow: 0 4px 12px rgba(47, 127, 232, .20);
  animation: funnelGrow .95s cubic-bezier(.22, 1, .36, 1) both; animation-delay: calc(var(--i) * 70ms + .12s); }
.dfunnel-bar::after { content: ''; position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,.42), transparent);
  transform: translateX(-120%); animation: funnelSheen 3.6s ease-in-out 1.2s infinite; }
.dfunnel-val { font-family: 'Bahnschrift', 'Microsoft YaHei', sans-serif; font-size: 13px; color: #16223a;
  text-align: right; font-variant-numeric: tabular-nums; }
.dfunnel-conv { font-size: 10.5px; color: #0f8a5b; text-align: right; font-variant-numeric: tabular-nums; }
.dfunnel-conv.warn { color: #d98317; }
@keyframes funnelRow { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: none; } }
@keyframes funnelGrow { from { width: 0; } }
@keyframes funnelSheen { 0%, 55% { transform: translateX(-120%); } 85%, 100% { transform: translateX(120%); } }
@media (max-width: 1280px) {
  .dfunnel-row { grid-template-columns: 42px minmax(0, 1fr) 50px; }
  .dfunnel-conv { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .dfunnel-row, .dfunnel-bar { animation: none; }
  .dfunnel-bar::after { animation: none; opacity: 0; }
}
</style>