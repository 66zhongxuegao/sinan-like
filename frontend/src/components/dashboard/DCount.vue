<template>
  <span class="dcount">{{ prefix }}{{ display }}<span v-if="suffix" class="dcount-suffix">{{ suffix }}</span></span>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  value: number
  decimals?: number
  duration?: number
  prefix?: string
  suffix?: string
}>(), { decimals: 0, duration: 1200, prefix: '', suffix: '' })

const display = ref('0')
let raf = 0

function fmt(n: number): string {
  const fixed = Math.max(0, n).toFixed(props.decimals)
  const [int, dec] = fixed.split('.')
  const withSep = (int || '0').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return dec ? `${withSep}.${dec}` : withSep
}

function run(from: number, to: number) {
  cancelAnimationFrame(raf)
  if (typeof window === 'undefined' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    display.value = fmt(to)
    return
  }
  const start = performance.now()
  const tick = (t: number) => {
    const p = Math.min(1, (t - start) / props.duration)
    const eased = 1 - Math.pow(1 - p, 3)
    display.value = fmt(from + (to - from) * eased)
    if (p < 1) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

onMounted(() => run(0, props.value))
watch(() => props.value, (v, old) => run(old ?? 0, v))
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<style scoped>
.dcount { font-variant-numeric: tabular-nums; }
.dcount-suffix { margin-left: 2px; }
</style>