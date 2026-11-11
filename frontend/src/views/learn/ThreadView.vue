<template>
  <div class="thread">
    <div class="cols">
      <section class="mid card">
        <div class="chat-head">
          <div class="ch-left">
            <span class="spid">{{ spId }}</span>
            <span class="spname">{{ name || '加载中…' }}</span>
            <span v-if="isBridge" class="spkind">文化桥</span>
          </div>
          <div class="ch-right">
            <router-link v-if="isBridge" class="tc-btn ghost mini" :to="`/learn/bridge/${spId}`">
              看文化桥内容
            </router-link>
            <router-link class="tc-btn ghost mini" to="/learn">学习地图</router-link>
          </div>
        </div>

        <div class="msgs">
          <template v-for="(m, i) in messages" :key="i">
            <!-- 判分结果挂在题卡上，不单独占一行 -->
            <div v-if="m.kind !== 'quiz_result'" class="msg" :class="m.role === 'user' ? 'me' : 'ai'">
              <div class="bubble-wrap">
                <div class="who">{{ m.role === 'user' ? '我' : '司南老师' }}</div>
                <div class="bubble">
                  <MarkdownView v-if="m.role === 'ai'" :text="m.content" />
                  <span v-else>{{ m.content }}</span>
                </div>
                <div v-if="m.role === 'ai'" class="ai-acts">
                  <button class="trace-toggle" @click="openTranslate(m)"><SIcon name="link" :size="11" /> 翻译</button>
                </div>
                <div v-if="m.role === 'ai' && m.evidence?.length" class="trace">
                  <button class="trace-toggle" @click="m.open = !m.open">
                    <SIcon name="link" :size="11" /> {{ m.open ? '收起溯源' : '展开溯源' }}
                  </button>
                  <div v-if="m.open" class="trace-body">
                    <div class="trace-hd">本次回复用到的来源</div>
                    <div v-for="e in m.evidence" :key="e" class="trace-item"><span class="c-n"><SIcon name="link" :size="10" /></span>{{ e }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 题目卡：跟着聊天记录走，每道题各一张；答过的那张留在原位变只读回放 -->
            <div v-if="m.kind === 'quiz'" class="quiz card">
              <div class="q-head">
                <span class="q-tag">难度 {{ m.quiz.difficulty }}</span>
                <span class="q-nth">第 {{ m.nth }} 题</span>
                <span v-if="m.result" class="q-state" :class="m.result.correct ? 'ok' : 'bad'">
                  {{ m.result.correct ? '已答对' : '已答错' }}
                </span>
                <span v-else class="q-state todo">待作答</span>
              </div>
              <div class="q-stem">{{ m.quiz.stem }}</div>

              <template v-if="!m.result">
                <div v-if="m.quiz.type === 'choice'" class="q-opts">
                  <label v-for="(o, oi) in m.quiz.options" :key="oi" class="q-opt"
                    :class="{ on: m.pick === String.fromCharCode(65 + oi) }">
                    <input type="radio" :value="String.fromCharCode(65 + oi)" v-model="m.pick" />
                    <span class="q-key">{{ String.fromCharCode(65 + oi) }}</span>{{ o }}
                  </label>
                </div>
                <textarea v-else v-model="m.pick" class="q-short" rows="3" placeholder="写下你的答案（简答）"></textarea>
                <div class="q-foot">
                  <button class="tc-btn" :disabled="!m.pick || busy" @click="submitQuiz(m)">交卷</button>
                </div>
              </template>

              <template v-else>
                <div class="q-ans">
                  <span class="qa-lbl">我的答案</span>
                  <span class="qa-val">{{ answerText(m) }}</span>
                </div>
                <div class="q-foot">
                  <span class="q-result" :class="{ ok: m.result.correct }">
                    {{ m.result.correct ? '答对' : '答错' }} · 掌握度 {{ trendArrow(m.result.trend) }} · 难度 {{ m.result.difficulty }}
                  </span>
                </div>
                <div v-if="m.result.explain" class="q-explain">{{ m.result.explain }}</div>
              </template>
            </div>
          </template>

          <div v-if="!messages.length" class="empty">向老师提问、讲解、做题或复盘。</div>
        </div>

        <div class="chat-input">
          <div class="quick">
            <button v-for="a in QUICK" :key="a.label" class="qbtn" :disabled="busy" @click="fill(a)">
              <SIcon :name="a.icon" :size="13" /> {{ a.label }}
            </button>
          </div>
          <div class="composer">
            <textarea ref="iptEl" v-model="q" class="ipt" rows="2"
              placeholder="问老师，或点上面的按钮自动填入这一项…" @keydown.enter.exact.prevent="send" />
            <button class="tc-btn send" :disabled="busy" @click="send">
              <SIcon name="right" :size="14" /> {{ busy ? '思考中…' : '发送' }}
            </button>
          </div>
        </div>
      </section>

      <aside class="right">
        <div class="card panel">
          <div class="col-title"><SIcon name="target" :size="14" /> 当前掌握度</div>
          <div class="rings">
            <div v-for="r in rings" :key="r.name" class="ring">
              <svg viewBox="0 0 88 88" class="ring-svg">
                <circle cx="44" cy="44" r="34" fill="none" stroke="#eef1f5" stroke-width="9" />
                <circle cx="44" cy="44" r="34" fill="none" :stroke="r.color" stroke-width="9" stroke-linecap="round"
                  :stroke-dasharray="CIRC" :stroke-dashoffset="offset(r.value)" transform="rotate(-90 44 44)" />
              </svg>
              <div class="ring-val" :style="{ color: r.color }">{{ Math.round(r.value) }}<i>%</i></div>
              <div class="ring-name"><i class="swatch" :style="{ background: r.color }" />{{ r.name }}</div>
            </div>
          </div>
        </div>

        <div class="card panel">
          <div class="col-title"><SIcon name="wave" :size="14" /> 题目难度曲线</div>
          <div class="diff">
            <div class="diff-meter">
              <span v-for="l in 5" :key="l" class="diff-seg" :class="{ on: l <= currentDiff, cur: l === currentDiff }">{{ 'L' + l }}</span>
            </div>
            <svg class="diff-chart" viewBox="0 0 220 56" preserveAspectRatio="none">
              <line v-for="l in 5" :key="'g' + l" :x1="0" :x2="220" :y1="yFor(l)" :y2="yFor(l)" class="diff-grid" />
              <path :d="diffPath" fill="none" stroke="#2577e3" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
              <circle v-if="diffHistory.length" :cx="lastPt.x" :cy="lastPt.y" r="3.5" fill="#2577e3" />
            </svg>
            <div class="diff-foot">
              <span class="diff-cur">难度 <b>L{{ currentDiff }}</b></span>
              <span v-if="lastTrend && lastTrend !== 'flat'" class="diff-trend" :class="lastTrend">{{ lastTrend === 'up' ? '难度 ↑' : '难度 ↓' }}</span>
            </div>
          </div>
        </div>

        <div class="card panel">
          <div class="col-title"><SIcon name="filetext" :size="14" /> 个性资源栏</div>
          <div v-if="assets.length" class="a-list">
            <div v-for="a in assets" :key="a.asset_id" class="a-item" @click="openAsset(a)">
              <SIcon name="filetext" :size="13" /> {{ a.title }}
            </div>
          </div>
          <div v-else class="a-empty">暂无资源</div>
        </div>
      </aside>
    </div>

    <div v-if="preview" class="mask" @click.self="preview = null">
      <div class="modal card">
        <div class="m-head">
          <span class="m-title">{{ preview.title }}</span>
          <div class="m-actions">
            <button class="tc-btn ghost mini" @click="preview = null">关闭</button>
          </div>
        </div>
        <div class="m-body"><MarkdownView :text="preview.content" /></div>
      </div>
    </div>

    <transition name="adock">
      <div v-if="agentsOn" class="agent-overlay">
        <div class="agent-modal">
          <div class="am-head">
            <div class="am-title"><span class="am-live" />多 Agent 协作</div>
            <span class="am-sub">司南老师 · 核心调度</span>
          </div>
          <div v-if="scheduling" class="am-sched">
            <img class="sched-bg" :src="yunBg" alt="" />
            <div class="sched-grid" />
            <div class="sched-core">
              <span class="sched-ring r1" /><span class="sched-ring r2" /><span class="sched-ring r3" />
              <span class="sweep" />
              <div class="sched-node"><SIcon name="book" :size="24" /></div>
            </div>
            <div class="am-sched-title">司南老师 · 核心调度</div>
            <div class="am-sched-sub">正在判断本轮需要调用哪些 Agent<span class="dots"><i /><i /><i /></span></div>
            <div class="sched-scan">
              <span class="scan-label">正在扫描</span>
              <span class="scan-ic" :style="{ color: candidates[scanIdx].color, background: candidates[scanIdx].color + '1a' }"><SIcon :name="candidates[scanIdx].icon" :size="13" /></span>
              <span class="scan-name">{{ candidates[scanIdx].name }}</span>
            </div>
          </div>
          <div v-else class="am-body">
            <div class="am-group-label">协作者</div>
            <div v-for="a in collaborators" :key="a.id" class="am-row" :class="a.status">
              <span class="am-ic" :style="{ color: agentColor(a.id), background: agentColor(a.id) + '1a' }"><SIcon :name="a.icon || 'circle'" :size="16" /></span>
              <span class="am-name">{{ a.name }}</span>
              <span class="am-state">
                <span v-if="a.status === 'working'" class="spin" />
                <span v-else-if="a.status === 'pending'" class="pend" />
                <span v-else class="ok"><SIcon name="check" :size="14" /></span>
              </span>
            </div>
            <template v-if="hats.length">
              <div class="am-group-label">六帽审查</div>
              <div v-for="a in hats" :key="a.id" class="am-row" :class="a.status">
                <span class="am-ic" :style="{ color: agentColor(a.id), background: agentColor(a.id) + '1a' }"><SIcon :name="a.icon || 'circle'" :size="16" /></span>
                <span class="am-name">{{ a.name }}</span>
                <span class="am-state">
                  <span v-if="a.status === 'working'" class="spin" />
                  <span v-else-if="a.status === 'pending'" class="pend" />
                  <span v-else class="ok"><SIcon name="check" :size="14" /></span>
                </span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </transition>

    <transition name="toast">
      <div v-if="diffToast" class="diff-toast" :class="diffToast.kind">
        <SIcon :name="diffToast.kind === 'up' ? 'up' : 'down'" :size="15" />
        {{ diffToast.text }}
      </div>
    </transition>
  <!-- 悬浮翻译面板：保持 Markdown 渲染。
       两个约束同时满足：
       1) **本组件顶层只能有一个根元素**（这里是 .thread）——否则 App.vue 的
          <transition mode="out-in"> 无法解析动画元素，leave 钩子不完成，
          离开本页后新路由不挂载 → 正文空白（已发生的演示阻断）。
       2) 浮层用 <Teleport to="body"> 挂到 body：过渡类会给视图根加 transform，
          否则 position: fixed 会被该 transform 变成「相对祖先定位」而错位。
       Teleport 放在 .thread 内部，既保住单根，又保住 viewport 定位。
       scoped 样式对 Teleport 出去的内容依然生效（作用域属性随节点一起搬走）。 -->
  <Teleport to="body">
    <div v-if="tr.open" class="tr-mask" @click.self="tr.open = false">
      <div class="tr-panel">
        <div class="tr-hd">
          <b>翻译</b>
          <select v-model="tr.target" @change="doTranslate">
            <option v-for="l in LANGS" :key="l" :value="l">{{ l }}</option>
          </select>
          <span class="tr-hint">保持 Markdown 结构与术语</span>
          <button class="tr-x" @click="tr.open = false">关闭</button>
        </div>
        <div class="tr-body">
          <div v-if="tr.loading" class="tr-loading">翻译中…</div>
          <MarkdownView v-else-if="tr.text" :text="tr.text" />
          <div v-else class="tr-loading">{{ tr.error || '没有可翻译的内容' }}</div>
        </div>
      </div>
    </div>
  </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'
import SIcon from '@/components/SIcon.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { reactive } from 'vue'
import yunBg from '@/assets/deco/yun-blue.png'

const route = useRoute()
const spId = computed(() => String(route.params.sp || 'C2.2'))

/* ── 悬浮翻译 ── */
const LANGS = ['English', '한국어', '日本語', 'ไทย', 'Tiếng Việt', 'Bahasa Indonesia',
  'Español', 'Русский', 'Français', 'Deutsch', 'العربية', 'Português', 'Italiano', 'Türkçe']
const tr = reactive({ open: false, loading: false, target: 'English', text: '', src: '', error: '' })

function openTranslate(m: any) {
  tr.open = true
  tr.src = String(m?.content || '')
  tr.text = ''
  tr.error = ''
  doTranslate()
}

async function doTranslate() {
  if (!tr.src.trim()) { tr.error = '没有可翻译的内容'; return }
  tr.loading = true
  tr.error = ''
  try {
    const r = await client.post('/learn/translate', { text: tr.src, target: tr.target })
    tr.text = r.data?.text || ''
    if (!tr.text) tr.error = '翻译返回为空'
  } catch (e: any) {
    tr.error = e?.response?.data?.detail || '翻译失败，请稍后重试'
  } finally {
    tr.loading = false
  }
}

const userStore = useUserStore()
const USER = computed(() => userStore.userId)
const CIRC = 2 * Math.PI * 34

const name = ref('')
const isBridge = ref(false)
const iptEl = ref<HTMLTextAreaElement | null>(null)
const messages = ref<any[]>([])
const assets = ref<any[]>([])
const mastery = ref({ teach: 0, real: 0 })
const q = ref('')
const busy = ref(false)
const preview = ref<{ title: string; content: string } | null>(null)

const agents = ref<{ id: string; name: string; icon?: string; status: 'pending' | 'working' | 'done'; hat?: boolean }[]>([])
const agentsOn = ref(false)
const scheduling = ref(false)
let agentTimer: number | null = null
let agentHideTimer: number | null = null
const scanIdx = ref(0)
let scanTimer: number | null = null

const HAT_IDS = ['white', 'black', 'green', 'yellow', 'red', 'blue']
const AGENT_COLORS: Record<string, string> = {
  retrieval: '#2577e3', profile: '#7a5af8', teacher: '#2577e3', asset: '#12a76a',
  white: '#7a8ba3', black: '#334155', green: '#12a76a', yellow: '#e0a11e', red: '#e05b5b', blue: '#2577e3',
}
function agentIcon(id: string): string {
  return ({ retrieval: 'search', profile: 'user', teacher: 'book', asset: 'notebook',
    white: 'eye', black: 'shield', green: 'sparkle', yellow: 'star', red: 'user', blue: 'compass',
    judge: 'target', question: 'filetext', answer: 'check' } as any)[id] || 'circle'
}
function agentColor(id: string): string { return AGENT_COLORS[id] || '#2577e3' }

const collaborators = computed(() => agents.value.filter((a) => !HAT_IDS.includes(a.id)))
const hats = computed(() => agents.value.filter((a) => HAT_IDS.includes(a.id)))

const candidates = [
  { id: 'retrieval', name: '知识召回', icon: 'search', color: '#2577e3' },
  { id: 'profile', name: '画像顾问', icon: 'user', color: '#7a5af8' },
  { id: 'white', name: '白帽', icon: 'eye', color: '#7a8ba3' },
  { id: 'black', name: '黑帽', icon: 'shield', color: '#334155' },
  { id: 'green', name: '绿帽', icon: 'sparkle', color: '#12a76a' },
  { id: 'yellow', name: '黄帽', icon: 'star', color: '#e0a11e' },
  { id: 'red', name: '红帽', icon: 'user', color: '#e05b5b' },
  { id: 'blue', name: '蓝帽', icon: 'compass', color: '#2577e3' },
]

function beginAgentRun() {
  if (agentTimer) clearTimeout(agentTimer)
  if (agentHideTimer) clearTimeout(agentHideTimer)
  agents.value = []
  scheduling.value = true
  agentsOn.value = true
  scanIdx.value = 0
  if (scanTimer) clearInterval(scanTimer)
  scanTimer = window.setInterval(() => { scanIdx.value = (scanIdx.value + 1) % candidates.length }, 720)
}

function revealAgents(pipeline: { id: string; name: string; icon?: string }[]) {
  if (scanTimer) { clearInterval(scanTimer); scanTimer = null }
  if (!pipeline || !pipeline.length) { hideAgents(); return }
  scheduling.value = false
  agents.value = pipeline.map((a) => ({ id: a.id, name: a.name, icon: a.icon || agentIcon(a.id), status: 'pending', hat: HAT_IDS.includes(a.id) }))
  agentsOn.value = true
  let i = 0
  const tick = () => {
    if (i > 0) agents.value[i - 1].status = 'done'
    if (i >= agents.value.length) {
      agentHideTimer = window.setTimeout(() => { agentsOn.value = false }, 2100)
      return
    }
    agents.value[i].status = 'working'
    i++
    agentTimer = window.setTimeout(tick, 340)
  }
  tick()
}

function hideAgents() {
  if (agentTimer) clearTimeout(agentTimer)
  if (agentHideTimer) clearTimeout(agentHideTimer)
  if (scanTimer) { clearInterval(scanTimer); scanTimer = null }
  scheduling.value = false
  agentsOn.value = false
  agents.value = []
}

const rings = computed(() => [
  { name: '教学掌握度', value: mastery.value.teach, color: '#2577e3' },
  { name: '实战掌握度', value: mastery.value.real, color: '#e08a1e' },
])

const diffHistory = ref<number[]>([])
const lastTrend = ref('')
const diffToast = ref<{ kind: string; text: string } | null>(null)
let diffToastTimer: number | null = null
const currentDiff = computed(() => {
  const m = mastery.value.teach
  if (m >= 90) return 5
  if (m >= 80) return 4
  if (m >= 70) return 3
  if (m >= 60) return 2
  return 1
})
function diffNum(d: string) { const n = parseInt(String(d).replace('L', '')); return n >= 1 && n <= 5 ? n : 1 }
function yFor(l: number) { return 52 - (l - 1) * 11 }
const diffPoints = computed(() => {
  const n = diffHistory.value.length
  if (!n) return ''
  return diffHistory.value.map((v, i) => `${n === 1 ? 110 : 8 + i / (n - 1) * 204},${yFor(v)}`).join(' ')
})
/* 难度走势：用平滑曲线而不是折线 */
const diffPath = computed(() => {
  const n = diffHistory.value.length
  const pts = diffHistory.value.map((v, i) => ({ x: n === 1 ? 110 : 8 + i / (n - 1) * 204, y: yFor(v) }))
  if (!pts.length) return ''
  if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`
  let d = `M ${pts[0].x} ${pts[0].y}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`
  }
  return d
})

const lastPt = computed(() => {
  const n = diffHistory.value.length
  const v = n ? diffHistory.value[n - 1] : currentDiff.value
  return { x: n <= 1 ? 110 : 212, y: yFor(v) }
})

/* 八个动作只做一件事：把这句话填进输入框。点发送之后由服务端分流到
   讲解 / 出题 / 生成讲义 等流水线，手打同样的句子也走同一条路。 */
const QUICK = [
  { label: '讲解', icon: 'book', t: '请讲解「{n}」：先给结论，再讲要点和一个例子。' },
  { label: '做题', icon: 'filetext', t: '出一道「{n}」的题给我练。' },
  { label: '实战复盘', icon: 'target', t: '结合我在实战里的表现，帮我复盘「{n}」。' },
  { label: '问答', icon: 'chat', t: '我有个关于「{n}」的问题想问：' },
  { label: '讲义', icon: 'notebook', t: '给我生成一份「{n}」的讲义。' },
  { label: '实操指南', icon: 'clip', t: '给我生成一份「{n}」的实操指南。' },
  { label: '学习报告', icon: 'chart', t: '给我生成一份「{n}」的学习报告。' },
  { label: '错题本', icon: 'x', t: '把我「{n}」的错题整理成错题本。' },
]

function fill(a: any) {
  if (busy.value) return
  const n = name.value || spId.value
  q.value = String(a.t).replace('{n}', n)
  nextTick(() => iptEl.value?.focus())
}

/** 后端 payload 是 JSON 字符串，解析成对象；坏数据直接当没有 */
function parsePayload(raw: any) {
  if (!raw) return null
  if (typeof raw === 'object') return raw
  try { return JSON.parse(raw) } catch { return null }
}

/** 把后端消息整理成界面要的样子：
 *  - kind=quiz 的消息变成一张题卡（题目在 payload 里）
 *  - kind=quiz_result 不单独显示，按 question_id 挂回那张题卡
 *  这样每道题各占一张卡，答过的留在原位可回看。 */
function decorate(list: any[]) {
  const results: Record<string, any> = {}
  const out: any[] = []
  for (const m of list) {
    const p = parsePayload(m.payload)
    if (m.kind === 'quiz_result' && p) { results[p.question_id] = p; continue }
    if (m.kind === 'quiz' && p) {
      out.push({ ...m, kind: 'quiz', quiz: p, pick: '', result: null, open: false })
      continue
    }
    out.push({ ...m, open: false })
  }
  const cards = out.filter((m) => m.kind === 'quiz')
  cards.forEach((m, i) => {
    m.nth = i + 1
    m.result = results[m.quiz.question_id] || null
  })
  return out
}

/** 回看时把选项字母还原成选项内容 */
function answerText(m: any) {
  const r = m.result || {}
  const raw = String(r.answer_text || r.answer || '').trim()
  if (!raw) return '（未记录）'
  if (m.quiz?.type === 'choice') {
    const letter = raw.toUpperCase()[0]
    const opt = (m.quiz.options || [])[letter.charCodeAt(0) - 65]
    return opt ? `${letter}. ${opt}` : letter
  }
  return raw
}

function trendArrow(t: string) { return t === 'up' ? '↑' : t === 'down' ? '↓' : '→' }

function offset(v: number) { return CIRC * (1 - Math.max(0, Math.min(100, v)) / 100) }

async function load() {
  try {
    const s = (await client.get(`/threads/${spId.value}`, { params: { user_id: USER.value } })).data
    name.value = s.name
    isBridge.value = s.kind === 'bridge'
    messages.value = decorate(s.messages || [])
    assets.value = s.assets || []
    mastery.value = { teach: s.mastery?.teach || 0, real: s.mastery?.real || 0 }
    diffHistory.value = [currentDiff.value]
  } catch { messages.value = [] }
}
onMounted(load)
watch(spId, () => { messages.value = []; assets.value = []; load() })

async function send() {
  const text = q.value.trim()
  if (!text || busy.value) return
  messages.value.push({ role: 'user', content: text })
  q.value = ''
  busy.value = true
  beginAgentRun()
  try {
    const r = (await client.post(`/threads/${spId.value}/messages`, { user_id: USER.value, text })).data
    messages.value.push({ role: 'ai', content: r.content, evidence: r.evidence || [], open: false })
    revealAgents(r.pipeline || [])
    if (r.kind === 'quiz' && r.quiz) {          // 出题：这张题卡插在它自己那一轮对话后面
      const nth = messages.value.filter((m: any) => m.kind === 'quiz').length
      messages.value[messages.value.length - 1] = {
        role: 'ai', content: r.content, evidence: r.evidence || [], open: false,
        kind: 'quiz', quiz: r.quiz, pick: '', result: null, nth: nth,
      }
    }
    if (r.kind === 'asset' && r.asset) {        // 生成资源：同一条回复进聊天与个性资源栏
      assets.value = [r.asset, ...assets.value.filter((x: any) => x.asset_id !== r.asset.asset_id)]
    }
  } catch (e: any) {
    messages.value.push({ role: 'ai', content: '（老师暂不可用：' + (e?.response?.data?.detail || e.message) + '）' })
    hideAgents()
  } finally { busy.value = false }
}

async function submitQuiz(m: any) {
  if (!m?.quiz || !m.pick || m.result || busy.value) return
  busy.value = true
  beginAgentRun()
  try {
    const r = (await client.post(`/threads/${spId.value}/quiz/answer`,
      { user_id: USER.value, question: m.quiz, answer: m.pick })).data
    // 判分结果留在这一张卡上：刷新后从后端 quiz_result 消息还原
    m.result = { ...r, answer: m.pick, question_id: m.quiz.question_id }
    mastery.value.teach = r.teach
    diffHistory.value.push(diffNum(r.difficulty))
    lastTrend.value = r.trend
    if (r.trend === 'up' || r.trend === 'down') {
      diffToast.value = {
        kind: r.trend,
        text: r.trend === 'up' ? `题目难度升级：${r.prev_difficulty} → ${r.difficulty}` : `题目难度降级：${r.prev_difficulty} → ${r.difficulty}`,
      }
      if (diffToastTimer) clearTimeout(diffToastTimer)
      diffToastTimer = window.setTimeout(() => { diffToast.value = null }, 2600)
    }
    revealAgents(r.pipeline || [])
  } catch (e: any) { messages.value.push({ role: 'ai', content: '（判分失败：' + (e?.response?.data?.detail || e.message) + '）' }); hideAgents() }
  finally { busy.value = false }
}

function openAsset(a: any) { preview.value = { title: a.title, content: a.content } }
// R05：学员界面不提供 Markdown 导出；预览/复制等现有能力保留，内部渲染流程不变。
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.thread { max-width: 1500px; }
.cols { display: grid; grid-template-columns: 1fr 320px; gap: 14px; align-items: start; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.col-title { display: flex; align-items: center; gap: 6px; font-size: 15px; font-weight: 700; padding: 13px 14px 8px; }

.mid { display: flex; flex-direction: column; height: 720px; }
.chat-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid $color-border; }
.ch-left { display: flex; align-items: center; gap: 10px; }
.spid { font-family: ui-monospace, monospace; font-size: 15px; color: $color-primary; background: $color-primary-soft; padding: 3px 9px; border-radius: 5px; }
.spname { font-size: 19px; font-weight: 800; }
.spkind { font-size: 13px; color: #0ea5b7; background: #e9f8fa; border-radius: 999px; padding: 2px 10px; }
.ch-right { display: flex; align-items: center; gap: 8px; }
.quick { display: flex; flex-wrap: wrap; gap: 7px; }
.qbtn { display: inline-flex; align-items: center; gap: 5px; border: 1px solid $color-border; background: #fff;
  border-radius: 999px; padding: 5px 13px; font-size: 15px; color: $color-primary; cursor: pointer; transition: all .16s ease; }
.qbtn:hover:not(:disabled) { background: $color-primary-softer; border-color: $color-primary; }
.qbtn:disabled { opacity: .5; cursor: not-allowed; }
.msgs { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 18px; }
.msg { display: flex; }
.msg.me { justify-content: flex-end; }
.bubble-wrap { max-width: 86%; }
.who { font-size: 15px; color: $color-text-muted; margin-bottom: 5px; }
.msg.me .who { text-align: right; }
.bubble { padding: 12px 16px; border-radius: 10px; background: $color-primary-soft; font-size: 15.5px; }
.msg.me .bubble { background: $color-primary; color: #fff; line-height: 1.8; }
.trace { margin-top: 7px; }
.trace-toggle { display: inline-flex; align-items: center; gap: 4px; border: none; background: transparent; color: $color-primary; font-size: 15.5px; cursor: pointer; padding: 0; }
.trace-body { margin-top: 8px; border-left: 2px solid $color-primary-soft; padding: 8px 0 8px 13px; }
.trace-hd { font-size: 15px; color: $color-text-muted; margin-bottom: 6px; }
.trace-item { font-size: 15.5px; color: $color-text-secondary; line-height: 2; display: flex; gap: 7px; align-items: center; }
.c-n { width: 16px; height: 16px; border-radius: 4px; background: $color-primary-soft; color: $color-primary; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.empty { text-align: center; color: $color-text-muted; font-size: 15px; padding: 40px; }
.chat-input { display: flex; flex-direction: column; gap: 9px; padding: 12px 16px; border-top: 1px solid $color-border; }
.composer { display: flex; gap: 10px; align-items: flex-end; }
.ipt { flex: 1; border: 1px solid $color-border; border-radius: 8px; padding: 9px 12px; font-size: 15.5px; outline: none; resize: none; font-family: inherit; line-height: 1.7; }
.ipt:focus { border-color: $color-primary; }
.send { height: 38px; }

.quiz { padding: 16px 18px; background: $color-primary-softer; border-color: $color-primary; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.q-nth { font-size: 13.5px; color: $color-text-muted; }
.q-state { margin-left: auto; font-size: 13.5px; border-radius: 999px; padding: 1px 10px;
  color: #c77700; background: #fff4e3; }
.q-state.ok { color: #12a76a; background: #e8f7ee; }
.q-state.bad { color: #e04b4b; background: #fdeceb; }
.q-ans { display: flex; align-items: baseline; gap: 10px; background: #fff; border: 1px solid $color-border;
  border-radius: 8px; padding: 9px 12px; margin-bottom: 4px; }
.qa-lbl { flex: none; font-size: 13.5px; color: $color-text-muted; }
.qa-val { font-size: 15.5px; line-height: 1.7; }
.q-tag { font-size: 15px; background: $color-primary-soft; color: $color-primary; padding: 2px 9px; border-radius: 999px; }
.q-stem { font-size: 16px; font-weight: 600; line-height: 1.8; margin-bottom: 12px; }
.q-opts { display: flex; flex-direction: column; gap: 8px; }
.q-opt { display: flex; align-items: center; gap: 9px; font-size: 15px; padding: 8px 12px; border: 1px solid $color-border; border-radius: 8px; background: #fff; cursor: pointer; }
.q-opt.on { border-color: $color-primary; background: $color-primary-soft; }
.q-key { width: 20px; height: 20px; border-radius: 50%; background: #eef1f5; display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700; }
.q-short { width: 100%; border: 1px solid $color-border; border-radius: 8px; padding: 10px 12px; font-size: 15px; font-family: inherit; }
.q-foot { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.q-result { font-size: 15.5px; color: #e04b4b; }
.q-result.ok { color: #12a76a; }
.q-explain { margin-top: 10px; font-size: 15.5px; color: $color-text-secondary; background: #fff; border-radius: 8px; padding: 10px 12px; line-height: 1.8; }

.right { display: flex; flex-direction: column; gap: 12px; }
.panel { padding-bottom: 14px; }
.rings { display: flex; gap: 8px; justify-content: space-around; padding: 4px 8px 0; }
.ring { position: relative; text-align: center; }
.ring-svg { width: 88px; height: 88px; }
.ring-val { position: absolute; top: 30px; left: 0; right: 0; font-size: 20px; font-weight: 800; }
.ring-val i { font-size: 14.5px; font-style: normal; }
.ring-name { margin-top: 4px; font-size: 15px; color: $color-text-secondary; display: flex; align-items: center; justify-content: center; gap: 4px; }
.swatch { width: 7px; height: 7px; border-radius: 2px; display: inline-block; }
.assets { display: flex; flex-direction: column; gap: 6px; padding: 0 10px; }
.asset { display: flex; align-items: center; gap: 9px; padding: 7px 8px; border-radius: 7px; font-size: 15.5px; }
.a-ic { width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.a-name { flex: 1; }
.a-gen { border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 2px 11px; font-size: 15px; color: $color-primary; cursor: pointer; }
.a-gen:hover { background: $color-primary-soft; }
.a-list { padding: 8px 14px 0; display: flex; flex-direction: column; gap: 5px; }
.a-item { display: flex; align-items: center; gap: 6px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.a-item:hover { text-decoration: underline; }
.mini { padding: 5px 12px; font-size: 15.5px; }

.mask { position: fixed; inset: 0; background: rgba(16,26,42,0.45); display: flex; align-items: center; justify-content: center; z-index: 60; }
.modal { width: 780px; max-width: 92vw; max-height: 84vh; display: flex; flex-direction: column; }
.m-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid $color-border; }
.m-title { font-size: 16.5px; font-weight: 700; }
.m-actions { display: flex; gap: 8px; }
.m-body { padding: 18px 22px; overflow-y: auto; }

.agent-overlay { position: fixed; inset: 0; z-index: 80; display: flex; align-items: center; justify-content: center;
  background: rgba(245, 246, 248, 0.52); backdrop-filter: blur(9px) saturate(1.1); }
.agent-modal { width: 580px; max-width: 92vw; max-height: 82vh; overflow: hidden;
  background: rgba(255, 255, 255, 0.82); backdrop-filter: blur(22px) saturate(1.2);
  border: 1px solid rgba(207, 224, 247, 0.8); border-radius: 20px;
  box-shadow: 0 24px 80px rgba(26, 106, 224, 0.24), inset 0 0 0 1px rgba(255, 255, 255, 0.6); }
.am-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 22px; color: #fff;
  background: linear-gradient(135deg, rgba(42, 125, 235, 0.94), rgba(90, 159, 242, 0.94)); backdrop-filter: blur(10px); }
.am-title { display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 800; }
.am-live { width: 9px; height: 9px; border-radius: 50%; background: #fff; box-shadow: 0 0 10px #fff; animation: amPulse 1.4s ease-in-out infinite; }
.am-live.big { width: 14px; height: 14px; }
.am-sub { font-size: 15.5px; color: rgba(255, 255, 255, 0.86); }
.am-body { padding: 8px 18px 18px; max-height: 62vh; overflow-y: auto; }
.am-group-label { font-size: 14.5px; letter-spacing: 1.5px; color: #9aa8bb; font-weight: 700; padding: 14px 6px 7px; }
.am-row { display: flex; align-items: center; gap: 13px; padding: 11px 12px; border-radius: 10px; transition: background .2s ease; }
.am-row.working { background: #eaf3fe; }
.am-ic { width: 32px; height: 32px; border-radius: 9px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.am-name { flex: 1; font-size: 16px; font-weight: 600; color: #16223a; }
.am-state { width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; }
.spin { width: 17px; height: 17px; border-radius: 50%; border: 2.5px solid #cfe0f7; border-top-color: #2577e3; animation: amSpin .7s linear infinite; }
.pend { width: 8px; height: 8px; border-radius: 50%; background: #d4dae0; }
.ok { color: #12a76a; animation: amPop .28s cubic-bezier(.34,1.56,.64,1); }
.am-sched { position: relative; padding: 26px 24px 30px; display: flex; flex-direction: column; align-items: center; text-align: center; overflow: hidden; }
.sched-bg { position: absolute; inset: -10px; width: calc(100% + 20px); height: calc(100% + 20px); object-fit: cover;
  opacity: 0.07; pointer-events: none; mix-blend-mode: multiply; }
.sched-grid { position: absolute; inset: 0; opacity: .5;
  background-image: linear-gradient(rgba(37, 119, 227, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(37, 119, 227, 0.05) 1px, transparent 1px);
  background-size: 28px 28px;
  -webkit-mask-image: radial-gradient(circle at center, #000 0%, transparent 74%);
  mask-image: radial-gradient(circle at center, #000 0%, transparent 74%); }
.sched-core { position: relative; width: 132px; height: 132px; margin: 4px auto 0; }
.sched-ring { position: absolute; inset: 0; border-radius: 50%; border: 1.5px solid rgba(37, 119, 227, 0.28); animation: ringPulse 2.6s ease-out infinite; }
.sched-ring.r2 { animation-delay: .85s; }
.sched-ring.r3 { animation-delay: 1.7s; }
@keyframes ringPulse { 0% { transform: scale(.5); opacity: .95; } 100% { transform: scale(1.18); opacity: 0; } }
.sweep { position: absolute; inset: 7px; border-radius: 50%;
  background: conic-gradient(from 0deg, rgba(37, 119, 227, 0.32), rgba(37, 119, 227, 0.02) 70%);
  -webkit-mask: radial-gradient(circle, transparent 56%, #000 57%);
  mask: radial-gradient(circle, transparent 56%, #000 57%);
  animation: sweepSpin 2.4s linear infinite; }
@keyframes sweepSpin { to { transform: rotate(360deg); } }
.sched-node { position: absolute; inset: 31px; border-radius: 50%; color: #fff;
  background: linear-gradient(135deg, #2577e3, #4a8ff0); display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 30px rgba(37, 119, 227, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.35); }
.am-sched-title { margin-top: 16px; font-size: 17px; font-weight: 800; color: #16223a; }
.am-sched-sub { margin-top: 7px; font-size: 15px; color: #6b7a90; display: flex; align-items: center; }
.dots { display: inline-flex; gap: 4px; margin-left: 7px; }
.dots i { width: 5px; height: 5px; border-radius: 50%; background: #2577e3; animation: dotBounce 1.2s ease-in-out infinite; }
.dots i:nth-child(2) { animation-delay: .2s; }
.dots i:nth-child(3) { animation-delay: .4s; }
@keyframes dotBounce { 0%, 100% { transform: translateY(0); opacity: .35; } 50% { transform: translateY(-4px); opacity: 1; } }
.sched-scan { position: relative; overflow: hidden; margin-top: 22px; display: flex; align-items: center; gap: 9px; padding: 9px 16px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.82); border: 1px solid #e3e9f1; font-size: 15px; color: #6b7a90; box-shadow: 0 4px 16px rgba(26,106,224,.06); }
.sched-scan::after { content: ''; position: absolute; top: 0; bottom: 0; left: -40%; width: 36%;
  background: linear-gradient(90deg, transparent, rgba(37, 119, 227, 0.12), transparent);
  animation: scanShimmer 1.7s linear infinite; }
@keyframes scanShimmer { to { left: 110%; } }
.scan-label { font-size: 15.5px; color: #9aa8bb; }
.scan-ic { width: 24px; height: 24px; border-radius: 7px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all .3s ease; }
.scan-name { font-weight: 700; color: #16223a; min-width: 64px; text-align: left; }
@keyframes amSpin { to { transform: rotate(360deg); } }
@keyframes amPulse { 0%,100% { opacity: .5; transform: scale(.8); } 50% { opacity: 1; transform: scale(1.15); } }
@keyframes amPop { from { transform: scale(.4); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.adock-enter-active, .adock-leave-active { transition: opacity .24s ease; }
.adock-enter-from, .adock-leave-to { opacity: 0; }
.diff { padding: 6px 14px 14px; }
.diff-meter { display: flex; gap: 5px; }
.diff-seg { flex: 1; text-align: center; font-size: 14.5px; color: #b6c2d2; padding: 4px 0; border-radius: 5px; background: #eef1f5; }
.diff-seg.on { color: #fff; background: #2577e3; }
.diff-seg.cur { box-shadow: 0 0 0 2px rgba(37,119,227,.25); }
.diff-chart { width: 100%; height: 56px; margin-top: 8px; }
.diff-grid { stroke: #eef1f5; stroke-width: 1; }
.diff-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 4px; }
.diff-cur { font-size: 15px; color: #6b7a90; }
.diff-cur b { font-size: 17px; color: #2577e3; font-weight: 800; }
.diff-trend { font-size: 15.5px; font-weight: 700; }
.diff-trend.up { color: #12a76a; }
.diff-trend.down { color: #e04b4b; }

.a-empty { padding: 4px 14px 16px; font-size: 15.5px; color: $color-text-muted; }
.ai-acts { margin-top: 6px; }
.tr-mask { position: fixed; inset: 0; background: rgba(15, 30, 50, .28); z-index: 120;
  display: flex; align-items: center; justify-content: center; }
.tr-panel { width: min(860px, 84vw); max-height: 78vh; display: flex; flex-direction: column;
  background: #fff; border-radius: 16px; box-shadow: 0 24px 60px rgba(15, 30, 50, .24); overflow: hidden; }
.tr-hd { display: flex; align-items: center; gap: 12px; padding: 14px 18px; border-bottom: 1px solid #eef2f7; }
.tr-hd b { font-size: 15px; }
.tr-hd select { border: 1px solid #d8e2f0; border-radius: 8px; padding: 5px 10px; font-size: 13px; background: #fff; }
.tr-hint { font-size: 12px; color: $color-text-muted; }
.tr-x { margin-left: auto; border: 1px solid #d8e2f0; background: #fff; border-radius: 8px;
  padding: 5px 12px; font-size: 13px; cursor: pointer; color: $color-text-secondary; }
.tr-body { padding: 18px 22px; overflow: auto; }
.tr-loading { padding: 24px 0; text-align: center; color: $color-text-secondary; font-size: 14px; }

.diff-toast { position: fixed; top: 22px; left: 50%; transform: translateX(-50%); z-index: 95;
  display: flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.96); backdrop-filter: blur(10px); border: 1px solid #e3e9f1;
  box-shadow: 0 12px 40px rgba(26, 106, 224, 0.18); font-size: 15px; font-weight: 700; }
.diff-toast.up { color: #12a76a; border-color: rgba(18, 167, 106, 0.3); }
.diff-toast.down { color: #e08a1e; border-color: rgba(224, 138, 30, 0.3); }
.toast-enter-active, .toast-leave-active { transition: opacity .25s ease, transform .25s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, -14px); }
</style>