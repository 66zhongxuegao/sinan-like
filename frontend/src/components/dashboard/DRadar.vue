<template>
  <div class="dradar">
    <svg viewBox="0 0 340 316" class="dradar-svg">
      <defs>
        <radialGradient :id="teamFill" cx="50%" cy="50%" r="50%">
          <stop offset="55%" stop-color="#2f7fe8" stop-opacity=".03" />
          <stop offset="100%" stop-color="#2f7fe8" stop-opacity=".20" />
        </radialGradient>
        <linearGradient :id="sweepFill" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#2fe3c8" stop-opacity="0" />
          <stop offset="100%" stop-color="#10a99a" stop-opacity=".10" />
        </linearGradient>
      </defs>

      <g class="dradar-grid">
        <polygon v-for="(lvl, i) in levels" :key="`p-${i}`" :points="polygon(lvl / 100)" />
        <line v-for="(a, i) in axes" :key="`ax-${i}`" :x1="CX" :y1="CY"
          :x2="point(R, ratio(i)).x" :y2="point(R, ratio(i)).y" />
      </g>

      <g class="dradar-base">
        <polygon :points="polygon(1, 'base')" />
      </g>

      <g class="dradar-team">
        <polygon :points="polygon(1, 'team')" :fill="`url(#${teamFill})`" />
        <circle v-for="(a, i) in axes" :key="`dot-${i}`" :cx="point(R * a.team / 100, ratio(i)).x"
          :cy="point(R * a.team / 100, ratio(i)).y" r="3.2" class="dradar-dot"
          :style="{ animationDelay: `${0.7 + i * 0.07}s` }" />
      </g>

      <g class="dradar-sweep">
        <path :d="wedgePath" :fill="`url(#${sweepFill})`" />
        <line :x1="CX" :y1="CY" :x2="CX" :y2="CY - R" class="dradar-sweep-line" />
      </g>

      <g class="dradar-labels">
        <text v-for="(a, i) in axes" :key="`lb-${i}`" :x="point(RL, ratio(i)).x" :y="point(RL, ratio(i)).y"
          :text-anchor="anchor(ratio(i))" dominant-baseline="middle">{{ a.label }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { useId } from 'vue'
import type { RadarAxis } from '@/data/dashboard'

const props = defineProps<{ axes: RadarAxis[] }>()

const CX = 170
const CY = 158
const R = 96
const RL = 124
const uid = useId()
const teamFill = `radar-team-${uid}`
const sweepFill = `radar-sweep-${uid}`
const levels = [25, 50, 75, 100]

function ratio(i: number): number {
  return (i / props.axes.length) * Math.PI * 2 - Math.PI / 2
}
function point(radius: number, angle: number): { x: number; y: number } {
  return {
    x: Number((CX + Math.cos(angle) * radius).toFixed(2)),
    y: Number((CY + Math.sin(angle) * radius).toFixed(2)),
  }
}
function polygon(scale: number, field: 'team' | 'base' = 'team'): string {
  return props.axes.map((a, i) => {
    const p = point((R * a[field] / 100) * scale, ratio(i))
    return `${p.x},${p.y}`
  }).join(' ')
}
function anchor(angle: number): string {
  const c = Math.cos(angle)
  if (c > 0.3) return 'start'
  if (c < -0.3) return 'end'
  return 'middle'
}
const wedgePath = (() => {
  const a0 = -Math.PI / 2
  const a1 = a0 + Math.PI / 6
  const p0 = point(R, a0)
  const p1 = point(R, a1)
  return `M${CX},${CY} L${p0.x},${p0.y} A${R},${R} 0 0 1 ${p1.x},${p1.y} Z`
})()
</script>

<style scoped>
.dradar { display: flex; align-items: center; justify-content: center; width: 100%; }
.dradar-svg { width: 100%; max-width: 380px; height: auto; overflow: visible; }
.dradar-grid polygon { fill: none; stroke: #e6eef8; stroke-width: 1; }
.dradar-grid line { stroke: #eaf1f9; stroke-width: 1; }
.dradar-base polygon { fill: #f4f8fd; stroke: #c9d8ea; stroke-width: 1.2;
  stroke-dasharray: 4 4; animation: radarIn .9s cubic-bezier(.22, 1, .36, 1) both; }
.dradar-team polygon { stroke: #2f7fe8; stroke-width: 2; stroke-linejoin: round;
  filter: drop-shadow(0 0 10px rgba(47, 127, 232, .20));
  transform-box: view-box; transform-origin: 170px 158px;
  animation: radarIn 1.1s cubic-bezier(.22, 1, .36, 1) .12s both; }
.dradar-dot { fill: #ffffff; stroke: #2f7fe8; stroke-width: 1.2; opacity: 0; animation: dotIn .4s ease forwards; }
.dradar-sweep { transform-box: view-box; transform-origin: 170px 158px; animation: radarSpin 14s linear infinite; }
.dradar-sweep-line { stroke: rgba(16, 169, 154, .32); stroke-width: 1; }
.dradar-labels text { fill: #5c6f8a; font-size: 11.5px; font-weight: 600; letter-spacing: .3px; }
@keyframes radarIn { from { opacity: 0; transform: scale(.55); } to { opacity: 1; transform: scale(1); } }
@keyframes dotIn { from { opacity: 0; transform: scale(.2); } to { opacity: 1; transform: scale(1); } }
@keyframes radarSpin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .dradar-base polygon, .dradar-team polygon { animation: none; opacity: 1; transform: none; }
  .dradar-dot { animation: none; opacity: 1; }
  .dradar-sweep { animation: none; opacity: 0; }
}
</style>