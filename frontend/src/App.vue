<template>
  <router-view v-if="standalone" />
  <div v-else class="app-shell">
    <aside v-if="!isFullscreen" class="sidebar">
      <div class="side-top">
        <AppLogo />
      </div>
      <nav class="side-nav">
        <template v-for="g in groups" :key="g.title">
          <div v-if="g.title" class="nav-group">{{ g.title }}</div>
          <router-link v-for="item in g.items" :key="item.path" :to="item.path"
            class="nav-item" :class="{ active: isActive(item.path) }">
            <SIcon :name="item.icon" :size="16" />
            <span>{{ item.title }}</span>
          </router-link>
        </template>
      </nav>
      <div class="side-foot">
        <router-link to="/" class="foot-card" :class="{ on: route.path === '/' }">
          <span class="foot-title"><SIcon name="home" :size="15" /> 返回首页</span>
        </router-link>
      </div>
    </aside>

    <main class="main">
      <header v-if="showTopbar" class="topbar" :class="{ plain: isFullscreen }">
        <div v-if="!isFullscreen" class="topbar-left">
          <h1 class="page-title">{{ pageHeading }}</h1>
        </div>
        <div class="topbar-right">
          <span v-if="route.path !== '/'" class="status" :class="online ? 'on' : 'off'"><i class="dot" />{{ online ? '已连接' : '未连接' }}</span>
          <!-- 学情画像与个人资料都在右上角用户菜单里（R12：从侧边栏移入这里） -->
          <UserMenu v-if="showUserMenu" />
        </div>
      </header>

      <section class="content" :class="{ plain: isFullscreen }">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </section>
      <ProgressDock v-if="route.path.startsWith('/practice') && route.path !== '/practice'" :order-id="String(route.params.id || '')" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppLogo from '@/components/AppLogo.vue'
import SIcon from '@/components/SIcon.vue'
import UserMenu from '@/components/UserMenu.vue'
import ProgressDock from '@/components/ProgressDock.vue'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'

/**
 * 应用外壳：侧边栏 + 顶栏 + 用户菜单 + 内容区。
 *
 * 身份相关只做两件事：把右上角菜单挂上（UserMenu 自带个人资料 / 学情画像 / 退出），
 * 登录页与注册页走 fullscreen 路由（不挂侧边栏）。会话恢复与未登录拦截由
 * router/index.ts 的全局守卫 + stores/user.ts 负责，外壳不重复实现。
 *
 * 旧版「演示账户自动播放」（demo/DemoCursor、DemoBar、demo/store、axios 拦截伪造响应）
 * 已整体删除。标准案例不再是公开入口：**演示实例由工作人员用内部启动方式开启**，
 * 服务端把随机游客替换成固定案例，界面走同一套正常流程；内部排查页 /demo 只在演示实例可见。
 */

const route = useRoute()
const userStore = useUserStore()
const online = ref(false)

const groups = [
  { title: '学习中心', items: [
    { path: '/learn', title: '学习地图', icon: 'book' },
  ]},
  { title: '对话实战', items: [
    { path: '/practice/messages', title: '消息中心', icon: 'chat' },
    { path: '/practice', title: '订单管理', icon: 'layers' },
    { path: '/practice/im', title: '聊天界面', icon: 'chat' },
  ]},
  { title: '训练反馈', items: [
    // R12：学情画像与个人资料**只在右上角用户菜单**（UserMenu）里进入。
    // 这里不再保留「学情画像」入口，避免与右上角菜单形成两个入口。
    { path: '/toolbox', title: '工具台', icon: 'map' },
  ]},
]

function isActive(p: string) {
  if (p === '/') return route.path === '/'
  if (p === '/practice') return route.path === '/practice'
  return route.path.startsWith(p)
}

/*
 * 主标题只承载「这是什么页面」，不写实现语言、不堆装饰分隔符（R17）。
 * 六阶段口径见 contracts/stages.py；这里不再出现「13 步」这类内部编号。
 * 已删除 /learn/tutor、/learn/practice 两条：路由表里并不存在这两个路径（死键）。
 */
const HEADINGS: Record<string, string> = {
  '/': '定制师全流程实战',
  '/login': '登录',
  '/register': '注册',
  '/demo': '标准案例演示',
  '/learn': '学习地图',
  '/practice': '订单管理',
  '/practice/messages': '消息中心',
  '/practice/orders': '订单详情',
  '/practice/im': '聊天界面',
  '/profile': '学情画像',
  '/toolbox': '工具台',
  '/dashboard': '训练数据看板',
}
const pageHeading = computed(() => HEADINGS[route.path] || String(route.meta.title || '总览'))
/* 全画面路由（总览 / 登录 / 注册）：不挂侧边栏 */
const isFullscreen = computed(() => !!route.meta.fullscreen)
/* 独立控制台（数据看板）：不挂侧边栏、顶栏与用户菜单 */
const standalone = computed(() => !!route.meta.standalone)
/* 登录页与注册页还没登录，不显示用户菜单 */
const showUserMenu = computed(() => userStore.isAuthenticated)
const showTopbar = computed(() => !isFullscreen.value || userStore.isAuthenticated)

onMounted(async () => {
  try { online.value = (await client.get('/')).data?.status === 'ok' } catch { online.value = false }
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
/* 底纹位移走 GPU 合成：曾直接动画 background-position，导致整屏逐帧重绘。 */
/* 只让内容区滚动，避免长表单聚焦时把侧栏和顶栏一起卷走。 */
.app-shell { position: relative; display: flex; height: 100vh; overflow: clip; background: $color-bg; }
.app-shell::before {
  content: ''; position: absolute; inset: -25%; z-index: 0; pointer-events: none;
  background:
    radial-gradient(720px 520px at 22% 22%, rgba(37, 119, 227, 0.05), transparent 62%),
    radial-gradient(620px 480px at 74% 74%, rgba(74, 143, 240, 0.04), transparent 60%);
  will-change: transform;
  animation: shellDrift 32s ease-in-out infinite alternate;
}
@keyframes shellDrift { from { transform: translate3d(0, 0, 0); } to { transform: translate3d(90px, 60px, 0); } }

.sidebar { position: relative; z-index: 1; width: $sidebar-width; flex-shrink: 0; display: flex; flex-direction: column; background: $color-surface; border-right: 1px solid $color-border; }
.side-top { flex-shrink: 0; padding: 20px 20px 16px; border-bottom: 1px solid $color-border; }
.side-nav { padding: 10px 10px; display: flex; flex-direction: column; gap: 2px; flex: 1; overflow-y: auto; }
.nav-group { font-size: 14px; color: $color-text-muted; letter-spacing: .5px; padding: 16px 12px 6px; font-weight: 700; }
.nav-item { position: relative; display: flex; align-items: center; gap: 11px; padding: 11px 12px; border-radius: $radius-md; color: $color-text-secondary; font-size: 15.5px; transition: all .15s ease; }
.nav-item::before { content: ''; position: absolute; left: 0; top: 50%; width: 3px; height: 0; border-radius: 0 3px 3px 0;
  background: $color-primary; transform: translateY(-50%); transition: height .18s cubic-bezier(.34,1.3,.6,1); }
.nav-item.active::before { height: 18px; }
.nav-item:hover { background: $color-primary-softer; color: $color-primary; }
.nav-item.active { background: $color-primary-soft; color: $color-primary; font-weight: 600; }
.side-foot { flex-shrink: 0; padding: 14px; }
.foot-card { display: block; padding: 13px 15px; border-radius: $radius-md; color: #fff;
  background: linear-gradient(135deg, $color-primary, $color-primary-dark);
  box-shadow: 0 6px 16px rgba(37,119,227,0.24);
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease; }
.foot-card:hover { transform: translateY(-2px); box-shadow: 0 12px 24px rgba(37,119,227,0.32); }
.foot-card.on { box-shadow: 0 0 0 3px rgba(37,119,227,0.18), 0 6px 16px rgba(37,119,227,0.24); }
.foot-title { display: inline-flex; align-items: center; gap: 7px; font-size: 16px; font-weight: 700; }

.main { position: relative; z-index: 1; flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px 28px; background: $color-surface; border-bottom: 1px solid $color-border; }
/* 全画面路由（总览 / 登录 / 注册）：不写大标题，顶栏退成一层薄边 */
.topbar.plain { padding: 12px 28px; background: transparent; border-bottom: none; justify-content: flex-end; }
.content.plain { padding: 12px 28px 28px; }
.page-title { font-size: $fs-page-title; font-weight: 800; letter-spacing: .3px; line-height: 1.25; }

.topbar-right { display: flex; align-items: center; gap: 12px; }
.status { display: inline-flex; align-items: center; gap: 7px; font-size: 14.5px; padding: 6px 14px; border-radius: 999px; background: $color-bg; border: 1px solid $color-border; }
.status .dot { width: 8px; height: 8px; border-radius: 50%; }
.status.on { color: $color-success; } .status.on .dot { background: $color-success; }
.status.off { color: $color-danger; } .status.off .dot { background: $color-danger; }

.content { flex: 1; overflow-y: auto; padding: 20px 28px 40px; }
.fade-enter-active, .fade-leave-active { transition: opacity .16s ease, transform .16s ease; }
.fade-enter-from { opacity: 0; transform: translateY(5px); }
.fade-leave-to { opacity: 0; }

/* 窄屏（App-like）：侧边栏收起为横向可滚动的导航条，表单与内容保持可读可点 */
@media (max-width: 900px) {
  /*
   * 横向溢出修复（Codex 实测 390px 视口 scrollWidth=488）：
   * 此前桌面态 .app-shell 用 overflow:hidden，窄屏为了允许纵向翻页改成了 overflow:visible，
   * 于是装饰层 .app-shell::before 的 inset:-25% 直接把文档撑宽 25%×2 → 488/390 ≈ 1.25，正好对上。
   * 现在：横向用 clip（不产生滚动容器，也不裁掉纵向可见性），并关掉这层装饰底纹。
   */
  .app-shell { flex-direction: column; height: auto; min-height: 100vh; overflow-x: clip; overflow-y: visible; }
  .app-shell::before { display: none; }
  .sidebar { width: 100%; max-width: 100%; border-right: none; border-bottom: 1px solid $color-border; }
  .side-top { padding: 12px 16px 10px; }
  .side-nav { flex-direction: row; overflow-x: auto; overflow-y: hidden; gap: 6px; padding: 8px 12px; }
  .nav-group { display: none; }
  .nav-item { white-space: nowrap; padding: 8px 12px; font-size: 14.5px; }
  .nav-item::before { display: none; }
  .side-foot { display: none; }
  .main { overflow: visible; min-width: 0; max-width: 100%; }
  .topbar { padding: 12px 16px; flex-wrap: wrap; gap: 10px; }
  .topbar.plain { padding: 10px 16px; }
  /* 顶栏右侧（连接状态 + 用户菜单）在窄屏允许换行，不把标题挤出视口 */
  .topbar-right { flex-wrap: wrap; gap: 8px; row-gap: 8px; min-width: 0; }
  .content { padding: 14px 16px 32px; }
  .page-title { font-size: 18px; overflow-wrap: anywhere; }
}

/* 更窄（≤400px，含 390px 视口）：状态徽标只留圆点与短文案，保证顶栏不横向撑开 */
@media (max-width: 400px) {
  .topbar { padding: 10px 12px; }
  .status { padding: 5px 9px; font-size: 13px; }
  .content { padding: 12px 12px 28px; }
}
</style>
