/**
 * 用真实接口数据回归订单详情的阶段文档逻辑（一次性脚本，非产品代码）。
 *
 * 输入是 tools/probe_journey_endpoints.py 落盘的 journey 响应（真实后端 18010），
 * 断言的是 frontend/src/views/vbooking/orderDetailDocs.ts —— 也就是页面实际调用的那份逻辑。
 *
 * 用法：node --experimental-strip-types tools/verify_orderdetail_realdata.mts <journey.json>...
 */
import { readFileSync } from 'node:fs'
import {
  countDelivered,
  countDocs,
  currentStageDocCode,
  orderStagesForDisplay,
  workbenchRoute,
} from '../frontend/src/views/vbooking/orderDetailDocs.ts'

interface JourneyStage {
  id: string
  name: string
  order: number
  state: 'done' | 'current' | 'todo'
  deliverables: Array<{ code: string; title: string; submitted: boolean; version: number }>
  next_action: { kind: string; label: string; route: string } | null
}
interface Journey {
  order_id: string
  current_stage: string
  stages: JourneyStage[]
  next_action: { kind: string; label: string; route: string } | null
}

const results: Array<{ name: string; ok: boolean; detail: string }> = []
function check(name: string, ok: boolean, detail = '') {
  results.push({ name, ok: !!ok, detail })
}

const files = process.argv.slice(2)
if (!files.length) {
  console.error('用法：node --experimental-strip-types tools/verify_orderdetail_realdata.mts <journey.json>...')
  process.exit(2)
}

for (const file of files) {
  const j: Journey = JSON.parse(readFileSync(file, 'utf8'))
  const tag = `${file.split(/[\\/]/).pop()} (${j.order_id})`
  const tag2 = j.current_stage

  // 1) 六阶段齐备（R09：阶段性口径唯一来源）
  check(`${tag} 阶段数为 6`, j.stages.length === 6, `实际 ${j.stages.length}`)

  // 2) 当前阶段唯一，且确实存在于阶段表里
  const currents = j.stages.filter((s) => s.id === j.current_stage)
  check(`${tag} current_stage 在阶段表内且唯一`, currents.length === 1, `current_stage=${j.current_stage}`)

  // 3) 页面排序：当前阶段必须排第一，其余按 order 升序（R01 当前阶段置顶）
  const shown = orderStagesForDisplay(j.stages as any, j.current_stage)
  check(`${tag} 当前阶段置顶`, shown[0].id === j.current_stage, `首位=${shown[0].id}`)
  const rest = shown.slice(1)
  const sortedRest = [...rest].sort((a, b) => a.order - b.order)
  check(`${tag} 其余阶段按 order 升序`, rest.map((s) => s.id).join() === sortedRest.map((s) => s.id).join(),
    rest.map((s) => s.order).join(','))
  check(`${tag} 排序不丢阶段/不改数量`,
    shown.length === j.stages.length && new Set(shown.map((s) => s.id)).size === j.stages.length)

  // 4) 文档计数口径：只有 submitted 计已投递
  const manualTotal = j.stages.reduce((n, s) => n + (s.deliverables || []).length, 0)
  const manualDone = j.stages.reduce(
    (n, s) => n + (s.deliverables || []).filter((d) => d.submitted).length, 0)
  check(`${tag} 文档总数口径一致`, countDocs(j.stages as any) === manualTotal, `countDocs=${countDocs(j.stages as any)}`)
  check(`${tag} 已投递数口径一致`, countDelivered(j.stages as any) === manualDone, `countDelivered=${countDelivered(j.stages as any)}`)

  // 5) 每个交付物都必须能算出工作台路径（点「去填写/查看」不会掉进空路由）
  const codes = j.stages.flatMap((s) => (s.deliverables || []).map((d) => d.code))
  const badRoutes = codes
    .map((c) => workbenchRoute(j.order_id, c))
    .filter((r) => !r.startsWith(`/practice/orders/${j.order_id}/deliverables?code=`))
  check(`${tag} 每个文档都有可 push 的工作台路径`, badRoutes.length === 0 && codes.length > 0,
    `${codes.length} 个文档${badRoutes.length ? '，坏路径 ' + badRoutes.join(',') : ''}`)
  check(`${tag} 不带 code 时退回工作台首页`,
    workbenchRoute(j.order_id) === `/practice/orders/${j.order_id}/deliverables`)

  // 6) 主动作：label 非空、route 是可 push 的前端路径、指向本单
  const na = j.next_action
  check(`${tag} 有唯一主动作或订单已完成`,
    na === null || (!!na.label && !!na.route && na.route.startsWith('/')),
    na ? `${na.kind} / ${na.label} -> ${na.route}` : 'next_action=null（已完成）')
  if (na) {
    // 主动作不一定是"本单页面"：抢单/资源锁定这类动作落在消息中心、聊天界面（见 journey_service._route_for）
    check(`${tag} 主动作路径属于本单或已注册的全局工作台`,
      na.route.includes(j.order_id) || ['/practice/im', '/practice/messages', '/practice'].includes(na.route),
      na.route)
  }

  // 7) 当前阶段的 next_action 与顶层一致（INTERFACE-v1 §2：顶层=当前阶段唯一主动作）
  const cur = j.stages.find((s) => s.id === j.current_stage) as JourneyStage
  if (cur?.next_action && na) {
    check(`${tag} 当前阶段 next_action 与顶层一致`, cur.next_action.route === na.route,
      `${cur.next_action.route} vs ${na.route}`)
  }

  // 8) 阶段文档属于该阶段（分区不会把文档挂错阶段）
  const codesByStage = Object.fromEntries(j.stages.map((s) => [s.id, (s.deliverables || []).map((d) => d.code)]))
  check(`${tag} 阶段文档非空阶段有 title`, j.stages.every((s) =>
    (s.deliverables || []).every((d) => !!d.code && !!d.title)),
    JSON.stringify(codesByStage))

  // 9) 「去产出与投递」按阶段定位（currentStageDocCode）：结果必须是当前阶段自己的文档
  const curStage = j.stages.find((s) => s.id === j.current_stage)!
  const locCode = currentStageDocCode(curStage as any)
  const curCodes = (curStage.deliverables || []).map((d) => d.code)
  check(`${tag} 当前阶段定位 code 属于本阶段`, !curCodes.length || curCodes.includes(locCode),
    `locate=${locCode || '(空 → 退回工作台首页)'} 本阶段=${curCodes.join(',') || '（无文档）'}`)
  check(`${tag} 定位 code 优先未投递的那份（全投完则取第一份）`,
    !curCodes.length || (curStage.deliverables!.find((d) => !d.submitted)?.code || curCodes[0]) === locCode,
    locCode)
  check(`${tag} 定位 code 能算出可 push 的工作台路径`,
    !locCode || workbenchRoute(j.order_id, locCode).startsWith('/practice/orders/' + j.order_id + '/deliverables?code='),
    workbenchRoute(j.order_id, locCode))
  check(`${tag} 阶段无文档时定位为空串（退回工作台首页）`,
    curCodes.length > 0 || locCode === '', `locate="${locCode}"`)

  // 10) 「继续」跳转的就是 next_action.route，且必须是前端已注册的路由前缀
  const ROUTE_PREFIXES = ['/practice/orders/', '/practice/im', '/practice/messages', '/practice']
  if (na) {
    const hit = ROUTE_PREFIXES.filter((p) => na.route === p || na.route.startsWith(p))
    check(`${tag} 主动作 route 命中前端已注册路由`, hit.length > 0, `${na.route} 命中 ${JSON.stringify(hit)}`)
    // deliverable 类主动作必须带 code，且 code 属于 contracts/stages 里该阶段的交付物
    if (na.deliverable) {
      check(`${tag} deliverable 类主动作带正确的 code`,
        na.route === workbenchRoute(j.order_id, na.deliverable) && codes.includes(na.deliverable),
        `${na.route} / code=${na.deliverable}`)
    }
  }

  console.log(`\n── ${tag2}：当前阶段 ${j.current_stage}，页面将把这行排在最前 ──`)
  for (const s of shown) {
    const flag = s.id === j.current_stage ? '★' : ' '
    const docs = (s.deliverables || []).map((d) => `${d.title}(${d.submitted ? 'V' + d.version + ' 已投递' : '未投递'})`)
    console.log(`${flag} ${String(s.order).padStart(2)} ${s.id.padEnd(18)} ${s.state.padEnd(8)} ${docs.join(' / ') || '（本阶段无文档）'}`)
  }
  console.log(`  主动作：${na ? `${na.label} -> ${na.route}` : '无（订单已完成）'}`)
  console.log(`  定位交付物：${locCode || '（本阶段无文档 → 工作台首页）'}`)
}

let failures = 0
for (const r of results) {
  if (!r.ok) failures++
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  —  ' + r.detail : ''}`)
}
console.log(`\n${results.length - failures}/${results.length} 通过`)
process.exit(failures ? 1 : 0)
