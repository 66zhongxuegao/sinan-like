<template>
  <div class="logo-wrap">
    <img class="logo-mark" src="@/assets/logo-tripcraft.webp" alt="司南礼客" />
    <div class="logo-text">
      <span class="logo-title font-serif">司南礼客</span>
      <span class="logo-sub">TripCraft</span>
    </div>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.logo-wrap { display: flex; align-items: center; gap: 10px; }
.logo-mark { width: 38px; height: 38px; object-fit: contain; }
.logo-text { display: flex; flex-direction: column; line-height: 1.15; }
.logo-title { font-size: 19px; font-weight: 800; letter-spacing: 3px; color: $color-primary; }
.logo-sub { font-size: 13px; letter-spacing: 2.4px; color: $color-text-muted; text-transform: uppercase; }
</style>