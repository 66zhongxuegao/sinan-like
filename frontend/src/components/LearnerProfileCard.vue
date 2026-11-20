<template>
  <section class="lpc card">
    <header class="lpc-head">
      <div class="lpc-title"><SIcon name="user" :size="16" /> 个性化画像</div>
      <span class="lpc-sub">决定每个技能点「怎么教」，不改变你要学哪些技能点</span>
      <router-link v-if="view?.has_profile" class="lpc-redo" to="/profile/quiz?part=personal">重新测评</router-link>
    </header>

    <div v-if="loading" class="lpc-empty">正在读取…</div>

    <div v-else-if="!view?.has_profile" class="lpc-empty">
      <p>你还没有完成个性化测评。完成后，每个技能点的<b>讲义会按你的学习风格、背景和目标客源国重新定制</b>：
        视觉型学员的讲义会配示意图，目标客源国会带来对应的语言与文化提示。</p>
      <router-link class="tc-btn" to="/profile/quiz?part=personal"><SIcon name="sparkle" :size="14" /> 开始个性化测评（约 2 分钟）</router-link>
    </div>

    <template v-else>
      <!-- ① 学习风格：四条两端滑杆，一眼看到偏向哪一边 -->
      <div class="lpc-part">
        <h4><i>1</i> 学习风格 <em>Felder–Silverman</em></h4>
        <div v-for="r in view.style" :key="r.id" class="sty">
          <div class="sty-top"><b>{{ r.name }}</b><span>{{ r.en }}</span></div>
          <div class="sty-bar">
            <span :class="{ on: r.value < 0 }">{{ r.id === 'AR' ? '主动型' : r.id === 'SI' ? '感知型' : r.id === 'VV' ? '视觉型' : '序列型' }}</span>
            <div class="track"><i class="mid" /><i class="dot" :style="{ left: dotLeft(r.value) }" /></div>
            <span :class="{ on: r.value > 0 }">{{ r.id === 'AR' ? '反思型' : r.id === 'SI' ? '直觉型' : r.id === 'VV' ? '言语型' : '整体型' }}</span>
          </div>
          <p class="sty-text">{{ r.strength }}{{ r.pole }}：{{ r.gist }}</p>
        </div>
        <div v-if="background.status_label || background.note" class="bg">
          <b>背景</b><span>{{ [background.status_label, background.note].filter(Boolean).join(' · ') }}</span>
        </div>
      </div>

      <!-- ② 目标客源国与语言水平 -->
      <div class="lpc-part">
        <h4><i>2</i> 目标客源国与语言</h4>
        <div v-if="market.country" class="mk">
          <div class="mk-top">
            <b>{{ market.country }}</b>
            <span class="pill">{{ view.knowledge?.service_language }}</span>
            <span v-if="market.language_level_name" class="pill hi">水平：{{ market.language_level_name }}</span>
          </div>
          <div v-if="market.language_skills" class="mk-skills">
            <span v-for="(n, k) in SKILL_NAME" :key="k">{{ n }} <b>{{ market.language_skills[k] }}</b>/3</span>
          </div>
          <details v-if="view.knowledge" class="kb">
            <summary>查看{{ market.country }}知识库（文化 {{ view.knowledge.culture.length }} · 习俗 {{ view.knowledge.customs.length }} · 政策 {{ view.knowledge.policy.length }} · 用语 {{ view.knowledge.phrases.length }}）</summary>
            <div v-for="sec in KB_SECTIONS" :key="sec.key" class="kb-sec">
              <h5>{{ sec.name }}</h5>
              <p v-for="it in view.knowledge[sec.key]" :key="it.title"><b>{{ it.title }}</b>　{{ it.body }}</p>
            </div>
            <div class="kb-sec">
              <h5>常用客服用语</h5>
              <p v-for="p in view.knowledge.phrases" :key="p.scene"><b>{{ p.scene }}</b>　{{ p.zh }} → {{ p.text }}<em v-if="p.read">（{{ p.read }}）</em></p>
            </div>
            <div class="kb-sec">
              <h5>网络来源</h5>
              <p v-for="s in view.knowledge.sources" :key="s.id"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.title }} ↗</a></p>
            </div>
          </details>
        </div>
        <p v-else class="lpc-none">还没有选择目标客源国。</p>
      </div>

      <!-- ③ 八维掌握度：来自初始测评，下面只解释它与前两部分的分工 -->
      <div class="lpc-part">
        <h4><i>3</i> 八维掌握度</h4>
        <p class="lpc-none">来自上方的 12 道能力题，决定「学什么、先学哪个」。无论你的风格和客源国是什么，八个维度的技能点最终都要学完。</p>
      </div>

      <!-- 对教学的影响：与讲义下方「依据」里的说法一致 -->
      <div class="lpc-part fx">
        <h4>这些会怎样改变你的讲义</h4>
        <div v-for="e in view.effects" :key="e.group + e.title" class="fx-row">
          <span class="fx-g">{{ e.group }}</span>
          <div><b>{{ e.title }}</b><p>{{ e.effect }}</p></div>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import client from '@/api/client'
import SIcon from '@/components/SIcon.vue'

const props = defineProps<{ userId: string; refreshKey?: number }>()
const view = ref<any>(null)
const loading = ref(true)

const SKILL_NAME: Record<string, string> = { listen: '听', speak: '说', write: '读写' }
const KB_SECTIONS = [
  { key: 'culture', name: '文化' }, { key: 'customs', name: '习俗' }, { key: 'policy', name: '政策（需以官方公告核验）' },
]
const background = computed(() => view.value?.background || {})
const market = computed(() => view.value?.market || {})
/** 分值 -2…+2 映射到滑杆位置（4 个取值：10% / 35% / 65% / 90%） */
function dotLeft(v: number) { return ({ '-2': '10%', '-1': '35%', '1': '65%', '2': '90%' } as Record<string, string>)[String(v)] || '50%' }

async function load() {
  if (!props.userId) return
  loading.value = true
  try { view.value = (await client.get(`/profiles/${props.userId}/learner`)).data } catch { view.value = null } finally { loading.value = false }
}
onMounted(load)
watch(() => [props.userId, props.refreshKey], load)
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.lpc { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }
.lpc-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; }
.lpc-title { display: inline-flex; align-items: center; gap: 7px; font-size: 18px; font-weight: 800; }
.lpc-sub { flex: 1 1 200px; font-size: 13.5px; color: $color-text-muted; }
.lpc-redo { font-size: 14px; font-weight: 600; color: $color-primary; border: 1px solid $color-border-strong; border-radius: 999px; padding: 5px 14px; }
.lpc-empty { padding: 4px 0; font-size: 15px; line-height: 1.8; color: $color-text-secondary; display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
.lpc-empty b { color: $color-text; }
.lpc-empty .tc-btn { text-decoration: none; }
.lpc-none { margin: 0; font-size: 14.5px; line-height: 1.7; color: $color-text-secondary; }

.lpc-part { padding-top: 12px; border-top: 1px dashed $color-border-strong; }
.lpc-part h4 { margin: 0 0 8px; display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 800; }
.lpc-part h4 i { width: 22px; height: 22px; border-radius: 50%; background: $color-primary; color: #fff; font-style: normal; font-size: 13px; display: inline-flex; align-items: center; justify-content: center; }
.lpc-part h4 em { font-style: normal; font-size: 12.5px; font-weight: 600; color: $color-text-muted; }

.sty { margin-bottom: 10px; }
.sty-top { display: flex; justify-content: space-between; font-size: 14px; }
.sty-top span { color: $color-text-muted; font-size: 12.5px; }
.sty-bar { display: grid; grid-template-columns: 54px 1fr 54px; align-items: center; gap: 8px; margin: 4px 0 2px; font-size: 13px; color: $color-text-muted; }
.sty-bar span:last-child { text-align: right; }
.sty-bar span.on { color: $color-primary; font-weight: 800; }
.track { position: relative; height: 6px; border-radius: 999px; background: $blue-100; }
.track .mid { position: absolute; left: 50%; top: -3px; width: 2px; height: 12px; background: $blue-200; }
.track .dot { position: absolute; top: -6px; width: 18px; height: 18px; margin-left: -9px; border-radius: 50%; background: $color-primary; border: 3px solid #fff; box-shadow: 0 1px 4px rgba(13,40,63,.35); }
.sty-text { margin: 0; font-size: 13.5px; color: $color-text-secondary; }
.bg { display: flex; gap: 10px; font-size: 14.5px; padding-top: 4px; }
.bg b { flex-shrink: 0; }

.mk-top { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 16px; }
.pill { font-size: 12.5px; font-weight: 600; padding: 2px 10px; border-radius: 999px; background: $color-primary-soft; color: $color-primary; }
.pill.hi { background: $color-primary; color: #fff; }
.mk-skills { display: flex; gap: 16px; margin: 8px 0; font-size: 14px; color: $color-text-secondary; }
.mk-skills b { color: $color-primary; }
.kb { margin-top: 6px; border: 1px solid $color-border; border-radius: 10px; padding: 8px 12px; background: $color-primary-softer; }
.kb summary { cursor: pointer; font-size: 14px; font-weight: 600; color: $color-primary; }
.kb-sec h5 { margin: 10px 0 4px; font-size: 13px; color: $color-text-secondary; }
.kb-sec p { margin: 3px 0; font-size: 14px; line-height: 1.65; }
.kb-sec em { font-style: normal; color: $color-text-muted; }
.kb-sec a { color: $color-primary; text-decoration: underline; text-underline-offset: 3px; }

.fx { background: $color-primary-softer; border: 1px solid $color-border; border-radius: 12px; padding: 12px 14px; }
.fx-row { display: flex; gap: 10px; padding: 5px 0; }
.fx-g { flex-shrink: 0; width: 64px; font-size: 12.5px; font-weight: 700; color: #fff; background: $blue-500; border-radius: 6px; text-align: center; height: 22px; line-height: 22px; }
.fx-row b { font-size: 14.5px; }
.fx-row p { margin: 1px 0 0; font-size: 13.5px; color: $color-text-secondary; line-height: 1.6; }
</style>
