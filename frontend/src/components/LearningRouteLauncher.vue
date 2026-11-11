<template>
  <section class="route-launcher">
    <div class="rl-copy">
      <span class="rl-kicker"><SIcon name="sparkle" :size="14" /> 学习路线管家</span>
      <h3>把这次想补的能力告诉管家</h3>
      <p>可以根据你的初始画像直接排一条路线，也可以补充具体需求。管家会把更该先练的技能点放到前面。</p>
    </div>
    <div class="rl-form">
      <textarea v-model="demand" rows="2" maxlength="240"
        placeholder="例如：下个月要接一个亲子团，重点补报价、亲子节奏和突发处理；或者直接点生成推荐路线" />
      <div class="rl-actions">
        <button class="tc-btn primary" :disabled="busy" data-role="route-generate" @click="generate">
          <span v-if="busy" class="spin" />
          <SIcon v-else name="right" :size="14" />
          {{ busy ? '正在排路线…' : (demand.trim() ? '按需求生成路线' : '直接生成推荐路线') }}
        </button>
        <button class="tc-btn ghost" :disabled="busy || !hasExisting" @click="openExisting">
          查看当前路线 <SIcon name="right" :size="13" />
        </button>
      </div>
      <p v-if="error" class="rl-error" role="alert">{{ error }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'
import SIcon from '@/components/SIcon.vue'

defineProps<{ title?: string }>()
const router = useRouter()
const userStore = useUserStore()
const demand = ref('')
const busy = ref(false)
const error = ref('')
const hasExisting = ref(false)

async function loadExisting() {
  try {
    const r = (await client.get(`/profiles/${userStore.userId}/learning-route`)).data
    hasExisting.value = !!r.route
  } catch { hasExisting.value = false }
}

async function generate() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await client.post(`/profiles/${userStore.userId}/learning-route`, { demand: demand.value.trim() })
    await router.push('/learn?mode=route')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '路线生成失败，请稍后重试。'
  } finally { busy.value = false }
}

function openExisting() { router.push('/learn?mode=route') }
onMounted(loadExisting)
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.route-launcher {
  display: grid; grid-template-columns: minmax(0, .78fr) minmax(0, 1.22fr); gap: 24px;
  padding: 24px 26px; border-radius: $radius-lg; border: 1px solid #dce8f8;
  background:
    radial-gradient(520px 240px at 4% 0%, rgba(37,119,227,.14), transparent 62%),
    linear-gradient(135deg, #fbfdff, #f5f9ff 58%, #fffaf2);
  box-shadow: $shadow-card;
}
.rl-copy { min-width: 0; }
.rl-kicker { display: inline-flex; align-items: center; gap: 7px; color: $color-primary; font-size: $fs-meta; font-weight: 700; }
.rl-copy h3 { margin: 9px 0 7px; font-size: 23px; line-height: 1.35; color: $color-text; }
.rl-copy p { margin: 0; max-width: 540px; color: $color-text-secondary; font-size: $fs-body; line-height: 1.75; }
.rl-form { min-width: 0; }
.rl-form textarea { width: 100%; min-height: 70px; resize: vertical; border: 1px solid #cedaeb; border-radius: 10px;
  padding: 11px 13px; background: rgba(255,255,255,.92); color: $color-text; font: inherit; font-size: $fs-body;
  line-height: 1.65; outline: none; transition: border-color .16s ease, box-shadow .16s ease; }
.rl-form textarea:focus { border-color: $color-primary; box-shadow: 0 0 0 3px rgba(37,119,227,.1); }
.rl-actions { display: flex; gap: 9px; flex-wrap: wrap; margin-top: 10px; }
.tc-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 38px; padding: 0 16px;
  border-radius: 8px; border: 1px solid transparent; font: inherit; font-size: $fs-meta; cursor: pointer; }
.tc-btn.primary { background: $color-primary; color: #fff; box-shadow: 0 5px 14px rgba(37,119,227,.2); }
.tc-btn.primary:hover:not(:disabled) { background: $color-primary-dark; }
.tc-btn.ghost { background: #fff; color: $color-text-secondary; border-color: #d7e2f0; }
.tc-btn.ghost:hover:not(:disabled) { color: $color-primary; border-color: #a9cafa; }
.tc-btn:disabled { opacity: .5; cursor: default; }
.spin { width: 14px; height: 14px; border-radius: 50%; border: 2px solid rgba(255,255,255,.35); border-top-color: #fff; animation: spin .8s linear infinite; }
.rl-error { margin: 8px 0 0; color: $color-danger; font-size: $fs-meta; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 840px) { .route-launcher { grid-template-columns: minmax(0,1fr); gap: 15px; } }
</style>