<template>
  <div class="dheat">
    <div class="dheat-body">
      <div class="dheat-hours">
        <span v-for="(h, i) in hours" :key="h" :class="{ dim: i % 2 === 1 && i !== hours.length - 1 }">{{ i % 2 === 0 || i === hours.length - 1 ? h : '' }}</span>
      </div>
      <div class="dheat-grid">
        <div v-for="(day, r) in days" :key="day" class="dheat-row">
          <span class="dheat-day">{{ day }}</span>
          <div v-for="(v, c) in values[r]" :key="`${r}-${c}`" class="dheat-cell"
            :style="{ background: bg(v), '--i': r * 12 + c, boxShadow: v > 78 ? '0 0 0 1px rgba(16,169,154,.28)' : 'none' }"
            :title="`${day} ${hours[c]}:00 · 活跃度 ${v}`" />
        </div>
      </div>
    </div>
    <div class="dheat-legend">
      <span>低</span>
      <i v-for="n in 5" :key="n" :style="{ background: bg((n - 1) * 25) }" />
      <span>高</span>
      <b>峰值：周五 16:00</b>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  days: string[]
  hours: string[]
  values: number[][]
}>()

function bg(v: number): string {
  const t = Math.max(0, Math.min(1, v / 100))
  if (t > 0.72) return `rgba(16, 169, 154, ${(0.16 + t * 0.72).toFixed(2)})`
  if (t > 0.42) return `rgba(47, 127, 232, ${(0.12 + t * 0.62).toFixed(2)})`
  return `rgba(47, 127, 232, ${(0.05 + t * 0.30).toFixed(2)})`
}
</script>

<style scoped>
.dheat { display: flex; flex-direction: column; gap: 10px; }
.dheat-body { display: flex; flex-direction: column; gap: 5px; }
.dheat-hours { display: grid; grid-template-columns: 34px repeat(12, minmax(0, 1fr)); gap: 4px; padding-left: 0; }
.dheat-hours span { font-size: 9.5px; color: #8a9bb2; text-align: center; font-family: 'Bahnschrift', sans-serif; }
.dheat-hours span.dim { color: transparent; }
.dheat-grid { display: flex; flex-direction: column; gap: 4px; }
.dheat-row { display: grid; grid-template-columns: 34px repeat(12, minmax(0, 1fr)); gap: 4px; align-items: center; }
.dheat-day { font-size: 10.5px; color: #5c6f8a; white-space: nowrap; }
.dheat-cell { height: 17px; border-radius: 4px; animation: heatIn .5s cubic-bezier(.22, 1, .36, 1) both;
  animation-delay: calc(var(--i) * 7ms); transition: transform .15s ease, filter .15s ease; }
.dheat-cell:hover { transform: scale(1.16); filter: saturate(1.3); z-index: 2; }
.dheat-legend { display: flex; align-items: center; gap: 5px; font-size: 10px; color: #8a9bb2; }
.dheat-legend i { width: 16px; height: 8px; border-radius: 2px; display: inline-block; }
.dheat-legend b { margin-left: auto; font-weight: 600; color: #5c6f8a; }
@keyframes heatIn { from { opacity: 0; transform: scale(.5); } to { opacity: 1; transform: scale(1); } }
@media (prefers-reduced-motion: reduce) { .dheat-cell { animation: none; } }
</style>