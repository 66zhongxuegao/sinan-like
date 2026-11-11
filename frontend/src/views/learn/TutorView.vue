<template>
  <div class="tutor">
    <div class="card pick">
      <span class="lb">当前技能点</span>
      <select v-model="spId" class="sel" @change="loadRubric">
        <option v-for="s in sps" :key="s.id" :value="s.id">{{ s.id }} {{ s.name }}</option>
      </select>
      <span class="lb">维度</span><span class="vd">{{ sp?.dimension }}</span>
    </div>

    <div class="grid">
      <div class="card chat">
        <div class="chat-head">AI 老师 · 围绕该技能点问答</div>
        <div class="msgs">
          <div v-for="(m, i) in msgs" :key="i" class="msg" :class="m.role">
            <div class="bubble">{{ m.text }}</div>
          </div>
          <div v-if="!msgs.length" class="empty">选一个技能点，向老师提问（如"这一步我总做不好，怎么改？"）。</div>
        </div>
        <div class="chat-input">
          <input v-model="q" class="ipt" placeholder="向 AI 老师提问…" @keydown.enter="ask" />
          <button class="tc-btn" @click="ask">发送</button>
        </div>
      </div>

      <div class="card rubric">
        <div class="r-title">Rubric（评分标准）</div>
        <div v-if="rubric" class="r-body">
          <div class="r-target">{{ rubric.target }}</div>
          <div v-if="rubric.trigger" class="r-trigger">触发条件：{{ rubric.trigger }}</div>
          <div v-for="a in rubric.anchors" :key="a.level" class="anchor">
            <span class="lv">{{ a.level }}</span><span class="bh">{{ a.behavior }}</span>
          </div>
          <div class="r-pos">正例：{{ rubric.positive }}</div>
          <div class="r-neg">反例：{{ rubric.negative }}</div>
        </div>
        <div v-else class="empty">加载中…</div>
      </div>
    </div>

    <div class="card res">
      <div class="r-title">个性化学习资源</div>
      <div class="res-note">
        学习资料由数据基座生成（讲解 / 3 档资源 / 练习题），正在后台生成中。
        生成完成后，这里会按你的掌握度自动推送对应难度的资料与练习。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import client from '@/api/client'

const route = useRoute()
const sps = ref<any[]>([])
const spId = ref(String(route.query.sp || 'C2.2'))
const rubric = ref<any>(null)
const msgs = ref<{ role: string; text: string }[]>([])
const q = ref('')

const sp = computed(() => sps.value.find((s) => s.id === spId.value))

onMounted(async () => {
  try { sps.value = (await client.get('/contracts/skill-points')).data } catch { sps.value = [] }
  await loadRubric()
})
async function loadRubric() {
  try { rubric.value = (await client.get('/contracts/rubric/' + spId.value)).data }
  catch { rubric.value = null }
}
function ask() {
  const t = q.value.trim(); if (!t) return
  msgs.value.push({ role: 'me', text: t })
  msgs.value.push({ role: 'ai', text: '（AI 老师尚未接入）' })
  q.value = ''
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.tutor { width: 100%; max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.pick { display: flex; align-items: center; gap: 10px; padding: 12px 16px; }
.lb { font-size: 15.5px; color: $color-text-muted; }
.sel { height: 32px; border: 1px solid $color-border; border-radius: 6px; padding: 0 10px; font-size: 15px; }
.vd { font-size: 15px; color: $color-primary; }
.grid { display: grid; grid-template-columns: 1.1fr 1fr; gap: 12px; align-items: start; }
.chat { display: flex; flex-direction: column; height: 460px; }
.chat-head { padding: 12px 16px; border-bottom: 1px solid $color-border; font-size: 16px; font-weight: 700; }
.msgs { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.msg.me { align-items: flex-end; display: flex; }
.msg.ai { display: flex; }
.bubble { max-width: 78%; padding: 9px 13px; border-radius: 10px; font-size: 15px; line-height: 1.7; background: $color-primary-soft; color: $color-text; }
.msg.me .bubble { background: $color-primary; color: #fff; }
.empty { color: $color-text-muted; font-size: 15px; text-align: center; padding: 20px; }
.chat-input { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid $color-border; }
.ipt { flex: 1; height: 34px; border: 1px solid $color-border; border-radius: 6px; padding: 0 12px; font-size: 15px; outline: none; }
.ipt:focus { border-color: $color-primary; }
.rubric { padding: 16px; max-height: 460px; overflow-y: auto; }
.r-title { font-size: 16px; font-weight: 700; margin-bottom: 10px; }
.r-target { font-size: 15.5px; font-weight: 600; margin-bottom: 6px; }
.r-trigger { font-size: 15.5px; color: #b8741a; background: #fff7ea; padding: 7px 10px; border-radius: 6px; margin-bottom: 10px; }
.anchor { display: flex; gap: 8px; font-size: 15.5px; line-height: 1.7; padding: 5px 0; border-bottom: 1px dashed #f0f2f5; }
.lv { flex-shrink: 0; width: 28px; font-weight: 700; color: $color-primary; }
.r-pos { margin-top: 10px; font-size: 15.5px; color: #12a76a; }
.r-neg { margin-top: 6px; font-size: 15.5px; color: #e04b4b; }
.res { padding: 16px; }
.res-note { font-size: 15.5px; color: $color-text-secondary; line-height: 1.9; }
</style>