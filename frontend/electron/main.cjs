// 司南礼客桌面版（TripCraft 定制师实战系统）· Electron 主进程（最小入口）
//
// 入口语义（不做端口自动发现，只认显式配置）：
//  - 默认（`npm run desktop` / 原入口）：前端 http://127.0.0.1:5190、后端 http://127.0.0.1:18020；
//    已在跑就复用，没跑就拉起（保持原有默认语义）。
//  - 标准演示入口（`启动标准演示.ps1` / `司南礼客桌面版.bat`）：显式传
//    TRIPCRAFT_FRONTEND_URL=http://127.0.0.1:15191、TRIPCRAFT_BACKEND_URL=http://127.0.0.1:18930，
//    并置 TRIPCRAFT_REUSE=1 —— 复用已在跑的演示服务，**不拉起任何服务、不新建/重置数据库**。
//  - 复用模式下服务不通：显示可读错误页 + 写日志 + 非零退出（不白屏、不擅自启库）。
//  - 单实例：第二次启动只聚焦已有窗口。退出：只关本进程拉起的服务，复用来的服务一个都不动。
//
// 自检（仅显式开启时）：TRIPCRAFT_DESKTOP_SELFCHECK=1 → 动态加载 scripts/desktop_selfcheck.cjs，
// 由该独立验收入口完成断言（演示账号/密码与验证逻辑都不在本文件里）。
const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')
const fs = require('fs')

const ROOT = path.resolve(__dirname, '..', '..')          // _lvyuan
const FRONT = path.join(ROOT, 'frontend')
const LOG_DIR = process.env.TRIPCRAFT_DESKTOP_LOG_DIR || path.join(ROOT, 'logs')
const LOG = path.join(LOG_DIR, 'electron.log')
const started = []

const truthy = (v) => ['1', 'true', 'yes', 'on'].includes(String(v || '').toLowerCase())
const REUSE_ONLY = truthy(process.env.TRIPCRAFT_REUSE)
const SELFCHECK = truthy(process.env.TRIPCRAFT_DESKTOP_SELFCHECK)
const SELFCHECK_OUT = process.env.TRIPCRAFT_DESKTOP_SELFCHECK_OUT
  || path.join(ROOT, 'output', 'acceptance', 'output-audit-20261017', 'journey', 'desktop')
const FRONTEND = (process.env.TRIPCRAFT_FRONTEND_URL || 'http://127.0.0.1:5190').replace(/\/$/, '')
const BACKEND = (process.env.TRIPCRAFT_BACKEND_URL || 'http://127.0.0.1:18020').replace(/\/$/, '')

if (process.env.TRIPCRAFT_USER_DATA) {
  try { app.setPath('userData', process.env.TRIPCRAFT_USER_DATA) } catch (e) {}
}

function log(msg) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true })
    fs.appendFileSync(LOG, `[${new Date().toISOString()}] ${msg}\n`)
  } catch (e) {}
}

function alive(url, timeout = 5000) {
  return new Promise((resolve) => {
    let settled = false
    let timer
    const finish = (ok) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(ok)
    }
    const req = http.get(url, (res) => { res.resume(); finish(true) })
    req.on('error', () => finish(false))
    timer = setTimeout(() => { finish(false); req.destroy() }, timeout)
  })
}

async function reachable(url, label) {
  for (let attempt = 0; attempt < 3; attempt++) {
    if (await alive(url)) return true
    if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 500))
  }
  log(`${label}未响应：${url}`)
  return false
}

async function waitFor(url, label, seconds = 60) {
  for (let i = 0; i < seconds * 2; i++) {
    if (await alive(url)) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  log(`等待 ${label} 超时：${url}`)
  return false
}

function start(cmd, args, cwd, label, extraEnv = {}) {
  const env = { ...process.env, PYTHONUTF8: '1', ...extraEnv }
  delete env.ELECTRON_RUN_AS_NODE          // 否则 electron 会被当成纯 Node 跑，开不出窗口
  const p = spawn(cmd, args, { cwd, shell: true, windowsHide: true, env })
  p.stdout.on('data', (d) => log(`[${label}] ${d.toString().trim()}`))
  p.stderr.on('data', (d) => log(`[${label}] ${d.toString().trim()}`))
  started.push({ p, label })
  log(`拉起 ${label}：${cmd} ${args.join(' ')}`)
  return p
}

const portOf = (url) => String(new URL(url).port || '')

function errorPage(title, lines) {
  const esc = (s) => String(s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]))
  return 'data:text/html;charset=utf-8,' + encodeURIComponent(`<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>${esc(title)}</title><style>body{font-family:"Microsoft YaHei",system-ui,sans-serif;background:#f5f6f8;color:#1f2329;margin:0;padding:48px}
.card{max-width:820px;margin:0 auto;background:#fff;border:1px solid #e4e7ec;border-radius:12px;padding:28px 32px}
h1{font-size:22px;margin:0 0 12px}ul{line-height:1.9}code{background:#f2f4f7;padding:1px 6px;border-radius:4px}</style></head>
<body><div class="card"><h1>${esc(title)}</h1><p>司南礼客桌面版没有打开界面，原因如下（不是白屏，也不会重置任何数据）：</p>
<ul>${lines.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>
<p>日志：<code>${esc(LOG)}</code></p></div></body></html>`)
}

async function ensureServices() {
  const problems = []
  const [backendUp, frontendUp] = await Promise.all([
    reachable(BACKEND + '/', '后端'), reachable(FRONTEND, '前端'),
  ])
  if (backendUp) log(`后端复用：${BACKEND}`)
  if (frontendUp) log(`前端复用：${FRONTEND}`)

  if (!backendUp) {
    if (REUSE_ONLY) problems.push(`复用模式：后端 ${BACKEND} 没有在运行（本模式不自动拉起任何服务）`)
    else start('python', ['-X', 'utf8', '-m', 'uvicorn', 'tripcraft.api.app:create_app', '--factory',
                          '--host', '127.0.0.1', '--port', portOf(BACKEND)], ROOT, 'backend')
  }
  if (!frontendUp) {
    if (REUSE_ONLY) problems.push(`复用模式：前端 ${FRONTEND} 没有在运行（本模式不自动拉起任何服务）`)
    else start('npm', ['run', 'dev'], FRONT, 'frontend',
               { VITE_PORT: portOf(FRONTEND), VITE_API_PORT: portOf(BACKEND) })
  }
  if (problems.length) return { ok: false, problems }

  if (!backendUp && !(await waitFor(BACKEND + '/practice/steps', '后端'))) {
    problems.push(`后端未就绪：${BACKEND}`)
  }
  if (!frontendUp && !(await waitFor(FRONTEND, '前端'))) {
    problems.push(`前端未就绪：${FRONTEND}`)
  }
  return { ok: problems.length === 0, problems }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440, height: 940, minWidth: 1180, minHeight: 760,
    backgroundColor: '#f5f6f8',
    title: '司南礼客 · 定制师全流程模拟实战系统',
    icon: path.join(FRONT, 'src', 'assets', 'logo-tripcraft.png'),
    autoHideMenuBar: true,
    show: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false,
                      preload: path.join(__dirname, 'preload.cjs') },
  })
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' } })
  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    log(`界面加载失败：${url} ${desc} code=${code}`)
    win.loadURL(errorPage('界面加载失败', [`前端地址 ${url} 打不开（${desc}，code=${code}）`,
      `后端目标：${BACKEND}`])).catch(() => {})
  })
  win.webContents.on('render-process-gone', (_e, details) => log('渲染进程退出：' + JSON.stringify(details)))
  win.on('show', () => log('桌面窗口已显示'))
  win.once('ready-to-show', () => { win.show(); log('桌面页面已就绪') })
  return win
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  log('已有司南礼客桌面窗口在运行：本次启动直接退出（不重复开演示窗口）')
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = BrowserWindow.getAllWindows()[0]
    log('收到第二次启动请求：聚焦已有窗口')
    if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus() }
  })

  app.whenReady().then(async () => {
    log(`--- 启动 --- reuse=${REUSE_ONLY} selfcheck=${SELFCHECK} electron=${process.versions.electron}`)
    log(`    前端=${FRONTEND} 后端=${BACKEND}`)
    const win = createWindow()
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
      '<!doctype html><html lang="zh"><meta charset="utf-8"><title>司南礼客 · 正在启动</title>' +
      '<body style="font-family:Microsoft YaHei,system-ui,sans-serif;padding:48px;color:#1f2329">' +
      '<h1>司南礼客</h1><p>正在准备界面，请稍候…</p></body></html>'
    ))
    const services = await ensureServices()

    if (!services.ok) {
      await win.loadURL(errorPage('司南礼客服务未就绪', [...services.problems,
        `前端目标：${FRONTEND}`, `后端目标：${BACKEND}`,
        REUSE_ONLY ? '请使用本次启动模式对应的桌面入口重新启动。'
                   : '默认模式会自己拉起后端 18020 / 前端 5190；请检查 Python / Node 依赖。']))
      if (SELFCHECK) {
        fs.mkdirSync(SELFCHECK_OUT, { recursive: true })
        fs.writeFileSync(path.join(SELFCHECK_OUT, 'desktop-selfcheck.json'),
          JSON.stringify({ at: new Date().toISOString(), ok: false, problems: services.problems,
                           config: { frontend: FRONTEND, backend: BACKEND, reuse: REUSE_ONLY } }, null, 2), 'utf8')
        app.exit(2)
      }
      return
    }

    await win.loadURL(FRONTEND).catch((e) => log('loadURL 失败：' + e))
    log('窗口已加载 ' + FRONTEND)

    if (SELFCHECK) {
      // 验证逻辑与演示账号都在 scripts/desktop_selfcheck.cjs，仅显式开启自检时才加载
      const { runSelfcheck } = require(path.join(ROOT, 'scripts', 'desktop_selfcheck.cjs'))
      await runSelfcheck({ win, app, log, out: SELFCHECK_OUT,
                           config: { frontend: FRONTEND, backend: BACKEND, reuse: REUSE_ONLY } })
      app.quit()
    }

    app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) createWindow() })
  }).catch(async (e) => {
    log('桌面启动失败：' + (e.stack || e))
    try {
      const win = BrowserWindow.getAllWindows()[0] || createWindow()
      win.show()
      await win.loadURL(errorPage('司南礼客启动失败', [String(e)]))
    } catch (displayError) {
      log('启动错误页加载失败：' + displayError)
    }
  })
}

app.on('window-all-closed', () => {
  for (const { p, label } of started) {
    try { log(`关闭 ${label}（本进程拉起的）`); process.kill(p.pid) } catch (e) {}
  }
  if (REUSE_ONLY) log('复用模式：没有拉起任何服务，退出时不会结束任何后台服务')
  app.quit()
})
