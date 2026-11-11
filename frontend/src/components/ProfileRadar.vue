<template>
  <svg viewBox="0 0 600 420" class="ability-radar" role="img" :aria-label="description">
    <title>{{ description }}</title>
    <g class="radar-grid">
      <polygon v-for="level in [100, 80, 60, 40, 20]" :key="level"
        :points="ring(level)" :fill="level % 40 === 0 ? '#f8fafd' : '#fff'" />
      <line v-for="(_, i) in dimensions" :key="i" x1="300" y1="210"
        :x2="position(i, 100).x" :y2="position(i, 100).y" />
    </g>
    <g v-for="layer in plotted" :key="layer.key" :style="{ color: layer.color }">
      <polygon v-if="layer.complete" :points="layer.points" fill="currentColor"
        :fill-opacity="layer.key === 'initial' ? 0.22 : 0.10" stroke="currentColor"
        :stroke-width="layer.key === 'initial' ? 3.5 : 2.7" stroke-linejoin="round" />
      <template v-else>
        <line v-for="(edge, i) in layer.edges" :key="i" :x1="edge.a.x" :y1="edge.a.y"
          :x2="edge.b.x" :y2="edge.b.y" stroke="currentColor" stroke-width="2.7" />
      </template>
      <circle v-for="point in layer.markers" :key="point.id" :cx="point.x" :cy="point.y" r="4"
        fill="currentColor" stroke="#fff" stroke-width="1.2" tabindex="0">
        <title>{{ layer.label }} · {{ point.name }}：{{ point.value.toFixed(1) }}{{ point.inherited ? '（沿用初始画像）' : '' }}</title>
      </circle>
    </g>
    <g class="axis-labels">
      <text v-for="(dim, i) in dimensions" :key="dim.id" :x="labelPosition(i).x" :y="labelPosition(i).y"
        :text-anchor="labelAnchor(i)" dominant-baseline="middle">{{ dim.name }}</text>
      <text x="307" y="205" class="scale-label">0</text>
      <text x="307" y="78" class="scale-label">100</text>
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Dimension { id: string; name: string; value: number | null; assessed: boolean; inherited?: boolean }
interface Layer { key: string; label: string; color: string; visible: boolean; dimensions: Dimension[] }
const props = defineProps<{ dimensions: Dimension[]; layers: Layer[] }>()
const position = (i: number, value: number, radius = 130) => {
  const angle = -Math.PI / 2 - (2 * Math.PI * i) / Math.max(3, props.dimensions.length)
  const r = radius * Math.max(0, Math.min(100, value)) / 100
  return { x: 300 + r * Math.cos(angle), y: 210 + r * Math.sin(angle) }
}
const ring = (level: number) => props.dimensions.map((_, i) => {
  const p = position(i, level)
  return `${p.x},${p.y}`
}).join(' ')
const labelPosition = (i: number) => position(i, 100, 158)
function labelAnchor(i: number): 'start' | 'middle' | 'end' {
  const x = labelPosition(i).x
  return Math.abs(x - 300) < 1 ? 'middle' : x > 300 ? 'start' : 'end'
}
const plotted = computed(() => props.layers.filter(l => l.visible).map(layer => {
  const byId = new Map(layer.dimensions.map(d => [d.id, d]))
  const points = props.dimensions.map((dim, i) => {
    const row = byId.get(dim.id)
    return row?.assessed && typeof row.value === 'number'
      ? { ...position(i, row.value), id: dim.id, name: dim.name, value: row.value, inherited: !!row.inherited } : null
  })
  const markers = points.filter((p): p is NonNullable<typeof p> => p !== null)
  const edges = points.flatMap((a, i) => {
    const b = points[(i + 1) % points.length]
    return a && b ? [{ a, b }] : []
  })
  return { ...layer, complete: markers.length === props.dimensions.length && markers.length >= 3,
    points: markers.map(p => `${p.x},${p.y}`).join(' '), markers, edges }
}))
const description = computed(() => '能力雷达，刻度 0 至 100。' + props.layers.filter(l => l.visible)
  .map(l => `${l.label}：` + l.dimensions.map(d => `${d.name}${d.assessed && d.value !== null ? d.value : '未评估'}${d.inherited ? '（沿用初始画像）' : ''}`).join('、'))
  .join('。'))
</script>

<style scoped>
.ability-radar { display: block; width: 100%; height: auto; min-width: 300px; }
.radar-grid polygon, .radar-grid line { stroke: #e2e8f0; stroke-width: 1; }
.axis-labels text { fill: #687b94; font: 15px 'Microsoft YaHei', sans-serif; }
.axis-labels .scale-label { fill: #91a0b3; font-size: 11px; }
circle { outline: none; }
circle:focus { stroke: #1e3555; stroke-width: 2; }
</style>
