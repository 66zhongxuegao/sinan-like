<template>
  <div class="dtrend">
    <svg class="dtrend-svg" viewBox="0 0 760 240" @pointermove="onMove" @pointerleave="hoverIndex = null">
      <defs>
        <linearGradient v-for="(s, i) in series" :key="`g-${i}`" :id="gradId(i)" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="s.color" stop-opacity=".30" />
          <stop offset="70%" :stop-color="s.color" stop-opacity=".06" />
          <stop offset="100%" :stop-color="s.color" stop-opacity="0" />
        </linearGradient>
      </defs>

      <g class="dtrend-grid">
        <line v-for="(t, i) in ticks" :key="`grid-${i}`" :x1="PAD.l" :x2="plotRight" :y1="yAt(t)" :y2="yAt(t)" />
        <text v-for="(t, i) in ticks" :key="`yl-${i}`" :x="PAD.l - 12" :y="yAt(t) + 4" text-anchor="end">{{ tickText(t) }}</text>
        <template v-if="hasRight">
          <text v-for="(t, i) in rightTicks" :key="`yr-${i}`" :x="W - 6" :y="yAt(t, 'right') + 4" text-anchor="end"
            class="dtrend-right-label">{{ tickText(t) }}</text>
        </template>
      </g>

      <g class="dtrend-series">
        <template v-for="(s, i) in series" :key="`s-${i}`">
          <path v-if="area && i === 0" :d="areaPath(s)" :fill="`url(#${gradId(i)})`" class="dtrend-area" />
          <path :d="linePath(s)" :stroke="s.color" fill="none" stroke-width="2.4" stroke-linecap="round"
            stroke-linejoin="round" pathLength="1" class="dtrend-line"
            :style="{ animationDelay: `${0.1 + i * 0.14}s` }" />
        </template>
      </g>

      <g class="dtrend-axis">
        <text v-for="(l, i) in labels" v-show="i % labelStep === 0 || i === labels.length - 1" :key="`xl-${i}`"
          :x="xAt(i)" :y="H - 12" :text-anchor="i === labels.length - 1 ? 'end' : 'middle'">{{ l }}</text>
      </g>

      <g v-if="hoverIndex !== null" class="dtrend-hover">
        <line :x1="xAt(hoverIndex)" :x2="xAt(hoverIndex)" :y1="PAD.t" :y2="H - PAD.b" />
        <circle v-for="(s, i) in series" :key="`dot-${i}`" :cx="xAt(hoverIndex)" :cy="yOf(s, hoverIndex)"
          r="4.5" :fill="s.color" stroke="#ffffff" stroke-width="2" />
      </g>
    </svg>

    <div v-if="hoverIndex !== null" class="dtrend-tip" :style="tipStyle">
      <div class="dtrend-tip-label">{{ labels[hoverIndex] }}</div>
      <div v-for="(s, i) in series" :key="`tip-${i}`" class="dtrend-tip-row">
        <i :style="{ background: s.color }" />
        <span>{{ s.name }}</span>
        <b>{{ fmt(s.data[hoverIndex] ?? 0) }}</b>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import type { TrendSeries } from '@/data/dashboard'

const props = withDefaults(defineProps<{
  labels: string[]
  series: TrendSeries[]
  area?: boolean
}>(), { area: true })

const W = 760
const H = 240
const PAD = { l: 48, r: 16, t: 18, b: 34 }
const uid = useId()
const hoverIndex = ref<number | null>(null)

const n = computed(() => props.labels.length)
const hasRight = computed(() => props.series.some((s) => s.axis === 'right'))
const padR = computed(() => (hasRight.value ? 54 : 16))
const plotRight = computed(() => W - padR.value)
const plotW = computed(() => plotRight.value - PAD.l)
const plotH = H - PAD.t - PAD.b

function niceStep(x: number): number {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(x, 1e-6))))
  const norm = x / mag
  const c = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10
  return c * mag
}

function niceScale(raw: number): { max: number; intervals: number } {
  const target = Math.max(1, raw) * 1.06
  let best: { max: number; intervals: number } | null = null
  for (const intervals of [4, 5]) {
    const max = niceStep(target / intervals) * intervals
    if (max >= target && (!best || max < best.max)) best = { max, intervals }
  }
  return best || { max: target, intervals: 4 }
}

const leftData = computed(() => props.series.filter((s) => s.axis !== 'right').flatMap((s) => s.data))
const rightData = computed(() => props.series.filter((s) => s.axis === 'right').flatMap((s) => s.data))

const scale = computed(() => niceScale(Math.max(1, ...leftData.value)))
const maxLeft = computed(() => scale.value.max)
const intervals = computed(() => scale.value.intervals)
const maxRight = computed(() => {
  if (!hasRight.value) return 100
  const raw = Math.max(1, ...rightData.value)
  return niceStep((raw * 1.06) / intervals.value) * intervals.value
})

const ticks = computed(() => Array.from({ length: intervals.value + 1 }, (_, i) => (maxLeft.value / intervals.value) * i))
const rightTicks = computed(() => Array.from({ length: intervals.value + 1 }, (_, i) => (maxRight.value / intervals.value) * i))
const labelStep = computed(() => (n.value > 10 ? 2 : 1))

function xAt(i: number): number {
  return n.value <= 1 ? PAD.l + plotW.value / 2 : PAD.l + (i / (n.value - 1)) * plotW.value
}
function yAt(v: number, axis: 'left' | 'right' = 'left'): number {
  const m = axis === 'right' ? maxRight.value : maxLeft.value
  return PAD.t + (1 - v / m) * plotH
}
function yOf(s: TrendSeries, i: number): number {
  return yAt(s.data[i] ?? 0, s.axis === 'right' ? 'right' : 'left')
}
function tickText(v: number): string {
  if (v >= 1000) {
    const k = v / 1000
    const txt = Number.isInteger(k) ? String(k) : k.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
    return `${txt}k`
  }
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(1)))
}
function fmt(v: number): string {
  return v.toLocaleString('zh-CN')
}
function gradId(i: number): string {
  return `trend-${uid}-${i}`
}

function smooth(points: { x: number; y: number }[]): string {
  if (points.length === 0) return ''
  if (points.length === 1) return `M${points[0].x},${points[0].y}`
  let d = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[i + 2] || p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`
  }
  return d
}

function pointsOf(s: TrendSeries): { x: number; y: number }[] {
  return s.data.map((v, i) => ({ x: xAt(i), y: yAt(v, s.axis === 'right' ? 'right' : 'left') }))
}
function linePath(s: TrendSeries): string {
  return smooth(pointsOf(s))
}
function areaPath(s: TrendSeries): string {
  const p = pointsOf(s)
  if (!p.length) return ''
  const base = H - PAD.b
  return `${smooth(p)} L${p[p.length - 1].x.toFixed(2)},${base} L${p[0].x.toFixed(2)},${base} Z`
}

function onMove(e: PointerEvent) {
  const el = e.currentTarget as SVGSVGElement
  const rect = el.getBoundingClientRect()
  const vx = ((e.clientX - rect.left) / rect.width) * W
  const raw = ((vx - PAD.l) / plotW.value) * (n.value - 1)
  hoverIndex.value = Math.min(n.value - 1, Math.max(0, Math.round(raw)))
}

const tipStyle = computed(() => {
  const i = hoverIndex.value
  if (i === null) return {}
  const x = xAt(i)
  const top = Math.min(...props.series.map((s) => yOf(s, i)))
  const shift = x < 120 ? '-14%' : x > W - 120 ? '-86%' : '-50%'
  return {
    left: `${(x / W) * 100}%`,
    top: `${(top / H) * 100}%`,
    transform: `translate(${shift}, -118%)`,
  }
})
</script>

<style scoped>
.dtrend { position: relative; width: 100%; }
.dtrend-svg { width: 100%; height: auto; display: block; overflow: visible; }
.dtrend-grid line { stroke: #e8eef7; stroke-width: 1; stroke-dasharray: 3 6; }
.dtrend-grid text, .dtrend-axis text { fill: #8a9bb2; font-size: 11.5px; font-family: 'Bahnschrift', 'Microsoft YaHei', sans-serif; }
.dtrend-grid text.dtrend-right-label { fill: #9aabc2; font-size: 10.5px; }
.dtrend-line { stroke-dasharray: 1; stroke-dashoffset: 1; animation: trendDraw 1.5s cubic-bezier(.22, 1, .36, 1) forwards; }
.dtrend-area { opacity: 0; animation: trendArea .9s ease .4s forwards; }
.dtrend-hover line { stroke: rgba(37, 119, 227, .28); stroke-width: 1; stroke-dasharray: 4 4; }
.dtrend-tip { position: absolute; pointer-events: none; z-index: 3; min-width: 132px; padding: 9px 11px;
  border-radius: 10px; background: #ffffff; border: 1px solid #e2ebf7;
  box-shadow: 0 14px 30px rgba(20, 70, 140, .16); backdrop-filter: blur(10px); }
.dtrend-tip-label { font-size: 11.5px; color: #8a9bb2; margin-bottom: 5px; letter-spacing: .4px; }
.dtrend-tip-row { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: #5c6f8a; line-height: 1.8; }
.dtrend-tip-row i { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dtrend-tip-row b { margin-left: auto; color: #16223a; font-family: 'Bahnschrift', sans-serif; }
@keyframes trendDraw { to { stroke-dashoffset: 0; } }
@keyframes trendArea { to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .dtrend-line { animation: none; stroke-dashoffset: 0; }
  .dtrend-area { animation: none; opacity: 1; }
}
</style>