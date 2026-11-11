<template>
  <div class="vb">
    <div class="vb-crumb">定制游工作台 / 消息中心</div>
    <div class="vb-body">
      <!-- 左侧分类 -->
      <aside class="vb-side">
        <div v-for="g in groups" :key="g.key" class="grp">
          <button class="grp-title" :class="{ active: active === g.key && !g.children.length }"
            @click="g.children.length ? null : (active = g.key)">
            {{ g.label }}
            <span v-if="g.key === 'custom-wait' && available.length" class="badge">{{ available.length }}</span>
            <span v-else-if="g.count" class="badge">{{ g.count }}</span>
          </button>
          <div v-if="g.children.length" class="grp-children">
            <button v-for="c in g.children" :key="c.key" class="child"
              :class="{ active: active === c.key }" @click="active = c.key">
              <span v-if="c.star" class="star">★</span>{{ c.label }}
              <span v-if="c.key === 'custom-wait' && available.length" class="badge">{{ available.length }}</span>
              <span v-else-if="c.count" class="badge">{{ c.count }}</span>
            </button>
          </div>
        </div>
      </aside>

      <!-- 右侧 -->
      <section class="vb-main">
        <!-- 待接单：持续刷新的可抢订单 -->
        <template v-if="active === 'custom-wait'">
          <div class="msg-head">
            <span class="msg-title">待接单通知</span>
            <span class="msg-sub">{{ available.length }} 个可抢 · 每 10 秒自动刷新</span>
            <label class="lang-pick" title="选一门外语就只出那门语言的客人；随机=各国都有">
              <SIcon name="lang" :size="13" />
              <select v-model="lang" class="lang-sel">
                <option value="">随机客源</option>
                <option v-for="l in languages" :key="l" :value="l">{{ l }}</option>
              </select>
            </label>
            <button class="refresh" :disabled="busy" @click="refresh">
              {{ busy ? '刷新中…' : '刷新' }}
            </button>
          </div>
          <div class="msg-list">
            <div v-for="o in available" :key="o.order_id" class="msg-card grab-card" @click="open(o)">
              <div class="avatar">抢</div>
              <div class="msg-content">
                <div class="msg-top">
                  <span class="msg-name">需求单 {{ o.order_id }}</span>
                  <span class="src-tag">{{ o.source_market }} · {{ o.language }}</span>
                  <Countdown :until="o.dispatch.window_end" prefix="剩" class="cd" />
                </div>
                <div v-if="o.difficulty" class="diff">
                  <span class="diff-tag">{{ o.difficulty }}</span>
                  <span class="diff-why">{{ o.rationale }}</span>
                </div>
                <div class="msg-text">
                  【{{ o.destination }}】{{ o.intent || (o.customer + '有出行意向，请及时沟通。') }}
                  <template v-if="(o.missing_fields || []).length">
                    　派单信息缺失：{{ o.missing_fields.join('、') }}
                  </template>
                </div>
                <div class="msg-foot">
                  <span class="rivals">{{ o.dispatch.rivals }} 位定制师同时在抢</span>
                  <span class="eta">最快约 {{ o.dispatch.rival_eta_min }} 分钟后被接走</span>
                  <button class="grab" :disabled="grabbing === o.order_id" @click.stop="grab(o)">
                    {{ grabbing === o.order_id ? '抢单中…' : '抢单' }}
                  </button>
                </div>
              </div>
            </div>
            <div v-if="!available.length && !busy" class="empty">
              当前没有可抢的派单，点右上角「刷新」拉取新派单。
            </div>
          </div>
        </template>

        <!-- 其他分类：普通消息流 -->
        <template v-else>
          <div class="msg-head">
            <span class="msg-title">{{ activeLabel }}</span>
            <span class="msg-sub">共 {{ list.length }} 条</span>
          </div>
          <div class="msg-list">
            <div v-for="m in list" :key="m.id" class="msg-card" @click="open(m)">
              <div class="avatar">{{ m.title.slice(0, 1) }}</div>
              <div class="msg-content">
                <div class="msg-top">
                  <span class="msg-name">{{ m.title }}</span>
                  <span v-if="m.starred" class="star">★</span>
                  <span class="msg-time">{{ m.time }}</span>
                </div>
                <div class="msg-text">{{ m.body }}</div>
                <div class="msg-foot"><span class="msg-link">链接 &gt;</span></div>
              </div>
            </div>
            <div v-if="!list.length" class="empty">该分类暂无消息</div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '@/api/client'
import SIcon from '@/components/SIcon.vue'
import Countdown from '@/components/Countdown.vue'

const router = useRouter()
const groups = ref<any[]>([])
const messages = ref<any[]>([])
const available = ref<any[]>([])
const active = ref('custom-wait')
const grabbing = ref('')
const languages = ref<string[]>([])
const lang = ref('')                 // '' = 随机出各国
const busy = ref(false)
let poll = 0

const LABELS = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  groups.value.forEach((g) => {
    m[g.key] = g.label
    ;(g.children || []).forEach((c: any) => { m[c.key] = c.label })
  })
  return m
})
const activeLabel = computed(() => LABELS.value[active.value] || '消息')
const list = computed(() => messages.value.filter((m) => m.group === active.value))

async function loadLanguages() {
  try { languages.value = (await client.get('/contracts/markets')).data.languages || [] } catch {}
}

async function loadMessages() {
  const { groups: gs, messages: ms } = (await client.get('/practice/messages')).data
  groups.value = gs
  messages.value = ms
}

async function loadAvailable() {
  try { available.value = (await client.get('/practice/orders/available')).data } catch { available.value = [] }
}

async function refresh() {
  busy.value = true
  try {
    // 刷新 = 按画像生成一条新派单，再读可抢列表
    await generate(true)
  } finally { busy.value = false }
}

async function generate(silent = false) {
  busy.value = true
  try {
    await client.post('/practice/dispatch/generate', { count: 1, language: lang.value })
    await loadAvailable()
  } catch (e: any) {
    if (!silent) alert(e?.response?.data?.detail || '生成失败')
  } finally { busy.value = false }
}

async function grab(o: any) {
  grabbing.value = o.order_id
  try {
    await client.post(`/practice/orders/${o.order_id}/grab`)
    await loadAvailable()
    // 抢到之后才进入「订单管理」（实战工作台），并高亮这单
    router.push(`/practice?grabbed=${o.order_id}`)
  } catch (e: any) {
    alert(e?.response?.data?.detail || '抢单失败')
    await loadAvailable()
  } finally {
    grabbing.value = ''
  }
}

function open(m: any) {
  if (m.order_id) router.push(`/practice/orders/${m.order_id}`)
}

onMounted(async () => {
  loadLanguages()
  await Promise.all([loadMessages(), loadAvailable()])
  poll = window.setInterval(loadAvailable, 10000)   // 持续刷新可抢的单
})
onUnmounted(() => { if (poll) clearInterval(poll) })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.vb { width: 100%; max-width: 1200px; margin: 0 auto; }
.vb-crumb { font-size: 15px; color: $color-text-muted; margin-bottom: 12px; }
.vb-body { display: flex; gap: 14px; }

.vb-side { width: 210px; flex-shrink: 0; background: #fff; border: 1px solid $color-border; border-radius: $radius-md; padding: 8px; }
.grp { margin-bottom: 2px; }
.grp-title {
  width: 100%; text-align: left; display: flex; align-items: center; gap: 6px;
  padding: 9px 12px; border: none; background: transparent; cursor: pointer; border-radius: 6px;
  font-size: 15.5px; color: $color-text; font-weight: 600;
  &:hover { background: $color-primary-softer; }
  &.active { background: $color-primary-soft; color: $color-primary; }
}
.grp-children { padding-left: 12px; }
.child {
  width: 100%; text-align: left; display: flex; align-items: center; gap: 5px;
  padding: 7px 10px; border: none; background: transparent; cursor: pointer; border-radius: 6px;
  font-size: 15px; color: $color-text-secondary;
  &:hover { background: $color-primary-softer; }
  &.active { background: $color-primary-soft; color: $color-primary; font-weight: 600; }
}
.star { color: #f5a623; font-size: 13px; }
.badge { margin-left: auto; font-size: 13px; background: #ffe9e6; color: #e04b4b; border-radius: 8px; padding: 1px 6px; }

.vb-main { flex: 1; min-width: 0; }
.msg-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.msg-title { font-size: 16.5px; font-weight: 700; }
.msg-sub { font-size: 15px; color: $color-text-secondary; }
.lang-pick { display: inline-flex; align-items: center; gap: 5px; margin-left: 10px; color: $color-text-secondary; }
.lang-sel { height: 30px; border: 1px solid $color-border-strong; border-radius: 6px; padding: 0 8px;
  font-size: 12.5px; color: $color-text; background: #fff; outline: none; cursor: pointer; }
.lang-sel:focus { border-color: $color-primary; box-shadow: 0 0 0 2px rgba(37,119,227,.1); }
.refresh { margin-left: auto; border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 4px 13px; font-size: 14px; color: $color-primary; cursor: pointer; }
.refresh:hover { background: $color-primary-softer; }
.refresh:disabled, .gen:disabled { opacity: .6; cursor: default; }
.gen { margin-left: 6px; border: none; background: linear-gradient(135deg, #2577e3, #1a63c4); color: #fff;
  border-radius: 999px; padding: 5px 14px; font-size: 14px; font-weight: 700; cursor: pointer; }
.gen:hover { filter: brightness(1.06); }
.diff { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.diff-tag { font-size: 14px; background: #efe9fe; color: #7a5af8; border-radius: 999px; padding: 2px 9px; flex-shrink: 0; }
.diff-why { font-size: 14.5px; color: $color-text-muted; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.link { border: none; background: none; color: $color-primary; font-size: 15px; cursor: pointer; text-decoration: underline; }
.msg-list { display: flex; flex-direction: column; gap: 10px; }
.msg-card {
  display: flex; gap: 12px; background: #fff; border: 1px solid $color-border; border-radius: $radius-md;
  padding: 14px 16px; cursor: pointer; transition: all .15s ease;
  &:hover { border-color: $color-primary; box-shadow: $shadow-hover; }
}
.grab-card { border-left: 3px solid $color-primary; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; font-weight: 700; font-size: 16px;
}
.msg-content { flex: 1; min-width: 0; }
.msg-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.msg-name { font-size: 17px; font-weight: 700; }
.src-tag { font-size: 13.5px; background: #efe9fe; color: #7a5af8; border-radius: 4px; padding: 1px 7px; }
.msg-time { margin-left: auto; font-size: 14px; color: $color-text-muted; }
.msg-text { margin-top: 7px; font-size: 16px; color: $color-text-secondary; line-height: 1.8; }
.msg-foot { margin-top: 10px; display: flex; align-items: center; gap: 10px 12px; flex-wrap: wrap; }
.msg-link { font-size: 14px; color: $color-primary; }
.rivals { font-size: 14px; color: #c77700; background: #fdf2e4; border-radius: 999px; padding: 2px 9px; }
.eta { font-size: 14px; color: $color-text-muted; }
.grab {
  margin-left: auto; flex-shrink: 0; border: none; cursor: pointer; font-size: 15.5px; font-weight: 700;
  color: #fff; background: linear-gradient(135deg, #2577e3, #1a63c4);
  border-radius: 999px; padding: 6px 20px; box-shadow: 0 4px 12px rgba(37,119,227,0.28);
}
.grab:hover { filter: brightness(1.06); }
.grab:disabled { opacity: .6; cursor: default; }
.cd { margin-left: auto; }
.empty { padding: 40px; text-align: center; color: $color-text-muted; font-size: 15px; }
</style>