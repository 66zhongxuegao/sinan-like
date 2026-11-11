<template>
  <div class="ph card rise">
    <div class="ph-icon"><SIcon name="chat" :size="26" /></div>
    <h3 class="ph-title">实战演练 · S2 首呼</h3>
    <p class="ph-desc">将按 VBooking 真实页面还原：派单卡 / 客户对话 / 需求单交付物。</p>
    <div class="ph-note">待接入 VBooking 真实页面描述后还原</div>
  </div>
</template>

<script setup lang="ts">
import SIcon from '@/components/SIcon.vue'
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.ph { max-width: 560px; margin: 60px auto; padding: 40px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 12px; }
.ph-icon { width: 60px; height: 60px; border-radius: 16px; display: flex; align-items: center; justify-content: center;
  background: -primary-soft; color: -primary; }
.ph-title { font-size: 24px; font-weight: 800; }
.ph-desc { font-size: 15.5px; line-height: 1.8; color: -text-secondary; }
.ph-note { margin-top: 6px; font-size: 14px; padding: 5px 14px; border-radius: 999px; background: -bg; color: -text-muted; border: 1px dashed -border-strong; }
</style>