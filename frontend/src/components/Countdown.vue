<template>
  <span class="cd" :class="{ urgent: left <= 180, over: left <= 0 }">
    <SIcon name="timer" :size="12" />{{ text }}
  </span>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import SIcon from '@/components/SIcon.vue'

const props = defineProps<{ until: string; prefix?: string }>()
const now = ref(Date.now())
let timer = 0
onMounted(() => { timer = window.setInterval(() => { now.value = Date.now() }, 1000) })
onUnmounted(() => { if (timer) clearInterval(timer) })

const left = computed(() => {
  const end = Date.parse(props.until || '')
  if (!end) return 0
  return Math.max(0, Math.floor((end - now.value) / 1000))
})
const text = computed(() => {
  const s = left.value
  if (s <= 0) {
    // 时间到了就别再显示「剩 00:00」——看起来像坏了
    const label = (props.prefix || '').replace(/剩$/, '')
    return label ? `${label}已超时` : '已超时'
  }
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  const body = s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${ss}` : `${mm}:${ss}`
  return `${props.prefix || '剩余'} ${body}`
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.cd { display: inline-flex; align-items: center; gap: 4px; font-size: 15.5px; font-family: ui-monospace, monospace;
  color: $color-text-secondary; background: #eef2f7; border-radius: 999px; padding: 2px 9px; }
.cd.urgent { color: #c77700; background: #fdf2e4; }
.cd.over { color: #c0392b; background: #fdeceb; }
</style>