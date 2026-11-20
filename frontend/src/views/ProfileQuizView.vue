<template>
  <div class="quiz">
    <section v-if="loading" class="card panel">正在读取账号 {{ userStore.username }} 的测评状态…</section>
    <section v-else-if="loadError" class="card panel" role="alert">
      <p>{{ loadError }}</p>
      <button class="tc-btn" type="button" @click="load">重新加载</button>
    </section>
    <!-- 只有已完成初始测评的账号关闭入口，训练记录不影响补做。 -->
    <section v-else-if="blocked" class="card panel rise blocked">
      <div class="bk-icon"><SIcon name="lock" :size="26" /></div>
      <div class="bk-title">当前账号已完成初始测评</div>
      <div class="bk-desc">账号 {{ userStore.username }} 的初始测评已保存。请到学情画像页查看结果或更新当前学情。</div>
      <router-link to="/profile" class="tc-btn"><SIcon name="chart" :size="15" /> 去学情画像</router-link>
    </section>

    <template v-else>
      <!-- 顶部进度 -->
      <section class="card panel head">
        <div class="head-left">
          <div class="head-title">{{ personalOnly ? '个性化测评' : '初始画像测评' }}</div>
          <div class="head-sub">账号 {{ userStore.username }} · {{ phase === 'quiz' ? `${partName} · 第 ${idx + 1} / ${total} 题` : '系统据此确定你的起始水平' }}</div>
        </div>
        <div class="head-bar"><i :style="{ width: progress + '%' }" /></div>
        <div class="head-pct">{{ Math.round(progress) }}%</div>
      </section>

      <!-- 答题 -->
      <section v-if="phase === 'quiz'" class="card panel qcard" data-tour="quiz-card">
        <transition name="swap" mode="out-in">
          <div :key="cur.id" class="qbody">
            <div class="q-dim"><i class="q-dot" />{{ cur.dim_name }}</div>
            <div class="q-title">{{ cur.title }}</div>

            <!-- 目标客源国：选一个，之后的语言题按该国语言出 -->
            <div v-if="cur.part === 'market'" class="mk-grid">
              <button v-for="m in cur.markets" :key="m.code" class="mk-chip" :class="{ on: answers[cur.id] === m.code }"
                @click="choose(m.code)">
                <b>{{ m.country }}</b><span>{{ m.service_language }}</span>
              </button>
              <button class="mk-chip none" :class="{ on: answers[cur.id] === 'NONE' }" @click="choose('NONE')">
                <b>暂不确定</b><span>先不定制客源国</span>
              </button>
            </div>

            <!-- 背景：选一个状态 + 选填一句话（需要点「下一题」，不自动跳） -->
            <template v-else-if="cur.part === 'background'">
              <div class="opts">
                <button v-for="(o, i) in cur.options" :key="o.key" class="opt"
                  :class="{ on: answers[cur.id] === o.key }" @click="chooseHold(o.key)">
                  <span class="opt-key">{{ 'ABCD'[i] }}</span>
                  <span class="opt-label">{{ o.label }}</span>
                  <span class="opt-check"><SIcon name="check" :size="14" /></span>
                </button>
              </div>
              <label class="bg-note">
                <span>{{ cur.text_label }}</span>
                <input v-model.trim="bgNote" type="text" maxlength="40" :placeholder="cur.text_placeholder" />
              </label>
            </template>

            <div v-else class="opts">
              <button v-for="(o, i) in cur.options" :key="o.key" class="opt"
                :class="{ on: answers[cur.id] === o.key }" :style="{ animationDelay: (0.04 * i) + 's' }"
                @click="choose(o.key)">
                <span class="opt-key">{{ 'ABCD'[i] }}</span>
                <span class="opt-label">{{ o.label }}</span>
                <span class="opt-check"><SIcon name="check" :size="14" /></span>
              </button>
            </div>
          </div>
        </transition>
        <div class="qfoot">
          <button class="btn-ghost" :disabled="idx === 0" @click="prev"><SIcon name="back" :size="14" /> 上一题</button>
          <div class="dots">
            <i v-for="(q, i) in questions" :key="q.id" :class="{ done: answered(q.id), cur: i === idx }" />
          </div>
          <button class="tc-btn" :disabled="!answers[cur.id]" @click="next">
            {{ idx === total - 1 ? (personalOnly ? '保存画像' : '提交并生成画像') : '下一题' }} <SIcon name="right" :size="14" />
          </button>
        </div>
      </section>

      <!-- 分析中 -->
      <section v-else-if="phase === 'analyzing'" class="card panel analyzing">
        <div class="ring-analyze">
          <svg viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="52" fill="none" stroke="#eef2f7" stroke-width="7" />
            <circle cx="60" cy="60" r="52" fill="none" stroke="#133450" stroke-width="7" stroke-linecap="round"
              stroke-dasharray="80 246" transform="rotate(-90 60 60)" class="spin-arc" />
            <circle cx="60" cy="60" r="38" fill="none" stroke="#eef2f7" stroke-width="6" />
            <circle cx="60" cy="60" r="38" fill="none" stroke="#e08a1e" stroke-width="6" stroke-linecap="round"
              stroke-dasharray="60 179" transform="rotate(-90 60 60)" class="spin-arc rev" />
          </svg>
          <div class="ring-core"><SIcon name="sparkle" :size="22" /></div>
        </div>
        <div class="an-title">正在生成你的初始画像</div>
        <div class="an-steps">
          <div v-for="(s, i) in analyzeSteps" :key="s" class="an-step" :class="{ on: i <= anIdx }">
            <i class="an-dot" />{{ s }}
          </div>
        </div>
      </section>

      <!-- 结果 -->
      <template v-else-if="phase === 'done'">
        <section class="card panel result-top">
          <div class="gauge">
            <svg viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="52" fill="none" stroke="#eef2f7" stroke-width="9" />
              <circle cx="60" cy="60" r="52" fill="none" stroke="#133450" stroke-width="9" stroke-linecap="round"
                :stroke-dasharray="C52" :stroke-dashoffset="off52" transform="rotate(-90 60 60)" class="ring-anim" />
            </svg>
            <div class="gauge-txt">
              <div class="g-num">{{ Math.round(animOverall) }}</div>
              <div class="g-cap">初始能力</div>
            </div>
          </div>
          <div class="result-mid">
            <div class="rm-title">初始画像已保存</div>
            <div class="rm-desc">{{ report.summary }}</div>
            <div class="rm-tags">
              <span v-for="d in focusDims" :key="d" class="tag-focus">{{ d }}</span>
            </div>
          </div>
          <div class="radar">
            <svg v-if="radarHasAxes" viewBox="0 0 220 220" class="radar-svg" :class="{ on: radarOn }">
              <g v-for="l in [25, 50, 75, 100]" :key="'g' + l">
                <polygon :points="ringPoints(l)" fill="none" :stroke="l === 100 ? '#d6e0ed' : '#eef2f7'" stroke-width="1" />
              </g>
              <line v-for="(p, i) in axes" :key="'a' + i" x1="110" y1="110" :x2="p.x" :y2="p.y" stroke="#eef2f7" stroke-width="1" />
              <polygon :points="initialPoints" fill="rgba(19,52,80,0.16)" stroke="#133450" stroke-width="2" stroke-dasharray="5 4" />
              <polygon :points="currentPoints" fill="rgba(224,138,30,0.14)" stroke="#e08a1e" stroke-width="2" />
              <text v-for="(p, i) in labels" :key="'t' + i" :x="p.x" :y="p.y" class="radar-label"
                text-anchor="middle" dominant-baseline="middle">{{ p.text }}</text>
            </svg>
            <div v-else class="radar-na">可对比维度不足 3 个，未画雷达</div>
          </div>
        </section>

        <!-- 同量纲核对：初始画像 vs 当前能力（真实日期来源 + 未评估逐维标注） -->
        <section class="card panel radar-check">
          <div class="rc-head">
            <SIcon name="target" :size="15" />
            <span>初始画像 vs 当前能力（同一刻度 0–100）</span>
            <span class="rc-legend"><i class="sw init" />初始画像</span>
            <span class="rc-legend"><i class="sw cur" />当前能力</span>
          </div>
          <div class="rc-meta">
            <span>初始画像：<b>{{ fmtAt(radarData.initial?.at) || '无日期' }}</b> · {{ sourceText(radarData.initial?.source) }}</span>
            <span>当前能力：<b>{{ fmtAt(radarData.current?.at) || '无日期' }}</b> · {{ sourceText(radarData.current?.source) }}</span>
          </div>
          <div v-if="radarUnassessed.length" class="rc-tip">
            未评估维度（不参与雷达、也不按 0 计）：{{ radarUnassessed.map(d => d.id + ' ' + d.name).join('、') }}
          </div>
          <div class="rc-table">
            <div class="rc-row rc-th"><span>维度</span><span>初始画像</span><span>当前能力</span><span>变化</span></div>
            <div v-for="d in radarRows" :key="d.id" class="rc-row">
              <span class="rc-dim"><i class="tag">{{ d.id }}</i>{{ d.name }}</span>
              <span class="rc-v" :class="{ na: d.initial === null }">{{ d.initial === null ? '未评估' : d.initial.toFixed(1) }}</span>
              <span class="rc-v cur" :class="{ na: d.current === null }">{{ d.current === null ? '未评估' : d.current.toFixed(1) }}</span>
              <span class="rc-d" :class="deltaClass(d)">{{ deltaText(d) }}</span>
            </div>
          </div>
        </section>

        <!-- 实测趋势口径：均分 + 样本数 + 题目/订单口径，示例与真实分开标识 -->
        <section class="card panel trend-scope">
          <div class="rc-head">
            <SIcon name="wave" :size="15" />
            <span>近期分数趋势</span>
            <span class="scope-badge" :class="scopeClass">{{ scopeLabel }}</span>
          </div>
          <div v-if="!trendData.has_data" class="ts-empty">
            完成训练后查看分数趋势：做几道题或完成一次实战评分后，这里会显示均分、变化与样本数。
          </div>
          <div v-else class="ts-grid">
            <div class="ts-box">
              <div class="ts-l">做题 · {{ trendData.quiz?.metric || '正确率(%)' }}</div>
              <div class="ts-v"><b>{{ numOr(trendData.quiz?.avg_score) }}</b><i>均分</i></div>
              <div class="ts-m">样本 <b>{{ trendData.quiz?.total_samples ?? 0 }}</b> 题 ·
                正答 <b>{{ trendData.quiz?.correct ?? 0 }}</b> ·
                准确率 <b>{{ trendData.quiz?.accuracy ?? '—' }}{{ trendData.quiz?.accuracy === null || trendData.quiz?.accuracy === undefined ? '' : '%' }}</b></div>
            </div>
            <div class="ts-box order">
              <div class="ts-l">实战订单 · {{ trendData.order?.metric || '订单评分(0-100)' }}</div>
              <div class="ts-v"><b>{{ numOr(trendData.order?.avg_score) }}</b><i>均分</i></div>
              <div class="ts-m">样本 <b>{{ trendData.order?.total_samples ?? 0 }}</b> 条评分 ·
                涉及 <b>{{ trendData.order?.distinct_orders ?? 0 }}</b> 单</div>
            </div>
          </div>
          <router-link to="/profile" class="rc-more">到学情画像看完整趋势曲线 <SIcon name="right" :size="12" /></router-link>
          <!-- 技术口径不进入主流程：收进折叠说明 -->
          <details class="tech-fold">
            <summary>口径与计算说明</summary>
            <div class="tf-body">
              能力记录分「学习」与「实战」两套口径（对应后端能力表的 teach / real_v 两列）；
              初始画像与当前能力用同一把 0–100 刻度对比，因此可以直接看差值；尚未评估过的维度显示
              「未评估」，既不参与对比也不按 0 分计入，不使用估算数字填充。分数趋势按两种来源分开统计：
              做题来源（每次答题记录 quiz_attempt）与订单来源（每次实战评分记录 order_score），
              各自给出均分与样本数，示例数据与真实训练数据分开标识。
            </div>
          </details>
        </section>

        <section class="result-grid">
          <div class="card panel">
            <div class="panel-head"><SIcon name="target" :size="15" /><span>维度点评</span></div>
            <div class="dimrows">
              <div v-for="d in dimRows" :key="d.id" class="dimrow">
                <span class="dr-id">{{ d.id }}</span>
                <span class="dr-name">{{ d.name }}</span>
                <div class="dr-track"><i :style="{ width: d.score + '%' }" /></div>
                <span class="dr-score">{{ d.score }}</span>
                <span class="dr-comment">{{ d.comment }}</span>
              </div>
            </div>
          </div>
          <div class="card panel">
            <div class="panel-head"><SIcon name="flame" :size="15" /><span>学习建议</span></div>
            <div class="sugs">
              <div v-for="(s, i) in report.suggestions || []" :key="i" class="sug" :style="{ animationDelay: (0.06 * i) + 's' }">
                <div class="sug-head">
                  <span class="sug-dim">{{ s.dim_name }}</span>
                  <span class="sug-title">{{ s.title }}</span>
                </div>
                <div class="sug-line"><span class="sug-k">为什么</span><span class="sug-v">{{ s.why }}</span></div>
                <div class="sug-line"><span class="sug-k">怎么练</span><span class="sug-v">{{ s.how }}</span></div>
                <button v-if="s.skill_point_id" class="sug-go" @click="goLearn(s.skill_point_id)">
                  {{ s.skill_point_id }} 去学习 <SIcon name="right" :size="12" />
                </button>
              </div>
            </div>
          </div>
        </section>

        <LearnerProfileCard v-if="userStore.userId" :user-id="userStore.userId" :refresh-key="learnerKey" />

        <LearningRouteLauncher />

        <div class="result-foot">
          <router-link to="/profile" class="tc-btn"><SIcon name="chart" :size="15" /> 进入学情画像</router-link>
          <router-link to="/learn" class="tc-btn ghost" data-tour="quiz-to-learn"><SIcon name="book" :size="15" /> 去学习地图</router-link>
        </div>
      </template>

      <div v-if="error" class="err card panel">{{ error }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import LearningRouteLauncher from '@/components/LearningRouteLauncher.vue'
import LearnerProfileCard from '@/components/LearnerProfileCard.vue'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const blocked = ref(false)
const loading = ref(true)
const loadError = ref('')
const questions = ref<any[]>([])
const answers = ref<Record<string, string>>({})
const idx = ref(0)
const phase = ref<'quiz' | 'analyzing' | 'done'>('quiz')
const report = ref<any>({})
const error = ref('')
const anIdx = ref(0)
let anTimer = 0

/* ── 测评步骤：①学习风格(4) + 背景(1) → ②目标客源国(1) + 语言水平(3) → ③八维掌握度(12) ──
   ?part=personal 时只做前两部分（已测过八维的老账号补做个性化画像），保存走 PUT /profiles/{id}/learner */
const personal = ref<any>({ style_questions: [], background_question: null, markets: [], language_questions: [] })
const personalOnly = computed(() => route.query.part === 'personal')
const bgNote = ref('')

interface Step { id: string; part: string; dim_name: string; title: string; options: any[]; [k: string]: any }
const marketCode = computed(() => answers.value.MK && answers.value.MK !== 'NONE' ? answers.value.MK : '')
const marketInfo = computed(() => (personal.value.markets || []).find((m: any) => m.code === marketCode.value))
const steps = computed<Step[]>(() => {
  const out: Step[] = []
  for (const q of personal.value.style_questions || []) out.push(q)
  if (personal.value.background_question) out.push(personal.value.background_question)
  if ((personal.value.markets || []).length) {
    out.push({ id: 'MK', part: 'market', dim_name: '目标客源国', options: [], markets: personal.value.markets,
               title: '你主要想接待哪个国家的客人？（讲义会加入该国的语言提示、文化提示和政策提示）' })
  }
  if (marketInfo.value) {
    for (const q of personal.value.language_questions || []) {
      out.push({ ...q, dim_name: `${marketInfo.value.country}客人 · ${marketInfo.value.service_language}水平（${q.skill_name}）`,
                 title: String(q.title).split('{lang}').join(marketInfo.value.lang_short || marketInfo.value.service_language) })
    }
  }
  if (!personalOnly.value) for (const q of questions.value) out.push({ ...q, part: 'ability' })
  return out
})
const PART_NAMES: Record<string, string> = {
  style: '第 1 部分 · 学习风格', background: '第 1 部分 · 学习风格', market: '第 2 部分 · 目标客源国',
  language: '第 2 部分 · 目标客源国', ability: '第 3 部分 · 八维能力',
}
const total = computed(() => steps.value.length || 12)
const cur = computed<Step>(() => steps.value[idx.value] || { id: '', part: '', dim_name: '', title: '', options: [] })
const partName = computed(() => PART_NAMES[cur.value.part] || '')
const answeredCount = computed(() => steps.value.filter((q) => answers.value[q.id]).length)
const progress = computed(() => (phase.value === 'quiz' ? (answeredCount.value / total.value) * 100 : 100))
function answered(id: string) { return !!answers.value[id] }
const learnerKey = ref(0)

const analyzeSteps = ['读取你的测评选择', '记录学习风格与目标客源国', '对齐你的能力起点', '生成定性描述与学习建议', '保存初始画像']
const C52 = 2 * Math.PI * 52
const animOverall = ref(0)
const radarOn = ref(false)

const DIMS = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8']
const SHORT: Record<string, string> = { C1: '沟通', C2: '需求', C3: '方案', C4: '资源', C5: '报价', C6: '应急', C7: '合规', C8: '跨文化' }
const DIM_NAMES: Record<string, string> = { C1: '沟通信任', C2: '需求洞察', C3: '方案能力', C4: '资源整合', C5: '报价利润', C6: '应急解决', C7: '合规效率', C8: '跨文化入境游沟通' }

/* ── 初始 vs 当前（/profiles/{id}/radar）：同一 0–100 量纲；缺值 = 未评估，不按 0 计 ── */
interface RadarDimRow {
  id: string
  name: string
  initial: number | null
  current: number | null
}
const radarData = ref<any>({})
const trendData = ref<any>({})

const radarRows = computed<RadarDimRow[]>(() => {
  const init = radarData.value?.initial?.dimensions || []
  const cur = radarData.value?.current?.dimensions || []
  const byId: Record<string, any> = {}
  for (const d of cur) byId[String(d.id)] = d
  return init.map((d: any): RadarDimRow => {
    const c = byId[String(d.id)]
    return {
      id: String(d.id),
      name: String(d.name || d.id),
      initial: d.assessed && typeof d.value === 'number' ? d.value : null,
      current: c && c.assessed && typeof c.value === 'number' ? c.value : null,
    }
  })
})
const radarComparable = computed(() => radarRows.value.filter((d) => d.initial !== null && d.current !== null))
const radarUnassessed = computed(() => radarRows.value.filter((d) => d.initial === null || d.current === null))
const radarHasAxes = computed(() => radarComparable.value.length >= 3)

const scopeClass = computed(() => (trendData.value?.data_scope?.scope === 'example' ? 'demo' : 'real'))
const scopeLabel = computed(() => trendData.value?.data_scope?.label
  || (userStore.isDemo ? '标准案例 / 演示数据' : '真实训练数据'))

function fmtAt(v?: string): string {
  return String(v || '').replace('T', ' ').slice(0, 16)
}
function sourceText(src?: string): string {
  const s = String(src || '')
  if (!s) return '来源未知'
  if (s === 'intake') return '来源：初始测评快照'
  if (s.startsWith('ability')) return '来源：历史能力记录'
  if (s === 'initial') return '来源：初始画像报告'
  if (s === 'refresh') return '来源：动态刷新报告'
  return `来源：${s}`
}
function numOr(v: any): string {
  return (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : String(v)
}
function deltaText(d: { initial: number | null; current: number | null }): string {
  if (d.initial === null || d.current === null) return '未评估'
  const v = Number((d.current - d.initial).toFixed(1))
  return (v > 0 ? '+' : '') + v.toFixed(1)
}
function deltaClass(d: { initial: number | null; current: number | null }): Record<string, boolean> {
  if (d.initial === null || d.current === null) return { na: true }
  const v = d.current - d.initial
  return { up: v > 0, down: v < 0, flat: v === 0 }
}

const scores = computed<Record<string, number>>(() => report.value.scores || {})
const overall = computed(() => {
  const v = DIMS.map((d) => scores.value[d] || 0)
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0
})
const off52 = computed(() => C52 * (1 - Math.min(100, animOverall.value) / 100))
const focusDims = computed(() => (report.value.focus || []).map((d: string) => `${d} ${SHORT[d] || d}`))
const dimRows = computed(() => DIMS.map((id) => ({
  id, name: DIM_NAMES[id], score: Math.round(scores.value[id] || 0),
  comment: (report.value.dimensions || {})[id] || '',
})))

function polar(i: number, r: number) {
  const n = Math.max(3, radarComparable.value.length)
  const a = (Math.PI * 2 * i) / n - Math.PI / 2
  return { x: 110 + r * Math.cos(a), y: 110 + r * Math.sin(a) }
}
const axes = computed(() => radarComparable.value.map((_, i) => polar(i, 78)))
function ringPoints(level: number) {
  return radarComparable.value.map((_, i) => {
    const p = polar(i, (78 * level) / 100)
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
  }).join(' ')
}
function polygonOf(key: 'initial' | 'current') {
  return radarComparable.value.map((d, i) => {
    const v = Math.max(0, Math.min(100, Number(d[key] ?? 0)))
    const p = polar(i, (78 * v) / 100)
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
  }).join(' ')
}
const initialPoints = computed(() => polygonOf('initial'))
const currentPoints = computed(() => polygonOf('current'))
const labels = computed(() => radarComparable.value.map((d, i) => {
  const p = polar(i, 98)
  return { x: p.x, y: p.y, text: SHORT[d.id] || d.name }
}))

async function loadRadar() {
  try {
    radarData.value = (await client.get(`/profiles/${userStore.userId}/radar`)).data || {}
  } catch { radarData.value = {} }
}

async function loadTrend() {
  try {
    trendData.value = (await client.get(`/profiles/${userStore.userId}/trend`)).data || {}
  } catch { trendData.value = {} }
}

async function load() {
  loading.value = true
  loadError.value = ''
  blocked.value = false
  try {
    const gate = await client.get(`/profiles/${userStore.userId}/intake`)
    // 补做个性化画像不受「已完成初始测评」限制
    if (!gate.data.can_assess && !personalOnly.value) { blocked.value = true; return }
    const r = await client.get('/profile/quiz')
    questions.value = r.data.questions || []
    personal.value = r.data.personal || personal.value
    if (!questions.value.length) throw new Error('测评题目暂时为空')
    if (!personalOnly.value) await Promise.all([loadRadar(), loadTrend()])
  } catch {
    loadError.value = '测评状态或题目暂时无法读取，请重新加载。'
  } finally {
    loading.value = false
  }
}

function choose(key: string) {
  const id = cur.value.id
  answers.value = { ...answers.value, [id]: key }
  // 换了客源国：之前答的语言题是按旧语种答的，作废重答
  if (id === 'MK') {
    const rest = { ...answers.value }
    for (const q of personal.value.language_questions || []) delete rest[q.id]
    answers.value = rest
  }
  if (idx.value < total.value - 1) {
    window.setTimeout(() => { if (answers.value[id] === key) next() }, 280)
  }
}
/** 背景题要留时间填「专业/原行业」，选完不自动跳 */
function chooseHold(key: string) { answers.value = { ...answers.value, [cur.value.id]: key } }
function next() {
  if (!answers.value[cur.value.id]) return
  if (idx.value < total.value - 1) { idx.value += 1; return }
  submit()
}
function prev() { if (idx.value > 0) idx.value -= 1 }

/** 个性化部分的答案，格式同后端 LearnerBody */
function personalPayload() {
  const pick = (ids: string[]) => Object.fromEntries(ids.filter((i) => answers.value[i]).map((i) => [i, answers.value[i]]))
  return {
    style: pick((personal.value.style_questions || []).map((q: any) => q.id)),
    background: { status: answers.value.BG1 || '', note: bgNote.value },
    market: marketCode.value,
    language: marketCode.value ? pick((personal.value.language_questions || []).map((q: any) => q.id)) : {},
  }
}

async function submit() {
  if (personalOnly.value) {          // 只补做个性化画像：保存后回到画像页
    phase.value = 'analyzing'
    anIdx.value = 0
    try {
      await client.put(`/profiles/${userStore.userId}/learner`, personalPayload())
      learnerKey.value += 1
      await router.replace('/profile')
    } catch (e: any) {
      phase.value = 'quiz'
      error.value = e?.response?.data?.detail || '保存失败，请重试。'
    }
    return
  }
  phase.value = 'analyzing'
  anIdx.value = 0
  anTimer = window.setInterval(() => { anIdx.value = Math.min(analyzeSteps.length - 1, anIdx.value + 1) }, 900)
  const payload = { user_id: userStore.userId, language: '中文', personal: personalPayload(),
    answers: questions.value.map((q) => ({ qid: q.id, key: answers.value[q.id] })) }
  try {
    const r = await client.post('/profile/assessment', payload)
    report.value = r.data.report || {}
    // 测评刚把初始基线（profile_baseline）与能力写入服务端：立刻回读同量纲雷达与趋势口径
    await Promise.all([loadRadar(), loadTrend()])
    await new Promise((res) => window.setTimeout(res, 600))
    phase.value = 'done'
    requestAnimationFrame(() => {
      const target = overall.value
      let cur01 = 0
      const tick = () => {
        cur01 = Math.min(target, cur01 + Math.max(0.8, target / 40))
        animOverall.value = cur01
        if (cur01 < target) requestAnimationFrame(tick)
      }
      tick()
      radarOn.value = true
    })
  } catch (e: any) {
    phase.value = 'quiz'
    error.value = e?.response?.data?.detail || '生成画像失败，请重试。'
  }
}

function goLearn(sp: string) { router.push(`/learn/thread/${sp}`) }

onMounted(load)
onUnmounted(() => { if (anTimer) clearInterval(anTimer) })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.quiz { width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; max-width: 1240px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }
.panel { padding: 20px 22px; }

.blocked { display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding: 34px 32px; }
.bk-icon { width: 52px; height: 52px; border-radius: 14px; display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; }
.bk-title { font-size: 21px; font-weight: 800; }
.bk-desc { font-size: 16px; line-height: 1.75; color: $color-text-secondary; max-width: 720px; }

.head { display: flex; align-items: center; gap: 18px; padding: 16px 22px; }
.head-left { min-width: 220px; }
.head-title { font-size: 19px; font-weight: 800; }
.head-sub { margin-top: 4px; font-size: 15px; color: $color-text-secondary; }
.head-bar { flex: 1; height: 8px; border-radius: 999px; background: #eef2f7; overflow: hidden; }
.head-bar i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #133450, #3a7bb0);
  transition: width .45s cubic-bezier(.34,1.1,.5,1); }
.head-pct { min-width: 54px; text-align: right; font-size: 17px; font-weight: 800; color: $color-primary; }

.qcard { padding: 26px 30px 20px; }
.q-dim { display: inline-flex; align-items: center; gap: 7px; font-size: 14.5px; font-weight: 600; color: $color-primary;
  background: $color-primary-soft; padding: 4px 12px; border-radius: 999px; }
.q-dot { width: 6px; height: 6px; border-radius: 50%; background: $color-primary; }
.q-title { margin: 16px 0 20px; font-size: 25px; font-weight: 800; line-height: 1.45; }
.opts { display: flex; flex-direction: column; gap: 11px; }
.opt { display: flex; align-items: center; gap: 14px; text-align: left; padding: 16px 18px; cursor: pointer;
  border: 1px solid $color-border; border-radius: $radius-md; background: #fff; font-size: 16.5px; line-height: 1.6;
  color: $color-text; animation: optIn .34s cubic-bezier(.34,1.3,.6,1) both;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s cubic-bezier(.34,1.4,.6,1), background .16s ease; }
@keyframes optIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.opt:hover { border-color: $color-primary; transform: translateY(-2px); box-shadow: 0 8px 20px rgba(19,52,80,0.12); }
.opt.on { border-color: $color-primary; background: $color-primary-softer; box-shadow: 0 0 0 3px rgba(19,52,80,0.12); }
.opt-key { width: 28px; height: 28px; flex-shrink: 0; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  font-size: 15px; font-weight: 800; color: $color-text-secondary; background: #edf2f6; transition: all .16s ease; }
.opt.on .opt-key { background: $color-primary; color: #fff; }
.opt-label { flex: 1; }
.opt-check { color: $color-primary; opacity: 0; transform: scale(.6); transition: all .2s cubic-bezier(.34,1.56,.64,1); }
.opt.on .opt-check { opacity: 1; transform: scale(1); }

.qfoot { margin-top: 22px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.dots { display: flex; gap: 5px; }
.dots i { width: 7px; height: 7px; border-radius: 50%; background: #e3e9f2; transition: all .2s ease; }
.dots i.done { background: #b9d0e6; }
.dots i.cur { width: 20px; border-radius: 999px; background: $color-primary; }
.btn-ghost { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; border-radius: 999px; cursor: pointer;
  border: 1px solid $color-border; background: #fff; color: $color-text-secondary; font-size: 15.5px; }
.btn-ghost:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.btn-ghost:disabled { opacity: .45; cursor: default; }
.qcard .tc-btn { display: inline-flex; align-items: center; gap: 6px; }
.qcard .tc-btn:disabled { opacity: 1; background: #b9d0e6; color: #fff; box-shadow: none; cursor: default; }
.swap-enter-active, .swap-leave-active { transition: opacity .22s ease, transform .22s cubic-bezier(.34,1.2,.6,1); }
.swap-enter-from { opacity: 0; transform: translateX(24px); }
.swap-leave-to { opacity: 0; transform: translateX(-24px); }

.analyzing { display: flex; flex-direction: column; align-items: center; gap: 20px; padding: 52px 24px 56px; }
.ring-analyze { position: relative; width: 150px; height: 150px; animation: breathe 3.2s ease-in-out infinite; }
@keyframes breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.045); } }
.ring-analyze svg { width: 100%; height: 100%; }
.spin-arc { transform-origin: 60px 60px; animation: arcSpin 1.5s linear infinite; }
.spin-arc.rev { animation: arcSpin 2.3s linear infinite reverse; }
@keyframes arcSpin { to { transform: rotate(360deg); } }
.ring-core { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: $color-primary; }
.an-title { font-size: 22px; font-weight: 800; }
.an-steps { display: flex; flex-direction: column; gap: 10px; min-width: 320px; }
.an-step { display: flex; align-items: center; gap: 10px; font-size: 16px; color: $color-text-muted; transition: color .3s ease; }
.an-step .an-dot { width: 8px; height: 8px; border-radius: 50%; background: #dbe3ee; transition: all .3s ease; }
.an-step.on { color: $color-text; }
.an-step.on .an-dot { background: $color-primary; box-shadow: 0 0 0 4px rgba(19,52,80,0.14); }

.result-top { display: flex; align-items: center; gap: 32px; padding: 26px 30px; }
.gauge { position: relative; width: 186px; height: 186px; flex-shrink: 0; }
.gauge svg { width: 100%; height: 100%; }
.ring-anim { transition: stroke-dashoffset 1.1s cubic-bezier(.4,0,.2,1); }
.gauge-txt { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; }
.g-num { font-size: 44px; font-weight: 900; color: $color-primary; line-height: 1.1; }
.g-cap { font-size: 15px; color: $color-text-secondary; }
.result-mid { flex: 1; min-width: 0; }
.rm-title { font-size: 21px; font-weight: 800; }
.rm-desc { position: relative; margin-top: 14px; padding: 15px 18px 15px 22px; border-radius: $radius-md;
  background: linear-gradient(135deg, #f4f8fb, #d9e4ec); border: 1px solid #d9e4ec;
  font-size: 16.5px; line-height: 2; letter-spacing: .2px; color: $color-text; }
.rm-desc::before { content: ''; position: absolute; left: 0; top: 13px; bottom: 13px; width: 3px;
  border-radius: 0 3px 3px 0; background: linear-gradient(180deg, $color-primary, #3a7bb0); }
.rm-tags { margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }
.tag-focus { font-size: 14.5px; font-weight: 700; color: #b3730f; background: #fdf3e3; border: 1px solid #f2dcb6;
  padding: 4px 12px; border-radius: 999px; }
.radar { width: 240px; height: 240px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.radar-svg { width: 100%; height: 100%; transform: scale(.25); opacity: 0;
  transition: transform .9s cubic-bezier(.34,1.3,.5,1), opacity .5s ease; }
.radar-svg.on { transform: scale(1); opacity: 1; }
.radar-label { font-size: 11.5px; fill: #6b7a90; }
.radar-na { font-size: $fs-meta; line-height: 1.7; color: $color-text-muted; text-align: center; padding: 0 8px; }

/* 同量纲核对：初始画像 vs 当前能力 */
.radar-check { padding: 18px 22px 16px; }
.rc-head { display: flex; align-items: center; gap: 10px; font-size: 18px; font-weight: 700; flex-wrap: wrap; }
.rc-head svg { color: $color-primary; }
.rc-legend { display: inline-flex; align-items: center; gap: 6px; font-size: $fs-badge; color: $color-text-secondary;
  background: $color-bg; border: 1px solid $color-border; padding: 2px 10px; border-radius: 999px; }
.sw { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.sw.init { background: #133450; }
.sw.cur { background: #e08a1e; }
.scope-badge { margin-left: auto; font-size: $fs-badge; font-weight: 700; padding: 2px 10px; border-radius: 999px; }
.scope-badge.real { color: $color-success; background: #e5f7ee; border: 1px solid #ccecd9; }
.scope-badge.demo { color: #b3730f; background: #fdf3e3; border: 1px solid #f2dcb6; }
.rc-meta { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; font-size: $fs-meta; color: $color-text-secondary; }
.rc-meta b { color: $color-text; }
.rc-tip { margin-top: 10px; padding: 8px 12px; border-radius: $radius-md; background: #fdf3e3; border: 1px solid #f2dcb6;
  color: #8a5a08; font-size: $fs-meta; line-height: 1.7; }
.rc-table { margin-top: 12px; border: 1px solid $color-border; border-radius: $radius-md; overflow: hidden; }
.rc-row { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; align-items: center; }
.rc-row > span { padding: 8px 12px; font-size: $fs-meta; }
.rc-th { background: $color-bg; font-size: $fs-badge; font-weight: 700; color: $color-text-secondary; }
.rc-row + .rc-row { border-top: 1px solid $color-border; }
.rc-dim { display: flex; align-items: center; gap: 8px; color: $color-text; }
.rc-dim .tag { font-size: $fs-badge; font-weight: 700; color: $color-primary; background: $color-primary-soft;
  padding: 1px 6px; border-radius: 5px; font-style: normal; }
.rc-v { font-weight: 700; color: #133450; }
.rc-v.cur { color: #e08a1e; }
.rc-v.na { color: $color-text-muted; font-weight: 500; }
.rc-d { font-weight: 700; color: $color-text-secondary; }
.rc-d.up { color: $color-success; }
.rc-d.down { color: $color-danger; }
.rc-d.na { color: $color-text-muted; font-weight: 500; }

/* 实测趋势口径 */
.trend-scope { padding: 18px 22px 16px; }
/* 技术口径折叠：不进入主流程（监督者要求：工程术语不下发到主界面） */
.tech-fold { margin-top: 12px; }
.tech-fold > summary { cursor: pointer; font-size: $fs-meta; color: $color-primary; list-style: none; }
.tech-fold > summary::-webkit-details-marker { display: none; }
.tech-fold > summary::before { content: '▸ '; }
.tech-fold[open] > summary::before { content: '▾ '; }
.tf-body { margin-top: 6px; padding: 10px 12px; font-size: $fs-meta; line-height: 1.8; color: $color-text-secondary;
  background: $color-bg; border: 1px solid $color-border; border-radius: $radius-md; }
.ts-empty { margin-top: 10px; padding: 12px 14px; border-radius: $radius-md; background: $color-bg;
  border: 1px dashed $color-border-strong; font-size: $fs-meta; line-height: 1.8; color: $color-text-secondary; }
.ts-grid { margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.ts-box { border: 1px solid $color-border; border-radius: $radius-md; padding: 12px 14px; background: $color-primary-softer; }
.ts-box.order { background: #fff9f1; border-color: #f2e0c8; }
.ts-l { font-size: $fs-badge; font-weight: 700; color: $color-text-secondary; }
.ts-v { display: flex; align-items: baseline; gap: 6px; margin: 4px 0 2px; }
.ts-v b { font-size: $fs-num-lg; font-weight: 800; color: #133450; }
.ts-box.order .ts-v b { color: #e08a1e; }
.ts-v i { font-style: normal; font-size: $fs-badge; color: $color-text-muted; }
.ts-m { font-size: $fs-badge; line-height: 1.7; color: $color-text-secondary; }
.ts-m b { color: $color-text; }
.rc-more { display: inline-flex; align-items: center; gap: 5px; margin-top: 12px; font-size: $fs-meta;
  font-weight: 700; color: $color-primary; }
.rc-more:hover { text-decoration: underline; }

.result-grid { display: grid; grid-template-columns: 1.05fr 1fr; gap: 16px; }
.panel-head { display: flex; align-items: center; gap: 9px; font-size: 18px; font-weight: 700; margin-bottom: 12px; }
.panel-head svg { color: $color-primary; }
.dimrows { display: flex; flex-direction: column; gap: 12px; }
.dimrow { display: grid; grid-template-columns: 40px 120px 90px 40px; align-items: center; gap: 10px; }
.dr-id { font-size: 14.5px; font-weight: 800; color: $color-primary; }
.dr-name { font-size: 15.5px; font-weight: 600; }
.dr-track { height: 7px; border-radius: 999px; background: #eef2f7; overflow: hidden; }
.dr-track i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #133450, #3a7bb0);
  transition: width 1s cubic-bezier(.4,0,.2,1); }
.dr-score { font-size: 15.5px; font-weight: 800; text-align: right; }
.dr-comment { grid-column: 1 / -1; font-size: 15px; line-height: 1.7; color: $color-text-muted; }

.sugs { display: flex; flex-direction: column; gap: 12px; }
.sug { border: 1px solid $color-border; border-radius: $radius-md; padding: 16px 18px 15px; background: #fff;
  box-shadow: 0 2px 10px rgba(19,52,80,0.04); animation: optIn .46s cubic-bezier(.34,1.2,.6,1) both;
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease, border-color .18s ease; }
.sug:hover { transform: translateY(-2px); border-color: #c9d9e6; box-shadow: 0 12px 26px rgba(19,52,80,0.12); }
.sug-head { display: flex; align-items: center; gap: 10px; padding-bottom: 11px; border-bottom: 1px dashed #e5ebf1; }
.sug-dim { font-size: 13.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft; padding: 3px 10px; border-radius: 6px; white-space: nowrap; }
.sug-title { font-size: 16.5px; font-weight: 800; line-height: 1.5; }
.sug-line { display: flex; gap: 10px; margin-top: 11px; }
.sug-k { flex-shrink: 0; width: 46px; font-size: 14px; font-weight: 700; color: $color-text-muted; line-height: 1.8; }
.sug-v { flex: 1; font-size: 15.5px; line-height: 1.8; color: $color-text-secondary; }
.sug-line:nth-of-type(3) .sug-v { color: $color-text; }
.sug-go { align-self: flex-start; margin-top: 14px; display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: 999px; cursor: pointer; font-size: 14.5px; font-weight: 700;
  color: $color-primary; background: $color-primary-softer; border: 1px solid #d7e3ec; transition: all .18s ease; }
.sug-go:hover { background: $color-primary; border-color: $color-primary; color: #fff; }
.sug-go svg { transition: transform .18s ease; }
.sug-go:hover svg { transform: translateX(3px); }

.mk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 9px; margin-top: 4px; }
.mk-chip { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 11px 12px; border-radius: 12px;
  border: 1px solid $color-border; background: #fff; cursor: pointer; text-align: left; font: inherit; -webkit-tap-highlight-color: transparent;
  transition: border-color .15s, background .15s, box-shadow .15s; }
.mk-chip b { font-size: 16px; color: $color-text; }
.mk-chip span { font-size: 12.5px; color: $color-text-muted; }
.mk-chip:hover { border-color: $color-primary-light; }
.mk-chip.on { border-color: $color-primary; background: $color-primary-soft; box-shadow: 0 0 0 3px rgba(19,52,80,.10); }
.mk-chip.none { border-style: dashed; }
.bg-note { display: flex; flex-direction: column; gap: 6px; margin-top: 14px; font-size: 14.5px; color: $color-text-secondary; }
.bg-note input { height: 46px; border: 1px solid $color-border-strong; border-radius: 12px; padding: 0 14px; font: inherit; font-size: 16px; color: $color-text; outline: none; background: #fff; }
.bg-note input:focus { border-color: $color-primary; box-shadow: 0 0 0 3px rgba(19,52,80,.10); }

.result-foot { display: flex; gap: 12px; }
.result-foot .tc-btn { display: inline-flex; align-items: center; gap: 6px; }
.result-foot .tc-btn.ghost { background: #fff; color: $color-primary; border: 1px solid $color-border; }
.err { color: #c0392b; font-size: 16px; }

@media (max-width: 640px) {
  .quiz { gap: 10px; }
  .panel { padding: 16px; }
  .head { align-items: stretch; flex-direction: column; gap: 12px; }
  .head-left { min-width: 0; }
  .head-bar { width: 100%; flex: 0 0 8px; }
  .head-pct { text-align: left; }
  .qcard { padding: 17px 15px 16px; }
  .q-title { margin: 14px 0 17px; font-size: 21px; line-height: 1.55; }
  .opt { align-items: flex-start; padding: 14px; font-size: 16px; gap: 11px; }
  .opt-key { width: 30px; height: 30px; }
  .qfoot { flex-wrap: wrap; gap: 10px; }
  .qfoot .tc-btn { flex: 1; justify-content: center; min-height: 44px; }
  .dots { order: 3; flex-basis: 100%; justify-content: center; }
  .an-steps { min-width: 0; width: 100%; }
  .result-top { align-items: center; flex-direction: column; padding: 20px 16px; gap: 18px; }
  .gauge { width: 160px; height: 160px; }
  .result-mid { width: 100%; }
  .radar { width: 100%; height: 230px; }
  .radar-check, .trend-scope { padding: 16px; }
  .rc-table { overflow-x: auto; }
  .rc-row { min-width: 500px; }
  .ts-grid, .result-grid { grid-template-columns: 1fr; gap: 10px; }
  .dimrow { grid-template-columns: 38px minmax(0,1fr) 42px; gap: 8px; }
  .dr-track { grid-column: 1 / -1; }
  .dr-comment { grid-column: 1 / -1; }
  .sug-head { align-items: flex-start; flex-wrap: wrap; }
  .sug-line { flex-direction: column; gap: 2px; }
  .sug-k { width: auto; }
  .result-foot { flex-direction: column; }
  .result-foot .tc-btn { width: 100%; }
}
</style>
