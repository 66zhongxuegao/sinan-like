import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes = [
  { path: '/', name: 'home', component: () => import('@/views/HomeView.vue'), meta: { title: '总览', fullscreen: true, public: true } },

  // ── 身份（公开页）──
  // 登录与注册已经收进首页；保留旧地址做兼容跳转。
  { path: '/login', redirect: (to: any) => ({ path: '/', query: { ...to.query, mode: 'login' } }) },
  { path: '/register', redirect: (to: any) => ({ path: '/', query: { ...to.query, mode: 'register' } }) },

  // ── 标准案例（需要登录：走真实服务/存储/权限，不是前端伪造链路）──
  // 页面内醒目标识「标准案例 / 演示数据」；demo- 前缀账号的数据口径为示例数据（R14）。
  { path: '/demo', name: 'demo-case', component: () => import('@/views/DemoCaseView.vue'), meta: { title: '标准案例' } },

  // ── 学习做题 ──
  { path: '/learn', name: 'learn-map', component: () => import('@/views/learn/LearnMapView.vue'), meta: { title: '学习地图' } },
  { path: '/learn/bridge/:code?', name: 'learn-bridge', component: () => import('@/views/learn/CultureBridgeView.vue'), meta: { title: '文化桥' } },
  { path: '/learn/thread/:sp', name: 'learn-thread', component: () => import('@/views/learn/ThreadView.vue'), meta: { title: '技能点对话工作台' } },

  // ── 对话实战（13 步业务流 + vbooking 工作台操作面，二者并列）──
  { path: '/practice', name: 'practice', component: () => import('@/views/practice/PracticeView.vue'), meta: { title: '实战工作台' } },
  { path: '/practice/im', name: 'p-im', component: () => import('@/views/practice/ImView.vue'), meta: { title: '聊天界面' } },
  { path: '/practice/messages', name: 'p-messages', component: () => import('@/views/vbooking/MessagesView.vue'), meta: { title: '消息中心' } },
  // 旧的 vbooking 订单管理表已废弃：订单列表并入「订单管理」（/practice）
  { path: '/practice/orders', redirect: '/practice' },
  { path: '/practice/orders/:id', name: 'p-order-detail', component: () => import('@/views/vbooking/OrderDetailView.vue'), meta: { title: '订单详情' } },
  { path: '/practice/orders/:id/call', name: 'p-order-call', component: () => import('@/views/practice/CallView.vue'), meta: { title: '通话' } },
  { path: '/practice/orders/:id/score', name: 'p-order-score', component: () => import('@/views/practice/OrderScoreView.vue'), meta: { title: '订单评分复盘' } },
  { path: '/practice/orders/:id/deliverables', name: 'p-deliverables', component: () => import('@/views/practice/DeliverableWorkbenchView.vue'), meta: { title: '文件夹' } },
  { path: '/practice/orders/:id/finance', name: 'p-finance', component: () => import('@/views/practice/FinanceView.vue'), meta: { title: '成本与结算' } },
  { path: '/practice/orders/:id/plan/new', name: 'p-plan-new', component: () => import('@/views/vbooking/PlanNewView.vue'), meta: { title: '创建方案' } },
  // 方案编辑已并入产出与投递：行程方案 = 逐日六要素编辑器（避免两处各维护一套行程表单）
  { path: '/practice/orders/:id/plan/edit', redirect: (to: any) => `/practice/orders/${to.params.id}/deliverables?code=itinerary` },

  // ── 数据看板（团队 / 运营双视角，纯前端演示数据，按埋点口径可替换）──
  { path: '/dashboard', name: 'dashboard', component: () => import('@/views/dashboard/DashboardView.vue'), meta: { title: '训练数据看板', standalone: true } },

  // ── 训练反馈 ──
  { path: '/profile', name: 'profile', component: () => import('@/views/ProfileView.vue'), meta: { title: '学情画像' } },
  { path: '/profile/quiz', name: 'profile-quiz', component: () => import('@/views/ProfileQuizView.vue'), meta: { title: '初始画像测评' } },
  { path: '/score', redirect: '/practice' },
  { path: '/toolbox', name: 'toolbox', component: () => import('@/views/ToolboxView.vue'), meta: { title: '工具台' } },
  { path: '/system', name: 'system', component: () => import('@/views/SystemStatusView.vue'), meta: { title: '系统状态' } },
]

const router = createRouter({ history: createWebHashHistory(), routes })

/**
 * 全局守卫（R08/R11）：没有服务端会话就先去登录，登录后回到原目标。
 *
 * - 首页是公开入口，登录 / 注册表单嵌在首页里；其余页面一律要求会话；
 * - 首次导航先 await store.restore()（GET /auth/session），刷新页面因此保持登录；
 * - 旧地址 /login、/register 兼容跳回首页并打开对应表单。
 */
router.beforeEach(async (to) => {
  const store = useUserStore()
  let authed = store.isAuthenticated
  if (!store.sessionReady) {
    try { authed = await store.restore() } catch { authed = false }
  }
  if (to.meta.public) return true
  if (!authed) {
    const query: Record<string, string> = { mode: 'login' }
    if (to.fullPath && to.fullPath !== '/') query.redirect = to.fullPath
    return { path: '/', query }
  }
  return true
})

export default router
