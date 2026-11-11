<template>
  <Teleport to="body">
    <div v-if="open" class="practice-completion" role="dialog" aria-modal="true"
      aria-labelledby="practice-completion-title" aria-describedby="practice-completion-description"
      data-role="practice-completion" @keydown.tab.prevent="continueButton?.focus()">
      <div class="completion-content">
        <div class="completion-emblem" aria-hidden="true"><SIcon name="check" :size="48" /></div>
        <h1 id="practice-completion-title">恭喜您完成了一次实战训练</h1>
        <p id="practice-completion-description">点击跳转至评分复盘</p>
        <button ref="continueButton" type="button" class="completion-continue" @click="$emit('continue')">
          跳转至评分复盘 <SIcon name="right" :size="18" />
        </button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import SIcon from '@/components/SIcon.vue'

const props = defineProps<{ open: boolean }>()
defineEmits<{ continue: [] }>()
const continueButton = ref<HTMLButtonElement | null>(null)
let previousOverflow: string | null = null
let previousFocus: HTMLElement | null = null
function restore() {
  if (previousOverflow === null) return
  document.body.style.overflow = previousOverflow
  previousOverflow = null
  previousFocus?.focus()
  previousFocus = null
}
watch(() => props.open, async (open) => {
  if (!open) { restore(); return }
  if (previousOverflow === null) {
    previousOverflow = document.body.style.overflow
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }
  document.body.style.overflow = 'hidden'
  await nextTick()
  if (props.open) continueButton.value?.focus()
}, { immediate: true })
onBeforeUnmount(restore)
</script>

<style scoped>
.practice-completion { position: fixed; inset: 0; z-index: 10000; display: grid; place-items: center;
  min-height: 100dvh; overflow-y: auto; padding: 32px; box-sizing: border-box;
  color: #172640; background: radial-gradient(ellipse at 18% 12%, #dceaff 0%, transparent 48%),
    radial-gradient(ellipse at 90% 85%, #e3f5f0 0%, transparent 44%), #f7faff; }
.completion-content { width: min(100%, 760px); text-align: center; }
.completion-emblem { display: grid; place-items: center; width: 108px; height: 108px; margin: 0 auto 36px;
  color: #fff; border-radius: 50%; background: linear-gradient(145deg, #438fff, #216de5);
  box-shadow: 0 0 0 14px #e7f0ff, 0 18px 48px #2577e326; }
h1 { margin: 0; font-size: clamp(26px, 3.2vw, 40px); font-weight: 750; line-height: 1.5; }
p { margin: 16px 0 36px; color: #6b7d97; font-size: clamp(18px, 2vw, 22px); line-height: 1.7; }
.completion-continue { display: inline-flex; align-items: center; justify-content: center; gap: 16px;
  min-height: 56px; padding: 14px 30px; border: 0; border-radius: 12px; color: #fff;
  background: #2577e3; box-shadow: 0 10px 24px #2577e330; cursor: pointer;
  font-family: inherit; font-size: 18px; font-weight: 700; }
.completion-continue:hover { background: #1768d5; }
.completion-continue:focus-visible { outline: 3px solid #163f7c; outline-offset: 5px; }
</style>
