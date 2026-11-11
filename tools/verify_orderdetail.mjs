/**
 * R01/R17 静态自检（一次性校验脚本，非产品代码）：
 *   1) SFC 模板 + 脚本能否编译（@vue/compiler-sfc）
 *   2) 模板里的按钮是否都有点击处理（无死按钮）
 *   3) 模板表达式引用的标识符是否都已声明（抓漏声明/错别字）
 *   4) 假数据/死按钮清单是否真的从文件里消失
 *   5) FinanceView 跳转是否用交付物 code 而不是中文标题
 * 用法：
 *   node tools/verify_orderdetail.mjs            # 正式校验
 *   node tools/verify_orderdetail.mjs --mutate   # 反向自检：故意注入 3 处缺陷，必须全部被检出
 */
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

function ROOT_DIR() {
  return decodeURIComponent(new URL('../', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1')
}
// 用 Node（CJS）构建：浏览器构建不能做 scss 预处理
const req = createRequire(join(ROOT_DIR(), 'frontend/package.json'))
const { parse, compileTemplate, compileScript, compileStyleAsync } = req('@vue/compiler-sfc')
const sass = req('sass')

const ROOT = ROOT_DIR()
const MUTATE = process.argv.includes('--mutate')

const OD = ROOT + 'frontend/src/views/vbooking/OrderDetailView.vue'
const FIN = ROOT + 'frontend/src/views/practice/FinanceView.vue'
const PLAN_EDIT = ROOT + 'frontend/src/views/vbooking/PlanEditView.vue'

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail })
}

/** --mutate：只做反向自检，不碰真实文件（只改动读进内存的字符串） */
function mutate(file, src) {
  if (!MUTATE) return src
  if (file === OD) {
    return src
      .replace('@click="openDoc(d.code)"', '')                    // 注入死按钮
      .replace('{{ order?.customer || \'客户\' }}', '{{ orderZZ?.customer }}') // 注入未声明标识符
      .replace('availableStages', 'availableStagesXX')            // 注入清单断言失配
  }
  if (file === FIN) {
    return src.replace('?code=${settlementCode.value}', '?code=地接结算核对单') // 注入中文 code
  }
  return src
}

function load(file) {
  const src = mutate(file, readFileSync(file, 'utf8'))
  const { descriptor, errors } = parse(src, { filename: file })
  if (errors.length) throw new Error(`${file} 解析失败: ${errors.map((e) => e.message).join('; ')}`)
  const script = compileScript(descriptor, { id: 'verify' })
  const tpl = compileTemplate({
    source: descriptor.template.content,
    filename: file,
    id: 'verify',
    compilerOptions: { bindingMetadata: script.bindings },
  })
  if (tpl.errors.length) throw new Error(`${file} 模板编译失败: ${tpl.errors.map((e) => String(e)).join('; ')}`)
  return { src, descriptor, script, tpl }
}

// ── 1. 编译 ───────────────────────────────────────────────────────────────
const od = load(OD)
const fin = load(FIN)
check('OrderDetailView.vue 模板+脚本可编译', true, `template code ${od.tpl.code.length} 字节`)
check('FinanceView.vue 模板+脚本可编译', true, `template code ${fin.tpl.code.length} 字节`)

// ── 2. 样式编译（vite 交给 sass 处理；这里把 tokens 变量内联后按 scss 编译） ──
const TOKENS_SRC = readFileSync(ROOT + 'frontend/src/styles/tokens.scss', 'utf8')
for (const [file, f] of [['OrderDetailView', od], ['FinanceView', fin]]) {
  const styles = f.descriptor.styles
  let ok = styles.length > 0
  let detail = `${styles.length} 个 style 块`
  for (const s of styles) {
    // tokens.scss 全是 $var: 值; 声明：内联后只验证本组件样式，绕开 sass 的 @use 路径解析
    const source = s.content.replace(/@use\s+['"][^'"]*tokens\.scss['"]\s+as\s+\*;?/, TOKENS_SRC)
    const r = await compileStyleAsync({
      source, filename: file, id: 'verify', scoped: s.scoped, preprocessLang: s.lang,
      preprocessCustomRequire: (id) => (id === 'sass' || id === 'sass-embedded' ? sass : req(id)),
    })
    if (r.errors.length) {
      ok = false
      detail = r.errors.map((e) => e.message || String(e)).join('; ')
    } else {
      detail += `，CSS ${r.code.length} 字节`
    }
  }
  check(`${file} scoped SCSS 编译`, ok, detail)
}

// ── 3. 死按钮扫描 ─────────────────────────────────────────────────────────
function walk(node, visit) {
  if (!node || typeof node !== 'object') return
  visit(node)
  for (const k of Object.keys(node)) {
    const v = node[k]
    if (Array.isArray(v)) v.forEach((x) => walk(x, visit))
    else if (v && typeof v === 'object') walk(v, visit)
  }
}
function buttonReport(file, f) {
  const bad = []
  let total = 0
  walk(f.descriptor.template.ast, (n) => {
    if (n.type !== 1 || n.tag !== 'button') return
    total++
    const props = n.props || []
    const kind = props.find((p) => p.type === 7 && p.name === 'on' && p.arg?.content === 'click')
    const handler = props.find((p) => p.type === 6 && p.name === 'click')
    if (!kind && !handler) bad.push(`line ${n.loc.start.line}`)
  })
  check(`${file} 无无点击处理的 button`, bad.length === 0, `共 ${total} 个 button${bad.length ? '，缺失: ' + bad.join(',') : ''}`)
}
buttonReport('OrderDetailView.vue', od)
buttonReport('FinanceView.vue', fin)

// ── 4. 模板表达式引用的根标识符是否都已声明（抓错别字/漏声明） ──────────────
const KEYWORDS = new Set(['true', 'false', 'null', 'undefined', 'in', 'of', 'if', 'else', 'typeof',
  'return', 'new', 'void', 'delete', 'instanceof', 'this', 'function'])
/** 去掉字符串字面量与模板串，避免把中文文案当成标识符 */
function stripLiterals(src) {
  return src.replace(/`(?:\\.|[^`\\])*`/g, ' ').replace(/'(?:\\.|[^'\\])*'/g, ' ').replace(/"(?:\\.|[^"\\])*"/g, ' ')
}
/** 去掉属性链与方法调用，只留根标识符 */
function stripChains(src) {
  let out = src
  for (let i = 0; i < 4; i++) {
    const next = out.replace(/\??\.\s*[A-Za-z_$][\w$]*/g, '')
    if (next === out) break
    out = next
  }
  return out
}
/** 抽出表达式里的根标识符：跳过属性名（前一个非空字符是 `.`）与对象字面量的 key */
function rootsOf(src, into) {
  const body = stripChains(stripLiterals(src))
  for (const m of body.matchAll(/([A-Za-z_$][\w$]*)/g)) {
    const name = m[1]
    if (KEYWORDS.has(name)) continue
    let before = ''
    for (let i = m.index - 1; i >= 0; i--) {
      if (!/\s/.test(body[i])) { before = body[i]; break }
    }
    if (before === '.') continue          // 属性访问
    if (before === '{' || before === ',') { // 可能是对象字面量的 key
      const after = body.slice(m.index + name.length).match(/^\s*:/)
      if (after) continue
    }
    into.add(name)
  }
}
function identReport(file, f) {
  const tplSrc = f.descriptor.template.content
  const exprs = []
  // 插值
  for (const m of tplSrc.matchAll(/\{\{([\s\S]*?)\}\}/g)) exprs.push(m[1])
  // 指令表达式（v-if/v-for/v-show/v-model/@click/:prop/...）
  for (const m of tplSrc.matchAll(/(?:^|\s)(?:v-[\w-]+|[:@][\w-]+(?:\.\w+)*)="([^"]*)"/g)) exprs.push(m[1])
  // 模板局部作用域（v-for 别名、插槽参数）
  const local = new Set()
  for (const m of tplSrc.matchAll(/v-for="\s*\(?([^)"]*?)\)?\s+(?:in|of)\s/g)) {
    m[1].split(',').forEach((x) => local.add(x.trim()))
  }
  for (const m of tplSrc.matchAll(/v-slot(?::[\w-]+)?="\{?([^}"]*)\}?"/g)) {
    m[1].split(',').forEach((x) => local.add(x.trim().split(':')[0].trim()))
  }
  const declared = new Set([...Object.keys(f.script.bindings || {}), ...local, '$event', '$emit', '$slots', '$attrs'])
  const ids = new Set()
  exprs.forEach((e) => rootsOf(e, ids))
  const missing = [...ids].filter((id) => !declared.has(id))
  check(`${file} 模板表达式引用均已声明`, missing.length === 0,
    missing.length ? '未声明: ' + missing.join(',') : `已核对 ${ids.size} 个根标识符`)
}

identReport('OrderDetailView.vue', od)
identReport('FinanceView.vue', fin)

// ── 5. 假数据 / 死按钮 / 未使用代码清单是否真的清掉 ─────────────────────────
const REMOVED = [
  ['用户信息备注硬编码', '客户希望行程轻松，带一位老人'],
  ['假的合规告示', '目的地不支持国际、中国香港、中国台湾、中国澳门'],
  ['假「是否真需求单」状态', '是否真需求单'],
  ['假「是否添加企微」状态', '是否添加企微'],
  ['假「是否建立售前微信群」状态', '是否建立售前微信群'],
  ['死按钮：添加跟进备注', '添加跟进备注'],
  ['死链接：查看备注规则', '查看备注规则'],
  ['死按钮：取消订单', '取消订单'],
  ['死链接：建群流程话术', '点击查看建群流程和相关话术'],
  ['假引导文案（未读方案）', '客人还未阅读过任何方案'],
  ['未使用代码：HINTS', 'const HINTS'],
  ['未使用代码：DOC_MAP/docCode/openDoc 的中文映射', "'deliverable:需求确认单'"],
  ['未使用代码：doAction', 'async function doAction'],
  ['死数据：gate/loadGate', 'function loadGate'],
  ['死样式：.full', '\n.full {'],
]
for (const [label, needle] of REMOVED) {
  check(`OrderDetailView 已删除 ${label}`, !od.src.includes(needle), `查找 "${needle}"`)
}

const REQUIRED_OD = [
  ['接入 journey 阶段投影', 'useJourney(orderId)'],
  ['当前阶段置顶', 'availableStages'],
  ['阶段文档按 code 打开工作台', '@click="openDoc(d.code)"'],
  ['当前阶段显示唯一主动作', 'data-testid="next-action"'],
  ['主动作文案取自 journey', 'nextAction.label'],
  ['主动作「继续」入口存在', 'data-testid="next-action-go"'],
  ['「继续」走 journey 的 next_action.route', 'router.push(to)'],
  ['「继续」路由取自 nextAction.route', 'nextAction.value?.route'],
  ['工作台入口带 code', 'workbenchRoute(orderId.value, code)'],
  ['工作台入口按当前阶段定位', 'nextAction?.deliverable || currentDocCode'],
  ['当前阶段定位交付物 code', 'currentStageDocCode'],
  ['入口文案为学生人话（不含实现语言）', '填写当前阶段文档'],
  ['区块标题按语义命名', '文档提交与继续'],
  ['方案行按 ?plan= 定位版本（PlanNewView 的入参）', 'plan/new?plan='],
  ['订单错误态', 'data-testid="order-error"'],
  ['订单重试', '@click="loadOrder"'],
  ['journey 错误态', 'data-testid="journey-error"'],
  ['journey 重试', '@click="refreshJourney()"'],
  ['返回订单管理', 'router.push(\'/practice\')'],
  ['返回订单详情面包屑', '/practice/orders/${orderId}'],
]
for (const [label, needle] of REQUIRED_OD) {
  check(`OrderDetailView 具备 ${label}`, od.src.includes(needle), '')
}

// ── 6. FinanceView 跳转口径 ───────────────────────────────────────────────
check('FinanceView 跳转使用 code 参数', fin.src.includes('?code=${settlementCode.value}'), '')
check('FinanceView 不再用中文标题做 code', !/code=\$\{[^}]*地接结算核对单/.test(fin.src) && !fin.src.includes('code=地接结算核对单'), '')
check('FinanceView 用契约取结算物', fin.src.includes("SETTLEMENT_CODE = 'settlement'") && fin.src.includes('useStages()'), '')
check('FinanceView 跳转按钮有 disabled 门', fin.src.includes(':disabled="!settlementCode"'), '')

// ── 7. PlanEditView 已删除 ────────────────────────────────────────────────
check('PlanEditView.vue 已删除', !existsSync(PLAN_EDIT), PLAN_EDIT)

// ── 输出 ──────────────────────────────────────────────────────────────────
let failures = 0
for (const r of results) {
  if (!r.ok) failures++
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  —  ' + r.detail : ''}`)
}
console.log(`\n${results.length - failures}/${results.length} 通过`)
process.exit(failures ? 1 : 0)
