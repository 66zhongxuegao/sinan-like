<template>
  <svg viewBox="0 0 400 160" fill="none" xmlns="http://www.w3.org/2000/svg" :class="className" aria-hidden="true">
    <ellipse cx="200" cy="200" rx="260" ry="120" fill="rgba(24,58,99,0.04)" />
    <path d="M0 140 Q60 60 120 90 Q160 110 200 50 Q240 -10 280 70 Q320 130 360 80 Q390 50 400 90 L400 160 L0 160Z" fill="rgba(24,58,99,0.07)" />
    <path d="M0 155 Q80 100 150 120 Q200 135 250 100 Q300 65 360 110 Q385 125 400 115 L400 160 L0 160Z" fill="rgba(24,58,99,0.05)" />
    <path d="M50 160 Q100 130 160 145 Q210 155 260 135 Q310 115 370 140 L400 150 L400 160 L0 160Z" fill="rgba(201,168,106,0.10)" />
  </svg>
</template>

<script setup lang="ts">
defineProps<{ className?: string }>()
</script>