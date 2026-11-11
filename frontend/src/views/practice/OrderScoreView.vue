<template>
  <div class="oscore">
    <div class="card head">
      <div class="h-l">
        <button class="back" @click="router.push(`/practice/orders/${orderId}`)"><SIcon name="back" :size="13" /> 返回订单</button>
        <span class="oid">{{ orderId }}</span>
        <span class="ocust">{{ summary?.customer }} · {{ summary?.destination }}</span>
        <span v-if="summary?.source_market" class="otag inbound">{{ summary.source_market }} · 入境接待 · {{ summary?.language }}</span>
      </div>
      <div class="h-r">
        <div class="avg-wrap">
          <template v-if="summary?.average !== null && summary?.average !== undefined">
            <span class="avg">{{ summary.average }}</span>
            <span class="avg-u">平均分<br />已评 {{ summary.evaluated }} · 本单考 {{ plannedTotal }}</span>
          </template>
          <template v-else>
            <span class="avg none">未评分</span>
            <span class="avg-u">本单暂无评分<br />本单考 {{ plannedTotal }} 个点 · 证据 {{ evidence.length }} 条</span>
          </template>
        </div>
        <button class="run" :disabled="running" @click="runScore">
          <SIcon :name="running ? 'refresh' : 'sparkle'" :size="13" />
          {{ running ? '评分中…' : summary?.average == null ? '生成本单评分' : '重新评分' }}
        </button>
      </div>
    </div>

    <div class="card stage">
      <span class="st-label">当前订单状态</span>
      <span class="st-name">{{ summary?.stage_name || '—' }}</span>
      <span class="st-gates">完成条件 {{ gateDone }}/{{ gateTotal }}</span>
      <span class="st-ev">可评分证据</span>
      <span v-for="e in evidence" :key="e.ref" class="ev-chip">{{ e.kind }} · {{ e.chars }}字</span>
      <span v-if="!evidence.length" class="st-ev muted">暂无（先拨打电话或投递交付物）</span>
    </div>

    <div v-if="coverage" class="card cover" :class="{ pass: coverage.passed }">
      <div class="cv-left">
        <span class="cv-title">覆盖校验</span>
        <span class="cv-num">{{ coverage.covered }}<i>/{{ coverage.targets }}</i></span>
        <span class="cv-pct">覆盖度 {{ Math.round(coverage.ratio * 100) }}%</span>
      </div>
      <div class="cv-bar"><i :style="{ width: Math.round(coverage.ratio * 100) + '%' }" /></div>
      <div class="cv-right">
        <span class="cv-state">覆盖率供复盘参考，不影响画像展示</span>
        <button class="lnk" @click="showGaps = !showGaps">{{ showGaps ? '收起未覆盖项' : '查看未覆盖项' }}</button>
      </div>
      <div v-if="staleCount" class="cv-stale">
        有 {{ staleCount }} 个点本单已经考到、但还没评出分（评分要手动触发）。
        点右上角「{{ summary?.average == null ? '生成本单评分' : '重新评分' }}」补评一次即可。
      </div>
      <div v-if="showGaps" class="cv-gaps">
        <div v-for="g in uncovered" :key="g.skill_point_id" class="gap">
          <span class="gap-id">{{ g.skill_point_id }}</span>
          <span class="gap-name">{{ g.name }}</span>
          <span class="gap-kind">{{ g.checkpoint }} 型</span>
          <span class="gap-reason">{{ g.reason }}</span>
          <button v-if="canRespond(g)" class="tc-btn ghost p-btn" @click="fixTo(g)">去回应</button>
          <button v-else class="tc-btn ghost p-btn" @click="review(g.skill_point_id)">去练习</button>
        </div>
        <div v-if="!uncovered.length" class="gap none">全部目标技能点均已覆盖</div>
      </div>
    </div>

    <!-- 加载失败必须可见：以前整页在 catch 里被清空，学员看到的是空白而不是「加载失败」 -->
    <div v-if="loadErrors.length" class="card notice bad">
      数据没有全部加载成功：{{ loadErrors.map((e) => e.section).join('、') }} 失败（{{ loadErrors[0].detail }}）。
      其余内容按已成功加载的部分显示，请刷新或稍后重试。
    </div>

    <div v-if="notice" class="card notice" :class="notice.kind">{{ notice.text }}</div>

    <div v-if="reviewsFailed" class="card notice warn">
      待复核列表没有加载成功：下面看不到待复核项**不代表没有待复核**，请刷新重试。
    </div>

    <div v-if="reviews.length" class="card reviews">
      <div class="rv-head">
        <span class="rv-title">待人工复核</span>
        <span class="rv-sub">低置信度或贴近档位边界的判定不写入画像</span>
      </div>
      <div v-for="r in reviews" :key="r.skill_point_id" class="rv-row">
        <span class="rv-id">{{ r.skill_point_id }}</span>
        <span class="rv-score">{{ r.score }}<i>{{ r.level }}</i></span>
        <span class="rv-conf">置信 {{ r.confidence }}</span>
        <span class="rv-why">{{ r.review_reason }}</span>
        <span class="rv-ops">
          <button class="tc-btn ghost p-btn" @click="resolve(r, 'accept')">采纳</button>
          <button class="tc-btn ghost p-btn" @click="resolve(r, 'reject')">驳回</button>
        </span>
      </div>
    </div>

    <div class="dims">
      <div v-for="d in dimsView" :key="d.id" class="card dim">
        <div class="d-head" @click="openId = openId === d.id ? '' : d.id">
          <span class="d-dot" :style="{ background: color(d.id) }" />
          <span class="d-id">{{ d.id }}</span>
          <span class="d-name">{{ d.name }}</span>
          <span class="d-cnt">已评 {{ d.evaluated }} · 本单考 {{ d.planned }} / 共 {{ d.total }}</span>
          <span class="d-score" :style="{ color: d.score == null ? '#a9b4c2' : color(d.id) }">
            {{ d.score == null ? '未评估' : d.score }}
          </span>
          <SIcon class="d-arrow" :class="{ on: openId === d.id }" name="right" :size="14" />
        </div>
        <transition name="fold">
          <div v-if="openId === d.id" class="d-body">
            <div v-for="p in d.points" :key="p.id" class="p-row" :class="{ dimmed: p.state === 'notplanned' }">
              <span class="p-id">{{ p.id }}</span>
              <span class="p-name">{{ p.name }}<i v-if="p.hint" class="p-hint">{{ p.hint }}</i></span>
              <span v-if="p.status === '待复核'" class="p-lv pending">待复核</span>
              <span v-else-if="p.evaluated" class="p-lv" :class="p.level">{{ p.level }}</span>
              <span v-else class="p-lv" :class="p.state">{{ p.stateText }}</span>
              <span class="p-score">{{ p.evaluated ? p.score : '—' }}</span>
              <button v-if="p.evaluated" class="tc-btn ghost p-btn" @click.stop="toggleEvidence(p.id)">依据</button>
              <button class="tc-btn ghost p-btn"
                @click.stop="p.evaluated ? review(p.id) : (p.state === 'missed' ? fixTo(p) : review(p.id))">
                {{ p.evaluated ? '复盘' : (p.state === 'missed' ? fixLabel(p) : '去练习') }}
              </button>
            </div>
            <div v-if="openEvidence" class="ev-box">
              <template v-for="p in d.points" :key="'ev' + p.id">
                <div v-if="openEvidence === p.id && p.evaluated" class="ev-detail">
                  <div class="ev-comment">{{ p.comment }}</div>
                  <div v-for="(e, i) in p.evidence" :key="i" class="ev-quote">
                    <span class="ev-kind">{{ e.kind || 'message' }}</span>「{{ e.quote }}」
                  </div>
                </div>
              </template>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <transition name="sm-fade">
      <div v-if="resultOpen" class="sm-overlay" @click.self="closeResult">
        <div class="sm-dialog" role="dialog" aria-modal="true" aria-labelledby="sm-title">
          <div class="sm-head">
            <div>
              <span class="sm-kicker">本单复盘 · 评分完成</span>
              <h2 id="sm-title">评分结果与下一单难度</h2>
              <p>{{ summary?.customer }} · {{ summary?.destination }} · {{ orderId }}</p>
            </div>
            <button type="button" class="sm-x" aria-label="关闭" @click="closeResult">×</button>
          </div>

          <div class="sm-stats">
            <div><b>{{ result?.average ?? '—' }}</b><span>本单平均分</span></div>
            <div><b>{{ result?.scored ?? 0 }}</b><span>评出技能点</span></div>
            <div><b>{{ result?.profile_impact?.written ?? result?.written ?? 0 }}</b><span>写回画像</span></div>
            <div><b>{{ result?.escalated?.length ?? 0 }}</b><span>待复核</span></div>
          </div>

          <section v-if="result?.profile_impact" class="sm-block">
            <div class="sm-block-head">
              <h3>对画像的影响</h3>
              <span v-if="result.profile_impact.average_after != null">
                已写回点均分 {{ result.profile_impact.average_before ?? '—' }} → {{ result.profile_impact.average_after }}
              </span>
            </div>
            <div v-if="result.profile_auto_updated" class="sm-ok">画像已自动更新并保存快照</div>
            <div v-else class="sm-warn">本次没有正式写回画像；待复核项采纳后才会改变能力值</div>
            <div v-if="result.profile_impact.items?.length" class="sm-impact-list">
              <div v-for="it in result.profile_impact.items" :key="it.skill_point_id" class="sm-impact-row">
                <span class="sm-id">{{ it.skill_point_id }}</span>
                <span class="sm-name">{{ it.name }}<i>{{ it.before_level }} → {{ it.after_level }}</i></span>
                <span class="sm-score">{{ it.score ?? '—' }}<i>{{ it.level || '' }}</i></span>
                <span class="sm-ba">{{ it.before ?? '—' }} → <b>{{ it.after ?? '—' }}</b></span>
                <span class="sm-delta" :class="{ up: (it.delta || 0) > 0, down: (it.delta || 0) < 0 }">{{ deltaText(it) }}</span>
                <span class="sm-status" :class="{ ok: it.written }">{{ it.written ? '已写回' : '待复核' }}</span>
              </div>
            </div>
          </section>

          <section v-if="result?.next_order" class="sm-block next">
            <div class="sm-block-head">
              <h3>下一单难度</h3>
              <span>评分写回后自动重算</span>
            </div>
            <div class="sm-diff">
              <span class="sm-current">{{ result.current_order?.difficulty || '本单' }}</span>
              <span class="sm-arrow">→</span>
              <span class="sm-next">{{ result.next_order.label }}</span>
            </div>
            <p v-if="result.next_order.branch === '补救'" class="sm-explain">
              下一单的 3 个主考点里仍有低于 60 分的项，系统先走补救分支；本单已经写回的高分不会回退。
            </p>
            <div class="sm-targets">
              <span v-for="(id, i) in result.next_order.target_skill_points" :key="id" class="sm-target">
                {{ id }} · {{ result.next_order.target_names?.[i] || '' }}
              </span>
            </div>
            <div class="sm-knobs">
              <div v-for="(v, k) in result.next_order.knobs" :key="k" class="sm-knob">
                <span>{{ result.next_order.knob_labels?.[k] || k }}</span>
                <i><b :style="{ width: `${Math.max(0, Math.min(4, Number(v))) * 25}%` }" /></i>
                <em>{{ result.next_order.knob_words?.[k] || v }}</em>
              </div>
            </div>
            <p class="sm-rationale">{{ result.next_order.rationale }}</p>
            <div class="sm-plan">
              <span>首呼 {{ result.next_order.plan?.first_call_limit_min ?? '—' }} 分钟</span>
              <span v-if="result.next_order.carried_over?.length">补考 {{ result.next_order.carried_over.join('、') }}</span>
            </div>
            <p v-if="result.next_order_error" class="sm-warn">{{ result.next_order_error }}</p>
          </section>

          <div class="sm-actions">
            <button type="button" class="tc-btn ghost" @click="closeResult">留在本页</button>
            <button type="button" class="tc-btn ghost" @click="goProfile">查看画像</button>
            <button type="button" class="tc-btn" @click="goMessages">去生成下一单</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const summary = ref<any>(null)
const gates = ref<any>({ done: 0, total: 0 })
const evidence = ref<any[]>([])
const coverage = ref<any>(null)
const reviews = ref<any[]>([])
const dims = ref<any[]>([])
const openId = ref('C1')
const openEvidence = ref('')
const showGaps = ref(false)
const running = ref(false)
const notice = ref<{ kind: string; text: string } | null>(null)
const resultOpen = ref(false)
const result = ref<any>(null)
/** 加载失败必须可见：不允许某一项请求失败就把整页静默清空（历史缺陷）。 */
const loadErrors = ref<{ key: string; section: string; detail: string }[]>([])
const reviewsFailed = computed(() => loadErrors.value.some((e) => e.key === 'reviews'))

const COLORS: Record<string, string> = {
  C1: '#2577e3', C2: '#12a76a', C3: '#7a5af8', C4: '#e08a1e',
  C5: '#e0567a', C6: '#0ea5b7', C7: '#64748b', C8: '#8b5cf6',
}
function color(id: string) { return COLORS[id] || '#2577e3' }

const gateDone = computed(() => gates.value.done || 0)
const gateTotal = computed(() => gates.value.total || 0)
const uncovered = computed<any[]>(() => (coverage.value?.items || []).filter((i: any) => !i.covered))
const plannedTotal = computed(() => coverage.value?.targets ?? 0)
/** 已经考到、却还没有分的点：多半是评分跑在那件事之前，重跑一次就能补上 */
const staleCount = computed(() => dimsView.value.reduce(
  (n: number, d: any) => n + d.points.filter((p: any) => p.state === 'planned').length, 0))

/** 本单目标清单：skill_point_id -> 覆盖情况（含未覆盖原因） */
const planMap = computed<Record<string, any>>(() => {
  const m: Record<string, any> = {}
  for (const i of coverage.value?.items || []) m[i.skill_point_id] = i
  return m
})

/** 每个技能点在本单里的实际状态：
 *  scored    已评估
 *  planned   已覆盖但没评出（评分 Agent 没给出可引用证据的判定）
 *  missed    本单考了但没覆盖（没产出交付物 / 事件注入了但没在群里回应）
 *  notplanned 本单没抽到，本轮不评 */
const dimsView = computed<any[]>(() => (dims.value || []).map((d: any) => {
  const points = (d.points || []).map((p: any) => {
    const plan = planMap.value[p.id]
    let state = 'scored', stateText = p.level || '已评', hint = ''
    if (!p.evaluated) {
      const counted = plan ? plan.counted !== false : false
      if (!plan) { state = 'notplanned'; stateText = '本单未考'; hint = '本单没抽到这个点' }
      else if (!counted) { state = 'notplanned'; stateText = '本单未考'; hint = '本单没考到（不计入覆盖率）' }
      else if (!plan.covered) { state = 'missed'; stateText = '未覆盖'; hint = plan.reason || '' }
      else { state = 'planned'; stateText = '未评出'; hint = '已覆盖，但评分没给出可引用证据的判定' }
    }
    return { ...p, plan, state, stateText, hint,
             checkpoint: plan?.checkpoint || '' }
  })
  return { ...d, points, planned: points.filter((p: any) => p.plan).length }
}))

async function load() {
  // 只请求**学员可用**的端点。绝不请求 /calibration：那是平台调试面（管理员专属），
  // 学员账号会拿到 404；历史上它放在同一个 Promise.all 里，导致 404 让整页数据全部落空。
  const reqs = [
    { key: 'scores', section: '评分明细', url: `/practice/orders/${orderId.value}/scores` },
    { key: 'gates', section: '阶段通关', url: `/practice/orders/${orderId.value}/gates` },
    { key: 'evidence', section: '证据链', url: `/practice/orders/${orderId.value}/evidence` },
    { key: 'coverage', section: '覆盖度', url: `/practice/orders/${orderId.value}/coverage` },
    { key: 'reviews', section: '待复核', url: `/practice/orders/${orderId.value}/reviews` },
  ]
  // 各项**独立**结算：一项失败不影响其余各项，且失败必须可见。
  const results = await Promise.allSettled(reqs.map((r) => client.get(r.url)))
  const data: Record<string, any> = {}
  const errors: { key: string; section: string; detail: string }[] = []
  results.forEach((res, i) => {
    const req = reqs[i]
    if (res.status === 'fulfilled') { data[req.key] = res.value.data; return }
    const resp = (res.reason as any)?.response
    const detail = resp?.data?.detail || (res.reason as any)?.message || '未知错误'
    errors.push({ key: req.key, section: req.section, detail: resp?.status ? `HTTP ${resp.status} · ${detail}` : detail })
  })
  loadErrors.value = errors

  if ('gates' in data) gates.value = data.gates
  if ('evidence' in data) evidence.value = data.evidence || []
  if ('coverage' in data) coverage.value = data.coverage
  if ('reviews' in data) reviews.value = data.reviews || []
  if ('scores' in data) {
    summary.value = data.scores
    const dimsRaw = data.scores.dimensions || []
    // 待复核的点也显示出来
    for (const d of dimsRaw) {
      for (const p of d.points || []) {
        const rv = (reviews.value || []).find((x: any) => x.skill_point_id === p.id)
        if (rv) { p.pending = true; p.score = rv.score; p.level = rv.level }
      }
    }
    dims.value = dimsRaw
  }
}

function openResult(r: any) {
  result.value = r
  resultOpen.value = true
}

function closeResult() {
  resultOpen.value = false
}

function deltaText(it: any) {
  if (it.delta == null) return '—'
  return it.delta > 0 ? `+${it.delta}` : String(it.delta)
}

function goProfile() {
  closeResult()
  router.push('/profile')
}

function goMessages() {
  closeResult()
  router.push('/practice/messages')
}

async function runScore() {
  running.value = true
  notice.value = { kind: 'info', text: '评分 Agent 正在对照 Rubric 逐点判定，每条判定都要引用证据，请稍候…' }
  try {
    const r = (await client.post(`/practice/orders/${orderId.value}/score`)).data
    openResult(r)
    const bits = [`本单评出 ${r.scored} 个技能点（平均 ${r.average ?? '—'}）`]
    if (r.dropped?.length) bits.push(`${r.dropped.length} 个因拿不到证据未给分`)
    if (r.escalated?.length) bits.push(`${r.escalated.length} 个转人工复核`)
    if (r.written) bits.push(`已写回画像 ${r.written} 项`)
    if (r.profile_auto_updated) bits.push('画像已自动更新')
    if (r.deferred) bits.push('本次评分待校准，尚未确认的维度沿用初始画像')
    if (r.profile_refresh_error) bits.push(`画像自动更新未完成：${r.profile_refresh_error}`)
    notice.value = { kind: r.deferred || r.escalated?.length || r.profile_refresh_error ? 'warn' : 'ok', text: bits.join('；') + '。' }
    await load()
  } catch (e: any) {
    notice.value = { kind: 'bad', text: e?.response?.data?.detail || '评分失败，请稍后重试' }
  } finally {
    running.value = false
  }
}

async function resolve(r: any, decision: string) {
  try {
    await client.post(`/practice/orders/${orderId.value}/reviews/${r.skill_point_id}`, { decision })
    await load()
  } catch (e: any) {
    notice.value = { kind: 'bad', text: e?.response?.data?.detail || '操作失败' }
  }
}

function toggleEvidence(id: string) { openEvidence.value = openEvidence.value === id ? '' : id }
function review(id: string) { router.push(`/learn/thread/${id}`) }

/** 未覆盖的点按考法给对入口：
 *  事件型（B）= 去聊天界面回应那件事；交付物型（A）= 去产出与投递把东西做出来。 */
function fixTo(p: any) {
  if (p?.checkpoint === 'B') { router.push('/practice/im'); return }
  if (p?.checkpoint === 'A') { router.push(`/practice/orders/${orderId.value}/deliverables`); return }
  review(p?.id || '')
}
function fixLabel(p: any) {
  if (p?.checkpoint === 'B') return '去回应'
  if (p?.checkpoint === 'A') return '去补产出'
  return '去练习'
}

/** 事件真的注入过，才谈得上「去回应」；只是没排到的点，去教学线程先学一遍更合适 */
function canRespond(g: any) {
  const reason = String(g?.reason || '')
  if (reason.includes('事件已注入')) return true
  if (reason.includes('未在群里回应')) return true
  return false
}

onMounted(load)
watch(orderId, () => {
  summary.value = null
  dims.value = []
  reviews.value = []
  notice.value = null
  resultOpen.value = false
  result.value = null
  load()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.oscore { max-width: 1000px; display: flex; flex-direction: column; gap: 12px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 18px; }
.h-l { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.back { display: inline-flex; align-items: center; gap: 4px; border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 5px 13px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.back:hover { background: $color-primary-softer; }
.oid { font-family: ui-monospace, monospace; font-size: 15px; color: #e04b4b; font-weight: 600; }
.ocust { font-size: 15.5px; font-weight: 600; }
.otag { font-size: 15.5px; padding: 2px 9px; border-radius: 4px; }
.otag.inbound { background: #efe9fe; color: #7a5af8; }
.h-r { display: flex; align-items: center; gap: 14px; }
.avg-wrap { display: flex; align-items: center; gap: 7px; }
.avg { font-size: 26px; font-weight: 800; color: $color-primary; }
.avg.none { font-size: 16px; color: $color-text-muted; }
.avg-u { font-size: 15px; color: $color-text-muted; line-height: 1.4; }
.run {
  display: inline-flex; align-items: center; gap: 6px; border: none; cursor: pointer;
  border-radius: 999px; padding: 9px 18px; font-size: 15px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, #2577e3, #1a63c4); box-shadow: 0 6px 16px rgba(37,119,227,0.28);
}
.run:hover { filter: brightness(1.06); }
.run:disabled { opacity: .7; cursor: default; }

.stage { display: flex; align-items: center; gap: 10px; padding: 12px 18px; flex-wrap: wrap; }
.st-label { font-size: 15.5px; color: $color-text-muted; }
.st-name { font-size: 15.5px; font-weight: 700; }
.st-gates { font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 3px 12px; }
.st-ev { margin-left: 8px; font-size: 15.5px; color: $color-text-muted; }
.st-ev.muted { color: $color-text-muted; }
.ev-chip { font-size: 15.5px; background: $color-primary-softer; color: $color-text-secondary; border-radius: 999px; padding: 3px 11px; }

.cover { display: grid; grid-template-columns: 260px 1fr; grid-template-areas: "left bar" "gaps gaps"; align-items: center; gap: 10px 16px; padding: 13px 18px; border-left: 4px solid $color-primary; }
.cover.pass { border-left-color: #12a76a; }
.cv-left { grid-area: left; display: flex; align-items: baseline; gap: 10px; }
.cv-title { font-size: 15px; font-weight: 700; }
.cv-num { font-size: 20px; font-weight: 800; color: $color-primary; }
.cv-num i { font-size: 15.5px; color: $color-text-muted; font-style: normal; }
.cv-pct { font-size: 15.5px; color: $color-text-secondary; }
.cv-bar { grid-area: bar; height: 8px; border-radius: 999px; background: #eef1f5; overflow: hidden; }
.cv-bar i { display: block; height: 100%; background: linear-gradient(90deg, #2577e3, #4f9bf5); }
.cover.pass .cv-bar i { background: linear-gradient(90deg, #12a76a, #35c084); }
.cv-right { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; }
.cv-state { font-size: 15.5px; color: $color-text-secondary; }
.cv-state.ok { color: #0d8a55; }
.cv-stale { grid-column: 1 / -1; font-size: 14.5px; line-height: 1.7; color: #a35b00; margin-top: 8px;
  background: #fff8ec; border: 1px solid #f4e3c2; border-radius: 8px; padding: 8px 11px; }
.cv-state.bad { color: #c0392b; }
.cv-gaps { grid-area: gaps; border-top: 1px dashed #eef1f5; padding-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.gap { display: flex; align-items: center; gap: 10px; font-size: 15.5px; padding: 4px 0; }
.gap.none { color: $color-text-muted; }
.gap-id { font-family: ui-monospace, monospace; color: $color-text-muted; width: 46px; }
.gap-name { font-weight: 600; }
.gap-kind { font-size: 14.5px; background: #eef1f5; border-radius: 4px; padding: 1px 6px; color: $color-text-secondary; }
.gap-reason { color: $color-text-secondary; }

.notice { padding: 11px 16px; font-size: 15.5px; line-height: 1.7; }
.notice.info { background: $color-primary-softer; color: $color-text-secondary; }
.notice.ok { background: #e8f7ee; color: #0d8a55; }
.notice.warn { background: #fff6e8; color: #a3620c; }
.notice.bad { background: #fdeceb; color: #c0392b; }

.reviews { padding: 13px 18px; }
.rv-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.rv-title { font-size: 15.5px; font-weight: 700; }
.rv-sub { font-size: 15.5px; color: $color-text-muted; }
.rv-row { display: flex; align-items: center; gap: 12px; padding: 7px 0; border-top: 1px dashed #f1f3f5; font-size: 15.5px; }
.rv-id { font-family: ui-monospace, monospace; color: #d98324; font-weight: 600; width: 50px; }
.rv-score { font-weight: 700; }
.rv-score i { font-style: normal; font-size: 14.5px; color: $color-text-muted; margin-left: 4px; }
.rv-conf { font-size: 15px; color: $color-text-muted; }
.rv-why { flex: 1; color: $color-text-secondary; }
.rv-ops { display: flex; gap: 6px; }

.dims { display: flex; flex-direction: column; gap: 10px; }
.dim { overflow: hidden; }
.d-head { display: flex; align-items: center; gap: 11px; padding: 13px 18px; cursor: pointer; }
.d-head:hover { background: $color-primary-softer; }
.d-dot { width: 9px; height: 9px; border-radius: 50%; }
.d-id { font-family: ui-monospace, monospace; font-size: 15.5px; color: $color-text-muted; }
.d-name { font-size: 16px; font-weight: 700; }
.d-cnt { font-size: 15px; color: $color-text-muted; }
.d-score { margin-left: auto; font-size: 17px; font-weight: 800; }
.d-arrow { color: $color-text-muted; transition: transform .2s ease; }
.d-arrow.on { transform: rotate(90deg); }
.d-body { border-top: 1px solid #f1f3f5; padding: 8px 18px 12px; }
.p-row { display: flex; align-items: center; gap: 11px; padding: 8px 0; font-size: 15px; border-bottom: 1px dashed #f4f6f9; }
.p-row:last-child { border-bottom: none; }
.p-row.dimmed { opacity: .55; }
.p-id { font-family: ui-monospace, monospace; font-size: 15.5px; color: $color-text-muted; width: 44px; }
.p-name { flex: 1; }
.p-lv { font-size: 15.5px; font-weight: 700; }
.p-lv.none { color: $color-text-muted; font-weight: 500; }
.p-lv.notplanned { color: $color-text-muted; font-weight: 500; }
.p-lv.missed { color: #e0567a; font-weight: 600; }
.p-lv.planned { color: #c77700; font-weight: 600; }
.p-hint { display: block; font-style: normal; font-size: 13.5px; color: $color-text-muted; margin-top: 2px; }
.p-lv.pending { color: #d98324; }
.p-lv.M1 { color: #e04b4b; } .p-lv.M2 { color: #d98324; } .p-lv.M3 { color: #2577e3; } .p-lv.M4 { color: #12a76a; } .p-lv.M5 { color: #0d8a55; }
.p-score { font-weight: 700; width: 34px; text-align: right; }
.p-btn { padding: 4px 12px; font-size: 15.5px; }
.ev-box { margin-top: 6px; }
.ev-detail { background: $color-primary-softer; border-radius: 8px; padding: 10px 13px; }
.ev-comment { font-size: 15.5px; color: $color-text; line-height: 1.7; margin-bottom: 6px; }
.ev-quote { font-size: 15.5px; color: $color-text-secondary; line-height: 1.8; }
.ev-kind { font-size: 14.5px; background: #fff; border: 1px solid $color-border; border-radius: 4px; padding: 1px 6px; margin-right: 6px; }
.lnk { border: none; background: none; color: $color-primary; font-size: 15.5px; cursor: pointer; padding: 0; }
.fold-enter-active, .fold-leave-active { transition: opacity .18s ease; }
.fold-enter-from, .fold-leave-to { opacity: 0; }

.sm-overlay {
  position: fixed; inset: 0; z-index: 1200; padding: 24px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(15, 23, 42, .56); backdrop-filter: blur(4px);
}
.sm-dialog {
  width: min(780px, 100%); max-height: min(88vh, 920px); overflow: auto;
  background: #fff; border-radius: 18px; padding: 24px 26px;
  box-shadow: 0 24px 80px rgba(15, 23, 42, .3);
}
.sm-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.sm-kicker { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: $color-primary; font-weight: 700; }
.sm-head h2 { margin: 5px 0 4px; font-size: 26px; letter-spacing: -.02em; }
.sm-head p { margin: 0; font-size: 14px; color: $color-text-muted; }
.sm-x { width: 32px; height: 32px; border: 0; border-radius: 50%; background: #f1f5f9; color: #64748b; font-size: 21px; line-height: 1; cursor: pointer; }
.sm-x:hover { background: #e2e8f0; }
.sm-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 18px 0 4px; }
.sm-stats > div { padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #f8fafc; }
.sm-stats b { display: block; font-size: 24px; color: #0f172a; line-height: 1.2; }
.sm-stats span { display: block; margin-top: 3px; font-size: 12px; color: $color-text-muted; }
.sm-block { margin-top: 16px; padding-top: 16px; border-top: 1px solid #eef2f7; }
.sm-block-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.sm-block-head h3 { margin: 0; font-size: 17px; }
.sm-block-head span { font-size: 13px; color: $color-text-muted; }
.sm-ok, .sm-warn { margin: 8px 0; padding: 8px 10px; border-radius: 8px; font-size: 13px; line-height: 1.6; }
.sm-ok { background: #ecfdf5; color: #047857; }
.sm-warn { background: #fff7ed; color: #b45309; }
.sm-impact-list { max-height: 220px; overflow: auto; margin-top: 8px; }
.sm-impact-row {
  display: grid; grid-template-columns: 52px minmax(0, 1fr) 54px 92px 48px 58px;
  align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px dashed #eef2f7; font-size: 14px;
}
.sm-impact-row:last-child { border-bottom: 0; }
.sm-id { font-family: ui-monospace, monospace; color: $color-text-muted; }
.sm-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sm-name i, .sm-score i { display: block; margin-top: 2px; font-style: normal; font-size: 11px; color: #94a3b8; }
.sm-score { text-align: right; font-weight: 700; }
.sm-ba { text-align: right; color: $color-text-muted; white-space: nowrap; }
.sm-ba b { color: #0f172a; }
.sm-delta { text-align: right; font-weight: 800; color: $color-text-muted; }
.sm-delta.up { color: #059669; }
.sm-delta.down { color: #dc2626; }
.sm-status { padding: 2px 6px; border-radius: 999px; font-size: 11px; text-align: center; background: #fff7ed; color: #b45309; white-space: nowrap; }
.sm-status.ok { background: #ecfdf5; color: #047857; }
.sm-diff { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 10px 0 12px; }
.sm-explain { margin: -2px 0 10px; padding: 8px 10px; border-radius: 8px; background: #eff6ff; color: #1d4ed8; font-size: 13px; line-height: 1.6; }
.sm-current, .sm-next { padding: 6px 12px; border-radius: 999px; font-weight: 700; }
.sm-current { background: #f1f5f9; color: #475569; }
.sm-next { background: #fff7ed; color: #c2410c; }
.sm-arrow { color: #94a3b8; font-weight: 700; }
.sm-targets { display: flex; flex-wrap: wrap; gap: 6px; }
.sm-target { padding: 4px 9px; border-radius: 999px; background: #eff6ff; color: #1d4ed8; font-size: 13px; }
.sm-knobs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 18px; margin: 14px 0; }
.sm-knob { display: grid; grid-template-columns: 94px 1fr 62px; align-items: center; gap: 8px; font-size: 13px; }
.sm-knob > span { color: #475569; }
.sm-knob i { display: block; height: 7px; overflow: hidden; border-radius: 999px; background: #eef2f7; }
.sm-knob i b { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #2577e3, #4f9bf5); }
.sm-knob em { font-style: normal; text-align: right; font-size: 11px; color: $color-text-muted; }
.sm-rationale { margin: 12px 0; padding: 9px 11px; border-left: 3px solid $color-primary; border-radius: 6px; background: #f8fafc; color: #475569; font-size: 14px; line-height: 1.7; }
.sm-plan { display: flex; gap: 10px; flex-wrap: wrap; font-size: 13px; color: $color-text-muted; }
.sm-actions { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; margin-top: 20px; }
.sm-fade-enter-active, .sm-fade-leave-active { transition: opacity .2s ease; }
.sm-fade-enter-from, .sm-fade-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .sm-overlay { padding: 12px; }
  .sm-dialog { padding: 20px 18px; }
  .sm-stats { grid-template-columns: 1fr 1fr; }
  .sm-impact-row { grid-template-columns: 48px minmax(0, 1fr) 48px 80px 42px 52px; gap: 6px; font-size: 13px; }
  .sm-knobs { grid-template-columns: 1fr; }
}
</style>
