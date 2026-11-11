<template>
  <svg class="dspark" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" :style="{ width: `${width}px`, height: `${height}px` }">
    <defs>
      <linearGradient :id="gid" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity=".22" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path :d="area" :fill="`url(#${gid})`" class="dspark-area" />
    <path :d="line" :stroke="color" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
      vector-effect="non-scaling-stroke" pathLength="1" class="dspark-line" />
  </svg>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'

const props = withDefaults(defineProps<{
  data: number[]
  color?: string
  width?: number
  height?: number
}>(), { color: '#5b9dff', width: 104, height: 36 })

const W = 100
const H = 36
const gid = `spark-${useId()}`

const points = computed(() => {
  const d = props.data.length ? props.data : [0, 0]
  const min = Math.min(...d)
  const max = Math.max(...d)
  const span = max - min || 1
  const pad = 4
  return d.map((v, i) => ({
    x: d.length === 1 ? W / 2 : (i / (d.length - 1)) * W,
    y: pad + (1 - (v - min) / span) * (H - pad * 2),
  }))
})

function smooth(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return ''
  if (pts.length === 1) return `M${pts[0].x},${pts[0].y}`
  let d = `M${pts[0].x},${pts[0].y}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`
  }
  return d
}

const line = computed(() => smooth(points.value))
const area = computed(() => `${line.value} L${W},${H} L0,${H} Z`)
</script>

<style scoped>
.dspark { display: block; overflow: visible; }
.dspark-line { stroke-dasharray: 1; stroke-dashoffset: 1; animation: sparkDraw 1.25s cubic-bezier(.22, 1, .36, 1) .15s forwards; }
.dspark-area { opacity: 0; animation: sparkFade .9s ease .45s forwards; }
@keyframes sparkDraw { to { stroke-dashoffset: 0; } }
@keyframes sparkFade { to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .dspark-line { animation: none; stroke-dashoffset: 0; }
  .dspark-area { animation: none; opacity: 1; }
}
</style>
