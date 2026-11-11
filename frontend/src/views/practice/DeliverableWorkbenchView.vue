<template>
  <div class="dw">
    <div class="dw-head">
      <button class="back" data-role="back-order" @click="router.push(`/practice/orders/${orderId}`)">
        <SIcon name="back" :size="13" /> 返回订单
      </button>
      <span class="dw-oid">{{ orderId }}</span>
      <span v-if="order" class="dw-cust">{{ order.customer }} · {{ order.source_market }} · {{ order.destination }}</span>
      <span v-if="currentStageLabel" class="dw-stage" data-role="current-stage">{{ currentStageLabel }}</span>
    </div>

    <div class="dw-body">
      <section class="dw-main">
        <div v-if="stageError" class="tab-err" data-role="stage-error">
          <span>阶段信息加载失败：{{ stageError }}</span>
          <button class="mini" @click="reloadStages">重试</button>
        </div>

          <div class="card f-head">
            <div ref="documentPickerRef" class="doc-picker" @keydown="onDocumentPickerKey" @focusout="onDocumentPickerBlur">
              <button ref="documentTriggerRef" class="doc-picker-btn" type="button"
                data-role="document-picker" aria-haspopup="listbox" aria-controls="document-options"
                :aria-expanded="documentMenuOpen ? 'true' : 'false'" :disabled="!documentChoices.length || submitting || importBusy"
                @click="documentMenuOpen = !documentMenuOpen">
                <span class="doc-picker-title">{{ selectedDocumentTitle }}</span>
                <span class="doc-picker-chevron" :class="{ open: documentMenuOpen }" aria-hidden="true" />
              </button>
              <transition name="doc-menu">
                <div v-if="documentMenuOpen" id="document-options" class="doc-picker-menu" role="listbox"
                  aria-label="选择需要填写的文件">
                  <button v-for="d in documentChoices" :key="d.code" type="button" class="doc-picker-option"
                    :class="{ selected: d.code === activeCode }" role="option"
                    :aria-selected="d.code === activeCode ? 'true' : 'false'"
                    :aria-label="d.title + (d.submitted ? '，已提交' : '')"
                    data-role="doc-tab" :data-code="d.code" @click="selectDocument(d.code)">
                    <span>{{ d.title }}</span>
                    <SIcon v-if="d.submitted" name="check" :size="16" class="doc-submitted-check" />
                  </button>
                </div>
              </transition>
            </div>
            <div v-if="spec" class="fh-r">
              <span v-if="savedVersion" class="fh-ver" data-role="saved-version">
                <SIcon name="check" :size="13" /> 已提交 V{{ savedVersion }}
              </span>
              <button class="exp import-template" type="button" data-role="import-template"
                :disabled="importBusy || submitting || opening || !pendingDocumentCount" @click="importTemplates">
                <span v-if="importBusy" class="spin" />
                <SIcon v-else name="filetext" :size="15" />
                {{ importBusy ? '导入中…' : '导入模板' }}
              </button>
              <div class="exp-group">
                <button class="exp" :disabled="pdfBusy || opening || importBusy" data-role="export-pdf" @click="exportPdf">
                  <span v-if="pdfBusy" class="spin" />
                  <SIcon v-else name="download" :size="15" />
                  <span class="ex-t">导出 <i class="ex-fmt">PDF</i></span>
                </button>
              </div>
              <button class="tc-btn submit-btn" :class="{ sending: submitting, done: documentSubmitted }"
                :disabled="submitting || importBusy || opening || documentSubmitted"
                data-role="submit" :aria-busy="submitting ? 'true' : 'false'" @click="submit">
                <span v-if="submitting" class="spin light" />
                <SIcon v-else name="check" :size="16" />
                <span class="sb-t">{{ submitting ? '提交中…' : documentSubmitted ? '已提交并投递' : (failure ? '重新提交' : '提交并投递') }}</span>
              </button>
            </div>
          </div>

        <div v-if="importMessage" class="card template-notice" :class="{ bad: importFailed }" role="status" data-role="import-result">
          {{ importMessage }}
        </div>
        <div v-if="documentSubmitted" class="submitted-note">本文件已提交并投递，内容已锁定。可继续导出 PDF 或切换至其他待填写文件。</div>

        <!-- 文件切换入口在加载失败时仍可用 -->
        <div v-if="loadError" class="card empty" data-role="list-error-main">
          <div>{{ loadError }}</div>
          <button class="tc-btn retry-docs" data-role="retry-docs" @click="retryList">重试</button>
        </div>
        <div v-else-if="!spec" class="card empty">请选择需要填写的文件</div>
        <template v-else>
          <div class="fh-purpose">{{ spec.purpose }}</div>

          <div class="document-content">
            <fieldset class="document-form" aria-label="文档内容" data-role="document-form"
              :disabled="documentSubmitted || submitting || importBusy || opening">
              <section v-for="section in formSections" :key="section.title" class="card form-section">
                <div class="section-head">
                  <SIcon name="filetext" :size="15" />
                  <h2>{{ section.title }}</h2>
                  <template v-if="section.fields.length === 1 && section.fields[0].type === 'rows'">
                    <i v-if="section.fields[0].required" class="req">*</i>
                    <span class="section-count">{{ rowsOf(section.fields[0].key).length }} 项</span>
                  </template>
                </div>
                <div class="field-grid">
                  <div v-for="f in section.fields" :key="f.key" class="fld"
                    :class="{ wide: ['textarea', 'rows', 'file'].includes(f.type) }" :data-field="f.key">
                    <label v-if="f.type !== 'rows'" class="lb" :for="`doc-${activeCode}-${f.key}`">
                      {{ f.label }}<i v-if="f.required" class="req">*</i>
                    </label>
                    <p v-if="f.help" class="help">{{ f.help }}</p>

                    <input v-if="f.type === 'text'" :id="`doc-${activeCode}-${f.key}`"
                      v-model="values[f.key]" class="inp" :placeholder="f.placeholder" />
                    <div v-else-if="f.type === 'number'" class="number-field">
                      <input :id="`doc-${activeCode}-${f.key}`" v-model="values[f.key]" type="number"
                        class="inp" :placeholder="f.placeholder" />
                      <span v-if="f.unit" class="field-unit">{{ f.unit }}</span>
                    </div>
                    <input v-else-if="f.type === 'date'" :id="`doc-${activeCode}-${f.key}`"
                      v-model="values[f.key]" type="date" class="inp" />
                    <select v-else-if="f.type === 'select'" :id="`doc-${activeCode}-${f.key}`" v-model="values[f.key]" class="inp">
                      <option value="" disabled hidden>请选择</option>
                      <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                    </select>
                    <textarea v-else-if="f.type === 'textarea'" :id="`doc-${activeCode}-${f.key}`"
                      v-model="values[f.key]" class="ta" rows="3" :placeholder="f.placeholder" />

                    <div v-else-if="f.type === 'rows'" class="entries">
                      <article v-for="(r, i) in rowsOf(f.key)" :key="i" class="entry-card">
                        <header class="entry-head">
                          <span class="entry-title">第 {{ i + 1 }} 项</span>
                          <button class="remove-entry" type="button" :aria-label="`删除${f.label}第 ${i + 1} 项`"
                            @click="removeRow(f.key, i)"><SIcon name="x" :size="14" /></button>
                        </header>
                        <div class="entry-grid">
                          <label v-for="c in f.columns" :key="c.key" class="entry-cell">
                            <span>{{ c.label }}</span>
                            <input v-model="r[c.key]" class="inp" :aria-label="`${f.label}第 ${i + 1} 项：${c.label}`" />
                          </label>
                        </div>
                      </article>
                      <p v-if="!rowsOf(f.key).length" class="entries-empty">暂无明细，点击下方添加。</p>
                      <button class="add-entry" type="button" @click="addRow(f)">
                        <SIcon name="plus" :size="14" /> 添加一项
                      </button>
                    </div>

                    <div v-else-if="f.type === 'file'" class="file">
                      <input :id="`doc-${activeCode}-${f.key}`" type="file" @change="onFile($event, f.key)" />
                      <span v-if="files[f.key]" class="fname">{{ files[f.key].filename }}</span>
                    </div>
                  </div>
                </div>
              </section>
            </fieldset>

            <section class="card preview" aria-label="文档预览" data-role="document-preview">
              <div class="pv-head">
                <SIcon name="filetext" :size="15" />
                <span class="pv-title">
                  文档预览 · {{ customerFacing ? '客户看到的版本' : '内部文档（不会发给客户）' }}
                </span>
                <span v-if="missing.length" class="pv-miss">缺 {{ missing.length }} 项必填</span>
              </div>
              <!-- 客户版文档：预览不含成本等内部口径；内部/地接文档：预览保留自身核算内容 -->
              <p v-if="customerFacing && withheld.length" class="pv-note">
                以下内容只留在内部，不会发给对方：{{ withheld.join('、') }}。相关说明请写到「内部核算说明」那一栏。
              </p>
              <div class="pv-paper" v-html="previewHtml" />
            </section>
          </div>

          <div class="card send-row">
            <span class="sr-ic"><SIcon name="users" :size="15" /></span>
            <span class="sr-k">发送对象</span>
            <span class="sr-v">{{ sendSummary }}</span>
            <button v-if="needPicker" class="tc-btn ghost sr-edit"
              :disabled="documentSubmitted || submitting || importBusy || opening" @click="sendModal = true">
              <SIcon name="users" :size="14" /> 选择接收人
            </button>
          </div>

          <!-- 失败两类：校验拦截（改完留在本页重提） / 网络失败（留在本页可重试） -->
          <div v-if="failure" class="card result bad" :class="failure.kind" data-role="submit-failure"
            :data-kind="failure.kind">
            <div class="r-head">
              <span class="r-tag">{{ failure.title }}</span>
            </div>
            <div v-for="(x, i) in failure.reasons" :key="i" class="r-line">× {{ x }}</div>
            <div class="r-hint">{{ failure.hint }}</div>
            <div class="r-acts">
              <button v-if="failure.retryable" class="tc-btn ghost" data-role="retry-submit"
                :disabled="submitting || documentSubmitted || importBusy || opening" @click="submit">
                <span v-if="submitting" class="spin" />
                {{ submitting ? '提交中…' : '重试提交' }}
              </button>
              <span class="r-keep">表单内容保留在本页，可直接修改</span>
            </div>
          </div>

          <!-- 成功回执：只有服务端返回 delivered=true 才出现（版本 / 去向 / 时间 + 下一步） -->
          <div v-if="receipt" class="card result ok" data-role="receipt">
            <div class="r-head">
              <span class="r-tag">已投递</span>
              <span class="r-ver" data-role="receipt-version">版本 V{{ receipt.version }}</span>
              <span class="r-at" data-role="receipt-at">{{ receipt.at }}</span>
            </div>
            <div class="r-line" data-role="receipt-targets">去向：{{ receipt.targets }}</div>
            <div v-if="receipt.message" class="r-line">{{ receipt.message }}</div>
            <div v-for="(x, i) in guardChecks" :key="i" class="r-line">
              <i class="dot" :class="x.ok ? 'ok' : 'warn'" />{{ x.name }}{{ x.detail ? '：' + x.detail : '' }}
            </div>
            <div v-for="(x, i) in receiptGuard?.semantic?.issues || []" :key="'s' + i" class="r-line">
              <i class="dot warn" />语义合规［{{ x.severity }}］{{ x.why }}
            </div>
            <div v-if="receiptReply" class="r-reply">
              <span class="r-who">客户反馈</span>{{ receiptReply }}
              <div v-for="(a, i) in receiptAsks" :key="i" class="r-ask">客户追问：{{ a }}</div>
            </div>
            <div v-if="receiptGates" class="r-gate">
              当前门槛 {{ receiptGates.done }}/{{ receiptGates.total }} · {{ receiptGates.stage_name }}
              <span v-if="receiptGates.next" class="r-next">下一步：{{ receiptGates.next.hint }}</span>
            </div>
            <div class="r-next-row">
              <button v-if="receiptNext" class="tc-btn" data-role="next-action" @click="goNext">
                <SIcon name="right" :size="14" /> {{ receiptNext.label || '下一步' }}
              </button>
              <span v-if="receiptNext" class="r-next-detail">{{ receiptNext.detail }}</span>
              <span v-else class="r-next-detail">本单六阶段已走完，没有更多待办。</span>
              <button class="tc-btn ghost" data-role="back-order" @click="router.push(`/practice/orders/${orderId}`)">
                返回订单
              </button>
            </div>
          </div>
        </template>
      </section>
    </div>

    <PracticeCompletionDialog :open="trainingComplete" @continue="goScoreReview" />

    <!-- 选择接收人：向聊天界面的会话列表靠齐 -->
    <transition name="pop">
      <div v-if="sendModal" class="modal-mask" @click.self="sendModal = false">
        <div class="modal">
          <div class="dlg-head">
            <span class="dlg-title">选择接收人</span>
            <span class="dlg-sub">{{ spec?.title }} · 勾选后提交即投递</span>
            <button class="dlg-x" @click="sendModal = false"><SIcon name="x" :size="16" /></button>
          </div>
          <div class="dlg-body">
            <button v-for="t in targetOptions" :key="t.session_id" class="pick"
              :class="{ on: pickedTargets.includes(t.session_id) }" @click="toggleTarget(t.session_id)">
              <span class="pk-av" :class="{ on: pickedTargets.includes(t.session_id) }">{{ (t.name || '?').slice(0, 1) }}</span>
              <span class="pk-mid">
                <span class="pk-name">{{ t.name }}</span>
                <span class="pk-hint">{{ t.hint }}</span>
              </span>
              <span class="pk-kind">{{ t.kind }}</span>
              <span class="pk-check"><SIcon name="check" :size="13" /></span>
            </button>
            <div v-if="!targetOptions.length" class="dlg-empty">
              暂无可投递的会话，请先到聊天界面添加客户或地接的联系方式
            </div>
          </div>
          <div class="dlg-foot">
            <span class="dlg-count">已选 {{ pickedTargets.length }} 个会话</span>
            <button class="tc-btn ghost" @click="sendModal = false">取消</button>
            <button class="tc-btn" @click="sendModal = false">确认</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import SIcon from '@/components/SIcon.vue'
import PracticeCompletionDialog from '@/components/PracticeCompletionDialog.vue'
import client from '@/api/client'
import { useStages } from '@/composables/useStages'
import { useJourney } from '@/composables/useJourney'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const list = ref<any[]>([])
const loadError = ref('')
const spec = ref<any>(null)
const activeCode = ref('')
const values = ref<Record<string, any>>({})
const fileIds = ref<Record<string, string>>({})
const files = ref<Record<string, any>>({})
const preview = ref('')
const previewHtml = ref('')
const withheld = ref<string[]>([])
const customerFacing = ref(true)
const missing = ref<string[]>([])
const order = ref<any>(null)
const savedVersion = ref(0)
const sendModal = ref(false)
const trainingComplete = ref(false)
const trainingCompletion = ref<any>(null)
const pdfBusy = ref(false)
const importBusy = ref(false)
const importMessage = ref('')
const importFailed = ref(false)
const opening = ref(false)
const localDrafts = ref<Record<string, Record<string, any>>>({})
const pendingDocumentCount = computed(() => list.value.filter(d => !d.submitted).length)
const documentSubmitted = computed(() => savedVersion.value > 0 || !!receipt.value
  || !!list.value.find(d => d.code === spec.value?.code)?.submitted)
const documentMenuOpen = ref(false)
const documentPickerRef = ref<HTMLElement | null>(null)
const documentTriggerRef = ref<HTMLButtonElement | null>(null)

// 与行程方案一致：按填写任务分区；字段定义与提交数据仍取自文档契约。
const DOCUMENT_SECTIONS: Record<string, [string, string[]][]> = {
  requirement_sheet: [
    ['基本信息', ['guest', 'source', 'people', 'dates', 'route']],
    ['需求分类', ['must', 'want', 'alternative', 'refuse']],
    ['预算与出行提醒', ['budget', 'docs', 'taboo', 'decision', 'note']],
  ],
  resource_quote: [
    ['资源信息', ['supplier', 'kind', 'availability', 'deadline']],
    ['报价说明', ['quote', 'included']],
    ['资源比价', ['compare']],
    ['备选与备注', ['backup', 'note']],
  ],
  quotation: [
    ['基本信息', ['people', 'dates']],
    ['分项明细', ['items']],
    ['费用与支付说明', ['total', 'per_person', 'insurance', 'pending', 'fx', 'note']],
    ['内部核算', ['cost', 'internal_note']],
  ],
  contract: [
    ['合同签署', ['contract_no', 'sign_date', 'sign_way', 'customer_signed']],
    ['保险信息', ['policy_no', 'insurer', 'insure_date', 'coverage']],
    ['定金与付款', ['deposit', 'deposit_at', 'deposit_state', 'pay_way', 'order_note']],
  ],
  departure_notice: [
    ['集合与联络', ['gather', 'guide', 'contact']],
    ['行前提醒', ['daily', 'docs', 'taboo', 'weather', 'confirm']],
  ],
  settlement: [
    ['结算信息', ['settle_no']],
    ['逐项核对', ['items']],
    ['汇总核对', ['total_settle', 'total_ours', 'diff']],
    ['差异处理', ['reason', 'decision']],
    ['内部核算', ['actual_cost', 'actual_margin']],
  ],
  review: [
    ['回访信息', ['time', 'satisfaction', 'balance_state']],
    ['客户反馈与补救', ['quote', 'issue', 'remedy']],
    ['本单复盘', ['good', 'improve', 'next', 'profit']],
  ],
}
const formSections = computed(() => {
  const fields: any[] = spec.value?.fields || []
  const remaining = new Map<string, any>(fields.map(f => [f.key, f]))
  const sections: { title: string; fields: any[] }[] = []
  for (const [title, keys] of DOCUMENT_SECTIONS[spec.value?.code] || []) {
    const grouped = keys.flatMap(key => {
      const field = remaining.get(key)
      remaining.delete(key)
      return field ? [field] : []
    })
    if (grouped.length) sections.push({ title, fields: grouped })
  }
  // 新增契约字段仍会显示；明细各自成区，避免新增文件需要同步一份字段定义。
  const extra = [...remaining.values()].filter(f => f.type !== 'rows')
  if (extra.length) sections.push({ title: sections.length ? '补充说明' : '基本信息', fields: extra })
  for (const field of remaining.values()) {
    if (field.type === 'rows') sections.push({ title: field.label, fields: [field] })
  }
  return sections
})

/* ── 提交状态：submitting 同时是「防重复点击」与「提交中动画」的唯一开关 ── */
const submitting = ref(false)
const receipt = ref<any>(null)
const failure = ref<{ kind: 'validation' | 'network'; title: string; reasons: string[]; hint: string; retryable: boolean } | null>(null)
const submitNextAction = ref<any>(null)
const listNextAction = ref<any>(null)
const receiptRaw = ref<any>(null)

/* ── 六阶段：阶段表只从 /practice/stages 取（不在前端内置第二份阶段表） ── */
const { stages: stageDefs, stageOfDeliverable, error: stageError, load: loadStages } = useStages()
const { currentStageId: journeyStageId, nextAction: journeyNextAction, refresh: refreshJourney } = useJourney(orderId)
const listCurrentStage = ref('')

const currentStageId = computed(() => listCurrentStage.value || journeyStageId.value || '')
const nextAction = computed<any>(
  () => submitNextAction.value || listNextAction.value || journeyNextAction.value || null,
)
const receiptNext = computed<any>(() => (nextAction.value?.route ? nextAction.value : null))

function stageDefOf(id: string) {
  return id ? stageDefs.value.find((s) => s.id === id) : undefined
}

/** 阶段角标：「行前N」由阶段顺序派生，行中 / 行后用契约里的 short，不写死阶段表。 */
function badgeOf(order: number, name: string, short: string): string {
  if (name.includes('行前')) return `行前${order}`
  return short || name
}

/** 每个交付物归到哪个阶段：优先接口字段，其次 /practice/stages 的 stage_of_deliverable。 */
function stageOf(d: any): { id: string; name: string; order: number; focus: string; short: string } {
  const sid: string = d.stage || stageOfDeliverable.value[d.code] || ''
  const def = stageDefOf(sid)
  return {
    id: sid,
    name: d.stage_name || def?.name || '',
    order: Number(d.stage_order ?? def?.order ?? 99),
    focus: def?.focus || '',
    short: def?.short || '',
  }
}

const stageGroups = computed(() => {
  const cur = currentStageId.value
  const buckets = new Map<string, any>()
  const unstaged: any[] = []
  const items = list.value.map((d) => {
    const st = stageOf(d)
    return {
      ...d,
      isNext: !!d.is_next || (!!nextAction.value?.deliverable && nextAction.value.deliverable === d.code),
      _stage: st,
    }
  })
  for (const d of items) {
    if (!d._stage.id) { unstaged.push(d); continue }
    let g = buckets.get(d._stage.id)
    if (!g) {
      g = {
        key: d._stage.id,
        badge: badgeOf(d._stage.order, d._stage.name, d._stage.short),
        label: d._stage.name || d._stage.id,
        hint: d._stage.focus,
        order: d._stage.order,
        isCurrent: d._stage.id === cur,
        items: [] as any[],
      }
      buckets.set(d._stage.id, g)
    }
    g.items.push(d)
  }
  const rank = (d: any) => (d.isNext ? 0 : d.submitted ? 2 : 1)
  const groups = [...buckets.values()]
  for (const g of groups) {
    g.items.sort((a: any, b: any) => rank(a) - rank(b))
    g.submittedCount = g.items.filter((d: any) => d.submitted).length
  }
  // 当前阶段置顶，其余按阶段顺序（行前1 → 行后）
  groups.sort((a, b) => (a.isCurrent === b.isCurrent ? a.order - b.order : a.isCurrent ? -1 : 1))
  if (unstaged.length) {
    groups.push({ key: '_unstaged', badge: '待归类', label: '待归类',
      hint: '暂时没能确定这些文档属于哪个阶段，稍后重试即可。',
      order: 99, isCurrent: false, items: unstaged,
      submittedCount: unstaged.filter((d) => d.submitted).length })
  }
  return groups
})

const currentGroup = computed(() => stageGroups.value.find((g) => g.isCurrent) || null)
const currentStageLabel = computed(() => {
  const g = currentGroup.value
  if (g) return `${g.badge} · ${g.label}`
  return order.value?.stage_name || ''
})
const documentChoices = computed<any[]>(() => stageGroups.value.flatMap((group) => group.items))
const selectedDocumentTitle = computed(() =>
  documentChoices.value.find((d) => d.code === activeCode.value)?.title || spec.value?.title || '选择文件',
)

function selectDocument(code: string) {
  documentMenuOpen.value = false
  documentTriggerRef.value?.focus()
  void open(code)
}

function onDocumentPickerOutside(event: MouseEvent) {
  if (!documentPickerRef.value?.contains(event.target as Node)) documentMenuOpen.value = false
}

function onDocumentPickerBlur(event: FocusEvent) {
  if (!documentPickerRef.value?.contains(event.relatedTarget as Node | null)) documentMenuOpen.value = false
}

function onDocumentPickerKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    if (!documentMenuOpen.value) return
    event.preventDefault()
    event.stopPropagation()
    documentMenuOpen.value = false
    documentTriggerRef.value?.focus()
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || submitting.value || !documentChoices.value.length) return
  event.preventDefault()
  const wasOpen = documentMenuOpen.value
  documentMenuOpen.value = true
  void nextTick(() => {
    const options = Array.from(documentPickerRef.value?.querySelectorAll<HTMLButtonElement>('[role="option"]') || [])
    if (!options.length) return
    let index = options.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Home') index = 0
    else if (event.key === 'End') index = options.length - 1
    else if (!wasOpen || index < 0) index = Math.max(0, documentChoices.value.findIndex((d) => d.code === activeCode.value))
    else index = (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
    options[index]?.focus()
  })
}

const NEEDS_PICK = ['地接社']          // 只有"要给客户以外的人"的产出才让学员选
const needPicker = computed(() => (spec.value?.audience || []).some((a: string) => NEEDS_PICK.includes(a)))
const fixedTargetsText = computed(() => {
  const map: Record<string, string> = { 客户: '客户（客户单聊，客户可直接阅读并回复）',
                                        平台: '平台报备', 内部: '内部留档（不发送）' }
  return (spec.value?.audience || []).map((a: string) => map[a] || a).join(' + ') || '内部留档'
})

const targetOptions = ref<any[]>([])
const pickedTargets = ref<string[]>([])

const guardChecks = computed<any[]>(() => receiptRaw.value?.guard?.deterministic?.checks || [])
const receiptGuard = computed<any>(() => receiptRaw.value?.guard || null)
const receiptReply = computed(() => receiptRaw.value?.routing?.customer_reply || '')
const receiptAsks = computed<string[]>(() => receiptRaw.value?.routing?.asks || [])
const receiptGates = computed<any>(() => receiptRaw.value?.gates || null)

function rowsOf(key: string) {
  if (!Array.isArray(values.value[key])) values.value[key] = []
  return values.value[key]
}
function addRow(f: any) {
  rowsOf(f.key).push({})
  loadPreview()
}
function removeRow(key: string, i: number) {
  rowsOf(key).splice(i, 1)
  loadPreview()
}

async function onFile(ev: Event, key: string) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  const buf = await f.arrayBuffer()
  let bin = ''
  const bytes = new Uint8Array(buf)
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)) as number[])
  }
  const r = (await client.post('/deliverables/files', {
    filename: f.name, mime: f.type || 'application/octet-stream',
    data_b64: btoa(bin), order_id: orderId.value, deliverable_id: spec.value?.id || '',
  })).data
  fileIds.value[key] = r.file_id
  files.value[key] = r
}

function setPreview(text: string) {
  const raw = marked.parse(text || '', { async: false, gfm: true, breaks: true, pedantic: false }) as string
  // 宽表格单独包一层，横向滚动而不是把列挤到换行
  const wrapped = raw
    .replace(/<table>/g, '<div class="pv-table"><table>')
    .replace(/<\/table>/g, '</table></div>')
  previewHtml.value = DOMPurify.sanitize(wrapped, { ADD_ATTR: ['target', 'rel'] })
}

/** 默认打开哪一份：路由指定 > 当前阶段下一个待办 > 当前阶段第一份 > 全单第一份。 */
function pickDefaultCode(): string {
  const want = String(route.query.code || '')
  if (want && list.value.some((d) => d.code === want || d.id === want)) return want
  const cur = currentStageId.value
  const inCur = list.value.filter((d) => stageOf(d).id === cur)
  const pool = inCur.length ? inCur : list.value
  const next = pool.find((d) => d.is_next)
    || pool.find((d) => !d.submitted)
    || pool[0]
  return next?.code || list.value[0]?.code || ''
}

async function loadList() {
  const oid = orderId.value
  loadError.value = ''
  try {
    const r = (await client.get(`/practice/orders/${oid}/deliverables`)).data
    if (oid !== orderId.value) return
    list.value = r.deliverables || []
    trainingCompletion.value = r.training_completion || null
    listCurrentStage.value = r.current_stage || ''
    listNextAction.value = r.next_action || null
    if (!activeCode.value && list.value.length) {
      const code = pickDefaultCode()
      if (code) await open(code)
    }
  } catch (e: any) {
    if (oid !== orderId.value) return
    // 列表加载失败：给出错误态与重试入口，不把页面留成空白（R17）
    if (!spec.value) activeCode.value = ''
    loadError.value = e?.response?.data?.detail || '交付物列表加载失败，请检查登录状态后重试'
  }
}

function retryList() {
  if (!spec.value) activeCode.value = ''
  loadList()
}

/** 打开/切换某一份交付物：选中态、正文、预览、导出都以它为准。
 *
 * 同一订单内切换文档（回执「下一步」会 push 同路径不同 `?code=`）必须走这里；
 * `openSeq` 是竞态闸门：只有最后一次选择的响应可以写入界面，晚返回的旧文档不得覆盖新选择。
 */
let openSeq = 0

function stashDraft() {
  if (spec.value && !documentSubmitted.value && !opening.value) {
    localDrafts.value[spec.value.code] = JSON.parse(JSON.stringify(values.value))
  }
}

async function open(code: string, preserveDraft = true) {
  if (code === 'requirement_sheet') {
    try {
      const r = (await client.get('/practice/im/contacts',
                                  { params: { order_id: orderId.value } })).data
      const customerAdded = (r.contacts || []).some((c: any) => c.kind === '客户' && c.added)
      if (!customerAdded) {
        await router.replace({ path: '/practice/im', query: { order: orderId.value } })
        return
      }
    } catch { /* 联系人查询失败时交给提交接口再次校验 */ }
  }
  // 行程方案统一走「行程方案」页（唯一编辑入口），工作台不再提供第二套编辑器
  const hit = list.value.find((x: any) => x.code === code || x.id === code)
  if (code === 'itinerary' || code === '行程方案' || hit?.code === 'itinerary') {
    router.replace(`/practice/orders/${orderId.value}/plan/new`)
    return
  }
  if (preserveDraft) stashDraft()
  opening.value = true
  documentMenuOpen.value = false
  const seq = ++openSeq
  previewSequence++
  activeCode.value = code
  receipt.value = null
  receiptRaw.value = null
  failure.value = null
  if (pvTimer) { clearTimeout(pvTimer); pvTimer = 0 }
  let d: any = null
  try {
    d = (await client.get(`/practice/orders/${orderId.value}/deliverables/${code}`)).data
  } catch (e: any) {
    if (seq !== openSeq) return                       // 已被更晚的选择取代：丢弃这次失败态
    // 单个文档打不开也要能重试，不能把上一次的表单留在屏幕上冒充这一次
    spec.value = null
    opening.value = false
    loadError.value = e?.response?.data?.detail || '打开这份交付物失败，请重试'
    return
  }
  if (seq !== openSeq) return                         // 晚返回的旧文档：不覆盖当前选择
  loadError.value = ''
  spec.value = d.spec
  targetOptions.value = d.target_options || []
  pickedTargets.value = (d.target_options || []).filter((t: any) => t.default)
    .map((t: any) => t.session_id)
  savedVersion.value = d.version || 0
  values.value = savedVersion.value ? (d.values || {}) : (localDrafts.value[d.spec.code] || d.values || {})
  opening.value = false
  fileIds.value = {}
  files.value = {}
  ;(d.spec.fields || []).forEach((f: any) => {
    if (f.type === 'rows' && !Array.isArray(values.value[f.key])) values.value[f.key] = [{}]
      if (f.type === 'select' && values.value[f.key] == null) values.value[f.key] = ''
  })
  preview.value = d.rendered || ''
  withheld.value = d.customer_withheld || []
  customerFacing.value = d.customer_facing !== false
  setPreview(preview.value)
  await loadPreview()
  // 文件菜单切换时同步 code，刷新/分享后仍是同一份文档。
  if (seq === openSeq && String(route.query.code || '') !== code) {
    router.replace({ path: route.path, query: { ...route.query, code } })
  }
}

async function loadPreview() {
  if (!spec.value) return
  const sequence = ++previewSequence
  const oid = orderId.value
  const code = spec.value.code
  try {
    const r = (await client.post(
      `/practice/orders/${orderId.value}/deliverables/${code}/preview`, { values: values.value })).data
    if (sequence !== previewSequence || oid !== orderId.value || !spec.value || spec.value.code !== code) return
    preview.value = r.rendered
    withheld.value = r.customer_withheld || []
    customerFacing.value = r.customer_facing !== false
    missing.value = r.missing || []
    setPreview(r.rendered)
  } catch { /* 预览失败不打断填写 */ }
}

function toggleTarget(id: string) {
  const i = pickedTargets.value.indexOf(id)
  if (i >= 0) pickedTargets.value.splice(i, 1)
  else pickedTargets.value.push(id)
}

const sendSummary = computed(() => {
  if (!needPicker.value) return '固定发给：' + fixedTargetsText.value
  const names = targetOptions.value.filter((t) => pickedTargets.value.includes(t.session_id)).map((t) => t.name)
  return names.length ? '将发给：' + names.join('、') : '尚未选择接收人'
})

async function importTemplates() {
  if (importBusy.value || submitting.value || opening.value || !pendingDocumentCount.value) return
  stashDraft()
  const oid = orderId.value
  const code = spec.value?.code || activeCode.value
  importBusy.value = true
  importMessage.value = ''
  importFailed.value = false
  try {
    const result = (await client.post(`/practice/orders/${oid}/deliverables/import-template`, {
      drafts: localDrafts.value,
    })).data
    if (oid !== orderId.value) return
    localDrafts.value = {}
    importMessage.value = result.message || `已为 ${result.count || 0} 份文件导入草稿。`
    await loadList()
    if (oid === orderId.value && code) await open(code, false)
  } catch (e: any) {
    if (oid !== orderId.value) return
    importFailed.value = true
    const detail = String(e?.response?.data?.detail || '')
    const backendNeedsReload = (e?.response?.status === 400 && detail.includes('未知交付物') && detail.includes('import-template'))
      || (e?.response?.status === 404 && detail === 'Not Found')
    importMessage.value = backendNeedsReload
      ? '后端尚未加载“导入模板”功能。请结束当前通话后运行“重启司南礼客.bat”，再重试。原有填写内容保留。'
      : detail || '模板导入失败，原有填写内容保留，可重试。'
  } finally { importBusy.value = false }
}

/** 导出 PDF：版式由后端按同一份渲染结果生成，前端不重拼；学员界面只保留这一个下载入口。 */
async function exportPdf() {
  if (!spec.value || pdfBusy.value) return
  pdfBusy.value = true
  try {
    const r = await client.post(
      `/practice/orders/${orderId.value}/deliverables/${spec.value.code}/export.pdf`,
      { values: values.value }, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([r.data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${spec.value.title || spec.value.code}-${orderId.value}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    alert('导出 PDF 失败，请稍后重试')
  } finally {
    pdfBusy.value = false
  }
}

function nowText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 回执去向：优先服务端 receipt.targets，其次 routing 里的会话名。 */
function targetText(r: any): string {
  const fromReceipt = (r?.receipt?.targets || []).filter(Boolean)
  if (fromReceipt.length) return fromReceipt.join('、')
  const names = (r?.routing?.targets || []).map((t: any) => t?.name).filter(Boolean)
  if (names.length) return names.join('、')
  const sent = (r?.routing?.sent_to || []).filter(Boolean)
  if (sent.length) return sent.join('、')
  return '内部留存'
}

/** 网络类失败：没有 response（断网/超时）或 5xx。其余按服务端给出的原因当校验拦截。 */
function classifyError(e: any) {
  const status = Number(e?.response?.status || 0)
  const detail = e?.response?.data?.detail
  if (!e?.response) {
    return { kind: 'network' as const, title: '网络异常，提交未完成',
      reasons: ['没有收到服务器回应：网络中断或请求超时，这次提交不算投递。'],
      hint: '内容保留在本页；网络恢复后点「重试提交」，不会重复投递。', retryable: true }
  }
  if (status >= 500) {
    return { kind: 'network' as const, title: `服务暂时不可用（HTTP ${status}）`,
      reasons: [String(detail || '服务器返回错误，未确认投递。')],
      hint: '内容保留在本页；稍后点「重试提交」即可。', retryable: true }
  }
  return { kind: 'validation' as const, title: '提交被拦截，未投递',
    reasons: [String(detail || '提交没有通过校验，请按下面的提示修改后重试。')],
    hint: '按上面的原因修改表单，留在本页直接重新提交。', retryable: true }
}

async function submit() {
  // 防重复点击：请求期间再次触发直接返回（按钮同时 disabled，双保险）
  if (!spec.value || submitting.value || documentSubmitted.value || importBusy.value || opening.value) return
  const oid = orderId.value
  const code = spec.value.code
  const sequence = openSeq
  const completionWasKnown = !!trainingCompletion.value?.completed
  submitting.value = true
  receipt.value = null
  receiptRaw.value = null
  failure.value = null
  submitNextAction.value = null
  try {
    const r = (await client.post(`/practice/orders/${oid}/deliverables/${code}`, {
      values: values.value, file_ids: Object.values(fileIds.value), submit_once: true,
      targets: needPicker.value ? pickedTargets.value : [],
    })).data
    if (oid !== orderId.value || sequence !== openSeq) return
    if (r?.delivered === true) {
      delete localDrafts.value[code]
      if (r.already_submitted) {
        const saved = (await client.get(`/practice/orders/${oid}/deliverables/${code}`)).data
        if (oid !== orderId.value || sequence !== openSeq) return
        values.value = saved.values || values.value
      }
      // 只有服务端确认投递完成（delivered === true）才展示「已投递」回执
      receiptRaw.value = r
      const rec = r.receipt || {}
      receipt.value = {
        version: rec.version ?? r.version ?? savedVersion.value,
        at: rec.at || nowText(),
        targets: targetText(r),
        message: rec.message || '',
      }
      savedVersion.value = Number(receipt.value.version) || savedVersion.value
      submitNextAction.value = r.next_action || null
      listNextAction.value = r.next_action || listNextAction.value
      if (r.training_completion) trainingCompletion.value = r.training_completion
      if (!completionWasKnown && r.training_completion?.completed && ['settlement', 'review'].includes(code)) {
        sendModal.value = false
        trainingComplete.value = true
      }
      await loadList()
      await refreshJourney()
      try { order.value = (await client.get(`/practice/orders/${orderId.value}`)).data } catch { /* 订单信息非必需 */ }
      if (code === 'requirement_sheet') {
        const customerSession = r?.routing?.im_session || ''
        await router.push({ path: '/practice/im',
                            query: { session: customerSession, order: oid } })
        return
      }
      if (code === 'departure_notice') {
        const customerSession = r?.routing?.im_session || ''
        const incident = (r?.triggered_incidents || [])[0]
        if (customerSession) {
          await router.push(`/practice/im?session=${encodeURIComponent(customerSession)}`)
          if (incident?.session_id) {
            window.setTimeout(() => {
              router.push(`/practice/im?session=${encodeURIComponent(incident.session_id)}`)
            }, 900)
          }
        } else if (incident?.session_id) {
          await router.push(`/practice/im?session=${encodeURIComponent(incident.session_id)}`)
        }
      }
    } else {
      // 服务端明确拦截（blocked）或未确认投递：留在原处展示原因，可改可重提
      const reasons: string[] = [...(r?.guard?.reasons || [])]
      if (!reasons.length && r?.message) reasons.push(String(r.message))
      if (!reasons.length) reasons.push('没有收到投递成功的确认，本次按未投递处理，可以重试。')
      failure.value = {
        kind: 'validation',
        title: r?.blocked ? '未通过校验，未投递' : '未确认投递，请核对后重提',
        reasons,
        hint: '按上面的原因修改表单，留在本页直接重新提交。',
        retryable: true,
      }
    }
  } catch (e: any) {
    if (oid === orderId.value && sequence === openSeq) failure.value = classifyError(e)
  } finally {
    submitting.value = false
  }
}

function goNext() {
  if (receiptNext.value?.route) router.push(receiptNext.value.route)
}

function goScoreReview() {
  trainingComplete.value = false
  router.push(trainingCompletion.value?.score_route || `/practice/orders/${orderId.value}/score`)
}

function reloadStages() {
  loadStages(true)
}

// 输入即刷新预览（防抖 500ms），不必手动点
let pvTimer = 0
let previewSequence = 0
watch(values, () => {
  if (!spec.value) return
  if (pvTimer) clearTimeout(pvTimer)
  pvTimer = window.setTimeout(loadPreview, 500)
}, { deep: true })

onMounted(async () => {
  document.addEventListener('mousedown', onDocumentPickerOutside)
  loadStages()                                  // 阶段表缺失不阻塞工作台，只在导航区提示重试
  try { order.value = (await client.get(`/practice/orders/${orderId.value}`)).data } catch { /* 顶部信息非必需 */ }
  await loadList()
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocumentPickerOutside)
  if (pvTimer) clearTimeout(pvTimer)
  openSeq++
})
watch(orderId, async () => {
  trainingComplete.value = false
  trainingCompletion.value = null
  localDrafts.value = {}
  importMessage.value = ''
  opening.value = false
  savedVersion.value = 0
  documentMenuOpen.value = false
  openSeq++                                     // 换单：上一单的在途响应一律作废
  activeCode.value = ''
  spec.value = null
  receipt.value = null
  failure.value = null
  listCurrentStage.value = ''
  listNextAction.value = null
  await loadList()
})

/** 同一订单内 `?code=` 变化（回执「下一步」/ 订单详情的文档入口）：正文、预览、导出一起切到新文档。 */
watch(() => String(route.query.code || ''), async (code) => {
  if (!code || code === activeCode.value) return
  if (!list.value.length) return                // 列表未到：onMounted/loadList 会按 query 选默认文档
  const known = list.value.some((d: any) => d.code === code || d.id === code)
  if (!known) {
    // 非法 code：明确报错并清空正文，绝不拿上一份文档冒充（R03/R17）
    openSeq++
    activeCode.value = ''
    spec.value = null
    receipt.value = null
    failure.value = null
    preview.value = ''
    previewHtml.value = ''
    loadError.value = '这个文档不属于本订单，请从文件菜单重新选择'
    return
  }
  await open(code)
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.dw { display: flex; flex-direction: column; gap: 16px; width: 100%; max-width: 1600px; margin: 0 auto; }
.dw-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.back { display: inline-flex; align-items: center; gap: 4px; border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 6px 14px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.dw-oid { font-family: ui-monospace, monospace; font-size: 15.5px; color: #e04b4b; }
.dw-cust { font-size: 15px; }
.dw-stage { margin-left: auto; font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 3px 12px; }

.dw-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; width: 100%; max-width: 1600px; margin: 0 auto; align-items: start; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }
.dw-main { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.empty { padding: 40px; text-align: center; color: $color-text-muted; }
.retry-docs { margin-top: 14px; }

/* 文件选择与提交操作共用一栏；菜单只显示文件名。 */
.doc-picker { position: relative; max-width: 100%; min-width: 0; }
.doc-picker-btn { display: inline-flex; align-items: center; gap: 14px; height: 42px; max-width: 100%;
  padding: 0 16px; border: 1px solid $color-border; border-radius: 999px; background: #fff;
  color: $color-text; font-family: inherit; font-size: 18px; font-weight: 700; cursor: pointer;
  transition: border-color .15s ease, box-shadow .15s ease; }
.doc-picker-btn:hover:not(:disabled), .doc-picker-btn[aria-expanded='true'] { border-color: $color-primary; box-shadow: $shadow-card; }
.doc-picker-btn:disabled { opacity: .6; cursor: default; }
.doc-picker-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-picker-chevron { width: 7px; height: 7px; flex-shrink: 0; border-right: 1.5px solid $color-text-secondary;
  border-bottom: 1.5px solid $color-text-secondary; transform: rotate(45deg) translateY(-2px); transition: transform .15s ease; }
.doc-picker-chevron.open { transform: rotate(225deg) translate(-1px, -1px); }
.doc-picker-menu { position: absolute; top: calc(100% + 8px); left: 0; z-index: 60;
  width: max-content; min-width: 100%; max-width: min(360px, calc(100vw - 64px)); max-height: min(440px, 60vh);
  overflow-y: auto; padding: 6px; border: 1px solid $color-border; border-radius: 12px;
  background: #fff; box-shadow: 0 16px 40px rgba(16,32,56,.18); }
.doc-picker-option { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  width: 100%; padding: 11px 14px; border: none; border-radius: 8px;
  background: transparent; color: $color-text; font-family: inherit; font-size: 15.5px; line-height: 1.5;
  text-align: left; cursor: pointer; overflow-wrap: anywhere; }
.doc-picker-option:hover, .doc-picker-option.selected { background: $color-primary-softer; color: $color-primary; }
.doc-picker-option.selected { font-weight: 700; }
.doc-submitted-check { flex-shrink: 0; color: $color-success; }
.doc-picker-btn:focus-visible, .doc-picker-option:focus-visible { outline: 2px solid $color-primary; outline-offset: 2px; }
.doc-menu-enter-active, .doc-menu-leave-active { transition: opacity .15s ease, transform .15s ease; }
.doc-menu-enter-from, .doc-menu-leave-to { opacity: 0; transform: translateY(-4px); }
.tab-err { display: flex; align-items: center; gap: 10px; font-size: 15px; color: #c77700;
  background: #fdf7ec; border: 1px solid #f0dcbb; border-radius: $radius-sm; padding: 8px 12px; }
.mini { font-size: 15px; border: 1px solid $color-border; background: #fff; color: $color-text-secondary;
  border-radius: $radius-sm; padding: 4px 12px; cursor: pointer; }

.f-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 18px; flex-wrap: wrap;
  position: sticky; top: 0; z-index: 8; }
.fh-r { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.fh-ver { display: inline-flex; align-items: center; gap: 5px; font-size: 15.5px; color: #0d8a55;
  background: #e8f7ee; border-radius: 999px; padding: 2px 10px; }
.fh-purpose { font-size: 16px; color: $color-text-secondary; padding: 0 4px; line-height: 1.6; }

.document-content, .document-form { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.document-form { border: 0; padding: 0; margin: 0; }
.form-section { padding: 20px 22px 22px; min-width: 0; }
.section-head { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.section-head h2 { margin: 0; font-size: $fs-body; font-weight: 700; line-height: 1.5; }
.section-count { margin-left: auto; color: $color-text-muted; font-size: $fs-meta; font-variant-numeric: tabular-nums; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; }
.fld { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.fld.wide { grid-column: 1 / -1; }
.lb { display: block; font-size: $fs-body; color: $color-text-secondary; line-height: 1.5; }
.req { color: #e04b4b; font-style: normal; margin-left: 3px; }
.help { margin: 0; font-size: $fs-meta; color: $color-text-muted; line-height: 1.6; }
.inp, .ta { width: 100%; min-width: 0; border: 1px solid $color-border-strong; border-radius: $radius-sm;
  padding: 7px 11px; font-size: $fs-body; font-family: inherit; color: $color-text; background: #fff;
  outline: none; transition: border-color .2s ease-out, box-shadow .2s ease-out; }
.inp { height: 38px; }
.inp:focus, .ta:focus { border-color: $color-primary; box-shadow: 0 0 0 2px rgba(37,119,227,.10); }
.ta { padding: 9px 11px; resize: vertical; line-height: 1.7; }
.number-field { display: flex; align-items: center; gap: 8px; }
.field-unit { flex-shrink: 0; color: $color-text-muted; font-size: $fs-meta; }
.entries { display: flex; flex-direction: column; align-items: stretch; gap: 10px; }
.entry-card { border: 1px solid $color-border; border-radius: $radius-md;
  background: linear-gradient(180deg, #fbfdff, #fff); padding: 14px 16px; }
.entry-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.entry-title { font-size: $fs-body; font-weight: 600; color: $color-primary; }
.remove-entry { width: 28px; height: 28px; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid transparent; background: none; border-radius: $radius-sm; color: $color-text-muted; cursor: pointer; }
.remove-entry:hover:not(:disabled) { color: $color-danger; border-color: $color-border; background: #fff; }
.entry-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 12px; }
.entry-cell { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.entry-cell > span { font-size: $fs-meta; color: $color-text-secondary; }
.entries-empty { margin: 0; padding: 8px 0; font-size: $fs-meta; color: $color-text-muted; }
.add-entry { align-self: flex-start; display: inline-flex; align-items: center; gap: 5px; margin-top: 2px;
  border: 1px dashed $color-border-strong; border-radius: $radius-sm; padding: 8px 14px; background: $color-primary-softer;
  color: $color-primary; font: inherit; font-size: $fs-body; cursor: pointer; }
.add-entry:hover:not(:disabled) { border-color: $color-primary; background: $color-primary-soft; }
.add-entry:focus-visible, .remove-entry:focus-visible { outline: 2px solid $color-primary; outline-offset: 2px; }
.document-form:disabled input, .document-form:disabled select, .document-form:disabled textarea {
  color: #6f7e91; background: #f6f8fb; }
.document-form:disabled .add-entry, .document-form:disabled .remove-entry { opacity: .5; cursor: default; }
.file { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.fname { font-size: 15.5px; color: #0d8a55; }

.preview { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.pv-head { display: flex; align-items: center; gap: 9px; padding: 11px 14px; border-bottom: 1px solid $color-border;
  font-size: 15.5px; font-weight: 700; flex-wrap: wrap; background: #fff; color: $color-primary; }
.pv-title { font-size: 15.5px; font-weight: 700; color: $color-text; }
.pv-miss { margin-left: auto; font-size: 15px; color: #c77700; font-weight: 400; }
.pv-note { margin: 10px 14px 0; padding: 8px 10px; font-size: 14.5px; line-height: 1.6;
  color: #8a5a00; background: #fff8ec; border: 1px solid #f2dcb6; border-radius: $radius-sm; }
/* 预览正文：页面内排版，无任何下载入口 */
.pv-paper { padding: 22px 26px 28px; font-size: 15.5px; line-height: 1.85; color: $color-text; word-break: break-word; }
.pv-paper :deep(> :first-child) { margin-top: 0; }
.pv-paper :deep(h1), .pv-paper :deep(h2), .pv-paper :deep(h3), .pv-paper :deep(h4) {
  margin: 18px 0 8px; font-weight: 700; line-height: 1.5; }
.pv-paper :deep(h1) { font-size: 20px; }
.pv-paper :deep(h2) { font-size: 16px; padding-bottom: 6px; border-bottom: 1px solid $color-border; }
.pv-paper :deep(h3) { font-size: 16.5px; }
.pv-paper :deep(p) { margin: 8px 0; }
.pv-paper :deep(ul), .pv-paper :deep(ol) { margin: 8px 0 8px 22px; }
.pv-paper :deep(ul) { list-style: disc; }
.pv-paper :deep(ol) { list-style: decimal; }
.pv-paper :deep(li) { margin: 4px 0; }
.pv-paper :deep(strong) { font-weight: 700; }
.pv-paper :deep(code) { background: #f2f4f7; border-radius: 4px; padding: 1px 5px;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 15.5px; }
.pv-paper :deep(blockquote) { margin: 10px 0; padding: 8px 14px; border-left: 3px solid $color-primary-light;
  background: $color-primary-softer; color: $color-text-secondary; border-radius: 0 6px 6px 0; }
.pv-paper :deep(hr) { border: none; border-top: 1px solid $color-border; margin: 16px 0; }
.pv-paper :deep(.pv-table) { margin: 12px 0; overflow-x: auto; border: 1px solid $color-border; border-radius: 8px; }
.pv-paper :deep(table) { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 15px; }
.pv-paper :deep(th), .pv-paper :deep(td) { border-right: 1px solid $color-border; border-bottom: 1px solid $color-border;
  padding: 8px 12px; text-align: left; vertical-align: top; min-width: 76px; white-space: normal; }
.pv-paper :deep(th:last-child), .pv-paper :deep(td:last-child) { border-right: none; }
.pv-paper :deep(th) { background: #fafbfc; font-weight: 600; color: $color-text-secondary; white-space: nowrap; }

.send-row { display: flex; align-items: center; gap: 11px; padding: 12px 16px; }
.sr-ic { width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; flex-shrink: 0; }
.sr-k { font-size: 15px; font-weight: 700; white-space: nowrap; }
.sr-v { flex: 1; min-width: 0; font-size: 15px; color: $color-text-secondary; }
.sr-edit { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }

/* ── 结果区：失败两类 + 成功回执 ── */
.result { padding: 13px 16px; animation: reveal .26s cubic-bezier(.22,.9,.3,1) both; }
.result.ok { border-left: 4px solid #12a76a; }
.result.bad { border-left: 4px solid #e04b4b; }
.result.bad.network { border-left-color: #d98324; }
@keyframes reveal { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
.r-head { display: flex; align-items: center; gap: 10px; margin-bottom: 7px; flex-wrap: wrap; }
.r-tag { font-size: 15.5px; font-weight: 700; }
.result.ok .r-tag { color: #0d8a55; }
.result.bad .r-tag { color: #c0392b; }
.result.bad.network .r-tag { color: #b5701c; }
.r-ver, .r-at { font-size: 15.5px; color: $color-text-muted; }
.r-at { margin-left: auto; }
.r-why { font-size: 15.5px; color: #c0392b; margin-bottom: 5px; }
.r-line { display: flex; align-items: center; gap: 7px; font-size: 15.5px; line-height: 1.9; color: $color-text-secondary; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #d5dce5; flex-shrink: 0; }
.dot.ok { background: #12a76a; }
.dot.warn { background: #d98324; }
.r-hint { margin-top: 7px; font-size: 15.5px; color: $color-text-muted; line-height: 1.7; }
.r-acts { display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; }
.r-keep { font-size: 14.5px; color: $color-text-muted; }
.r-reply { margin-top: 7px; font-size: 15.5px; line-height: 1.8; background: $color-primary-softer; border-radius: 8px; padding: 9px 12px; }
.r-who { font-weight: 700; color: $color-primary; margin-right: 7px; }
.r-ask { font-size: 15.5px; color: $color-text-muted; }
.r-gate { margin-top: 7px; font-size: 15.5px; color: $color-text-secondary; }
.r-next { margin-left: 8px; color: $color-primary; }
.r-next-row { display: flex; align-items: center; gap: 12px; margin-top: 12px; padding-top: 12px;
  border-top: 1px dashed $color-border; flex-wrap: wrap; }
.r-next-detail { font-size: 15px; color: $color-text-muted; }

/* ── 动作按钮 ── */
.tc-btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px; height: 36px; padding: 0 16px;
  border: 1px solid transparent; border-radius: 8px; background: $color-primary; color: #fff; font-size: 15px;
  font-family: inherit; cursor: pointer; transition: all .16s ease; }
.tc-btn:hover:not(:disabled) { background: $color-primary-dark; }
.tc-btn:disabled { opacity: .6; cursor: default; }
.tc-btn.ghost { background: #fff; color: $color-primary; border-color: $color-border; }
.tc-btn.ghost:hover:not(:disabled) { border-color: $color-primary; }
.exp-group { display: inline-flex; align-items: center; gap: 10px; }
.exp { display: inline-flex; align-items: center; gap: 7px; height: 42px; padding: 0 16px;
  border: 1px solid #d9e3f1; border-radius: $radius-md; background: linear-gradient(#ffffff, #f6faff);
  color: $color-text-secondary; font-size: 15px; font-family: inherit; cursor: pointer;
  box-shadow: 0 1px 2px rgba(16, 42, 80, 0.05); transition: all .16s ease; }
.exp:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; background: $color-primary-softer;
  box-shadow: 0 6px 14px rgba(37, 119, 227, 0.14); transform: translateY(-1px); }
.exp:disabled { opacity: .6; cursor: default; }
.ex-t { display: inline-flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.ex-fmt { font-style: normal; font-weight: 700; letter-spacing: .2px; color: $color-text; }
.exp:hover:not(:disabled) .ex-fmt { color: $color-primary; }
.submit-btn { display: inline-flex; align-items: center; gap: 8px; height: 42px; padding: 0 24px;
  border-radius: $radius-md; font-weight: 700; letter-spacing: .2px;
  background: linear-gradient(135deg, #3389f7, #1a63d8);
  box-shadow: 0 6px 16px rgba(26, 99, 216, 0.26); }
.submit-btn:hover:not(:disabled) { background: linear-gradient(135deg, #4598ff, #1a5cc6);
  box-shadow: 0 10px 22px rgba(26, 99, 216, 0.32); transform: translateY(-1px); }
.submit-btn:disabled { opacity: .72; cursor: default; }
.submit-btn.done:disabled { background: #dce1e8; color: #7d8898; box-shadow: none; opacity: 1; cursor: not-allowed; }
.import-template { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.template-notice { padding: 12px 18px; color: #28764f; background: #f0faf4; border-color: #d5e9dd; line-height: 1.8; }
.template-notice.bad { color: #a24336; background: #fff7f5; border-color: #f1d7d1; }
.submitted-note { padding: 8px 4px; font-size: 13px; color: #7c899b; line-height: 1.6; }
.submit-btn.sending { animation: pulse-send 1.4s ease-in-out infinite; }
@keyframes pulse-send { 0%, 100% { box-shadow: 0 6px 16px rgba(26, 99, 216, 0.26); }
  50% { box-shadow: 0 6px 22px rgba(26, 99, 216, 0.48); } }
.spin { width: 15px; height: 15px; flex-shrink: 0; border-radius: 50%; display: inline-block;
  border: 2px solid rgba(37, 119, 227, .28); border-top-color: $color-primary; animation: spin .8s linear infinite; }
.spin.light { border-color: rgba(255, 255, 255, .35); border-top-color: #fff; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 选择接收人弹窗 ── */
.modal-mask { position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center;
  background: rgba(16, 32, 56, 0.42); backdrop-filter: blur(2px); }
@keyframes popIn { from { opacity: 0; transform: translateY(-8px) scale(.98); } to { opacity: 1; transform: none; } }
.modal { width: 560px; max-width: 92vw; max-height: 82vh; display: flex; flex-direction: column; background: #fff;
  border-radius: $radius-xl; box-shadow: $shadow-deep; overflow: hidden; animation: popIn .22s cubic-bezier(.22,.9,.3,1) both; }
.dlg-head { display: flex; align-items: baseline; gap: 10px; padding: 18px 20px 14px; border-bottom: 1px solid $color-border; }
.dlg-title { font-size: 19px; font-weight: 800; }
.dlg-sub { flex: 1; min-width: 0; font-size: 14.5px; color: $color-text-muted; }
.dlg-x { border: none; background: none; cursor: pointer; color: $color-text-muted; padding: 2px; line-height: 0; }
.dlg-x:hover { color: $color-danger; }
.dlg-body { flex: 1; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }
.pick { display: flex; align-items: center; gap: 12px; text-align: left; padding: 12px 14px; cursor: pointer;
  font-family: inherit; border: 1px solid $color-border; border-radius: $radius-md; background: #fff; transition: all .16s ease; }
.pick:hover { border-color: $color-primary; background: $color-primary-softer; }
.pick.on { border-color: $color-primary; background: $color-primary-softer; box-shadow: 0 0 0 2px rgba(37,119,227,.10); }
.pk-av { width: 36px; height: 36px; flex-shrink: 0; border-radius: $radius-md; display: flex; align-items: center;
  justify-content: center; background: $color-primary-soft; color: $color-primary; font-size: 16px; font-weight: 700; }
.pk-av.on { background: $color-primary; color: #fff; }
.pk-mid { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.pk-name { font-size: 15.5px; font-weight: 700; }
.pk-hint { font-size: 14px; color: $color-text-muted; }
.pk-kind { font-size: 13.5px; color: $color-text-secondary; background: #f1f4f8; border-radius: 6px; padding: 2px 9px; white-space: nowrap; }
.pk-check { width: 20px; height: 20px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; color: #fff; border: 1px solid $color-border-strong; transition: all .16s ease; }
.pick.on .pk-check { background: $color-primary; border-color: $color-primary; }
.dlg-empty { padding: 26px 12px; text-align: center; font-size: 15px; color: $color-text-muted; }
.dlg-foot { display: flex; align-items: center; gap: 10px; padding: 14px 20px; border-top: 1px solid $color-border; }
.dlg-count { flex: 1; font-size: 14.5px; color: $color-text-secondary; }
.pop-enter-active, .pop-leave-active { transition: opacity .2s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; }

@media (max-width: 1180px) { .entry-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) {
  .field-grid, .entry-grid { grid-template-columns: minmax(0, 1fr); }
  .form-section { padding: 16px; }
  .f-head { padding: 12px; }
  .fh-r { gap: 8px; }
  .entry-card { padding: 12px; }
  .pv-paper { padding: 18px 16px; }
  .send-row { flex-wrap: wrap; }
  .sr-v { flex-basis: calc(100% - 110px); }
}
@media (prefers-reduced-motion: reduce) {
  .modal, .result { animation: none; }
  .spin { animation-duration: 2.4s; }
  .submit-btn.sending { animation: none; }
}
</style>
