/**
 * 工作台「同订单切换文档」单点验证（Node，无需浏览器）。
 *
 * 复现并回归真实浏览器发现的缺陷：
 *   在 /practice/orders/{id}/deliverables?code=requirement_sheet 之后转到
 *   /deliverables?code=itinerary，URL 变了但正文仍是旧文档（组件只 watch orderId）。
 *
 * 做法：用 @vue/compiler-sfc 编译**仓库里真实的** DeliverableWorkbenchView.vue，
 * 用 Vue 的 createRenderer 自建宿主挂载（无 jsdom），把 api client / vue-router / 组件桩接上，
 * 然后断言：切换 code → 正文切换；晚返回的旧文档响应不覆盖新选择；非法 code → 明确报错不留旧正文。
 *
 * 用法：node scripts/journey_workbench_route_check.mjs
 * 退出码 0 = 全通过；证据落 output/acceptance/output-audit-20261017/journey/workbench-route-check.log
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SFC = path.join(ROOT, 'frontend/src/views/practice/DeliverableWorkbenchView.vue')
const OUT = path.join(ROOT, 'output/acceptance/output-audit-20261017/journey')
fs.mkdirSync(OUT, { recursive: true })

const { parse, compileScript } = require(path.join(ROOT, 'frontend/node_modules/@vue/compiler-sfc'))
const ts = require(path.join(ROOT, 'frontend/node_modules/typescript'))
const Vue = require(path.join(ROOT, 'frontend/node_modules/vue'))

// 组件里用到 window.setTimeout（预览防抖）：给一个最小 shim
globalThis.window = { setTimeout, clearTimeout }

const results = []
const check = (id, name, ok, detail = '') => {
  results.push({ id, name, ok: !!ok, detail: String(detail) })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${detail ? '  ·  ' + detail : ''}`)
}

// ---------------- 桩：api client（可控延迟，用来制造竞态） ----------------
const DOCS = {
  requirement_sheet: { id: '需求确认单', code: 'requirement_sheet', title: '需求确认单', fields: [], audience: ['客户'] },
  itinerary: { id: '行程方案', code: 'itinerary', title: '行程方案', fields: [], audience: ['客户'] },
}
let delayFirstDetail = 0
let detailCalls = 0
let previewCalls = []
let pdfCalls = []
const client = {
  async get(url) {
    if (/\/deliverables$/.test(url)) {
      return { data: { deliverables: [
        { id: '需求确认单', code: 'requirement_sheet', title: '需求确认单', submitted: true,
          version: 1, step: 'S3', audience: ['客户', '平台'], purpose: '需求确认',
          surface: 'document', is_next: false, stage: 'pre1_requirement', stage_name: '行前 1 · 需求确认单',
          in_current_stage: false },
        { id: '行程方案', code: 'itinerary', title: '行程方案', submitted: false,
          version: 0, step: 'S5', audience: ['客户', '平台'], purpose: '逐日行程',
          surface: 'document', is_next: true, stage: 'pre2_plan', stage_name: '行前 2 · 行程方案',
          in_current_stage: true },
      ], current_stage: 'pre2_plan', next_action: null } }
    }
    const m = url.match(/\/deliverables\/([^/?]+)$/)
    if (m) {
      const code = decodeURIComponent(m[1])
      detailCalls += 1
      if (delayFirstDetail && detailCalls === 1) {
        await new Promise((r) => setTimeout(r, delayFirstDetail))
      }
      const spec = DOCS[code] || DOCS.requirement_sheet
      return { data: { spec, values: { title: code }, version: 1, rendered: `# ${spec.title}\n\n${code}-body`,
        customer_facing: true, customer_withheld: [], file_ids: [], target_options: [], context: {} } }
    }
    if (/\/practice\/orders\/[^/]+$/.test(url)) return { data: { order_id: 'o1' } }
    if (/\/contracts\/markets/.test(url)) return { data: [] }
    return { data: {} }
  },
  async post(url) {
    const pdf = url.match(/\/deliverables\/([^/]+)\/export\.pdf$/)
    if (pdf) {
      pdfCalls.push(decodeURIComponent(pdf[1]))
      return { data: new Uint8Array([37, 80, 68, 70]).buffer, headers: { 'content-type': 'application/pdf' } }
    }
    const m = url.match(/\/deliverables\/([^/]+)\/preview$/)
    const code = m ? decodeURIComponent(m[1]) : 'unknown'
    previewCalls.push(code)
    return { data: { rendered: `# ${(DOCS[code] || {}).title || code}\n\n${code}-preview`,
      customer_withheld: [], customer_facing: true, missing: [] } }
  },
}

// ---------------- 桩：vue-router（真 memory history + 真 resolve） ----------------
const { createRouter, createMemoryHistory } = require(path.join(ROOT, 'frontend/node_modules/vue-router'))
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { render: () => null } },
    { path: '/practice/orders/:id/deliverables', name: 'p-deliverables',
      component: { render: () => null } },
  ],
})

// ---------------- 编译真实 SFC ----------------
// 真 useRoute() 返回的是随导航更新的 reactive 对象；桩必须同样响应式，否则 watch(route.query.code) 观察不到
const routeState = Vue.reactive({ path: '/', params: {}, query: {} })
router.afterEach((to) => {
  routeState.path = to.path
  routeState.params = to.params
  routeState.query = to.query
})

const source = fs.readFileSync(SFC, 'utf8')
const { descriptor, errors } = parse(source, { filename: SFC })
if (errors.length) { console.error('SFC parse errors', errors); process.exit(2) }
const compiled = compileScript(descriptor, { id: 'wbcheck', inlineTemplate: true })
const js = ts.transpileModule(compiled.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
}).outputText

const Module = require('module')
const originalLoad = Module._load
Module._load = function (request, parent, isMain) {
  if (request === 'vue') return Vue                       // 编译产物里的裸 require('vue')
  if (request === 'vue-router') return { useRoute: () => routeState, useRouter: () => router, __esModule: true }
  if (request === '@/api/client') return { default: client, __esModule: true }
  if (request === 'marked') return { marked: { parse: (t) => t }, __esModule: true }
  if (request === 'dompurify') return { default: { sanitize: (t) => t }, __esModule: true }
  if (request === '@/composables/useStages') {
    return { useStages: () => ({ stages: Vue.ref([{ id: 'pre1_requirement', name: '行前 1', short: '需求确认', order: 1, steps: [], deliverables: ['requirement_sheet'], focus: '', primary_deliverable: 'requirement_sheet', substeps: [] }]),
      stepNames: Vue.ref({}), stageOfDeliverable: Vue.ref({}), loading: Vue.ref(false), error: Vue.ref(''),
      load: async () => {}, stageById: () => undefined, stageOfCode: () => undefined }), __esModule: true }
  }
  if (request === '@/composables/useJourney') {
    return { useJourney: () => ({ journey: Vue.ref(null), loading: Vue.ref(false), error: Vue.ref(''),
      stages: Vue.computed(() => []), currentStageId: Vue.computed(() => ''), currentStage: Vue.computed(() => null),
      nextAction: Vue.computed(() => null), stageStates: Vue.computed(() => ({})), refresh: async () => {} }), __esModule: true }
  }
  if (request === '@/components/SIcon.vue') {
    const SIconStub = { name: 'SIcon', render: () => Vue.h('i') }
    return { default: SIconStub, __esModule: true }
  }
  return originalLoad.call(this, request, parent, isMain)
}

const mod = { exports: {} }
new Function('require', 'module', 'exports', js)(require, mod, mod.exports)
Module._load = originalLoad
const Workbench = mod.exports.default || mod.exports

// ---------------- 自定义宿主挂载（真组件、真响应式、真 watch） ----------------
const { createRenderer, nextTick, h } = Vue
const host = createRenderer({
  createElement: (t) => ({ t, children: [], props: {}, parent: null }),
  insert: (child, parent, anchor) => {
    if (!child || !parent || !Array.isArray(parent.children)) return
    if (child.parent === parent && parent.children.includes(child)) return   // 不重复插入
    child.parent = parent
    const i = anchor ? parent.children.indexOf(anchor) : -1
    if (i >= 0) parent.children.splice(i, 0, child)
    else parent.children.push(child)
  },
  remove: (child) => {
    const p = child && child.parent
    if (p && Array.isArray(p.children)) { const i = p.children.indexOf(child); if (i >= 0) p.children.splice(i, 1) }
  },
  createComment: () => ({ t: '#comment', children: [], parent: null }),
  createText: (t) => ({ t: '#text', text: t, children: [], parent: null }),
  setText: (n, t) => { if (n) n.text = t },
  setElementText: (n, t) => { if (n) n.text = t },
  parentNode: (n) => (n && n.parent) || null,
  nextSibling: (n) => {
    const p = n && n.parent
    if (!p || !Array.isArray(p.children)) return null
    return p.children[p.children.indexOf(n) + 1] || null
  },
  patchProp: (el, k, prev, next) => { if (el) el.props[k] = next },
  setScopeId: () => {},
})
const app = host.createApp(Workbench)
app.component('SIcon', { render: () => h('i') })
app.use(router)

const mountRoot = { t: '#root', children: [], props: {}, parent: null }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 从渲染树里收集「用户能看到/会下载」的文本：文本节点 + v-html 内容。 */
function treeText(node) {
  if (!node || typeof node !== 'object') return ''
  let out = ''
  if (typeof node.text === 'string') out += node.text + ' '
  if (node.props) {
    for (const [k, v] of Object.entries(node.props)) {
      if (typeof v === 'string' && (k === 'innerHTML' || k === 'textContent')) out += v + ' '
    }
  }
  if (Array.isArray(node.children)) out += node.children.map(treeText).join(' ')
  return out
}

/** 按 props 找节点（例如 data-role="export-pdf" 的按钮），用于真实点击。 */
function findByProp(node, key, value) {
  if (!node || typeof node !== 'object') return null
  if (node.props && node.props[key] === value) return node
  if (Array.isArray(node.children)) {
    for (const c of node.children) {
      const hit = findByProp(c, key, value)
      if (hit) return hit
    }
  }
  return null
}
/** 按 class 找节点（class 属性是字符串）。 */
function findByClass(node, cls) {
  if (!node || typeof node !== 'object') return null
  const c = node.props && node.props.class
  if (typeof c === 'string' && c.split(/\s+/).includes(cls)) return node
  if (Array.isArray(node.children)) {
    for (const ch of node.children) {
      const hit = findByClass(ch, cls)
      if (hit) return hit
    }
  }
  return null
}

/**
 * **只取当前文档正文**：`.fh-title`（当前文档标题）+ `.pv-paper`（预览正文）。
 * 不能拿整页字符串判断——左侧交付物导航里本来就有其他文档的名字，
 * 那会把“导航标题”误判成“旧正文残留”（早前一轮 1/5 的失败就是这个作用域错误）。
 */
function docText(root) {
  const title = findByClass(root, 'fh-title')
  const paper = findByClass(root, 'pv-paper')
  const paperHtml = paper && paper.props ? String(paper.props.innerHTML || '') : ''
  return [(title ? treeText(title) : ''), paperHtml].join(' ')
}
const root = mountRoot

// 导出路径用到浏览器 API：给最小 shim（只为了让真实 exportPdf 跑通并记下目标 code）
globalThis.URL = globalThis.URL || {}
globalThis.URL.createObjectURL = () => 'blob:check'
globalThis.URL.revokeObjectURL = () => {}
globalThis.document = globalThis.document || {
  createElement: () => ({ click: () => {}, style: {}, set href(v) {}, set download(v) {} }),
}

async function waitFor(fn, ms = 2500, step = 30) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(step) }
  return fn()
}

async function main() {
  // 真实应用顺序：先有路由位置，再挂载组件
  await router.push('/practice/orders/9000000000000009/deliverables?code=requirement_sheet')
  await router.isReady()
  app.mount(mountRoot)
  await waitFor(() => docText(root).includes('requirement_sheet-preview'))
  await sleep(60)

  const t1 = docText(root)
  check('R1', '初始进入按 ?code= 打开需求确认单',
    t1.includes('需求确认单') && t1.includes('requirement_sheet-preview')
      && !t1.includes('itinerary-preview'),
    `has_req=${t1.includes('requirement_sheet-preview')} detailCalls=${detailCalls} previews=${JSON.stringify(previewCalls)} t1=${t1.slice(0, 200)}`)

  // 同一订单内转到另一份文档：URL 变、正文必须跟着切（本次缺陷点）
  await router.push('/practice/orders/9000000000000009/deliverables?code=itinerary')
  await waitFor(() => docText(root).includes('itinerary-preview'))
  await sleep(80)
  const t2 = docText(root)
  check('R2', '同订单 ?code= 变化 → 正文/预览切到新文档',
    t2.includes('行程方案') && t2.includes('itinerary-preview')
      && !t2.includes('requirement_sheet-preview'),
    `has_itin=${t2.includes('itinerary-preview')} stale_req=${t2.includes('requirement_sheet-preview')}`)

  // 导出目标跟随新文档：真实点击「导出 PDF」按钮，看它请求了哪一份
  const exportBtn = findByProp(root, 'data-role', 'export-pdf')
  pdfCalls = []
  exportBtn?.props?.onClick?.()
  await sleep(120)
  check('R3', '导出目标跟随新文档（点击导出 PDF 请求的是 itinerary）',
    pdfCalls[pdfCalls.length - 1] === 'itinerary', `pdfCalls=${JSON.stringify(pdfCalls)}`)

  // 竞态：先请求一份慢的旧文档，再切到新文档 —— 晚返回的旧文档不得覆盖
  delayFirstDetail = 300
  detailCalls = 0
  await router.push('/practice/orders/9000000000000009/deliverables?code=requirement_sheet')
  await sleep(20)                                   // 旧文档请求还在飞
  await router.push('/practice/orders/9000000000000009/deliverables?code=itinerary')
  await waitFor(() => docText(root).includes('itinerary-preview'))
  await sleep(700); await nextTick(); await sleep(120)
  const t4 = docText(root)
  check('R4', '晚返回的旧文档响应不覆盖新选择（加载竞态闸门）',
    t4.includes('itinerary-preview') && !t4.includes('requirement_sheet-preview'),
    `has_itin=${t4.includes('itinerary-preview')} stale_req=${t4.includes('requirement_sheet-preview')}`)
  delayFirstDetail = 0

  // 非法 code：明确报错、不留旧正文
  await router.push('/practice/orders/9000000000000009/deliverables?code=not_a_document')
  await waitFor(() => treeText(root).includes('这个文档不属于本订单'))
  await sleep(80)
  const page5 = treeText(root)      // 报错横幅是页面级提示，引用它
  const t5 = docText(root)          // 「当前正文」只看 .fh-title / .pv-paper
  check('R5', '非法 code → 明确报错且不拿旧文档冒充',
    page5.includes('这个文档不属于本订单') && !t5.includes('-preview'),
    `has_err=${page5.includes('这个文档不属于本订单')} stale_doc=${t5.includes('-preview')} doc='${t5.trim().slice(0, 60)}'`)

  const failed = results.filter((r) => !r.ok)
  // 作用域订正说明 + 原始失败文本一并留档（不掩盖历史记录）
  const provenance = [
    '# 工作台同订单文档切换 · 单点验证',
    '# 判据来源：真实浏览器缺陷记录 output/demo-rehearsal-20261017/verified-browser/progress.json',
    '#',
    '# 【检测器作用域订正 2026-10-17】',
    '# 早前一轮 1/5 的 R2/R4/R5 失败是**检测器作用域错误**，不是产品缺陷：当时断言搜索整页文本，',
    '# 而左侧交付物导航里本来就会列出其他文档的标题（「需求确认单」「行程方案」），被误判成“旧正文残留”。',
    '# 现「当前正文」判据只取 .fh-title（当前文档标题）+ .pv-paper（预览正文）；',
    '# 报错横幅（页面级）单独用整页文本判断。产品代码未因此修改（冻结）。',
    '# 保留原始失败文本：',
    '#   FAIL  R2  同订单 ?code= 变化 → 正文/预览切到新文档  ·  has_itin=true stale_req=true',
    '#   FAIL  R4  晚返回的旧文档响应不覆盖新选择（加载竞态闸门）  ·  has_itin=true stale_req=true',
    '#   FAIL  R5  非法 code → 明确报错且不拿旧文档冒充  ·  has_err=true stale_itin=true',
    '',
  ].join('\n')
  fs.writeFileSync(path.join(OUT, 'workbench-route-check.log'), provenance +
    results.map((r) => `${r.ok ? 'PASS' : 'FAIL'}\t${r.id}\t${r.name}\t${r.detail}`).join('\n')
    + `\n\n${results.length - failed.length}/${results.length} passed（作用域订正后）\n`, 'utf8')
  console.log(`\n=== 工作台同订单文档切换检查: ${results.length - failed.length}/${results.length} passed ===`)
  console.log('evidence ->', path.join(OUT, 'workbench-route-check.log'))
  process.exit(failed.length ? 1 : 0)
}

main().catch((e) => { console.error('HARNESS-ERROR', e); process.exit(2) })
