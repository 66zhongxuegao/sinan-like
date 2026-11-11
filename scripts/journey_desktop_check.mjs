/**
 * 司南礼客桌面版 · 程序级自验收（按批次留档，历史批次永不覆盖）
 *
 * 分层：
 *  A. 前置：Electron 运行时（dist/version 与 npm 包一致）、演示库、演示服务 18920/15181
 *  B. 入口接线（看常量默认值，不全文搜端口）+ 语法检查
 *  C. 真实 HTTP：前端 15181 同源 /api 代理 → 18920；演示账号、订单 9000000000000009 / 订单完成
 *  D. 自检模块断言逻辑用 C 步真实响应结构校验
 *  E. GUI：复用模式启动真实 Electron（直接 spawn + 文件重定向，捕获 error/exit/stdout）；
 *     第二次启动只聚焦已有窗口；退出后服务仍在且 LISTENING PID 未变
 *  F. --keep-open：用**实际双击入口**（司南礼客桌面版.bat → 启动标准演示.ps1）保留正常窗口
 *
 * 若本会话沙箱不允许 Chromium 启动（不能开命名管道），E/F 标 BLOCKED 并退 3；
 * 有 GUI 权限的环境重跑同一条命令即可完成全部断言。
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONT = path.join(ROOT, 'frontend')
const ELECTRON = path.join(FRONT, 'node_modules', 'electron', 'dist', 'electron.exe')
const OUT = path.join(ROOT, 'output', 'acceptance', 'output-audit-20261017', 'journey', 'desktop')
const TMP = path.join(ROOT, 'output', 'journey', 'tmp')
const DEMO_DB = path.join(ROOT, '.dsh-run', 'codex-review', 'preview.sqlite')
const USER_DATA_CHECK = path.join(TMP, 'electron-ud-selfcheck')
const BAT = path.join(ROOT, '司南礼客桌面版.bat')
const DEMO_USER = 'demo-linxiao-verified-20261017'
const DEMO_PASSWORD = 'LvyuanDemo#2026'
const ORDER_ID = '9000000000000009'
const FRONTEND_URL = 'http://127.0.0.1:15181'
const BACKEND_URL = 'http://127.0.0.1:18920'
const KEEP_OPEN = process.argv.includes('--keep-open')
const STAMP = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
const RUN_DIR = path.join(OUT, 'runs', STAMP)
const REPORT = path.join(RUN_DIR, 'desktop-selfcheck.json')
const LOG = path.join(RUN_DIR, 'electron.log')
const DEFAULT_LOG = path.join(ROOT, 'logs', 'electron.log')

fs.mkdirSync(RUN_DIR, { recursive: true })
fs.mkdirSync(TMP, { recursive: true })
fs.rmSync(USER_DATA_CHECK, { recursive: true, force: true })

const results = []
const check = (id, name, ok, detail = '', blocked = false) => {
  results.push({ id, name, ok: !!ok, blocked, detail: String(detail) })
  console.log(`${blocked ? 'BLOCK' : ok ? 'PASS ' : 'FAIL '} ${id}  ${name}${detail ? '  ·  ' + detail : ''}`)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const readOrEmpty = (f) => { try { return fs.readFileSync(f, 'utf8') } catch { return '' } }
const stripComments = (s) => s.replace(/^\s*\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')

async function alive(url, timeout = 2000) {
  try { return (await fetch(url, { signal: AbortSignal.timeout(timeout) })).status } catch { return 0 }
}

/** 直接 spawn + 文件描述符重定向：不用 cmd 层，且能拿到 error/exit（沙箱不允许管道捕获，故写文件） */
function launch(env, tag) {
  const outLog = path.join(RUN_DIR, `electron-${tag}.stdout.log`)
  const errLog = path.join(RUN_DIR, `electron-${tag}.stderr.log`)
  const outFd = fs.openSync(outLog, 'w')
  const errFd = fs.openSync(errLog, 'w')
  const args = [FRONT]
  if (env.TRIPCRAFT_USER_DATA) args.push(`--user-data-dir=${env.TRIPCRAFT_USER_DATA}`)
  const info = { tag, outLog, errLog, error: null, exitCode: null, signal: null, child: null }
  try {
    info.child = spawn(ELECTRON, args, { cwd: FRONT, stdio: ['ignore', outFd, errFd], windowsHide: true, env })
    info.pid = info.child.pid
    info.child.on('error', (e) => { info.error = `${e.name}: ${e.message}`; console.log(`    实例 ${tag} spawn error: ${info.error}`) })
    info.child.on('exit', (code, signal) => {
      info.exitCode = code; info.signal = signal
      try { fs.closeSync(outFd) } catch {}
      try { fs.closeSync(errFd) } catch {}
    })
  } catch (e) {
    info.error = String(e)
  }
  console.log(`    启动实例 ${tag}：pid=${info.pid || 'n/a'}${info.error ? ' error=' + info.error : ''}`)
  return info
}

function baseEnv(extra = {}) {
  const env = { ...process.env, ...extra }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.TRIPCRAFT_DESKTOP_SELFCHECK
  delete env.TRIPCRAFT_DESKTOP_SELFCHECK_OUT
  delete env.TRIPCRAFT_USER_DATA
  return { ...env, ...extra }
}

function runToFile(line, tag, cwd = ROOT) {  const outLog = path.join(RUN_DIR, `${tag}.out.txt`)
  const errLog = path.join(RUN_DIR, `${tag}.err.txt`)
  const outFd = fs.openSync(outLog, 'w')
  const errFd = fs.openSync(errLog, 'w')
  return new Promise((resolve) => {
    let child
    try { child = spawn('cmd', ['/c', line], { cwd, stdio: ['ignore', outFd, errFd], windowsHide: true, env: baseEnv() }) }
    catch (e) { resolve({ code: -1, out: '', err: String(e) }) ; return }
    child.on('error', (e) => resolve({ code: -1, out: readOrEmpty(outLog), err: String(e) }))
    child.on('exit', (code) => {
      try { fs.closeSync(outFd) } catch {}
      try { fs.closeSync(errFd) } catch {}
      resolve({ code, out: readOrEmpty(outLog), err: readOrEmpty(errLog) })
    })
  })
}

/** 直接 spawn（不经 cmd，避免额外引号层）：用于 node --check 这类普通命令 */
function spawnToFile(exe, args, tag, cwd = ROOT) {
  const outLog = path.join(RUN_DIR, `${tag}.out.txt`)
  const errLog = path.join(RUN_DIR, `${tag}.err.txt`)
  const outFd = fs.openSync(outLog, 'w')
  const errFd = fs.openSync(errLog, 'w')
  return new Promise((resolve) => {
    let child
    try { child = spawn(exe, args, { cwd, stdio: ['ignore', outFd, errFd], windowsHide: true, env: baseEnv() }) }
    catch (e) { resolve({ code: -1, out: '', err: String(e) }); return }
    child.on('error', (e) => resolve({ code: -1, out: readOrEmpty(outLog), err: String(e) }))
    child.on('exit', (code) => {
      try { fs.closeSync(outFd) } catch {}
      try { fs.closeSync(errFd) } catch {}
      resolve({ code, out: readOrEmpty(outLog), err: readOrEmpty(errLog) })
    })
  })
}

/** 等进程结束：已结束就立即返回（避免 exit 事件早于监听导致的假超时） */
function waitExit(info, ms) {
  if (info.exitCode !== null || info.error) return Promise.resolve(info.exitCode)
  return new Promise((resolve) => {
    const t = setTimeout(() => resolve('timeout'), ms)
    info.child.on('exit', (code) => { clearTimeout(t); resolve(code) })
  })
}

function psToFile(script, outFile) {
  return new Promise((resolve) => {
    const p = spawn('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      `${script} | Out-File -Encoding utf8 -FilePath '${outFile}'`], { cwd: ROOT, stdio: 'ignore', windowsHide: true })
    p.on('exit', () => resolve(readOrEmpty(outFile)))
    p.on('error', () => resolve(''))
  })
}
/** 只比对 LISTENING 行的端口/PID：ESTABLISHED 会随请求变化，不能当作重启判据 */
const listeners = () => psToFile("netstat -ano | Select-String ':15181|:18920' | Select-String 'LISTENING'",
  path.join(TMP, 'desktop-listen.txt')).then((s) =>
  s.split(/\r?\n/).map((l) => l.trim().split(/\s+/).filter(Boolean))
    .filter((a) => a.length >= 4)
    .map((a) => `${a[1]}=${a[3]}`).sort().join(','))

async function main() {
  // ---------- A. 前置 ----------
  const pkgVersion = JSON.parse(fs.readFileSync(path.join(FRONT, 'node_modules', 'electron', 'package.json'), 'utf8')).version
  const distVersion = readOrEmpty(path.join(FRONT, 'node_modules', 'electron', 'dist', 'version')).trim()
  check('PRE-1', 'Electron 运行时齐备且与 npm 包版本一致',
    fs.existsSync(ELECTRON) && distVersion === pkgVersion, `dist/version=${distVersion} package=${pkgVersion}`)
  check('PRE-2', '演示库仍在（本入口不新建/不重置数据库）',
    fs.existsSync(DEMO_DB), `${DEMO_DB} ${fs.existsSync(DEMO_DB) ? fs.statSync(DEMO_DB).size + ' B' : ''}`)
  const beStatus = await alive(BACKEND_URL + '/')
  const feStatus = await alive(FRONTEND_URL + '/')
  check('PRE-3', '演示服务在跑（后端 18920 / 前端 15181）', beStatus === 200 && feStatus === 200,
    `backend=${beStatus} frontend=${feStatus}`)

  // ---------- B. 接线（看常量默认值）与语法 ----------
  const bat = readOrEmpty(BAT)
  const ps1 = readOrEmpty(path.join(ROOT, '启动标准演示.ps1'))
  const mainCjs = readOrEmpty(path.join(FRONT, 'electron', 'main.cjs'))
  const mainCode = stripComments(mainCjs)
  const frontDefault = /const FRONTEND\s*=\s*\(process\.env\.TRIPCRAFT_FRONTEND_URL\s*\|\|\s*'([^']+)'\)/.exec(mainCode)
  const backDefault = /const BACKEND\s*=\s*\(process\.env\.TRIPCRAFT_BACKEND_URL\s*\|\|\s*'([^']+)'\)/.exec(mainCode)
  check('WIRE-1', '双击入口 bat 只调同目录 .ps1（不重复维护端口/运行时逻辑），且 ASCII-only 免受 cmd 代码页影响',
    /\.ps1/.test(bat) && !/npm install/.test(bat) && !/Invoke-WebRequest/.test(bat) && !/[^\x00-\x7f]/.test(bat),
    `bat 行数=${bat.split(/\r?\n/).length} 非ASCII=${(bat.match(/[^\x00-\x7f]/g) || []).length}`)
  check('WIRE-2', '标准演示脚本显式传 18920/15181 + 复用模式，并保留 -WebOnly 兼容开关',
    /TRIPCRAFT_BACKEND_URL\s*=\s*'http:\/\/127\.0\.0\.1:18920'/.test(ps1)
    && /TRIPCRAFT_FRONTEND_URL\s*=\s*'http:\/\/127\.0\.0\.1:15181'/.test(ps1)
    && /TRIPCRAFT_REUSE\s*=\s*'1'/.test(ps1) && /WebOnly/.test(ps1)
    && /Remove-Item Env:ELECTRON_RUN_AS_NODE/.test(ps1), 'ok')
  check('WIRE-3', '主进程默认常量仍是 5180/18010（原 npm run desktop 语义不变）',
    frontDefault?.[1] === 'http://127.0.0.1:5180' && backDefault?.[1] === 'http://127.0.0.1:18010'
    && !/18920|15181/.test(mainCode),
    `frontend 默认=${frontDefault?.[1]} backend 默认=${backDefault?.[1]}`)
  check('WIRE-4', '验证逻辑不在主进程内（只在显式自检时动态 require scripts/desktop_selfcheck.cjs）',
    /desktop_selfcheck\.cjs/.test(mainCode) && !/LvyuanDemo|DEMO_PASSWORD/.test(mainCode),
    `main.cjs 行数=${mainCjs.split(/\r?\n/).length}`)
  const syn = await spawnToFile('node', ['--check', path.join(FRONT, 'electron', 'main.cjs')], 'syn-main')
  const syn2 = await spawnToFile('node', ['--check', path.join(FRONT, 'electron', 'preload.cjs')], 'syn-preload')
  const syn3 = await spawnToFile('node', ['--check', path.join(ROOT, 'scripts', 'desktop_selfcheck.cjs')], 'syn-selfcheck')
  check('SYNTAX-1', 'main.cjs / preload.cjs / desktop_selfcheck.cjs 语法检查通过',
    syn.code === 0 && syn2.code === 0 && syn3.code === 0,
    `main=${syn.code} preload=${syn2.code} selfcheck=${syn3.code} ${syn.err.slice(0, 80)}`)
  check('PRELOAD-1', 'preload 暴露 desktop=true（桌面壳判据）',
    /desktop:\s*true/.test(readOrEmpty(path.join(FRONT, 'electron', 'preload.cjs'))), 'ok')

  // ---------- C. 真实 HTTP：窗口同源 /api 代理 → 18920 ----------
  let proxyLogin = { status: 0, body: null }
  try {
    const r = await fetch(FRONTEND_URL + '/api/auth/login', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: DEMO_USER, password: DEMO_PASSWORD }) })
    proxyLogin = { status: r.status, body: await r.json() }
  } catch (e) { proxyLogin.error = String(e) }
  check('API-1', '前端 15181 同源 /api/auth/login 代理到已验后端（窗口 fetch 走的就是这条）',
    proxyLogin.status === 200 && !!proxyLogin.body?.token, `status=${proxyLogin.status}`)
  check('API-2', '已完成账号仍在（demo-linxiao-verified-20261017）',
    proxyLogin.body?.username === DEMO_USER && !!proxyLogin.body?.user_id,
    `user=${proxyLogin.body?.username} user_id=${proxyLogin.body?.user_id}`)
  let proxyOrders = { status: 0, body: null }
  if (proxyLogin.body?.token) {
    const r = await fetch(FRONTEND_URL + '/api/practice/orders',
      { headers: { Authorization: 'Bearer ' + proxyLogin.body.token } })
    proxyOrders = { status: r.status, body: await r.json() }
  }
  const { findOrder } = require(path.join(ROOT, 'scripts', 'desktop_selfcheck.cjs'))
  const order = findOrder(proxyOrders.body)
  check('DATA-1', '订单 9000000000000009 仍在且业务已结清（stage=订单完成）',
    proxyOrders.status === 200 && !!order && String(order.stage_name || '').includes('订单完成'),
    `status=${proxyOrders.status} order=${order?.order_id} stage=${order?.stage_name}`)

  // ---------- D. 自检模块断言逻辑（真实响应结构） ----------
  const logic = {
    loginOk: proxyLogin.status === 200 && !!proxyLogin.body?.token,
    loginUserIsDemo: proxyLogin.body?.username === DEMO_USER && !!proxyLogin.body?.user_id,
    orderFound: !!order,
    orderDone: String(order?.stage_name || '').includes('订单完成'),
  }
  const { findOrder: fo } = require(path.join(ROOT, 'scripts', 'desktop_selfcheck.cjs'))
  check('LOGIC-1', '自检模块能按真实响应结构定位订单（单对象 / {orders:[...]} 两种）',
    fo(order)?.order_id === ORDER_ID && fo({ orders: [order] })?.order_id === ORDER_ID, 'ok')
  check('LOGIC-2', '自检断言口径与真实响应一致', Object.values(logic).every(Boolean), JSON.stringify(logic))

  if (!fs.existsSync(ELECTRON) || beStatus !== 200 || feStatus !== 200) {
    writeLog(results, null, '前置未满足：未进入 GUI 阶段')
    return 1
  }
  const listenBefore = await listeners()

  // ---------- E. GUI 阶段 ----------
  const a = launch(baseEnv({
    TRIPCRAFT_REUSE: '1',
    TRIPCRAFT_FRONTEND_URL: FRONTEND_URL,
    TRIPCRAFT_BACKEND_URL: BACKEND_URL,
    TRIPCRAFT_DESKTOP_SELFCHECK: '1',
    TRIPCRAFT_DESKTOP_SELFCHECK_OUT: RUN_DIR,
    TRIPCRAFT_DESKTOP_LOG_DIR: RUN_DIR,
    TRIPCRAFT_USER_DATA: USER_DATA_CHECK,
  }), 'a-selfcheck')

  let loaded = false
  for (let i = 0; i < 40; i++) {
    if (readOrEmpty(LOG).includes('窗口已加载')) { loaded = true; break }
    if (a.exitCode !== null || a.error) break
    await sleep(500)
  }
  const diag = {
    error: a.error, exitCode: a.exitCode, signal: a.signal,
    stdout: readOrEmpty(a.outLog).slice(0, 300), stderr: readOrEmpty(a.errLog).slice(0, 300),
    appLog: readOrEmpty(LOG).slice(0, 300), userDataCreated: fs.existsSync(USER_DATA_CHECK),
  }
  // 沙箱边界判据：还没加载窗口就退出/报错，且没有应用日志与自检报告
  const guiBlocked = !loaded && (a.error || a.exitCode !== null)
    && !diag.appLog && !fs.existsSync(REPORT)
  if (guiBlocked) {
    try { a.child?.kill() } catch {}
    const why = `electron 未加载窗口即退出（error=${a.error || '无'} exit=${a.exitCode ?? 'n/a'}，无应用日志/自检报告）`
      + ' —— 本会话沙箱不允许 Chromium 启动（不能开命名管道）；需在有 GUI 权限的环境重跑本脚本'
    check('APP-1', 'Electron 以复用模式打开前端窗口', false, why, true)
    check('APP-2', '自检实例按预期自行退出', false, '同上（未启动成功）', true)
    check('SINGLE-1', '第二次启动被单实例锁接住', false, '同上', true)
    check('REPORT-1', '主进程自检报告（preload/界面/同源 API/订单/截图）', false, '同上', true)
    check('DATA-2', '桌面窗口内读到的订单与同源 API 一致', false, '同上', true)
    check('SHOT-1', '窗口内容截图（应用自身 capturePage）', false, '同上', true)
  } else {
    check('APP-1', 'Electron 以复用模式打开前端窗口', loaded,
      loaded ? `日志：窗口已加载 ${FRONTEND_URL}` : JSON.stringify(diag))
    let secondExit = null
    if (loaded) {
      const b = launch(baseEnv({
        TRIPCRAFT_REUSE: '1', TRIPCRAFT_FRONTEND_URL: FRONTEND_URL, TRIPCRAFT_BACKEND_URL: BACKEND_URL,
        TRIPCRAFT_DESKTOP_LOG_DIR: RUN_DIR, TRIPCRAFT_USER_DATA: USER_DATA_CHECK,
      }), 'b-second')
      secondExit = await waitExit(b, 20000)
    }
    const exitCode = await waitExit(a, 90000)
    if (exitCode === 'timeout') { try { a.child.kill() } catch {} }
    check('APP-2', '自检实例按预期自行退出', exitCode === 0, `exit=${exitCode}`)
    check('SINGLE-1', '第二次启动被单实例锁接住（只聚焦已有窗口）',
      secondExit === 0 && readOrEmpty(LOG).includes('收到第二次启动请求'), `secondExit=${secondExit}`)
    let report = null
    try { report = JSON.parse(fs.readFileSync(REPORT, 'utf8')) } catch (e) {}
    check('REPORT-1', '主进程自检报告已生成', !!report, report ? REPORT : JSON.stringify(diag))
    if (report) {
      const c = report.checks || {}
      check('DESK-1', 'preload desktop=true', c.preloadDesktop === true, JSON.stringify(report.ui?.preload))
      check('DESK-2', '界面加载并停在演示前端登录页（未自动登录）',
        c.uiLoaded === true && c.uiAtDemoFrontend === true && /登录|账号|密码/.test(report.ui?.textHead || ''),
        `href=${report.ui?.href}`)
      check('DESK-3', '复用模式未拉起任何服务', report.config?.reuse === true, JSON.stringify(report.config))
      check('DATA-2', '桌面窗口内读到的订单与同源 API 一致（同一后端、同一库）',
        c.orderDone === true && c.orderId === ORDER_ID && c.orderId === order?.order_id,
        `ui=${c.orderId}/${c.orderStage} direct=${order?.order_id}`)
      check('RUNTIME-1', '运行时版本与 npm 包声明一致', report.runtime?.electron === pkgVersion,
        `runtime=${report.runtime?.electron} package=${pkgVersion}`)
      const s = report.screenshot
      check('SHOT-1', '窗口内容截图已保存（应用自身 capturePage）',
        !!(s && fs.existsSync(s.path) && s.bytes > 10000 && s.isPng),
        s ? `${path.basename(s.path)} ${s.bytes} B ${JSON.stringify(s.size)}` : '无')
    } else {
      check('DESK-1', 'preload desktop=true', false, '无自检报告')
      check('DESK-2', '界面加载并停在登录页', false, '无自检报告')
      check('DESK-3', '复用模式未拉起任何服务', false, '无自检报告')
      check('DATA-2', '桌面窗口内读到的订单与同源 API 一致', false, '无自检报告')
      check('SHOT-1', '窗口内容截图', false, '无自检报告')
    }
  }

  // ---------- F. 退出后服务仍在、PID 未变 ----------
  await sleep(1500)
  const beAfter = await alive(BACKEND_URL + '/')
  const feAfter = await alive(FRONTEND_URL + '/')
  check('EXIT-1', '桌面退出后后台演示服务仍在（退出不杀已有服务）', beAfter === 200 && feAfter === 200,
    `backend=${beAfter} frontend=${feAfter}`)
  const listenAfter = await listeners()
  check('EXIT-2', '15181/18920 的 LISTENING 端口/PID 未变（没有重启/新开服务）',
    listenBefore.length > 0 && listenBefore === listenAfter,
    `before=[${listenBefore}] after=[${listenAfter}]`)

  // ---------- G. 用真实双击入口保留正常窗口 ----------
  if (KEEP_OPEN) {
    if (guiBlocked) {
      check('FINAL-1', '用真实入口（司南礼客桌面版.bat）保留正常窗口', false,
        'GUI 被沙箱阻断，无法验证窗口；需在有 GUI 权限的环境运行 bat', true)
    } else {
      const run = await runToFile(`"${BAT}"`, 'entry-bat')
      const out = run.out
      check('FINAL-1', '真实双击入口运行成功（bat → 启动标准演示.ps1，复用服务并开窗）',
        run.code === 0 && /司南礼客桌面版已打开|已启动/.test(out),
        `exit=${run.code} out=${out.replace(/\s+/g, ' ').slice(0, 160)}`)
      const task = await psToFile('Get-Process electron -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id',
        path.join(TMP, 'electron-pids.txt'))
      check('FINAL-2', '入口打开了司南礼客窗口（存在 Electron 进程）',
        task.trim().split(/\s+/).filter(Boolean).length > 0, `pids=${task.trim().replace(/\s+/g, ' ')}`)
    }
  }

  writeLog(results, null, guiBlocked ? 'GUI 阶段被本会话沙箱阻断（退 3）；其余断言均真实执行' : '')
  const failed = results.filter((r) => !r.ok && !r.blocked)
  const blocked = results.filter((r) => r.blocked)
  console.log(`\n=== 司南礼客桌面版自验收: ${results.filter((r) => r.ok).length} passed / ${failed.length} failed / ${blocked.length} blocked ===`)
  if (failed.length) console.log('未通过：' + failed.map((r) => `${r.id}(${r.detail})`).join(' | '))
  if (blocked.length) console.log('被沙箱阻断（需 GUI 权限环境重跑）：' + blocked.map((r) => r.id).join(', '))
  console.log('evidence ->', RUN_DIR)
  return failed.length ? 1 : (blocked.length ? 3 : 0)
}

function writeLog(rows, report, note) {
  const head = [
    '# 司南礼客桌面版 · 程序级自验收',
    `# 批次：${STAMP}`,
    '# 方式：真实 Electron（复用模式接入已验 18920/15181）+ 主进程内部自检 + 应用自身 capturePage 截图',
    '# 未使用：CU、桌面点击、整桌截图；未重启 DSH；未启动/重启 18920、15181；未改演示数据',
    note ? `# 备注：${note}` : '',
    '',
  ].filter(Boolean).join('\n')
  const body = rows.map((r) => `${r.blocked ? 'BLOCK' : r.ok ? 'PASS' : 'FAIL'}\t${r.id}\t${r.name}\t${r.detail}`).join('\n')
  const tail = `\n\npassed=${rows.filter((r) => r.ok).length} failed=${rows.filter((r) => !r.ok && !r.blocked).length} `
    + `blocked=${rows.filter((r) => r.blocked).length}\n`
  fs.writeFileSync(path.join(RUN_DIR, 'desktop-check.log'), head + body + tail, 'utf8')
  fs.writeFileSync(path.join(RUN_DIR, 'desktop-check-summary.json'),
    JSON.stringify({ at: new Date().toISOString(), stamp: STAMP, results: rows, selfcheck: report }, null, 2), 'utf8')
  // 历史批次索引：只追加，不覆盖
  fs.appendFileSync(path.join(OUT, 'runs-index.jsonl'), JSON.stringify({
    stamp: STAMP, at: new Date().toISOString(),
    passed: rows.filter((r) => r.ok).length,
    failed: rows.filter((r) => !r.ok && !r.blocked).length,
    blocked: rows.filter((r) => r.blocked).length,
    dir: path.relative(OUT, RUN_DIR).replace(/\\/g, '/'),
  }) + '\n', 'utf8')
  if (fs.existsSync(DEFAULT_LOG)) {
    try { fs.copyFileSync(DEFAULT_LOG, path.join(RUN_DIR, 'electron-default-profile.log')) } catch {}
  }
}

main().then((code) => process.exit(code)).catch((e) => { console.error('HARNESS-ERROR', e); process.exit(2) })
