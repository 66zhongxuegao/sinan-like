<template>
  <div class="prof">
    <section v-if="intakeError" class="card panel intake-notice" role="alert">
      <span>{{ intakeError }}</span>
      <button class="tc-btn" type="button" @click="loadReport">重新加载测评入口</button>
    </section>
    <section v-else-if="canAssess" class="card panel intake-notice">
      <div>
        <b>账号 {{ userStore.username }} 尚未完成初始测评</b>
        <div>已有学习或实战记录也可以补做，系统会保留你的训练进度。</div>
      </div>
      <router-link to="/profile/quiz" class="tc-btn">
        <SIcon name="sparkle" :size="15" /> 开始初始测评
      </router-link>
    </section>
    <!-- 顶部：综合掌握度 + 关键指标 -->
    <section class="card hero-card rise">
      <div class="gauge">
        <svg viewBox="0 0 120 120" class="gauge-svg">
          <circle cx="60" cy="60" r="52" fill="none" stroke="#eef2f7" stroke-width="9" />
          <circle cx="60" cy="60" r="52" fill="none" stroke="#2577e3" stroke-width="9" stroke-linecap="round"
            :stroke-dasharray="C52" :stroke-dashoffset="off(52, currentLearningValue ?? 0)" transform="rotate(-90 60 60)" class="ring-fill" />
          <circle cx="60" cy="60" r="38" fill="none" stroke="#eef2f7" stroke-width="8" />
          <circle cx="60" cy="60" r="38" fill="none" stroke="#e08a1e" stroke-width="8" stroke-linecap="round"
            :stroke-dasharray="C38" :stroke-dashoffset="off(38, currentPracticeValue ?? 0)" transform="rotate(-90 60 60)" class="ring-fill" />
        </svg>
        <div class="gauge-txt">
          <div class="g-vals">
            <span class="v teach"><i class="dot" />学习 {{ currentLearningValue ?? '未评估' }}</span>
            <span class="v real"><i class="dot" />实战 {{ currentPracticeValue ?? '未评估' }}</span>
          </div>
        </div>
      </div>
      <div class="hero-mid">
        <div class="t">当前训练掌握度</div>
        <div class="hero-tags">
          <span class="chip"><i class="sw teach" />学习掌握度</span>
          <span class="chip"><i class="sw real" />实战掌握度</span>
          <span class="chip scope" :class="scopeClass"><i class="sw dot-scope" />{{ scopeLabel }}</span>
        </div>
        <div class="hero-note">
          学习与实战分别来自相应训练，初始测评保留为独立基线。下方可按保存时间查看历史雷达。
        </div>
        <!-- 技术口径不进入主流程：收进折叠说明 -->
        <details class="tech-fold">
          <summary>口径与计算说明</summary>
          <div class="tf-body">
            掌握度来自 8 个维度、61 个技能点的能力记录，分「学习」与「实战」两套口径
            （对应后端能力表的 teach / real_v 两列）；能力雷达分别呈现初始、学习与实战三类能力，并保存每次更新的历史记录；分数趋势按两种来源分开统计：做题来源（每次答题记录
            quiz_attempt）与订单来源（每次实战评分记录 order_score）。训练未涉及的维度沿用本人的初始画像，
            并在雷达圆点上标注；尚无初始测评的维度显示「未评估」。
          </div>
        </details>
      </div>
      <div class="hero-stats">
        <div class="hs"><div class="n">{{ totalPoints }}</div><div class="l">技能点</div></div>
        <div class="hs"><div class="n warn">{{ weakPoints.length }}</div><div class="l">薄弱点</div></div>
        <div class="hs"><div class="n ok">{{ masteredPoints.length }}</div><div class="l">已熟练</div></div>
      </div>
    </section>

    <LearningRouteLauncher v-if="radarAssessed" />

    <!-- 图表区：初始 vs 当前雷达 + 真实趋势 -->
    <section class="charts">
      <div class="card panel rise radar-panel">
        <div class="panel-head">
          <SIcon name="target" :size="15" /><span>能力雷达</span>
          <span class="hd-badge">同一刻度 0–100</span>
          <button class="mem-refresh" :disabled="refreshing || snapshotLoading || !radarAssessed" @click="refreshProfile">
            <SIcon name="refresh" :size="14" /><span>{{ refreshing ? '正在更新画像…' : '手动刷新画像' }}</span>
          </button>
        </div>
        <p v-if="refreshMessage" class="refresh-receipt" role="status">{{ refreshMessage }}</p>
        <div class="radar-workspace">
          <aside class="radar-history" aria-label="画像历史记录">
            <div class="history-heading"><SIcon name="clock" :size="15" /> 查看记录</div>
            <button type="button" class="history-item" :class="{ active: !selectedSnapshotId }"
              :aria-pressed="!selectedSnapshotId" :disabled="snapshotLoading || refreshing" @click="selectCurrent">
              <b>当前能力</b><span>查看最新训练结果</span>
            </button>
            <div class="history-label">已保存的时间</div>
            <div v-if="historyLoading" class="history-hint">正在读取记录…</div>
            <div v-else-if="historyError" class="history-hint" role="alert">
              {{ historyError }}<button type="button" class="history-retry" @click="loadHistory">重新加载</button>
            </div>
            <div v-else-if="!radarHistory.length" class="history-hint">每次订单复盘评分后会自动更新；也可以手动刷新。</div>
            <div class="history-list">
              <button v-for="record in radarHistory" :key="record.id" type="button" class="history-item"
                :class="{ active: selectedSnapshotId === record.id }" :aria-pressed="selectedSnapshotId === record.id"
                :disabled="snapshotLoading || refreshing" @click="selectSnapshot(record.id)">
                <b>{{ fmtAt(record.at) || '时间未记录' }}</b>
                <span>{{ record.kind === 'initial' ? '初始测评' : '画像更新' }}</span>
              </button>
            </div>
          </aside>
          <div class="radar-viewer">
            <div class="radar-series-controls" aria-label="显示或隐藏能力图层">
              <button v-for="layer in radarControls" :key="layer.key" type="button" class="series-toggle"
                :class="{ selected: visibleLayers[layer.key] }" :aria-pressed="visibleLayers[layer.key]"
                :style="{ '--series-color': layer.color }" @click="toggleLayer(layer.key)">
                <i class="series-dot" /><b>{{ layer.label }}</b>
                <span>{{ visibleLayers[layer.key] ? '显示中' : '已隐藏' }}</span>
              </button>
            </div>
            <div class="radar-view-time">
              <b>{{ selectedSnapshotId ? '记录时间：' + fmtAt(selectedSnapshot?.at) : '当前能力' }}</b>
              <span v-if="!selectedSnapshotId && radarHistory[0]?.at">最近保存：{{ fmtAt(radarHistory[0].at) }}</span>
            </div>
            <div v-if="radarError" class="chart-empty inline" role="alert">
              {{ radarError }}<button type="button" class="tc-btn" @click="loadRadar">重新加载</button>
            </div>
            <div v-else-if="snapshotLoading || radarLoading" class="chart-empty inline">正在读取能力记录…</div>
            <template v-else>
              <ProfileRadar v-if="radarDims.length" :dimensions="radarDimensions" :layers="radarLayers" />
              <div v-if="!visibleRadarAssessed" class="radar-tip">
                {{ anyLayerVisible ? '所选图层尚无评估记录，完成相应测评或训练后即可查看。' : '三个图层均已隐藏，点击上方按钮可重新显示。' }}
              </div>
              <div v-else-if="radarLayers.some(l => l.visible && l.dimensions.some(d => d.inherited))" class="radar-tip">
                训练未涉及的维度沿用初始画像；悬停圆点可查看分值与来源。
              </div>
              <div v-else-if="radarLayers.some(l => l.visible && l.dimensions.some(d => !d.assessed))" class="radar-tip">
                未评估的维度保留空缺；悬停图上的圆点可查看分值。
              </div>
              <div class="radar-meta">
                <span v-for="layer in radarLayers.filter(l => l.visible)" :key="layer.key" class="rm-item">
                  <i class="series-dot" :style="{ background: layer.color }" />{{ layer.label }}
                  <b>{{ layer.dimensions.some(d => d.assessed) ? fmtAt(displayRadar[layer.key]?.at) || '已评估' : '未评估' }}</b>
                </span>
              </div>
              <div class="radar-table">
                <div class="rt-head"><span>维度</span><span class="initial-text">初始能力</span><span class="learning-text">学习能力</span><span class="practice-text">实战能力</span></div>
                <div v-for="dim in radarDims" :key="dim.id" class="rt-row">
                  <span class="rt-dim"><i class="tag">{{ dim.id }}</i>{{ dim.name }}</span>
                  <span class="rt-v initial-text" :class="{ na: dim.initial === null }">{{ dimensionText(dim.initial) }}</span>
                  <span class="rt-v learning-text" :class="{ na: dim.learning === null }">{{ dimensionText(dim.learning) }}</span>
                  <span class="rt-v practice-text" :class="{ na: dim.practice === null }">{{ dimensionText(dim.practice) }}</span>
                </div>
              </div>
            </template>
            <div class="radar-source-note">实战能力来自对话实战评分，学习能力来自学习地图；训练未涉及的维度沿用初始画像。</div>
          </div>
        </div>
      </div>

      <div class="card panel rise trend-panel">
        <div class="panel-head">
          <SIcon name="wave" :size="15" /><span>真实分数趋势</span>
          <span class="hd-badge" :class="scopeClass">{{ scopeLabel }}</span>
        </div>

        <div v-if="!trend.has_data" class="chart-empty">
          <div class="ce-ico"><SIcon name="chart" :size="22" /></div>
          <div class="ce-title">完成训练后查看分数趋势</div>
          <div class="ce-text">
            做几道题或完成一次实战评分后，这里会显示你的近期分数、变化幅度与样本数。
          </div>
        </div>

        <template v-else>
          <div class="trend-stats">
            <div class="ts quiz">
              <div class="ts-l">做题 · {{ trend.quiz?.metric || '正确率(%)' }}</div>
              <div class="ts-v">
                <b>{{ num(trend.quiz?.avg_score) }}</b><i>均分</i>
              </div>
              <div class="ts-m">
                样本 <b>{{ trend.quiz?.total_samples ?? 0 }}</b> 题 ·
                正答 <b>{{ trend.quiz?.correct ?? 0 }}</b> ·
                准确率 <b>{{ trend.quiz?.accuracy === null || trend.quiz?.accuracy === undefined ? '—' : trend.quiz.accuracy + '%' }}</b>
              </div>
            </div>
            <div class="ts order">
              <div class="ts-l">实战订单 · {{ trend.order?.metric || '订单评分(0-100)' }}</div>
              <div class="ts-v">
                <b>{{ num(trend.order?.avg_score) }}</b><i>均分</i>
              </div>
              <div class="ts-m">
                样本 <b>{{ trend.order?.total_samples ?? 0 }}</b> 条评分 ·
                涉及 <b>{{ trend.order?.distinct_orders ?? 0 }}</b> 单
              </div>
            </div>
          </div>

          <div class="chart line" ref="lineRef"></div>
          <div class="trend-note">两条线分别是「做题正确率」与「实战订单评分」，都可以看到样本数。</div>
          <details class="tech-fold">
            <summary>折线怎么读</summary>
            <div class="tf-body">
              两条线用同一个 0–100 刻度：做题线 = 当日答题正确率，订单线 = 当日订单评分均分。
              只有当日确实有样本的点才画圆点；当天该来源没有样本时，圆点不画、只为把折线连上而沿用
              上一次实测值，鼠标悬停会标注样本数与是否为沿用，避免误读成新增数据。
            </div>
          </details>
        </template>
      </div>
    </section>

    <!-- 画像记忆：画像 Agent 的定性描述与学习建议 -->
    <section class="card panel rise memory">
      <div class="panel-head">
        <SIcon name="notebook" :size="15" /><span>画像记忆</span>
        <span v-if="report.kind" class="mem-kind">{{ report.kind === 'initial' ? '初始画像' : '动态刷新' }}</span>
        <span v-if="report.created_at" class="mem-time">{{ fmtAt(report.created_at) }}</span>
      </div>

      <template v-if="report.summary">
        <div class="mem-summary">{{ report.summary }}</div>

        <template v-if="(report.strengths || []).length">
          <div class="mem-label">长板</div>
          <div class="mem-strengths">
            <div v-for="(s, i) in report.strengths" :key="i" class="strength">
              <i class="st-dot" /><span>{{ s }}</span>
            </div>
          </div>
        </template>

        <div class="mem-label">学习建议</div>
        <div class="mem-sugs">
          <div v-for="(s, i) in report.suggestions || []" :key="i" class="mem-sug"
            :style="{ animationDelay: (0.05 * i) + 's' }">
            <div class="ms-head">
              <span class="ms-dim">{{ s.dim_name }}</span>
              <span class="ms-title">{{ s.title }}</span>
            </div>
            <div class="ms-line"><span class="ms-k">为什么</span><span class="ms-v">{{ s.why }}</span></div>
            <div class="ms-line"><span class="ms-k">怎么练</span><span class="ms-v">{{ s.how }}</span></div>
            <button v-if="s.skill_point_id" class="ms-go" @click="go(s.skill_point_id)">
              {{ s.skill_point_id }} 去学习 <SIcon name="right" :size="12" />
            </button>
          </div>
        </div>
      </template>

      <div v-else class="mem-empty">
        <div class="me-text">{{ canAssess
          ? '还没有学情画像。先做一次初始测评，系统会给出你的起点与学习建议。'
          : '还没有学情画像。订单复盘评分后会自动更新画像；也可以点击上方「手动刷新画像」。' }}</div>
        <router-link v-if="canAssess" to="/profile/quiz" class="tc-btn">
          <SIcon name="sparkle" :size="15" /> 开始初始测评
        </router-link>
      </div>
    </section>

    <!-- 维度钻取 -->
    <section class="card panel rise">
      <div class="panel-head"><SIcon name="layers" :size="15" /><span>能力维度明细</span>
        <span class="hd-badge">8 个维度汇总</span>
      </div>
      <div class="dims">
        <div v-for="d in dims" :key="d.id" class="dim" :class="{ open: openSet.has(d.id) }">
          <div class="dim-head" @click="toggle(d.id)">
            <span class="tag">{{ d.id }}</span>
            <span class="dn">{{ d.name }}</span>
            <div class="dim-meters">
              <div class="meter"><span class="ml">学习</span><div class="track"><i class="teach" :style="{ width: d.teach + '%' }" /></div></div>
              <div class="meter"><span class="ml">实战</span><div class="track"><i class="real" :style="{ width: d.real + '%' }" /></div></div>
            </div>
            <span class="avg"><b>{{ d.teach }}</b> / <b class="real">{{ d.real }}</b></span>
            <SIcon :name="openSet.has(d.id) ? 'up' : 'right'" :size="16" class="chev" />
          </div>
          <transition name="expand">
            <div v-if="openSet.has(d.id)" class="expand-wrap">
              <div class="dim-body">
                <div v-for="p in d.points" :key="p.id" class="sp" @click="go(p.id)">
                  <span class="pid">{{ p.id }}</span>
                  <span class="pn">{{ p.name }}</span>
                  <span class="cp" :class="p.checkpoint">{{ p.checkpoint === 'B' ? '问题应对' : '动作' }}</span>
                  <div class="sp-bars">
                    <div class="track"><i class="teach" :style="{ width: p.teach + '%' }" /></div>
                    <div class="track"><i class="real" :style="{ width: p.real + '%' }" /></div>
                  </div>
                  <span class="lv" :class="'lv-' + masteryOf(p.real || p.teach)">{{ masteryOf(p.real || p.teach) }}</span>
                  <span class="go">去学习 ›</span>
                </div>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'
import SIcon from '@/components/SIcon.vue'
import ProfileRadar from '@/components/ProfileRadar.vue'
import LearningRouteLauncher from '@/components/LearningRouteLauncher.vue'

const router = useRouter()
const userStore = useUserStore()
const dims = ref<any[]>([])
const report = ref<any>({})
const canAssess = ref(false)
const intakeError = ref('')
const refreshing = ref(false)
const openSet = ref(new Set<string>())

/** /profiles/{id}/radar：初始画像快照 vs 当前能力（同为 0–100 维度值） */
const radar = ref<any>({})
/** /profiles/{id}/trend：题目口径 / 订单口径的真实分数与样本数 */
const trend = ref<any>({})

const lineRef = ref<HTMLElement | null>(null)
let lineChart: echarts.ECharts | null = null

const C52 = 2 * Math.PI * 52
const C38 = 2 * Math.PI * 38
const off = (r: number, v: number) => 2 * Math.PI * r * (1 - Math.min(100, Math.max(0, v)) / 100)

const allPoints = computed(() => dims.value.flatMap((d: any) => d.points || []))
const totalPoints = computed(() => allPoints.value.length)
const weakPoints = computed(() => allPoints.value.filter((p: any) => (p.real || p.teach) < 70))
const masteredPoints = computed(() => allPoints.value.filter((p: any) => (p.real || p.teach) >= 90))

/* ── 数据口径标识（示例 / 真实）── */
const scopeClass = computed(() => (trend.value?.data_scope?.scope === 'example' ? 'demo' : 'real'))
const scopeLabel = computed(() => trend.value?.data_scope?.label
  || (userStore.isDemo ? '标准案例 / 演示数据' : '真实训练数据'))

/* 三类能力独立显示；历史记录读取保存时的快照。 */
type LayerKey = 'initial' | 'learning' | 'practice'
interface RadarDimension { id: string; name: string; value: number | null; assessed: boolean; inherited?: boolean }
interface RadarDimRow { id: string; name: string; initial: number | null; learning: number | null; practice: number | null }
interface RadarHistory { id: string; kind: string; at: string }
const visibleLayers = ref<Record<LayerKey, boolean>>({ initial: true, learning: true, practice: true })
const radarHistory = ref<RadarHistory[]>([])
const selectedSnapshotId = ref('')
const selectedSnapshot = ref<any>(null)
const snapshotLoading = ref(false)
const historyLoading = ref(false)
const radarLoading = ref(false)
const historyError = ref('')
const radarError = ref('')
const refreshMessage = ref('')
const displayRadar = computed(() => selectedSnapshot.value?.radar || radar.value)
const radarAssessed = computed(() => !!radar.value?.assessed)
function currentLayerValue(key: LayerKey): number | null {
  const rows = (radar.value?.[key]?.dimensions || []).filter((d: RadarDimension) => d.assessed && !d.inherited && typeof d.value === 'number')
  const count = rows.reduce((n: number, d: any) => n + (d.assessed_points || 1), 0)
  return count ? Math.round(rows.reduce((sum: number, d: any) => sum + d.value * (d.assessed_points || 1), 0) / count * 10) / 10 : null
}
const currentLearningValue = computed(() => currentLayerValue('learning'))
const currentPracticeValue = computed(() => currentLayerValue('practice'))
const layerDefinitions: { key: LayerKey; label: string; color: string }[] = [
  { key: 'initial', label: '初始能力', color: '#b7c2d3' },
  { key: 'learning', label: '学习能力', color: '#2577e3' },
  { key: 'practice', label: '实战能力', color: '#eb8a18' },
]
const radarControls = [layerDefinitions[2], layerDefinitions[1], layerDefinitions[0]]
const radarLayers = computed(() => layerDefinitions.map(layer => ({ ...layer,
  visible: visibleLayers.value[layer.key],
  dimensions: (displayRadar.value?.[layer.key]?.dimensions || []) as RadarDimension[],
})))
const radarDimensions = computed<RadarDimension[]>(() => displayRadar.value?.initial?.dimensions || [])
const radarDims = computed<RadarDimRow[]>(() => radarDimensions.value.map(dim => {
  const valueOf = (key: LayerKey) => {
    const row = (displayRadar.value?.[key]?.dimensions || []).find((d: RadarDimension) => d.id === dim.id)
    return row?.assessed && typeof row.value === 'number' ? row.value : null
  }
  return { id: dim.id, name: dim.name, initial: valueOf('initial'), learning: valueOf('learning'), practice: valueOf('practice') }
}))
const anyLayerVisible = computed(() => Object.values(visibleLayers.value).some(Boolean))
const visibleRadarAssessed = computed(() => radarLayers.value.some(l => l.visible && l.dimensions.some(d => d.assessed)))
function toggleLayer(key: LayerKey) { visibleLayers.value[key] = !visibleLayers.value[key] }
function dimensionText(value: number | null): string { return value === null ? '未评估' : value.toFixed(1) }

function fmtAt(v?: string): string {
  return String(v || '').replace('T', ' ').slice(0, 19)
}

function num(v: any): string {
  return (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : String(v)
}

/* ── 图表 ── */
function lineOption(): any {
  const t: any[] = trend.value?.trend || []
  const quizName = '做题正确率(%)'
  const orderName = '实战订单评分'
  const fmt = (params: any) => {
    const list = Array.isArray(params) ? params : [params]
    const i = list[0]?.dataIndex ?? 0
    const p = t[i] || {}
    const rows = [
      `<div style="font-weight:700;margin-bottom:4px">${p.full_date || p.date || ''}</div>`,
    ]
    if (p.quiz_samples > 0) rows.push(`${quizName}：<b>${p.teach ?? '—'}</b>（当日样本 ${p.quiz_samples} 题）`)
    else if (p.teach !== null && p.teach !== undefined) rows.push(`${quizName}：<b>${p.teach}</b>（当日无答题样本，沿用上一次实测）`)
    else rows.push(`${quizName}：无数据`)
    if (p.order_samples > 0) rows.push(`${orderName}：<b>${p.real ?? '—'}</b>（当日样本 ${p.order_samples} 条）`)
    else if (p.real !== null && p.real !== undefined) rows.push(`${orderName}：<b>${p.real}</b>（当日无评分样本，沿用上一次实测）`)
    else rows.push(`${orderName}：无数据`)
    return rows.join('<br/>')
  }
  return {
    tooltip: { trigger: 'axis', formatter: fmt },
    legend: { top: 0, right: 4, itemWidth: 12, itemHeight: 8, textStyle: { color: '#6b7a90', fontSize: 14 } },
    grid: { left: 40, right: 16, top: 44, bottom: 30 },
    xAxis: {
      type: 'category', data: t.map((x: any) => x.date), boundaryGap: false,
      axisLine: { lineStyle: { color: '#e3e9f1' } }, axisTick: { show: false },
      axisLabel: { color: '#6b7a90', fontSize: 13 },
    },
    yAxis: {
      type: 'value', max: 100, min: 0, name: '分值（0–100）',
      nameTextStyle: { color: '#9aa8bb', fontSize: 12 },
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { color: '#9aa8bb', fontSize: 13 },
    },
    series: [
      {
        name: quizName, type: 'line', smooth: true, connectNulls: false,
        // 只有当日真的有答题样本才画点：沿用值不画点，避免被读成「新实测」
        data: t.map((x: any) => ({ value: x.teach, symbolSize: x.quiz_samples > 0 ? 6 : 0 })),
        lineStyle: { width: 2.5, color: '#2577e3' }, itemStyle: { color: '#2577e3' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(37,119,227,0.22)' }, { offset: 1, color: 'rgba(37,119,227,0)' }]) },
      },
      {
        name: orderName, type: 'line', smooth: true, connectNulls: false,
        data: t.map((x: any) => ({ value: x.real, symbolSize: x.order_samples > 0 ? 6 : 0 })),
        lineStyle: { width: 2.5, color: '#e08a1e' }, itemStyle: { color: '#e08a1e' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(224,138,30,0.2)' }, { offset: 1, color: 'rgba(224,138,30,0)' }]) },
      },
    ],
    animationDuration: 900, animationEasing: 'cubicOut',
  }
}

function renderCharts() {
  if (trend.value?.has_data && lineRef.value) {
    if (!lineChart) lineChart = echarts.init(lineRef.value)
    lineChart.setOption(lineOption(), true)
    lineChart.resize()
  }
}

function resize() { lineChart?.resize() }

async function loadMastery() {
  try {
    const r = await client.get('/learn/map')
    dims.value = r.data.dimensions || []
  } catch { dims.value = [] }
}

/** 当前能力与已保存的时间列表分别读取。 */
async function loadRadar() {
  radarLoading.value = true
  radarError.value = ''
  try {
    radar.value = (await client.get(`/profiles/${userStore.userId}/radar`)).data || {}
  } catch { radarError.value = '能力数据暂时无法读取，请重新加载。' }
  finally { radarLoading.value = false }
}
async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    radarHistory.value = (await client.get(`/profiles/${userStore.userId}/radar/history`)).data.history || []
  } catch { historyError.value = '历史记录暂时无法读取。' }
  finally { historyLoading.value = false }
}
function selectCurrent() {
  selectedSnapshotId.value = ''
  selectedSnapshot.value = null
  refreshMessage.value = ''
  void loadRadar()
}
async function selectSnapshot(id: string) {
  if (snapshotLoading.value || refreshing.value) return
  snapshotLoading.value = true
  radarError.value = ''
  refreshMessage.value = ''
  try {
    const response = await client.get(`/profiles/${userStore.userId}/radar/history/${encodeURIComponent(id)}`)
    selectedSnapshot.value = response.data
    selectedSnapshotId.value = id
  } catch { radarError.value = '这条历史记录暂时无法读取，请重新选择或重试。' }
  finally { snapshotLoading.value = false }
}

/** 趋势：题目口径（quiz_attempt）/ 订单口径（order_score），带均分与样本数 */
async function loadTrend() {
  try {
    trend.value = (await client.get(`/profiles/${userStore.userId}/trend`)).data || {}
  } catch { trend.value = {} }
}

async function loadReport() {
  intakeError.value = ''
  try {
    const r = await client.get(`/profiles/${userStore.userId}/intake`)
    report.value = r.data.report || {}
    canAssess.value = !!r.data.can_assess
  } catch {
    intakeError.value = '测评状态暂时无法读取，请重新加载后查看入口。'
  }
}

function masteryOf(v: number): string {
  if (v >= 90) return 'M5'
  if (v >= 80) return 'M4'
  if (v >= 70) return 'M3'
  if (v >= 60) return 'M2'
  return 'M1'
}

function toggle(id: string) {
  const s = new Set(openSet.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  openSet.value = s
}
function go(id: string) { router.push(`/learn/thread/${id}`) }

/** 更新画像：画像 Agent 重读掌握度 / 实战 / 答题 / 旧报告，重出定性描述与建议。 */
async function refreshProfile() {
  if (refreshing.value || snapshotLoading.value) return
  refreshing.value = true
  try {
    const r = await client.post(`/profiles/${userStore.userId}/refresh`)
    report.value = r.data.report || {}
    radar.value = r.data.radar || radar.value
    selectedSnapshotId.value = r.data.snapshot?.id || ''
    selectedSnapshot.value = r.data.snapshot ? { ...r.data.snapshot, radar: r.data.radar, report: r.data.report } : null
    radarError.value = ''
    refreshMessage.value = `已保存 ${fmtAt(r.data.snapshot?.at)} 的能力记录。`
    await Promise.all([loadMastery(), loadHistory(), loadTrend()])
    await nextTick()
    renderCharts()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '更新画像失败')
  } finally { refreshing.value = false }
}

onMounted(async () => {
  await Promise.all([loadMastery(), loadRadar(), loadHistory(), loadTrend(), loadReport()])
  await nextTick()
  renderCharts()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  lineChart?.dispose()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.intake-notice { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; line-height: 1.8; }
.ring-fill { transition: stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1); }
@keyframes gaugeIn { from { opacity: 0; transform: scale(.7); } to { opacity: 1; transform: scale(1); } }
.prof { width: 100%; max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }

/* 顶部总览 */
.hero-card { padding: 22px 26px; display: flex; align-items: center; gap: 28px; background: linear-gradient(135deg, #ffffff 0%, #f5f9ff 100%); }
.gauge { position: relative; width: 186px; height: 186px; flex-shrink: 0; animation: gaugeIn .7s cubic-bezier(.34,1.56,.64,1) both; }
.gauge-svg { width: 100%; height: 100%; }
.gauge-txt { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.g-vals { display: flex; flex-direction: column; gap: 3px; align-items: center; }
.v { font-size: 17px; font-weight: 800; line-height: 1.2; display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.v .dot { width: 6px; height: 6px; border-radius: 50%; }
.v.teach .dot { background: #2577e3; }.v.real .dot { background: #e08a1e; }
.v.teach { color: #2577e3; }
.v.real { color: #e08a1e; }
.hero-mid { flex: 1; }
.hero-mid .t { font-size: 26px; font-weight: 800; }
.hero-tags { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 15px; color: $color-text-secondary; background: #fff; border: 1px solid $color-border; padding: 4px 12px; border-radius: 999px; }
.chip.scope.real { color: $color-success; background: #e5f7ee; border-color: #ccecd9; font-weight: 700; }
.chip.scope.demo { color: #b3730f; background: #fdf3e3; border-color: #f2dcb6; font-weight: 700; }
.sw { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.sw.teach { background: #2577e3; }
.sw.real { background: #e08a1e; }
.sw.dot-scope { background: currentColor; }
.hero-note { margin-top: 12px; max-width: 560px; font-size: $fs-meta; line-height: 1.75; color: $color-text-secondary; }
/* 技术口径折叠：不进入主流程，需要时才展开（监督者要求：工程术语不下发到主界面） */
.tech-fold { margin-top: 10px; max-width: 640px; }
.tech-fold > summary { cursor: pointer; font-size: $fs-meta; color: $color-primary; list-style: none; }
.tech-fold > summary::-webkit-details-marker { display: none; }
.tech-fold > summary::before { content: '▸ '; }
.tech-fold[open] > summary::before { content: '▾ '; }
.tf-body { margin-top: 6px; padding: 10px 12px; font-size: $fs-meta; line-height: 1.8; color: $color-text-secondary;
  background: $color-bg; border: 1px solid $color-border; border-radius: $radius-md; }
.hero-stats { display: flex; gap: 12px; }
.hs { min-width: 84px; text-align: center; padding: 12px 14px; border-radius: $radius-md; background: #fff; border: 1px solid $color-border; }
.hs .n { font-size: 30px; font-weight: 800; color: $color-primary; }
.hs .n.warn { color: #e08a1e; }
.hs .n.ok { color: #12a76a; }
.hs .l { margin-top: 4px; font-size: 15px; color: $color-text-secondary; }

/* 图表 */
.charts { display: grid; grid-template-columns: 1.15fr 1fr; gap: 16px; }
.radar-panel, .trend-panel { grid-column: 1 / -1; min-width: 0; }
.radar-workspace { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 24px; margin-top: 16px; }
.radar-history { padding-right: 20px; border-right: 1px solid #e8edf5; min-width: 0; }
.history-heading { display: flex; align-items: center; gap: 7px; font-size: 15px; font-weight: 700; color: #243b5a; margin-bottom: 14px; }
.history-label { color: #8a99ad; font-size: 13px; margin: 20px 0 9px; }
.history-list { display: flex; flex-direction: column; gap: 8px; max-height: 580px; overflow-y: auto; padding-right: 3px; }
.history-item { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; width: 100%; padding: 12px 10px;
  background: #f8fafd; border: 1px solid #e5eaf2; border-radius: 10px; text-align: left; cursor: pointer; color: #465c77; }
.history-item b { font-size: 13px; font-weight: 700; line-height: 1.5; }
.history-item span { font-size: 12px; color: #8797ad; }
.history-item:hover { border-color: #a9cafa; }
.history-item.active { background: #edf4ff; border-color: #84b4f7; color: #2267c1; box-shadow: inset 3px 0 #2577e3; }
.history-item:disabled { cursor: wait; opacity: .65; }
.history-hint { font-size: 13px; line-height: 1.8; color: #8a99ad; margin-bottom: 10px; }
.history-retry { display: block; background: none; border: 0; color: #2577e3; cursor: pointer; padding: 4px 0; }
.radar-viewer { min-width: 0; }
.radar-series-controls { display: flex; flex-wrap: wrap; gap: 10px; }
.series-toggle { display: inline-flex; align-items: center; gap: 8px; border: 1px solid #e0e7f0; border-radius: 999px;
  background: #f7f9fc; color: #8996a8; padding: 9px 14px; cursor: pointer; font-size: 14px; transition: opacity .15s; }
.series-toggle.selected { background: #fff; color: #314663; box-shadow: 0 2px 7px #1b35540a; border-color: var(--series-color); }
.series-toggle span { font-size: 11px; color: #8a99ad; }
.series-toggle:not(.selected) .series-dot { opacity: .3; }
.series-dot { display: inline-block; width: 10px; height: 10px; flex-shrink: 0; border-radius: 50%; background: var(--series-color); box-shadow: 0 0 0 1px #364d6e15; }
.radar-view-time { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; margin-top: 16px; font-size: 13px; color: #8191a6; }
.radar-view-time b { color: #4b617d; font-weight: 600; }
.radar-source-note { margin-top: 12px; color: #8191a6; font-size: 12px; line-height: 1.8; }
.refresh-receipt { color: #278257; background: #f0faf4; border: 1px solid #d9eee2; border-radius: 9px; padding: 10px 14px; font-size: 14px; }
.initial-text { color: #8494aa; }
.learning-text { color: #2577e3; }
.practice-text { color: #d67a10; }
@media (max-width: 760px) {
  .radar-workspace { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .radar-history { border-right: 0; border-bottom: 1px solid #e8edf5; padding: 0 0 16px; }
  .history-list { flex-direction: row; overflow-x: auto; max-height: none; }
  .history-list .history-item { min-width: 170px; }
  .radar-series-controls { gap: 6px; }
  .series-toggle { padding: 8px 10px; }
}
.panel { padding: 16px 18px 14px; }
.panel-head { display: flex; align-items: center; gap: 9px; font-size: 19px; font-weight: 700; color: $color-text; margin-bottom: 8px; flex-wrap: wrap; }
.panel-head svg { color: $color-primary; }
.hd-badge { font-size: $fs-badge; font-weight: 600; color: $color-text-secondary; background: $color-bg;
  border: 1px solid $color-border; padding: 2px 9px; border-radius: 999px; }
.hd-badge.real { color: $color-success; background: #e5f7ee; border-color: #ccecd9; font-weight: 700; }
.hd-badge.demo { color: #b3730f; background: #fdf3e3; border-color: #f2dcb6; font-weight: 700; }

.chart { width: 100%; }
.chart.radar { height: 300px; }
.chart.line { height: 300px; }
.chart.hidden { display: none; }

.chart-empty { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; padding: 18px 16px;
  border: 1px dashed $color-border-strong; border-radius: $radius-md; background: $color-bg; }
.chart-empty.inline { padding: 12px 14px; }
.ce-ico { width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; }
.ce-title { font-size: $fs-list; font-weight: 800; }
.ce-text { font-size: $fs-meta; line-height: 1.8; color: $color-text-secondary; max-width: 640px; }
.chart-empty .tc-btn { display: inline-flex; align-items: center; gap: 6px; }

.radar-meta { display: flex; flex-direction: column; gap: 6px; margin: 6px 0 8px; }
.rm-item { display: flex; align-items: center; gap: 8px; font-size: $fs-meta; color: $color-text-secondary; flex-wrap: wrap; }
.rm-item b { color: $color-text; font-weight: 700; }
.rm-item em { font-style: normal; color: $color-text-muted; font-size: $fs-badge; }
.sw.init { background: #2577e3; }
.sw.cur { background: #e08a1e; }

.radar-tip { margin-bottom: 8px; padding: 8px 12px; border-radius: $radius-md; background: #fdf3e3;
  border: 1px solid #f2dcb6; color: #8a5a08; font-size: $fs-meta; line-height: 1.7; }

.radar-table { border: 1px solid $color-border; border-radius: $radius-md; overflow: hidden; }
.rt-head, .rt-row { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; align-items: center; }
.rt-head { background: $color-bg; font-size: $fs-badge; font-weight: 700; color: $color-text-secondary; }
.rt-head span, .rt-row > span { padding: 8px 10px; }
.rt-row { border-top: 1px solid $color-border; font-size: $fs-meta; }
.rt-row:hover { background: $color-primary-softer; }
.rt-dim { display: flex; align-items: center; gap: 8px; color: $color-text; }
.rt-dim .tag { font-size: $fs-badge; font-weight: 700; color: $color-primary; background: $color-primary-soft; padding: 1px 6px; border-radius: 5px; font-style: normal; }
.rt-v { font-weight: 700; }
.rt-v.initial-text { color: #8494aa; }
.rt-v.learning-text { color: #2577e3; }
.rt-v.practice-text { color: #d67a10; }
.rt-v.cur { color: #e08a1e; }
.rt-v.na { color: $color-text-muted; font-weight: 500; }
.rt-d { font-weight: 700; color: $color-text-secondary; }
.rt-d.up { color: $color-success; }
.rt-d.down { color: $color-danger; }
.rt-d.na { color: $color-text-muted; font-weight: 500; }

.trend-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 6px; }
.ts { border: 1px solid $color-border; border-radius: $radius-md; padding: 10px 12px; background: $color-primary-softer; }
.ts.order { background: #fff9f1; border-color: #f2e0c8; }
.ts-l { font-size: $fs-badge; font-weight: 700; color: $color-text-secondary; }
.ts-v { display: flex; align-items: baseline; gap: 6px; margin: 3px 0 2px; }
.ts-v b { font-size: $fs-num-lg; font-weight: 800; color: #2577e3; }
.ts.order .ts-v b { color: #e08a1e; }
.ts-v i { font-style: normal; font-size: $fs-badge; color: $color-text-muted; }
.ts-m { font-size: $fs-badge; color: $color-text-secondary; line-height: 1.6; }
.ts-m b { color: $color-text; }
.trend-note { margin-top: 8px; font-size: $fs-meta; line-height: 1.75; color: $color-text-secondary; }
.trend-note b { color: $color-text; }

/* 维度钻取 */
.dims { display: flex; flex-direction: column; gap: 8px; }
.dim { border: 1px solid $color-border; border-radius: $radius-md; overflow: hidden; transition: box-shadow .2s ease, border-color .2s ease; }
.dim.open { border-color: #cfe0f7; box-shadow: 0 4px 16px rgba(37,119,227,0.08); }
.dim-head { display: flex; align-items: center; gap: 12px; padding: 11px 14px; cursor: pointer; user-select: none; }
.dim-head:hover { background: $color-primary-softer; }
.tag { font-size: 15px; font-weight: 700; color: $color-primary; background: $color-primary-soft; padding: 2px 8px; border-radius: 5px; }
.dn { font-size: 17.5px; font-weight: 700; width: 170px; }
.dim-meters { flex: 1; display: flex; gap: 16px; max-width: 360px; }
.meter { display: flex; align-items: center; gap: 7px; width: 100%; }
.ml { font-size: 14.5px; color: $color-text-secondary; width: 26px; }
.track { position: relative; flex: 1; height: 6px; border-radius: 999px; background: #eef1f5; overflow: hidden; }
.track i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; transition: width .6s cubic-bezier(.4,0,.2,1); }
.track i.teach { background: #2577e3; }
.track i.real { background: #e08a1e; }
.avg { font-size: 15px; color: $color-text-secondary; white-space: nowrap; }
.avg b { color: #2577e3; font-weight: 800; }
.avg b.real { color: #e08a1e; }
.chev { color: $color-text-muted; transition: transform .25s ease; }
.dim.open .chev { transform: rotate(90deg); }

.expand-wrap { display: grid; grid-template-rows: 1fr; }
.dim-body { overflow: hidden; min-height: 0; display: flex; flex-direction: column; gap: 3px; padding: 0 14px 12px; background: #fbfdff; border-top: 1px solid $color-border; }
.expand-enter-active, .expand-leave-active { transition: grid-template-rows .4s cubic-bezier(.4,0,.2,1), opacity .25s ease; }
.expand-enter-from, .expand-leave-to { grid-template-rows: 0fr; opacity: 0; }
.expand-enter-to, .expand-leave-from { grid-template-rows: 1fr; opacity: 1; }

.sp { display: flex; align-items: center; gap: 10px; padding: 9px 8px; border-radius: 6px; font-size: 15.5px; cursor: pointer; }
.sp:hover { background: $color-primary-softer; }
.pid { font-family: ui-monospace, monospace; font-size: 14.5px; color: $color-text-muted; width: 38px; }
.pn { flex: 1; font-weight: 500; }
.cp { font-size: 14px; padding: 1px 7px; border-radius: 999px; background: #eef1f5; color: $color-text-muted; white-space: nowrap; }
.cp.B { background: #fff3e0; color: #b8741a; }
.sp-bars { width: 180px; display: flex; flex-direction: column; gap: 3px; }
.lv { font-size: 14px; font-weight: 800; width: 28px; text-align: center; padding: 2px 0; border-radius: 5px; }
.lv-M1 { color: #e04b4b; background: #fdecec; }
.lv-M2 { color: #e08a1e; background: #fdf2e2; }
.lv-M3 { color: #4a8ff0; background: #eaf3fe; }
.lv-M4 { color: #2577e3; background: #e0edfc; }
.lv-M5 { color: #12a76a; background: #e5f7ee; }
.go { font-size: 14.5px; color: $color-primary; opacity: 0; }
.sp:hover .go { opacity: 1; }

/* 画像记忆 */
.memory .panel-head { align-items: center; flex-wrap: wrap; gap: 10px; }
.mem-kind { font-size: 13.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft;
  padding: 3px 11px; border-radius: 999px; }
.mem-time { font-size: 14px; color: $color-text-muted; }
.mem-refresh { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px;
  border: none; border-radius: 999px; cursor: pointer; color: #fff; font-size: 15px; font-weight: 700;
  background: linear-gradient(135deg, #2f7ff0, #1a63c4);
  box-shadow: 0 6px 16px rgba(37,119,227,0.26);
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease, filter .18s ease; }
.mem-refresh:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(37,119,227,0.34); filter: brightness(1.04); }
.mem-refresh:active:not(:disabled) { transform: translateY(0); }
.mem-refresh:disabled { background: linear-gradient(135deg, #8fbdf5, #6fa3e6); cursor: default; box-shadow: none; }
.mem-refresh:disabled svg { animation: memSpin .9s linear infinite; }
@keyframes memSpin { to { transform: rotate(360deg); } }

.mem-summary { position: relative; margin-top: 4px; padding: 16px 20px 16px 24px; border-radius: $radius-md;
  background: linear-gradient(135deg, #f7fbff, #f2f7ff); border: 1px solid #e4eefb;
  font-size: 17px; line-height: 2; letter-spacing: .2px; color: $color-text; }
.mem-summary::before { content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
  border-radius: 0 3px 3px 0; background: linear-gradient(180deg, $color-primary, #6aa9f7); }

.mem-label { margin: 20px 0 10px; font-size: 15px; font-weight: 700; color: $color-text-secondary;
  letter-spacing: .4px; }
.mem-label::after { content: ''; display: block; margin-top: 7px; height: 1px;
  background: linear-gradient(90deg, #e4eefb, rgba(228,238,251,0)); }

.mem-strengths { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 9px; }
.strength { display: flex; align-items: flex-start; gap: 10px; padding: 11px 14px; border-radius: $radius-md;
  background: #f6fbf8; border: 1px solid #e2f1e8; font-size: 15.5px; line-height: 1.75; color: $color-text; }
.st-dot { width: 7px; height: 7px; flex-shrink: 0; margin-top: 9px; border-radius: 50%; background: #12a76a; }

.mem-sugs { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; }
.mem-sug { display: flex; flex-direction: column; border: 1px solid $color-border; border-radius: $radius-md;
  padding: 16px 18px 15px; background: #fff; box-shadow: 0 2px 10px rgba(23,52,94,0.04);
  animation: sugIn .46s cubic-bezier(.34,1.2,.6,1) both;
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease, border-color .18s ease; }
.mem-sug:hover { transform: translateY(-2px); border-color: #cfe0f7; box-shadow: 0 12px 26px rgba(37,119,227,0.12); }
@keyframes sugIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.ms-head { display: flex; align-items: center; gap: 10px; padding-bottom: 11px; border-bottom: 1px dashed #e8eef7; }
.ms-dim { font-size: 13.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft;
  padding: 3px 10px; border-radius: 6px; white-space: nowrap; }
.ms-title { font-size: 16.5px; font-weight: 800; line-height: 1.5; }
.ms-line { display: flex; gap: 10px; margin-top: 11px; }
.ms-k { flex-shrink: 0; width: 46px; font-size: 14px; font-weight: 700; color: $color-text-muted; line-height: 1.75; }
.ms-v { flex: 1; font-size: 15.5px; line-height: 1.8; color: $color-text-secondary; }
.ms-line:nth-of-type(3) .ms-v { color: $color-text; }
.ms-go { align-self: flex-start; margin-top: 14px; display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: 999px; cursor: pointer; font-size: 14.5px; font-weight: 700;
  color: $color-primary; background: $color-primary-softer; border: 1px solid #d8e7fa;
  transition: all .18s ease; }
.ms-go:hover { background: $color-primary; border-color: $color-primary; color: #fff; }
.ms-go svg { transition: transform .18s ease; }
.ms-go:hover svg { transform: translateX(3px); }

.mem-empty { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 8px 0 4px; }
.me-text { font-size: 16px; line-height: 1.8; color: $color-text-secondary; max-width: 820px; }
.mem-empty .tc-btn { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
</style>
