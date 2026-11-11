<template>
  <div class="pn">
    <!-- 顶栏：身份 + 三个动作（滚动时不动） -->
    <header class="topbar">
      <button class="back" @click="router.push(`/practice/orders/${orderId}`)">
        <SIcon name="back" :size="13" /> 返回订单
      </button>
      <div class="tb-id">
        <span class="title">行程方案</span>
        <span class="meta">{{ order ? order.customer + ' · ' + order.destination : '' }} · 订单 {{ orderId.slice(-4) }}</span>
      </div>
      <span v-if="plan" class="ver" :class="verClass">V{{ plan.version }} · {{ plan.status }}</span>
      <div class="tb-acts">
        <button class="btn ghost import-template" :disabled="busy || importBusy || pdfBusy"
          data-role="import-template" @click="importTemplate">
          <span v-if="importBusy" class="spin" />
          <SIcon v-else name="filetext" :size="14" />
          {{ importBusy ? '导入中…' : '导入模板' }}
        </button>
        <button class="btn ghost" :disabled="busy || importBusy" @click="saveDraft">保存草稿</button>
        <button class="btn ghost" :disabled="busy || importBusy || pdfBusy" data-role="export-pdf" @click="exportPlan">
          {{ pdfBusy ? '导出中…' : '导出 PDF' }}
        </button>
        <button class="btn primary" :disabled="busy || importBusy || !plan" @click="send">
          <SIcon name="right" :size="13" />{{ busy ? '发送中…' : (plan && plan.status !== '草稿' ? '重新发送' : '发送方案') }}
        </button>
      </div>
    </header>

    <div class="grid">
      <main class="col-main">
        <!-- 基本信息 -->
        <section class="card sec">
          <div class="sec-title"><SIcon name="filetext" :size="14" /><span>基本信息</span></div>
          <div class="fld">
            <label class="lb">方案标题<i class="req">*</i></label>
            <input v-model="title" class="ipt" placeholder="自己起，如：广西 5 天亲子行程（长辈同行版）" />
          </div>
          <div class="two basic-info-row">
            <div class="fld">
              <label class="lb">出发 / 返程<i class="req">*</i></label>
              <input v-model="dates" class="ipt" placeholder="如 2026-11-15 至 11-19" />
            </div>
            <div class="fld">
              <label class="lb">出行人数<i class="req">*</i></label>
              <input v-model="people" class="ipt" placeholder="如 3 大 1 小" />
            </div>
          </div>
        </section>

        <!-- 逐日行程：一天一张卡，字段各占一格，不再挤表格 -->
        <section class="card sec">
          <div class="sec-title">
            <SIcon name="route" :size="14" /><span>逐日行程</span>
            <span class="sec-hint">每天六要素：时间 / 交通+耗时 / 景点 / 餐食 / 住宿 / 导游</span>
            <span class="sec-count">{{ days.length }} 天</span>
          </div>
          <transition-group name="day" tag="div" class="days">
            <article v-for="(d, i) in days" :key="i" class="day">
              <header class="day-head">
                <span class="day-no">第 {{ i + 1 }} 天</span>
                <input v-model="d.day" class="ipt day-code" placeholder="D1" />
                <button class="icon-btn" title="删掉这一天" @click="days.splice(i, 1)">
                  <SIcon name="x" :size="12" />
                </button>
              </header>
              <div class="day-grid">
                <label v-for="c in DAY_COLS.filter((x) => x.key !== 'day')" :key="c.key" class="cell">
                  <span class="cell-label">{{ c.label }}</span>
                  <input v-model="d[c.key]" class="ipt" />
                </label>
              </div>
            </article>
          </transition-group>
          <button class="add-btn" @click="addDay"><SIcon name="plus" :size="13" />加一天</button>
        </section>

        <!-- 方案小节 + 模板 -->
        <section class="card sec">
          <div class="sec-title">
            <SIcon name="layout" :size="14" /><span>方案小节</span>
            <span class="sec-hint">标题自己写（交通 / 住宿 / 门票 / 提醒…），写好可存成模板复用</span>
            <span class="sec-count">{{ sections.length }} 节</span>
          </div>
          <transition-group name="day" tag="div" class="sects">
            <div v-for="(s, i) in sections" :key="i" class="sect">
              <input v-model="s.title" class="ipt st" placeholder="小节标题（自己写）" />
              <textarea v-model="s.body" class="ta" rows="2" placeholder="这一节写什么" />
              <button class="icon-btn" @click="sections.splice(i, 1)"><SIcon name="x" :size="12" /></button>
            </div>
          </transition-group>
          <div v-if="!sections.length" class="empty-sm">暂无小节。实际方案中的小节由定制师自行拟定。</div>
          <div class="tpl-bar">
            <div class="tpl-row">
              <button class="mini" @click="addSection">添加小节</button>
            </div>
            <div class="tpl-row">
              <select v-model="tplPick" class="ipt sel">
                <option value="" disabled hidden>套用我的模板…</option>
                <option v-for="t in templates" :key="t.template_id" :value="t.template_id">{{ t.name }}</option>
              </select>
              <button class="mini" :disabled="!tplPick" @click="applyTemplate">套用</button>
            </div>
            <div class="tpl-row">
              <input v-model="tplName" class="ipt nm" placeholder="模板名，如：亲子长辈同行" />
              <button class="mini" @click="saveTemplate">存为模板</button>
            </div>
          </div>
        </section>
        <!-- 交付要件：与《行程方案》契约字段一致，随方案发送并进入评分证据 -->
        <section class="card sec">
          <div class="sec-title">
            <SIcon name="filetext" :size="14" /><span>交付要件</span>
            <span class="sec-hint">随方案一起发给客户，并进入评分证据</span>
          </div>
          <div class="fld"><label class="lb">交通与用车</label>
            <textarea v-model="vehicle" class="ta" rows="2" placeholder="车型、座位、是否含司机与油费" /></div>
          <div class="fld"><label class="lb">住宿安排</label>
            <textarea v-model="hotel" class="ta" rows="2" placeholder="酒店名称、星标、位置、含早、确认状态" /></div>
          <div class="fld"><label class="lb">门票与预约</label>
            <textarea v-model="tickets" class="ta" rows="2" placeholder="景点门票、是否需实名预约" /></div>
          <div class="fld"><label class="lb">保险与合规</label>
            <textarea v-model="insurance" class="ta" rows="2" placeholder="保险类型、保额；景区预约与实名要求" /></div>
          <div class="fld"><label class="lb">入境与证件提醒</label>
            <textarea v-model="entry" class="ta" rows="2" placeholder="回乡证 / 台胞证 / 签证、证件有效期" /></div>
          <div class="fld"><label class="lb">备选方案</label>
            <textarea v-model="backup" class="ta" rows="2" placeholder="主选 A（已确认）；若 X 发生则换 B（价差 Y）" /></div>
          <div class="fld"><label class="lb">备注</label>
            <textarea v-model="noteText" class="ta" rows="2" /></div>
        </section>
      </main>

      <!-- 右栏：只放"这份方案现在到哪一步了" -->
      <aside class="col-side">
        <section class="card status">
          <div class="sec-title"><SIcon name="target" :size="14" /><span>发送状态</span></div>
          <ol class="steps">
            <li v-for="(st, i) in flow" :key="st.key" :class="{ on: st.on, now: st.now }">
              <i class="dot" />
              <div class="st-mid">
                <span class="st-name">{{ st.name }}</span>
                <span class="st-note">{{ st.note }}</span>
              </div>
              <span v-if="i < flow.length - 1" class="line" />
            </li>
          </ol>
          <div v-if="notice" class="notice">{{ notice }}</div>
          <div v-if="plan && plan.read_at" class="feedback">
            <div class="fb-head">客户已读 {{ plan.read_at.slice(5, 16) }}</div>
            <p class="fb-body">{{ plan.feedback || '（客户没有留言）' }}</p>
            <button v-if="plan.status !== '客户已确认'" class="btn primary" :disabled="busy" @click="confirm">
              登记「客户已确认方案」
            </button>
            <div v-else class="ok-line">客户已确认（{{ (plan.confirm_at || '').slice(5, 16) }}）</div>
          </div>
          <div v-else-if="plan && plan.status === '已发送'" class="feedback pending">
            <div class="fb-head">已发送，等客户读</div>
            <p class="fb-body">客户读过之后这里会显示阅读时间和他的反馈。</p>
          </div>
          <div v-else-if="!plan" class="feedback pending">
            <div class="fb-head">暂无版本</div>
            <p class="fb-body">先「保存草稿」生成一个版本，再发送给客户。</p>
          </div>
          <p class="side-note">方案只发给客户。</p>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const DAY_COLS = [
  { key: 'day', label: '天次' }, { key: 'time', label: '时间' },
  { key: 'transport', label: '交通+耗时' }, { key: 'spot', label: '景点' },
  { key: 'meal', label: '餐食' }, { key: 'hotel', label: '住宿' }, { key: 'guide', label: '导游' },
]

const order = ref<any>(null)
const plan = ref<any>(null)
const title = ref('')
const dates = ref('')
const people = ref('')
const days = ref<any[]>([{ day: 'D1' }])
const sections = ref<any[]>([])
const vehicle = ref('')
const hotel = ref('')
const tickets = ref('')
const insurance = ref('')
const entry = ref('')
const backup = ref('')
const noteText = ref('')
const targets = ref<any[]>([])
const picked = ref<string[]>([])
const templates = ref<any[]>([])
const tplPick = ref('')
const tplName = ref('')
const busy = ref(false)
const pdfBusy = ref(false)
const importBusy = ref(false)
const notice = ref('')

const verClass = computed(() => {
  const st = plan.value?.status || ''
  if (st === '客户已确认') return 'done'
  if (plan.value?.read_at || st === '已读') return 'read'
  return ''
})

// 右栏那条状态线：草稿 → 已发送 → 客户已读 → 客户已确认
const flow = computed(() => {
  const st = plan.value?.status || ''
  const read = !!plan.value?.read_at
  const reached = (k: string) => {
    if (k === 'draft') return !!plan.value
    if (k === 'sent') return ['已发送', '已读', '客户已确认'].includes(st) || read
    if (k === 'read') return read || st === '客户已确认'
    return st === '客户已确认'
  }
  const currentKey = !plan.value ? 'draft'
    : (st === '客户已确认' ? '' : reached('read') ? 'confirm' : reached('sent') ? 'read' : 'sent')
  const at = (t?: string) => (t ? t.slice(5, 16) : '')
  return [
    { key: 'draft', name: '方案草稿',
      note: plan.value ? `V${plan.value.version} · ${at(plan.value.created_at)}` : '暂无版本' },
    { key: 'sent', name: '已发送给客户',
      note: plan.value?.sent_at ? at(plan.value.sent_at) : '发送后客户才会看到' },
    { key: 'read', name: '客户已读',
      note: read ? at(plan.value?.read_at) : '客户读过后才有反馈' },
    { key: 'confirm', name: '客户已确认',
      note: plan.value?.confirm_at ? at(plan.value.confirm_at) : '确认后订单才会推进' },
  ].map((x) => ({ ...x, on: reached(x.key), now: x.key === currentKey }))
})

async function load() {
  const [o, p, d, t] = await Promise.all([
    client.get(`/practice/orders/${orderId.value}`),
    client.get(`/practice/orders/${orderId.value}/plans`),
    client.get(`/practice/orders/${orderId.value}/deliverables/行程方案`),
    client.get('/practice/doc-templates'),
  ])
  order.value = o.data
  targets.value = d.data.target_options || []
  picked.value = targets.value.filter((x: any) => x.default).map((x: any) => x.session_id)
  templates.value = t.data.templates || []
  // 已保存的《行程方案》契约字段：导出 PDF 时作为底稿合并，避免出现「（未填写）」
  savedItin.value = d.data.values || {}
  const want = String(route.query.plan || '')
  const list = p.data.plans || []
  const cur = (want && list.find((x: any) => x.plan_id === want))
    || list.filter((x: any) => x.status === '草稿').slice(-1)[0] || null
  plan.value = cur
  if (!cur) {
    const pl = o.data || {}
    people.value = pl.party || ''
    dates.value = pl.dates || ''
  }
  if (cur) {
    title.value = cur.values?.title || cur.title || ''
    dates.value = cur.values?.dates || ''
    people.value = cur.values?.people || ''
    days.value = cur.values?.days?.length ? cur.values.days : [{ day: 'D1' }]
    sections.value = cur.values?.sections || []
  }
  const saved = cur?.values || {}
  vehicle.value = saved.vehicle || savedItin.value.vehicle || ''
  hotel.value = saved.hotel || savedItin.value.hotel || ''
  tickets.value = saved.tickets || savedItin.value.tickets || ''
  insurance.value = saved.insurance || savedItin.value.insurance || ''
  entry.value = saved.entry || savedItin.value.entry || ''
  backup.value = saved.backup || savedItin.value.backup || ''
  noteText.value = saved.note || savedItin.value.note || ''
}

function addDay() { days.value.push({ day: `D${days.value.length + 1}` }) }
function addSection() { sections.value.push({ title: '', body: '' }) }

async function saveDraft() {
  busy.value = true
  notice.value = ''
  // 关键：本页只编辑 title/dates/people/days/sections，但《行程方案》契约还有
  // vehicle/hotel/tickets/insurance/entry/backup/note/freeform 等字段（在产出与投递里填）。
  // 保存时把已保存的交付物字段并进来、编辑器字段覆盖同名字段，否则「发送方案」会用
  // 这份缺字段的 values 提交交付物，把工作台已填全的内容覆盖成「（未填写）」。
  const values = itineraryValues()
  try {
    const r = plan.value && plan.value.status === '草稿'
      ? await client.put(`/practice/orders/${orderId.value}/plans/${plan.value.plan_id}`,
                         { values, note: '' })
      : await client.post(`/practice/orders/${orderId.value}/plans`, { values, note: '' })
    plan.value = r.data.plan
    notice.value = `已保存草稿 V${plan.value.version}`
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '保存失败'
  } finally { busy.value = false }
}

async function send() {
  busy.value = true
  notice.value = ''
  try {
    // 不给选人：方案只发给客户（后端按产出受众解析出这位客户的单聊）
    const r = (await client.post(
      `/practice/orders/${orderId.value}/plans/${plan.value.plan_id}/send`,
      { targets: [] })).data
    if (r.blocked) {
      notice.value = '未通过校验：' + ((r.guard?.reasons || []).join('；') || '请检查方案')
      return
    }
    plan.value = r.plan
    const cust = (r.plan?.routing?.targets || []).find((t: any) => t.kind === '客户')
    if (cust && cust.session_id) {
      // 发完直接切到和这位客户的聊天窗口：客户在那里读、在那里回
      router.push(`/practice/im?session=${cust.session_id}`)
      return
    }
    notice.value = '方案已发送。若尚未添加客户联系方式，请先在聊天界面添加客户。'
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '发送失败'
  } finally { busy.value = false }
}

/** 方案内容 → 《行程方案》契约字段：字段名与后端 render() 读取的 key 一致。
 *
 * 页面只采集 title/dates/people/days/小节；契约里还有 vehicle/hotel/tickets/insurance/
 * entry/backup/note 等字段（在产出与投递的行程方案表单里填）。导出前先把**已保存的**那份
 * 行程方案 values 作为底稿合并进来，页面值覆盖底稿，避免 PDF 上出现一排「（未填写）」。
 */
const savedItin = ref<Record<string, any>>({})

function itineraryValues() {
  const sectionsText = (sections.value || [])
    .map((s: any) => [String(s.title || '').trim(), String(s.body || '').trim()].filter(Boolean).join('：'))
    .filter(Boolean)
    .join('\n')
  return {
    ...savedItin.value,
    title: title.value,
    dates: dates.value,
    people: people.value,
    days: (days.value || []).map((d: any) => ({
      day: d.day || '', time: d.time || '', transport: d.transport || '',
      spot: d.spot || '', meal: d.meal || '', hotel: d.hotel || '', guide: d.guide || '',
    })),
    vehicle: vehicle.value,
    hotel: hotel.value,
    tickets: tickets.value,
    insurance: insurance.value,
    entry: entry.value,
    backup: backup.value,
    note: noteText.value,
    // 方案小节没有对应的契约字段，落到《行程方案》的自由正文段（有内容才覆盖已保存值）
    freeform: sectionsText || savedItin.value.freeform || '',
  }
}

function _hasImportValue(value: any): boolean {
  if (Array.isArray(value)) return value.some((item) => _hasImportValue(item))
  if (value && typeof value === 'object') return Object.values(value).some((item) => _hasImportValue(item))
  return String(value ?? '').trim() !== ''
}

/** 导入时只提交当前页真正写过的内容，空字段由服务端模板补齐。 */
function importDraft(): Record<string, any> {
  const draft = itineraryValues()
  const filledDays = (draft.days || []).filter((row: any) =>
    ['time', 'transport', 'spot', 'meal', 'hotel', 'guide'].some((key) => String(row?.[key] || '').trim()))
  const out: Record<string, any> = { ...draft }
  if (filledDays.length) out.days = filledDays
  else delete out.days
  for (const key of Object.keys(out)) {
    if (!_hasImportValue(out[key])) delete out[key]
  }
  return out
}

function applyItineraryTemplate(values: Record<string, any>) {
  if (!values || typeof values !== 'object') return
  savedItin.value = { ...savedItin.value, ...values }
  title.value = String(values.title || title.value || '')
  dates.value = String(values.dates || dates.value || '')
  people.value = String(values.people || people.value || '')
  if (Array.isArray(values.days) && values.days.length) {
    days.value = values.days.map((row: any) => ({ ...row }))
  }
  if (Array.isArray(values.sections)) {
    sections.value = values.sections.map((section: any) => ({
      title: String(section?.title || ''), body: String(section?.body || ''),
    }))
  }
  vehicle.value = String(values.vehicle ?? vehicle.value ?? '')
  hotel.value = String(values.hotel ?? hotel.value ?? '')
  tickets.value = String(values.tickets ?? tickets.value ?? '')
  insurance.value = String(values.insurance ?? insurance.value ?? '')
  entry.value = String(values.entry ?? entry.value ?? '')
  backup.value = String(values.backup ?? backup.value ?? '')
  noteText.value = String(values.note ?? noteText.value ?? '')
}

/** 补齐本单行程方案及其余文件的模板底稿；当前页已填写的内容优先保留。 */
async function importTemplate() {
  if (busy.value || importBusy.value) return
  importBusy.value = true
  notice.value = ''
  try {
    const result = (await client.post(
      `/practice/orders/${orderId.value}/deliverables/import-template`,
      { drafts: { itinerary: importDraft() } },
    )).data
    const detail = (await client.get(
      `/practice/orders/${orderId.value}/deliverables/行程方案`,
    )).data
    applyItineraryTemplate(detail.values || {})
    notice.value = `已导入行程方案模板${result?.count ? `（同时补齐 ${result.count} 份文件）` : ''}，请核对后保存草稿。`
  } catch (e: any) {
    const detail = String(e?.response?.data?.detail || '')
    const needsReload = e?.response?.status === 404
      || (e?.response?.status === 400 && detail.includes('import-template'))
    notice.value = needsReload
      ? '后端尚未加载“导入模板”功能，请重启司南礼客后再试。'
      : detail || '模板导入失败，请稍后重试。原有填写内容保留。'
  } finally {
    importBusy.value = false
  }
}
/** 导出：只走服务端的 PDF 接口（后端按同一份渲染结果出版式），本地不再拼任何文件。 */
async function exportPlan() {
  if (pdfBusy.value || busy.value) return
  // 从未保存过行程方案时，导出会得到一张大半空白的 PDF：明确停住并给出补齐入口
  if (!plan.value && !title.value.trim()) {
    notice.value = '请先填写方案标题并保存草稿，再导出 PDF'
    return
  }
  pdfBusy.value = true
  notice.value = ''
  try {
    const r = await client.post(
      `/practice/orders/${orderId.value}/deliverables/行程方案/export.pdf`,
      { values: itineraryValues() },
      { responseType: 'blob' },
    )
    const url = URL.createObjectURL(new Blob([r.data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${title.value || '行程方案'}-${orderId.value}.pdf`
    a.click()
    URL.revokeObjectURL(url)
    notice.value = '已导出 PDF'
  } catch {
    notice.value = '导出 PDF 失败，请稍后重试'
  } finally {
    pdfBusy.value = false
  }
}


async function confirm() {
  busy.value = true
  try {
    const r = (await client.post(
      `/practice/orders/${orderId.value}/plans/${plan.value.plan_id}/confirm`)).data
    if (r.ok) { plan.value = r.plan; notice.value = '已登记客户确认方案' }
    else notice.value = r.error
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '登记失败'
  } finally { busy.value = false }
}

function applyTemplate() {
  const t = templates.value.find((x) => x.template_id === tplPick.value)
  if (!t) return
  sections.value = (t.sections || []).map((s: any) => ({ title: s.title || '', body: '' }))
  notice.value = `已套用模板「${t.name}」`
}

async function saveTemplate() {
  const name = tplName.value.trim()
  if (!name) { notice.value = '请先为模板命名'; return }
  if (!sections.value.length) { notice.value = '暂无可保存的小节'; return }
  await client.post('/practice/doc-templates', {
    name, sections: sections.value.map((s) => ({ title: s.title })), kind: 'plan',
  })
  templates.value = (await client.get('/practice/doc-templates')).data.templates || []
  tplName.value = ''
  notice.value = `模板「${name}」已保存，下次创建方案可直接套用`
}

onMounted(load)
watch(orderId, load)
// 已发送的方案到点会变「已读」：轮询一次把状态拿回来。
// 注意：组件离开（比如发送后跳到聊天界面）必须清掉，否则会带着空 orderId 一直打接口。
let planTimer = 0
onMounted(() => {
  planTimer = window.setInterval(async () => {
    if (!orderId.value || !plan.value || plan.value.status !== '已发送') return
    try {
      const r = (await client.get(`/practice/orders/${orderId.value}/plans`)).data
      const cur = (r.plans || []).find((x: any) => x.plan_id === plan.value.plan_id)
      if (cur) plan.value = cur
    } catch { /* 忽略瞬时错误 */ }
  }, 10000)
})
onUnmounted(() => { if (planTimer) clearInterval(planTimer) })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

/* 页面骨架：填满可用宽度，超宽屏再拆两栏 */
.pn { display: flex; flex-direction: column; gap: 18px; animation: page-in .34s cubic-bezier(.22,.9,.3,1) both; }
@keyframes page-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }

.topbar {
  position: sticky; top: 0; z-index: 12; display: flex; align-items: center; gap: 12px;
  padding: 14px 20px; background: rgba(255,255,255,.92); backdrop-filter: blur(8px);
  border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card;
}
.back { display: inline-flex; align-items: center; gap: 4px; border: 1px solid $color-border; background: #fff;
  border-radius: 999px; padding: 6px 14px; font-size: 15.5px; color: $color-primary; cursor: pointer;
  transition: border-color .18s ease, transform .18s ease; }
.back:hover { border-color: $color-primary; transform: translateX(-2px); }
.tb-id { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tb-id .title { font-size: 24px; font-weight: 700; letter-spacing: -.2px; }
.tb-id .meta { font-size: 15.5px; font-weight: 400; color: $color-text-muted; white-space: nowrap; }
.ver { margin-left: auto; font-size: 15.5px; font-weight: 600; color: $color-text-secondary;
  background: #f1f4f8; border-radius: 999px; padding: 3px 12px; white-space: nowrap; }
.ver.read { color: $color-primary; background: $color-primary-soft; }
.ver.done { color: $color-success; background: #e8f7ee; }
.tb-acts { display: flex; align-items: center; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-left: 6px; }

.grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; align-items: start;
  width: 100%; max-width: 1600px; margin: 0 auto; }
.col-main { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.col-side { position: sticky; top: 78px; display: flex; flex-direction: column; gap: 14px; }

.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }
.sec { padding: 20px 22px 22px; }
.sec-title { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px; color: $color-text; }
.sec-title span { font-size: 16px; font-weight: 700; }
.sec-hint { font-size: 15px; color: $color-text-muted; flex: 1; min-width: 0; }
.sec-count { font-size: 15px; color: $color-text-muted; font-variant-numeric: tabular-nums; }

.fld { display: flex; flex-direction: column; gap: 6px; }
.fld + .fld, .fld + .two, .two + .fld, .fld + .days, .days + .add-btn { margin-top: 12px; }
.lb { font-size: 15.5px; color: $color-text-secondary; }
.req { color: $color-danger; font-style: normal; margin-left: 3px; }
.two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: 12px; margin-top: 12px; }
.basic-info-row .fld { min-width: 0; }
.basic-info-row .fld + .fld { margin-top: 0; }

.ipt { width: 100%; height: 36px; border: 1px solid $color-border-strong; border-radius: 6px; padding: 0 11px;
  font-size: 15px; color: $color-text; outline: none; background: #fff;
  transition: border-color .2s ease-out, box-shadow .2s ease-out; }
.ipt:hover { border-color: $color-border-strong; }
.ipt:focus { border-color: $color-primary; box-shadow: 0 0 0 2px rgba(37,119,227,.10); }
.ta { width: 100%; border: 1px solid $color-border-strong; border-radius: 6px; padding: 9px 11px; font-size: 15px;
  resize: vertical; outline: none; font-family: inherit; transition: border-color .2s ease-out, box-shadow .2s ease-out; }
.ta:focus { border-color: $color-primary; box-shadow: 0 0 0 2px rgba(37,119,227,.10); }

/* 逐日行程：一天一张卡 */
.days { display: flex; flex-direction: column; gap: 10px; }
.day { border: 1px solid $color-border; border-radius: $radius-md; background: linear-gradient(180deg,#fbfdff,#fff);
  padding: 14px 16px; transition: border-color .18s ease, box-shadow .18s ease; }
.day:hover { border-color: $color-primary-light; box-shadow: $shadow-hover; }
.day-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.day-no { font-size: 16px; font-weight: 600; color: $color-primary; white-space: nowrap; }
.day-code { width: 72px; height: 30px; text-align: center; }
.day-head .icon-btn { margin-left: auto; }
.icon-btn { width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid transparent; background: none; border-radius: 6px; color: $color-text-muted; cursor: pointer;
  transition: all .16s ease; }
.icon-btn:hover { color: $color-danger; border-color: $color-border; background: #fff; }
.day-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 12px; }
.cell { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.cell-label { font-size: 14.5px; color: $color-text-muted; white-space: nowrap; }
.cell .ipt { height: 32px; font-size: 15.5px; }
.add-btn { margin-top: 12px; display: inline-flex; align-items: center; gap: 5px; font-size: 15.5px;
  color: $color-primary; background: $color-primary-softer; border: 1px dashed $color-border-strong;
  border-radius: $radius-sm; padding: 8px 14px; cursor: pointer; transition: all .16s ease; }
.add-btn:hover { border-color: $color-primary; background: $color-primary-soft; transform: translateY(-1px); }

.sects { display: flex; flex-direction: column; gap: 10px; }
.sect { display: grid; grid-template-columns: minmax(180px, 240px) minmax(0, 1fr) 30px; gap: 10px; align-items: start; }
.tpl-bar { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; padding-top: 14px; border-top: 1px dashed $color-border; }
.tpl-row { display: flex; gap: 10px; }
.tpl-bar .sel { width: 260px; }
.tpl-bar .nm { width: 240px; }
.mini { font-size: 15.5px; border: 1px solid $color-border; background: #fff; color: $color-text-secondary;
  border-radius: $radius-sm; padding: 0 12px; height: 36px; cursor: pointer; transition: all .16s ease; }
.mini:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.mini:disabled { opacity: .5; cursor: default; }

/* 右栏状态 */
.status { padding: 16px 18px; }
.steps { list-style: none; margin: 0 0 4px; padding: 0; display: flex; flex-direction: column; }
.steps li { position: relative; display: flex; gap: 10px; padding: 0 0 16px; }
.steps .dot { width: 12px; height: 12px; border-radius: 50%; background: #e3e9f2; margin-top: 3px; flex-shrink: 0;
  transition: background .3s ease, box-shadow .3s ease; }
.steps li.on .dot { background: $color-primary; }
.steps li.now .dot { box-shadow: 0 0 0 4px rgba(37,119,227,.16); animation: pulse 1.8s ease-in-out infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 4px rgba(37,119,227,.16); transform: scale(1); }
  50% { box-shadow: 0 0 0 8px rgba(37,119,227,.05); transform: scale(1.2); } }
.steps .line { position: absolute; left: 5px; top: 16px; bottom: 0; width: 2px; background: #eef2f7; }
.steps li.on .line { background: $color-primary-soft; }
.st-mid { display: flex; flex-direction: column; gap: 2px; }
.st-name { font-size: 16px; font-weight: 500; color: $color-text-secondary; }
.steps li.on .st-name { color: $color-text; }
.st-note { font-size: 15.5px; font-weight: 400; color: $color-text-muted; opacity: .85; }

.feedback { margin-top: 14px; border: 1px solid $color-border; border-radius: 8px; padding: 16px;
  animation: reveal .28s cubic-bezier(.22,.9,.3,1) both; }
.feedback.pending { background: #f5f7fa; }
@keyframes reveal { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
.fb-head { font-size: 15.5px; font-weight: 700; color: $color-success; }
.feedback.pending .fb-head { color: $color-text-secondary; }
.fb-body { font-size: 15.5px; color: $color-text-secondary; line-height: 1.65; margin: 6px 0 0; }
.feedback .btn { margin-top: 10px; }
.ok-line { margin-top: 8px; font-size: 15.5px; color: $color-success; }
.side-note { margin: 12px 0 0; font-size: 15px; color: $color-text-muted; line-height: 1.6; }

.btn { display: inline-flex; align-items: center; justify-content: center; gap: 5px; height: 36px; padding: 0 16px;
  border-radius: 6px; border: 1px solid transparent; font-size: 15px; cursor: pointer;
  transition: transform .15s ease-out, box-shadow .15s ease-out, background .15s ease-out; }
.btn.primary { background: $color-primary; color: #fff; box-shadow: 0 6px 16px rgba(37,119,227,.24); }
.btn.primary:hover:not(:disabled) { background: $color-primary-dark; transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37,119,227,.30); }
.btn.ghost { background: #fff; color: $color-primary; border-color: $color-border; }
.btn.ghost:hover:not(:disabled) { border-color: $color-primary; }
.btn:disabled { opacity: .5; cursor: default; box-shadow: none; }
.import-template { white-space: nowrap; }
.spin { width: 14px; height: 14px; display: inline-block; border: 2px solid rgba(37,119,227,.25); border-top-color: $color-primary; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.notice { margin-top: 12px; font-size: 15.5px; color: $color-primary; background: $color-primary-softer;
  border-radius: $radius-sm; padding: 9px 11px; }
.empty-sm { font-size: 15.5px; color: $color-text-muted; padding: 8px 0; }

/* 动作驱动的动画：加/删一天，卡片自己进出 */
.day-enter-active, .day-leave-active { transition: all .3s cubic-bezier(.4,0,.2,1); }
.day-enter-from { opacity: 0; transform: translateY(10px); }
.day-leave-to { opacity: 0; transform: translateX(12px); }
.day-move { transition: transform .26s ease; }

/* 响应式：窄屏收成单栏；宽屏把主区摊开 */
@media (max-width: 1500px) { .day-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 1180px) { .grid { grid-template-columns: minmax(0, 1fr); } .col-side { position: static; } }
@media (max-width: 720px) { .sect { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 720px) {
  .topbar { flex-wrap: wrap; gap: 10px; }
  .back { flex-shrink: 0; white-space: nowrap; }
  .tb-id { flex: 1; min-width: 120px; }
  .tb-acts { flex-basis: 100%; margin-left: 0; justify-content: flex-start; }
}
@media (max-width: 560px) { .basic-info-row { grid-template-columns: minmax(0, 1fr); } }

@media (prefers-reduced-motion: reduce) {
  .pn, .feedback, .steps li.now .dot { animation: none; }
  .day-enter-active, .day-leave-active, .day-move { transition: none; }
}
</style>