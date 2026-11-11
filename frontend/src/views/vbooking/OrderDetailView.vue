<template>
  <div class="vb">
    <div class="vb-crumb">
      <span class="lnk" @click="router.push('/practice')">订单管理</span> &gt;
      <span class="lnk" @click="router.push(`/practice/orders/${orderId}`)">订单详情</span> &gt;
      <span class="mono">{{ orderId }}</span>
    </div>

    <!-- 订单加载失败：给错误原因 + 重试，不再显示空白骨架 -->
    <div v-if="orderError" class="card sec err-card" data-testid="order-error">
      <div class="err-title"><SIcon name="warn" :size="15" /> 订单加载失败</div>
      <div class="err-msg">{{ orderError }}</div>
      <div class="err-foot">
        <button class="tc-btn ghost" @click="router.push('/practice')">
          <SIcon name="back" :size="14" /> 返回订单管理
        </button>
        <button class="tc-btn" @click="loadOrder">
          <SIcon name="refresh" :size="14" /> 重试
        </button>
      </div>
    </div>

    <div v-else class="vb-body">
      <!-- 左主区 -->
      <section class="main-col">
        <div class="card head">
          <div class="head-left">
            <div class="row"><span class="k">提交时间</span><span class="v mono">{{ order?.created_at || '—' }}</span></div>
            <div class="row"><span class="k">需求单号</span><span class="v mono red">{{ orderId }}</span></div>
            <div class="row"><span class="k">客户</span><span class="v">{{ order?.customer || '客户' }}（{{ order?.destination || '—' }}）</span></div>
            <div class="row"><span class="k">客源地</span><span class="v">{{ order?.source_market || '—' }}<span class="src-tag">入境接待</span></span></div>
          </div>
          <div class="head-right">
            <!-- 入口落到「当前阶段」：优先按 journey 给的下一步交付物打开，没有就按本阶段第一份文档 -->
            <button class="tc-btn head-cta" data-testid="workbench-cta"
              @click="openWorkbench(nextAction?.deliverable || currentDocCode)">
              <SIcon name="filetext" :size="15" /> 文件夹
            </button>
            <button class="tc-btn ghost head-cta" data-testid="order-score-cta"
              @click="router.push(`/practice/orders/${orderId}/score`)">
              <SIcon name="chart" :size="15" /> 评分复盘
            </button>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>客户通话</span></div>
          <div class="call-row">
            <div class="call-info">
              <div class="ci-name">{{ order?.customer || '客户' }}</div>
              <div class="ci-hint">接通后按流程完成需求挖掘</div>
            </div>
            <button class="tc-btn call-btn" @click="startCall()"><SIcon name="mic" :size="14" /> 拨打电话</button>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>基础信息</span></div>
          <div class="grid2">
            <div class="row"><span class="k">服务语言</span><span class="v">{{ order?.language || '中文' }}</span></div>
            <div class="row"><span class="k">商家服务人员</span><span class="v">定制师 · {{ user.consultantName }}</span></div>
          </div>
          <div class="row mt"><span class="k">入境证件</span><span class="v">{{ order?.documents || '—' }}</span></div>
        </div>

        <div v-if="order?.dispatch" class="card tl">
          <template v-if="!order.dispatch.claimed && !order.dispatch.lost">
            <Countdown :until="order.dispatch.window_end" prefix="抢单窗口剩" />
            <span class="tl-note">{{ order.dispatch.rivals }} 位定制师同时在抢，最快的一位约 {{ order.dispatch.rival_eta_min }} 分钟后会接走</span>
          </template>
          <template v-else-if="order.dispatch.first_call">
            <Countdown :until="order.dispatch.first_call.due_at" prefix="首呼时限剩" />
            <Countdown :until="order.dispatch.plan.due_at" prefix="方案时限剩" />
          </template>
          <span v-if="order.dispatch.lost" class="tl-lost">{{ order.dispatch.lost_reason }}</span>
        </div>

        <!-- 六阶段文档入口：阶段分区 + 当前阶段置顶 + 该阶段唯一主动作（R01） -->
        <div class="card sec" data-testid="stage-docs">
          <div class="sec-title title-rule">
            <span>订单工作流</span>
            <span class="dw-stat">
              <b>{{ stepDone }}</b> / {{ stepTotal }} 步完成
            </span>
          </div>

          <div v-if="journeyError" class="err-inline" data-testid="journey-error">
            <span class="err-msg">{{ journeyError }}</span>
            <button class="tc-btn ghost sm" :disabled="journeyLoading" @click="refreshJourney()">
              <SIcon name="refresh" :size="13" /> {{ journeyLoading ? '重试中…' : '重试' }}
            </button>
          </div>

          <div v-if="journeyLoading && !availableStages.length" class="doc-empty">流程进度加载中…</div>
          <div v-else-if="!availableStages.length" class="doc-empty">暂无流程进度数据</div>

          <div v-else class="stage-list">
            <div v-for="s in availableStages" :key="s.id" class="stage-row"
              :class="[s.state, { first: s.id === currentStageId, folded: !isExpanded(s) }]"
              :data-testid="`stage-${s.id}`" :data-stage-state="s.state">
              <button class="st-head" type="button" :aria-expanded="isExpanded(s)"
                @click="toggleStage(s)">
                <span class="st-name">{{ s.name }}</span>
                <span class="st-state" :class="s.state">{{ STATE_LABEL[s.state] || s.state }}</span>
                <span class="st-step">{{ s.done_count }}/{{ s.total_count }}</span>
                <span class="st-chev" :class="{ open: isExpanded(s) }"><SIcon name="right" :size="13" /></span>
              </button>
              <template v-if="isExpanded(s)">
                <!-- 当前阶段唯一主动作：文案取自 journey 的 next_action（不在前端另写一份动作表） -->
                <div v-if="s.id === currentStageId" class="na" data-testid="next-action">
                  <div class="na-txt">
                    <span v-if="nextAction" class="na-label">当前步骤 · {{ nextAction.label }}</span>
                    <span v-else class="na-label">本单流程已全部完成</span>
                  </div>
                  <!-- 当前阶段唯一主动作：「继续」直接走 journey 给的下一步路由 -->
                  <button v-if="nextAction" class="tc-btn na-go" data-testid="next-action-go"
                    @click="continueNext">
                    <SIcon name="right" :size="14" /> 继续
                  </button>
                </div>

                <div v-if="(s.substeps || []).length" class="doc-list">
                  <button v-for="sub in s.substeps" :key="sub.id" class="doc-row step-row"
                    :class="{ done: sub.done, current: sub.state === 'current' }" type="button"
                    :data-testid="`step-${sub.id}`"
                    @click="goStep(sub)">
                    <span class="dr-ic"><SIcon :name="sub.done ? 'check' : 'right'" :size="13" /></span>
                    <span class="step-mid"><span class="dr-name">{{ sub.name }}</span></span>
                    <span v-if="docTagOf(s, sub)" class="dr-tag">{{ docTagOf(s, sub) }}</span>
                    <span v-if="sub.done" class="dr-done">已完成</span>
                    <span class="dr-go">进入</span>
                  </button>
                </div>
                <div v-else class="doc-empty">本阶段暂无步骤</div>
              </template>
            </div>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>方案信息</span></div>
          <div v-if="!plans.length" class="plan-empty">
            <span class="chip">方案未创建</span>
            <span class="plan-hint">暂未创建方案，尽快创建并发送给客户，成团机会更大。</span>
            <button class="tc-btn" @click="createPlan">创建方案</button>
          </div>
          <div v-else class="plan-list">
            <div v-for="p in plans" :key="p.plan_id" class="plan-row">
              <span class="p-ver">V{{ p.version }}</span>
              <div class="p-mid">
                <span class="p-title">{{ p.title || ('方案 V' + p.version) }}</span>
                <span class="p-meta">
                  {{ p.status }}
                  <template v-if="p.sent_at">· 发送 {{ p.sent_at.slice(5, 16) }}</template>
                  <template v-if="p.read_at">· 客户已读 {{ p.read_at.slice(5, 16) }}</template>
                </span>
                <span v-if="p.feedback" class="p-fb">客户反馈：{{ p.feedback }}</span>
              </div>
              <span class="p-tag" :class="planClass(p)">{{ p.status }}</span>
              <button v-if="p.status === '草稿'" class="tc-btn ghost p-btn" @click="editPlan(p.plan_id)">
                继续编辑
              </button>
              <button v-else class="tc-btn ghost p-btn" @click="editPlan(p.plan_id)">查看</button>
            </div>
            <div class="plan-foot">
              <button class="tc-btn" @click="createPlan">创建新版本</button>
              <span v-if="unreadPlans" class="plan-warn">
                还有 {{ unreadPlans }} 个方案客户未阅读，可到聊天界面提醒客户
              </span>
            </div>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>订单跟进信息</span></div>
          <div v-if="order?.hint" class="guide">{{ order.hint }}</div>
          <div v-if="order?.dispatch?.plan" class="pause">
            方案最晚发送时间：
            <Countdown :until="order.dispatch.plan.due_at" prefix="剩" />
          </div>

          <div class="sub-title">客户联系记录</div>
          <table class="tbl">
            <thead><tr><th style="width:220px">联系时间</th><th style="width:140px">状态</th><th>记录</th><th style="width:70px">录音</th></tr></thead>
            <tbody>
              <tr v-for="r in contacts" :key="r.time">
                <td class="mono">{{ r.time }}</td>
                <td><span class="tag" :class="r.status.includes('已接通') || r.status.includes('已添加') ? 'ok' : 'bad'">{{ r.status }}</span></td>
                <td>{{ r.detail || '—' }}</td>
                <td>
                  <button v-if="r.has_record" class="lnk" type="button" data-testid="record-link"
                    @click="openCall">录音</button>
                  <span v-else class="muted">—</span>
                </td>
              </tr>
              <tr v-if="!contacts.length"><td colspan="4" class="muted">暂无联系记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 右侧栏 -->
      <aside class="side-col">
        <div class="card sec">
          <div class="sec-title title-rule"><span>订单状态</span></div>
          <div class="timeline">
            <div v-for="(s, i) in steps" :key="s.label" class="step" :class="s.state">
              <div class="dot-col">
                <span class="dot" />
                <span v-if="i < steps.length - 1" class="line" />
              </div>
              <div class="step-body">
                <div class="step-label">{{ s.label }}
                  <span v-if="s.urgent" class="urgent">需处理</span>
                </div>
                <div v-if="s.deadline_at" class="step-note">
                  <Countdown :until="s.deadline_at" prefix="剩" />
                </div>
                <div v-else-if="s.note" class="step-note red">{{ s.note }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>客户与订单</span></div>
          <div class="info-row"><span class="k">客户</span><span class="v">{{ order?.customer || '—' }}</span></div>
          <div class="info-row"><span class="k">客源地</span><span class="v">{{ order?.source_market || '—' }}</span></div>
          <div class="info-row"><span class="k">目的地</span><span class="v">{{ order?.destination || '—' }}</span></div>
          <div class="info-row"><span class="k">订单状态</span><span class="v">{{ order?.status || '—' }}</span></div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import Countdown from '@/components/Countdown.vue'
import client from '@/api/client'
import { useJourney } from '@/composables/useJourney'
import { useUserStore } from '@/stores/user'
import { usePracticeStore } from '@/stores/practice'
import {
  countDelivered,
  countDocs,
  currentStageDocCode,
  orderStagesForDisplay,
  workbenchRoute,
} from './orderDetailDocs'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const user = useUserStore()
const practice = usePracticeStore()
practice.setActiveOrder(orderId.value)

const order = ref<any>(null)
const orderError = ref('')
const rawSteps = ref<any[]>([])
const steps = computed(() => rawSteps.value)
const contacts = computed<any[]>(() => order.value?.contacts || [])
const plans = ref<any[]>([])
const unreadPlans = computed(() => plans.value.filter((p) => p.status === '已发送' && !p.read).length)

// 阶段、阶段状态与唯一下一步动作全部来自 journey 投影（口径来源：tripcraft/contracts/stages.py）
const {
  loading: journeyLoading,
  error: journeyError,
  stages,
  currentStageId,
  nextAction,
  refresh: refreshJourney,
} = useJourney(orderId)

const STATE_LABEL: Record<string, string> = { done: '已完成', current: '进行中', todo: '未开始' }

/** 当前阶段在最前，其余按契约 order 排（行前 1 → 行后） */
const availableStages = computed(() => orderStagesForDisplay(stages.value, currentStageId.value))

/** 工作流折叠：默认只展开当前阶段，其余阶段折叠；点阶段头可切换 */
const expandedStages = ref<Record<string, boolean>>({})
function isExpanded(s: any) { return !!expandedStages.value[s.id] }
function toggleStage(s: any) {
  expandedStages.value = { ...expandedStages.value, [s.id]: !isExpanded(s) }
}
watch(currentStageId, (id) => {
  if (id) expandedStages.value = { ...expandedStages.value, [id]: true }
}, { immediate: true })

const totalDocs = computed(() => countDocs(stages.value))
const deliveredCount = computed(() => countDelivered(stages.value))
const stepTotal = computed(() => stages.value.reduce((a, s) => a + (s.substeps?.length || 0), 0))
const stepDone = computed(() => stages.value.reduce((a, s) => a + (s.substeps || []).filter((x: any) => x.done).length, 0))

/** 当前阶段的定位交付物 code：先取未投递的那份，工作台据此直接打开 */
const currentStage = computed(() => stages.value.find((s) => s.id === currentStageId.value) || null)
const currentDocCode = computed(() => currentStageDocCode(currentStage.value))

function planClass(p: any) {
  if (p.status === '客户已确认') return 'ok'
  if (p.status === '已读') return 'read'
  if (p.status === '已发送') return 'sent'
  return 'draft'
}

async function loadPlans() {
  try { plans.value = (await client.get(`/practice/orders/${orderId.value}/plans`)).data.plans || [] }
  catch { plans.value = [] }
}

/** 进入文档提交页：带交付物 code，工作台据此直接打开对应文档 */
function openWorkbench(code = '') {
  if (code === 'itinerary') { router.push(`/practice/orders/${orderId.value}/plan/new`); return }
  router.push(workbenchRoute(orderId.value, code))
}
function openDoc(code: string) {
  if (code) openWorkbench(code)
}
function goStep(sub: any) { if (sub?.route) router.push(sub.route) }
function docTagOf(stage: any, sub: any) {
  const code = String(sub?.deliverable || '')
  if (!code) return ''
  const d = (stage?.deliverables || []).find((x: any) => x.code === code)
  if (!d) return ''
  return d.submitted ? `V${d.version} 已投递` : '未投递'
}
/** 当前阶段的唯一主动作：直接走 journey 给的下一步路由，不在前端另排一份跳转表 */
function continueNext() {
  const to = nextAction.value?.route
  if (to) router.push(to)
}
function startCall() { router.push(`/practice/orders/${orderId.value}/call`) }
function openCall() { startCall() }
function createPlan() { router.push(`/practice/orders/${orderId.value}/plan/new`) }
/** 打开某一份方案：PlanNewView 按 ?plan= 定位版本，不带就只会落到最后一份草稿 */
function editPlan(planId: string) {
  router.push(`/practice/orders/${orderId.value}/plan/new?plan=${planId}`)
}

async function loadOrder() {
  const id = orderId.value
  orderError.value = ''
  try {
    const o = await client.get(`/practice/orders/${id}`)
    order.value = o.data
    rawSteps.value = (o.data.steps || []).map((s: any) => ({
      label: s.label, state: s.state, note: s.note || undefined,
      urgent: !!s.urgent, deadline_at: s.deadline_at || '',
    }))
    loadPlans()
  } catch (e: any) {
    order.value = null
    rawSteps.value = []
    plans.value = []
    orderError.value = e?.response?.data?.detail
      || (e?.response ? '订单详情读取失败，请重试' : '订单详情加载失败，请检查网络后重试')
  }
}

onMounted(loadOrder)
// 同一个组件实例在不同订单之间复用时，必须重新拉数据（hash 路由不会重建组件）
watch(orderId, () => {
  practice.setActiveOrder(orderId.value)
  order.value = null
  rawSteps.value = []
  plans.value = []
  loadOrder()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.vb { width: 100%; max-width: 1240px; margin: 0 auto; }
.vb-crumb { font-size: 15.5px; color: $color-text-muted; margin-bottom: 12px; }
.vb-body { display: flex; gap: 14px; align-items: flex-start; }
.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.side-col { width: 290px; flex-shrink: 0; display: flex; flex-direction: column; gap: 12px; }

.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.head { display: flex; justify-content: space-between; align-items: flex-start; padding: 16px 18px; }
.head-right { display: flex; gap: 10px; }
.sec { padding: 16px 18px; }
.sec-title { font-size: 19px; font-weight: 800; margin-bottom: 12px; }

.row { display: flex; align-items: baseline; gap: 10px; margin-bottom: 7px; font-size: 15px; }
.row.mt { margin-top: 4px; }
.k { color: $color-text-muted; width: 88px; flex-shrink: 0; }
.v { color: $color-text; }
.muted { color: $color-text-secondary; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 15.5px; }
.red { color: #e04b4b; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
.src-tag { margin-left: 8px; font-size: 14.5px; background: #efe9fe; color: #7a5af8; border-radius: 4px; padding: 1px 7px; }

.tl { display: flex; align-items: center; gap: 10px; padding: 11px 18px; flex-wrap: wrap; }
.tl-note { font-size: 15.5px; color: $color-text-muted; }
.tl-lost { font-size: 15.5px; color: #c0392b; }

.plan-empty { display: flex; align-items: center; gap: 14px; background: $color-primary-softer; border: 1px dashed $color-border-strong; border-radius: $radius-md; padding: 18px; }
.chip { background: $color-primary-soft; color: $color-primary; font-size: 15.5px; padding: 3px 10px; border-radius: 4px; }
.plan-hint { flex: 1; font-size: 15px; color: $color-text-secondary; }
.plan-list { display: flex; flex-direction: column; gap: 10px; }
.plan-row { display: flex; align-items: flex-start; gap: 12px; border: 1px solid $color-border; border-radius: $radius-md; padding: 12px 14px; }
.p-ver { font-size: 15.5px; font-weight: 800; color: $color-primary; background: $color-primary-soft; border-radius: 5px; padding: 3px 8px; }
.p-mid { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.p-title { font-size: 15.5px; font-weight: 700; }
.p-meta { font-size: 15px; color: $color-text-muted; }
.p-fb { font-size: 15.5px; color: $color-text-secondary; }
.p-tag { font-size: 15px; border-radius: 4px; padding: 2px 8px; }
.p-tag.draft { background: #f1f4f8; color: $color-text-secondary; }
.p-tag.sent { background: #fdf3e6; color: $color-warning; }
.p-tag.read { background: $color-primary-soft; color: $color-primary; }
.p-tag.ok { background: #e8f7ee; color: $color-success; }
.p-btn { flex-shrink: 0; }
.plan-foot { display: flex; align-items: center; gap: 12px; }
.plan-warn { font-size: 15.5px; color: $color-warning; }

.guide { background: $color-primary-softer; color: $color-text-secondary; font-size: 15.5px; padding: 9px 12px; border-radius: 6px; margin-bottom: 12px; }
.pause { font-size: 15.5px; color: $color-text-secondary; margin-bottom: 14px; }
.sub-title { font-size: 17px; font-weight: 700; margin-bottom: 8px; }

.tbl { width: 100%; border-collapse: collapse; font-size: 15.5px; }
.tbl th { background: #fafbfc; text-align: left; padding: 9px 12px; color: $color-text-secondary; font-weight: 600; border-bottom: 1px solid $color-border; }
.tbl td { padding: 10px 12px; border-bottom: 1px solid #f1f3f5; }
.tag { display: inline-block; padding: 2px 9px; border-radius: 4px; font-size: 15.5px; }
.tag.ok { background: #e8f7ee; color: #12a76a; }
.tag.bad { background: #fdeceb; color: #e04b4b; }
.lnk { color: $color-primary; cursor: pointer; font-size: 15.5px; background: none; border: none; padding: 0; font-family: inherit; }
.lnk:hover { text-decoration: underline; }

.timeline { margin-bottom: 0; }
.step { display: flex; gap: 10px; }
.dot-col { display: flex; flex-direction: column; align-items: center; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #cfd6de; margin-top: 3px; }
.line { width: 1px; flex: 1; background: #e3e7ec; min-height: 22px; }
.step.done .dot { background: #12a76a; }
.step.current .dot { background: #e04b4b; box-shadow: 0 0 0 3px rgba(224,75,75,0.16); }
.step-body { padding-bottom: 12px; }
.step-label { font-size: 15px; color: $color-text-secondary; display: flex; align-items: center; gap: 8px; }
.step.done .step-label { color: $color-text; }
.step.current .step-label { color: $color-text; font-weight: 700; }
.step-note { font-size: 15.5px; margin-top: 3px; }
.urgent { font-size: 14.5px; background: #e04b4b; color: #fff; border-radius: 8px; padding: 1px 7px; }

.sec-title { display: flex; align-items: center; gap: 8px; }
.head-cta { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.dw-stat { margin-left: auto; font-size: 14px; font-weight: 500; color: $color-text-secondary; }
.dw-stat b { font-size: 16px; font-weight: 800; color: $color-primary; }

/* ── 六阶段文档入口 ── */
.stage-list { display: flex; flex-direction: column; gap: 10px; }
.stage-row { border: 1px solid $color-border; border-radius: $radius-md; padding: 12px 14px; background: #fff; }
.stage-row.todo { opacity: .72; }
.stage-row.first { border-color: $color-primary; background: linear-gradient(180deg, #f7fbff, #fff);
  box-shadow: 0 6px 18px rgba(37,119,227,0.10); opacity: 1; }
.st-head { display: flex; align-items: baseline; gap: 9px; width: 100%; padding: 0; border: 0;
  background: none; font-family: inherit; text-align: left; cursor: pointer; }
.st-chev { margin-left: 4px; display: inline-flex; color: $color-text-muted; transition: transform .16s ease; }
.st-chev.open { transform: rotate(90deg); }
.st-name { font-size: 16px; font-weight: 700; }
.stage-row.first .st-name { color: $color-primary; }
.st-state { font-size: 13px; border-radius: 999px; padding: 1px 9px; background: #f1f4f8; color: $color-text-muted; }
.st-state.done { background: #e8f7ee; color: $color-success; }
.st-state.current { background: $color-primary-soft; color: $color-primary; }
.st-step { margin-left: auto; font-size: 14px; color: $color-text-muted; }
.doc-list { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.na { margin-top: 10px; display: flex; align-items: center; gap: 12px; background: $color-primary-soft;
  border-radius: 8px; padding: 8px 12px; }
.na-txt { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.na-label { font-size: 15px; font-weight: 700; color: $color-primary; }
.na-detail { font-size: 14.5px; color: $color-text-secondary; }
.na-go { flex-shrink: 0; display: inline-flex; align-items: center; gap: 5px; }
.doc-row { display: flex; align-items: center; gap: 10px; text-align: left; width: 100%; cursor: pointer;
  border: 1px solid $color-border; border-radius: $radius-md; background: #fff; padding: 9px 12px;
  font-family: inherit; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }
.doc-row:hover { border-color: $color-primary; transform: translateY(-1px); box-shadow: 0 6px 18px rgba(37,119,227,0.12); }
.step-mid { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.doc-row.current { border-color: $color-primary; background: $color-primary-soft; }
.step-row { align-items: flex-start; }
.step-row .dr-ic { margin-top: 1px; }
.dr-ic { width: 24px; height: 24px; flex-shrink: 0; border-radius: 8px; display: flex; align-items: center;
  justify-content: center; background: $color-primary-soft; color: $color-primary; }
.dr-name { flex: 1; min-width: 0; font-size: 15.5px; font-weight: 600; }
.dr-tag { font-size: 13px; color: $color-text-muted; white-space: nowrap; }
.dr-go { font-size: 14px; color: $color-primary; white-space: nowrap; }
.dr-done { font-size: 12px; line-height: 1; padding: 3px 8px; border-radius: 999px;
  background: #e8f7ee; color: #12a76a; font-weight: 600; white-space: nowrap; }
.doc-empty { margin-top: 8px; font-size: 15px; color: $color-text-muted; }

/* ── 错误态与重试 ── */
.err-card { border-color: #f3c9c4; }
.err-title { display: flex; align-items: center; gap: 7px; font-size: 17px; font-weight: 700; color: $color-danger; margin-bottom: 8px; }
.err-msg { font-size: 15.5px; color: $color-text-secondary; }
.err-foot { margin-top: 14px; display: flex; gap: 10px; }
.err-inline { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  background: #fdf1f0; border-radius: 8px; padding: 9px 12px; margin-bottom: 10px; }
.err-inline .err-msg { color: $color-danger; }
.tc-btn.sm { min-height: 32px; padding: 5px 12px; font-size: 14px; }

.call-row { display: flex; align-items: center; gap: 14px; }
.call-info { flex: 1; }
.ci-name { font-size: 19px; font-weight: 800; }
.ci-hint { margin-top: 3px; font-size: 15.5px; color: $color-text-muted; }
.call-btn { padding: 8px 18px; }

.info-row { display: flex; justify-content: space-between; font-size: 15.5px; margin-bottom: 8px; }
.info-row:last-child { margin-bottom: 0; }
</style>
