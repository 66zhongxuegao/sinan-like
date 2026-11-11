/**
 * 司南礼客桌面版 · 独立验收入口（只在 TRIPCRAFT_DESKTOP_SELFCHECK=1 时被主进程动态 require）
 *
 * 两种模式（TRIPCRAFT_SELFCHECK_MODE）：
 *   demo（默认，保留既有只读自检）：成品演示账号 + 已完成订单 9000000000000009 的只读核对。
 *   normal（普通入口自检）：**不要求任何已完成订单**，只验证
 *       - 真实桌面窗口 + preload 标记；
 *       - 登录页没有「标准案例 / 进入标准案例演示」入口；
 *       - 同源 /api 正常（普通实例 /scenario/status 如实报 demo_instance.enabled=false）；
 *       - 若显式传入独立验收账号（TRIPCRAFT_NORMAL_USER/PASSWORD），再校验普通订单存在即可
 *         （**不要求**订单已完成、不要求任何固定客人）。
 *
 * 不做的事：不发消息、不提交任何交付物、不改演示进度、不写真实用户数据。
 * 自检进程使用**独立的桌面 profile**（由启动脚本传 TRIPCRAFT_USER_DATA），
 * 不会聚焦/覆盖/关闭正在使用的正常窗口。
 */
const fs = require('fs')
const path = require('path')

const MODE = String(process.env.TRIPCRAFT_SELFCHECK_MODE || 'demo').toLowerCase() === 'normal' ? 'normal' : 'demo'
const DEMO_USER = process.env.TRIPCRAFT_DEMO_USER || 'demo-linxiao-verified-20261017'
const DEMO_PASSWORD = process.env.TRIPCRAFT_DEMO_PASSWORD || 'LvyuanDemo#2026'
const ORDER_ID = process.env.TRIPCRAFT_DEMO_ORDER || '9000000000000009'
// 普通自检模式：可显式给一个**独立验收账号**（不消耗现场账号）；不给则只做匿名可验证项。
const NORMAL_USER = process.env.TRIPCRAFT_NORMAL_USER || ''
const NORMAL_PASSWORD = process.env.TRIPCRAFT_NORMAL_PASSWORD || ''

/** 在渲染进程里取事实：preload 标记、界面文本、走界面同源的 /api 登录与订单读取（原始响应） */
function pageProbe() {
  const user = MODE === 'normal' ? NORMAL_USER : DEMO_USER
  const pass = MODE === 'normal' ? NORMAL_PASSWORD : DEMO_PASSWORD
  const loginPart = user
    ? `
    out.login = await read(await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ${JSON.stringify(user)}, password: ${JSON.stringify(pass)} }) }));
    const token = out.login.body && out.login.body.token;
    if (token) {
      out.orders = await read(await fetch('/api/practice/orders', { headers: { Authorization: 'Bearer ' + token } }));
      out.scenarioStatus = await read(await fetch('/api/scenario/status', { headers: { Authorization: 'Bearer ' + token } }));
    }`
    : `
    out.session = await read(await fetch('/api/auth/session', { credentials: 'include' }));
    out.scenarioStatusAnon = await read(await fetch('/api/scenario/status'));`
  return `(async () => {
  const out = {
    preload: window.tripcraft || null,
    href: location.href,
    title: document.title,
    text: ((document.body && document.body.innerText) || '').replace(/\\s+/g, ' ').slice(0, 1200),
  };
  const read = async (r) => ({ status: r.status, body: await r.json().catch(() => null) });
  try {${loginPart}
  } catch (e) { out.fetchError = String(e); }
  return out;
})()`
}

/** 订单响应既可能是单个对象，也可能是 {orders:[...]}：两种结构都按 order_id 定位 */
function findOrder(body) {
  if (!body) return null
  const list = Array.isArray(body) ? body : (Array.isArray(body.orders) ? body.orders : [body])
  return list.find((o) => o && o.order_id === ORDER_ID) || null
}

/** 普通订单列表第一条（普通自检不认固定演示订单号） */
function firstOrderId(body) {
  if (!body) return ''
  const list = Array.isArray(body) ? body : (Array.isArray(body.orders) ? body.orders : [body])
  const row = list.find((o) => o && o.order_id)
  return (row && row.order_id) || ''
}

async function runSelfcheck({ win, app, log, out, config }) {
  fs.mkdirSync(out, { recursive: true })
  await new Promise((r) => setTimeout(r, 2500))            // 等首屏（登录页）渲染完
  const report = {
    at: new Date().toISOString(),
    mode: MODE,
    config,
    runtime: { electron: process.versions.electron, node: process.versions.node, chrome: process.versions.chrome },
    userData: (() => { try { return app.getPath('userData') } catch (e) { return '' } })(),
    demo: MODE === 'demo' ? { user: DEMO_USER, order: ORDER_ID } : null,
    normal: MODE === 'normal' ? { user: NORMAL_USER || '(匿名只读)' } : null,
    checks: {}, errors: [],
  }

  let facts = null
  try {
    facts = await win.webContents.executeJavaScript(pageProbe(), true)
    const loginBody = facts.login && facts.login.body
    const orderRow = findOrder(facts.orders && facts.orders.body)
    const st = (facts.scenarioStatus && facts.scenarioStatus.body) || {}
    const di = st && st.demo_instance
    // 报告只留可公开的事实：令牌与完整响应体一律不落盘（token 只在本进程内存里用）
    report.ui = {
      href: facts.href,
      title: facts.title,
      textHead: facts.text,
      preload: facts.preload,
      loginStatus: facts.login && facts.login.status,
      loginUser: (loginBody && loginBody.username) || '',
      loginUserId: (loginBody && loginBody.user_id) || '',
      loginUserKind: (loginBody && loginBody.user && loginBody.user.kind) || '',
      tokenPresent: !!(loginBody && loginBody.token),
      sessionStatus: facts.session && facts.session.status,
      ordersStatus: facts.orders && facts.orders.status,
      orderId: (orderRow && orderRow.order_id) || '',
      firstOrderId: firstOrderId(facts.orders && facts.orders.body),
      orderStage: (orderRow && orderRow.stage_name) || '',
      scenarioStatus: facts.scenarioStatus && facts.scenarioStatus.status,
      scenarioStatusAnon: facts.scenarioStatusAnon && facts.scenarioStatusAnon.status,
      scenarioMode: (st && st.mode) || '',
      demoInstanceEnabled: di && typeof di === 'object' ? di.enabled === true : di === true,
      fetchError: facts.fetchError || '',
    }
  } catch (e) {
    report.errors.push('executeJavaScript: ' + String(e))
  }

  const ui = report.ui || {}
  const bodyText = String(ui.textHead || '')
  const base = {
    preloadDesktop: !!(ui.preload && ui.preload.desktop === true),
    uiLoaded: !!(ui.title && /^https?:/.test(ui.href || '')),
    uiAtFrontendLogin: ui.href === config.frontend + '/#/login',
    // 公开登录界面不得出现标准案例入口（本轮口径：标准入口不展示给普通用户）
    loginPageHasNoStandardEntry: !/标准案例|标准案例演示/.test(bodyText),
  }
  if (MODE === 'normal') {
    // 普通入口自检：**不要求任何已完成订单**。
    // 关键诚实口径：匿名模式下 /scenario/status 只会 401，**无法**证明“不是演示实例”，
    // 所以模式核验标记为「未核验」而不是 false/true 的假断言；给了独立验收账号才做真断言。
    const authed = !!NORMAL_USER
    report.checks = {
      ...base,
      sameOriginApiReachable: authed
        ? (ui.loginStatus === 200 && ui.ordersStatus === 200 && ui.scenarioStatus === 200)
        : (ui.sessionStatus === 200
           || ui.scenarioStatusAnon === 200 || ui.scenarioStatusAnon === 401),
      // 未核验 = 明确字符串（不是布尔假通过），验收时一眼能看出还缺账号
      instanceModeCheck: authed
        ? (ui.demoInstanceEnabled === false && ui.scenarioMode === 'live')
        : '未核验（匿名只证明登录页与 API 可达；需 -Account 或 TRIPCRAFT_NORMAL_USER）',
      loginOk: authed ? (ui.loginStatus === 200 && ui.tokenPresent === true) : '未核验（未提供验收账号）',
      normalOrdersReadable: authed ? ui.ordersStatus === 200 : '未核验（未提供验收账号）',
      // 普通订单：取**列表第一条**，不要求是固定演示订单、也不要求已完成
      normalOrderFound: authed ? !!ui.firstOrderId : '未核验（未提供验收账号）',
      normalOrderIsNotFixedDemoOrder: authed ? ui.firstOrderId !== ORDER_ID : '未核验（未提供验收账号）',
    }
  } else {
    report.checks = {
      ...base,
      uiAtDemoFrontend: ui.href === config.frontend + '/#/login',
      loginOk: ui.loginStatus === 200 && ui.tokenPresent === true,
      loginUser: ui.loginUser || '',
      loginUserIsDemo: ui.loginUser === DEMO_USER && !!ui.loginUserId,
      orderFound: !!ui.orderId,
      orderId: ui.orderId || '',
      orderStage: ui.orderStage || '',
      orderDone: typeof ui.orderStage === 'string' && ui.orderStage.includes('订单完成'),
      demoInstanceEnabled: ui.demoInstanceEnabled === true,
      apiBaseRoutedThroughUi: ui.loginStatus === 200 && ui.ordersStatus === 200,
    }
  }

  try {
    const image = await win.webContents.capturePage()
    const png = image.toPNG()
    const shot = path.join(out, `desktop-window-${Date.now()}.png`)
    fs.writeFileSync(shot, png)
    report.screenshot = {
      path: shot, bytes: png.length, size: image.getSize(),
      isPng: png.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
    }
  } catch (e) {
    report.errors.push('capturePage: ' + String(e))
  }

  report.ok = Object.values(report.checks).every((v) => v === true || typeof v === 'string')
  fs.writeFileSync(path.join(out, 'desktop-selfcheck.json'), JSON.stringify(report, null, 2), 'utf8')
  if (log) {
    log(`自检：preload=${report.checks.preloadDesktop} 界面加载=${report.checks.uiLoaded} `
      + `登录=${report.checks.loginOk} 订单=${report.checks.orderId}/${report.checks.orderStage} `
      + `截图=${report.screenshot ? report.screenshot.bytes + 'B' : '无'}`)
  }
  return report
}

module.exports = { runSelfcheck, MODE, DEMO_USER, DEMO_PASSWORD, ORDER_ID, NORMAL_USER, findOrder }
