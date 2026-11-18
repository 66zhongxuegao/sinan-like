<template>
  <Teleport to="body">
    <div v-if="active && rect" class="gt-root" :class="{ info: step.advance === 'next' }">
      <!-- 四块遮罩围出一个「洞」：洞里的按钮保持原亮度且可点击，其余区域变暗且点不到 -->
      <div class="gt-block" :style="{ top: 0, left: 0, right: 0, height: hole.top + 'px' }" />
      <div class="gt-block" :style="{ top: hole.bottom + 'px', left: 0, right: 0, bottom: 0 }" />
      <div class="gt-block" :style="{ top: hole.top + 'px', left: 0, width: hole.left + 'px', height: hole.h + 'px' }" />
      <div class="gt-block" :style="{ top: hole.top + 'px', left: hole.right + 'px', right: 0, height: hole.h + 'px' }" />
      <!-- 说明型步骤：洞里也不可点，只能点「知道了」 -->
      <div v-if="step.advance === 'next'" class="gt-block clear"
        :style="{ top: hole.top + 'px', left: hole.left + 'px', width: hole.w + 'px', height: hole.h + 'px' }" />
      <div class="gt-ring" :class="{ pulse: step.advance === 'click' }"
        :style="{ top: hole.top + 'px', left: hole.left + 'px', width: hole.w + 'px', height: hole.h + 'px' }" />

      <div ref="tipEl" class="gt-tip" :class="tipPos.side" :style="{ top: tipPos.top + 'px' }">
        <i v-if="tipPos.side !== 'float'" class="gt-arrow" :style="{ left: tipPos.arrowX + 'px' }" />
        <div class="gt-head">
          <span class="gt-count">{{ stepNo }} / {{ total }}</span>
          <span class="gt-stage">{{ step.stage }}</span>
          <button class="gt-skip" type="button" @click="finish">跳过引导</button>
        </div>
        <p class="gt-text">{{ altMatched ? step.alt!.text : step.text }}</p>
        <div v-if="step.advance === 'next'" class="gt-foot">
          <button class="gt-next" type="button" @click="advance">{{ isLast ? '完成' : '知道了' }}</button>
        </div>
        <div v-else class="gt-hint">↑ 点亮起的位置继续</div>
      </div>
    </div>

    <!-- 目标还没出现（在做测评、模型生成中、或用户走开了）：只留底部一条小提示，不挡操作 -->
    <div v-else-if="active && waitText" class="gt-wait">
      <i class="gt-dot" /><span>{{ waitText }}</span>
      <button type="button" @click="finish">跳过</button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * 手机端新手引导（聚光灯式）。
 *
 * 每一步只描述「要指向哪个元素、说什么、怎样算完成」，不关心页面逻辑：
 *  - 目标元素用 data-tour="xxx" 标记（各页面里已加好）；
 *  - advance='click'：学员点了亮起的元素就进入下一步（页面跳转由原按钮自己完成）；
 *  - advance='next' ：说明型步骤，点「知道了」进入下一步；
 *  - 目标暂时不在页面上（模型生成中、正在做测评、走到别的页面）时不挡操作，只在底部显示一行等待提示。
 * 进度按账号存在 localStorage（tc-guide:<user_id>），刷新页面可继续；演示访客每次登录都是新账号，所以每次都会从头引导。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'
import { useIsMobile } from '@/composables/useIsMobile'

interface Step {
  stage: string
  target: string                 // data-tour 值
  text: string
  advance: 'click' | 'next'
  last?: boolean                 // 有多个同名目标时取最后一个（如最新的题卡）
  ready?: (el: HTMLElement) => boolean
  notReadyText?: string          // 目标在但还不能点（例如按钮 disabled）时的等待提示
  waitText?: string              // 目标不在页面上时的提示
  skipIf?: string                // 页面上已有该目标 → 本步已不需要，直接跳过
  alt?: { target: string; text: string }   // 主目标不在时的替代目标；点它不推进步骤
}

const notDisabled = (el: HTMLElement) => !(el as HTMLButtonElement).disabled

const STEPS: Step[] = [
  { stage: '画像', target: 'home-start', advance: 'click',
    text: '欢迎来到司南礼客！先用 3 分钟做个初始测评，系统会据此生成你的能力画像。点这里开始。',
    waitText: '新手引导：回到首页点「开始测评」' },
  { stage: '画像', target: 'quiz-card', advance: 'next',
    text: '一共 12 道情景题，按你平时真实的做法选就好，没有标准答案。做完会生成你的初始画像。' },
  { stage: '画像', target: 'quiz-to-learn', advance: 'click',
    text: '画像生成好了！接下来去学习地图，让系统按你的短板排一条学习路线。',
    waitText: '做完 12 道测评题后，引导会继续' },
  { stage: '规划', target: 'gen-route', advance: 'click', skipIf: 'route-first',
    text: '点这里让学习管家按你的画像短板排路线；也可以先在上面写下这次最想补什么。',
    waitText: '新手引导：去「学习」页生成学习路线' },
  { stage: '规划', target: 'route-first', advance: 'click',
    text: '这是系统建议你最先学的技能点，点进去开始学习。',
    waitText: '学习管家正在排路线，请稍候…' },
  { stage: '学习', target: 'q-讲义', advance: 'click',
    text: '先让司南老师给你生成一份讲义：点「讲义」。',
    waitText: '新手引导：从学习路线进入第一个技能点' },
  { stage: '学习', target: 'thread-send', advance: 'click',
    text: '要说的话已经填好了，点「发送」。' },
  { stage: '学习', target: 'q-做题', advance: 'click', ready: notDisabled,
    notReadyText: '司南老师正在写讲义，写完后继续…',
    text: '讲义写好了，可以往上翻着看。看完点「做题」检验一下。' },
  { stage: '学习', target: 'thread-send', advance: 'click',
    text: '点「发送」，老师会按你当前水平出一道情景题。' },
  { stage: '学习', target: 'quiz-item', last: true, advance: 'next',
    text: '选一个答案后点「交卷」，系统会判分，并按对错自动调高或调低下一题的难度。',
    waitText: '正在按你的水平出题，请稍候…' },
  { stage: '实战', target: 'topbar-back', advance: 'click',
    text: '学习先到这里。点左上角返回，我们去接第一单实战。' },
  { stage: '实战', target: 'tab-practice', advance: 'click',
    text: '点底部的「实战」进入实战训练。',
    waitText: '新手引导：回到学习地图后点底部「实战」' },
  { stage: '实战', target: 'hub-messages', advance: 'click',
    text: '平台派来的单子都在「消息」里，点开看看。' },
  { stage: '实战', target: 'grab', advance: 'click',
    alt: { target: 'refresh-dispatch', text: '暂时没有可抢的派单，点「刷新」拉一批新单。' },
    text: '点「抢单」接下这一单——派单有倒计时，手慢了会被别的定制师接走。' },
  { stage: '实战', target: 'enter-order', advance: 'click',
    text: '抢到了！点「进入订单」。', waitText: '抢单成功后会回到订单列表' },
  { stage: '首呼', target: 'first-call', advance: 'click',
    text: '接单后第一件事是给客户打首呼电话，确认称呼、意向和后续联系方式。点「拨打电话」。' },
  { stage: '首呼', target: 'call-start', advance: 'next',
    text: '点中间的按钮拨通客户，用语音交流；不方便说话可以切到上方「文字」。打完后点左上角返回订单。' },
  { stage: '首呼', target: 'topbar-back', advance: 'click', text: '点左上角返回订单。' },
  { stage: '文件', target: 'folder', advance: 'click',
    text: '需求确认单、行程方案、报价单等文件都在「文件夹」里填写，填好后直接投递给客户。' },
  { stage: '文件', target: 'doc-picker', advance: 'next',
    // 还没通过首呼添加客户时，需求确认单不可填，系统会先跳到聊天页：此时改为解释这条规则
    alt: { target: 'im-root', text: '需求确认单要先通过首呼拿到客户联系方式、在聊天里添加客户后才能填写，所以系统先带你来到了聊天页。打完首呼、加上客户后，再回文件夹填写即可。' },
    text: '在这里切换要填写的文件。左侧表单填写，下方可以预览客户收到的样子，最后点「提交并投递」。' },
  { stage: '文件', target: 'topbar-back', advance: 'click', text: '点左上角回到订单。' },
  { stage: '下一步', target: 'progress-fab', advance: 'click',
    text: '不知道下一步该做什么？随时点右上角这个进度球。' },
  { stage: '下一步', target: 'next-action', advance: 'next',
    text: '这里永远只给你一个「下一步」，点它就能直接前往。引导到这里结束，祝训练顺利！' },
]

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const isMobile = useIsMobile()

const index = ref(-1)
const rect = ref<DOMRect | null>(null)
const waitText = ref('')
const altMatched = ref(false)
let targetEl: HTMLElement | null = null
let raf = 0
let scrolledFor = -1

const active = computed(() => isMobile.value && index.value >= 0 && index.value < STEPS.length)
const step = computed(() => STEPS[Math.max(0, Math.min(index.value, STEPS.length - 1))])
const total = STEPS.length
const stepNo = computed(() => index.value + 1)
const isLast = computed(() => index.value === STEPS.length - 1)

const key = () => `tc-guide:${userStore.userId}`
function save() {
  try { localStorage.setItem(key(), JSON.stringify({ step: index.value })) } catch { /* 隐私模式忽略 */ }
}
function load(): number | null {
  try {
    const raw = localStorage.getItem(key())
    if (!raw) return null
    const v = JSON.parse(raw)
    return typeof v.step === 'number' ? v.step : null
  } catch { return null }
}

function advance() {
  index.value += 1
  rect.value = null
  targetEl = null
  if (index.value >= STEPS.length) index.value = STEPS.length   // 结束
  save()
}
function finish() {
  index.value = STEPS.length
  rect.value = null
  save()
}

function find(name: string, last = false): HTMLElement | null {
  const all = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`))
    .filter((el) => el.offsetParent !== null || getComputedStyle(el).position === 'fixed')
  if (!all.length) return null
  return last ? all[all.length - 1] : all[0]
}

/** 每帧对齐聚光灯：目标会随滚动、键盘弹起、内容加载而移动 */
function tick() {
  raf = requestAnimationFrame(tick)
  if (!active.value) return
  const s = step.value
  if (s.skipIf && find(s.skipIf)) { advance(); return }
  let el = find(s.target, s.last)
  altMatched.value = false
  if (!el && s.alt) { el = find(s.alt.target); altMatched.value = !!el }
  if (!el) { targetEl = null; rect.value = null; waitText.value = s.waitText || ''; return }
  if (s.ready && !s.ready(el)) { targetEl = null; rect.value = null; waitText.value = s.notReadyText || ''; return }
  targetEl = el
  if (scrolledFor !== index.value * 2 + (altMatched.value ? 1 : 0)) {
    scrolledFor = index.value * 2 + (altMatched.value ? 1 : 0)
    el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' })
  }
  const r = el.getBoundingClientRect()
  const prev = rect.value
  if (!prev || Math.abs(prev.top - r.top) > 0.5 || Math.abs(prev.left - r.left) > 0.5
      || Math.abs(prev.width - r.width) > 0.5 || Math.abs(prev.height - r.height) > 0.5) rect.value = r
  waitText.value = ''
  if (tipEl.value && Math.abs(tipEl.value.offsetHeight - tipH.value) > 1) tipH.value = tipEl.value.offsetHeight
}

const PAD = 6
const hole = computed(() => {
  const r = rect.value
  if (!r) return { top: 0, left: 0, right: 0, bottom: 0, w: 0, h: 0 }
  const vw = window.innerWidth
  // 取整：四块遮罩在小数像素处拼接会露出细缝
  const left = Math.floor(Math.max(4, r.left - PAD)), right = Math.ceil(Math.min(vw - 4, r.right + PAD))
  const top = Math.floor(Math.max(0, r.top - PAD)), bottom = Math.ceil(r.bottom + PAD)
  return { top, left, right, bottom, w: right - left, h: bottom - top }
})

/** 说明框放在目标下方或上方（哪边放得下放哪边），箭头水平对准目标中心；
 *  目标太大（如整张题卡）两边都放不下时，说明框浮在屏幕底部、不带箭头。 */
const tipEl = ref<HTMLElement | null>(null)
const tipH = ref(150)
const tipPos = computed(() => {
  const h = hole.value
  const vh = window.innerHeight, vw = window.innerWidth
  const need = tipH.value + 22
  const center = h.left + h.w / 2
  const arrowX = Math.min(vw - 40, Math.max(24, center - 12)) - 12
  if (vh - h.bottom >= need) return { side: 'below', top: h.bottom + 14, arrowX }
  if (h.top >= need) return { side: 'above', top: h.top - 14 - tipH.value, arrowX }
  return { side: 'float', top: vh - tipH.value - 16, arrowX }
})

/** 点亮区域被点击 → 进入下一步（捕获阶段监听，不影响按钮本身的行为） */
function onClick(e: MouseEvent) {
  if (!active.value || step.value.advance !== 'click' || !targetEl || altMatched.value) return
  if (targetEl.contains(e.target as Node)) setTimeout(advance, 0)
}

/** 只给还没做过初始测评的账号自动开启；做过的账号视为老学员，不打扰 */
async function maybeStart() {
  if (!isMobile.value || !userStore.isAuthenticated || !userStore.userId) return
  const saved = load()
  if (saved !== null) { index.value = saved; return }
  try {
    const r = (await client.get(`/profiles/${userStore.userId}/radar`)).data
    index.value = r?.assessed ? STEPS.length : 0
  } catch {
    index.value = STEPS.length
  }
  save()
}

/** 「我的」菜单里的「新手引导」：做过测评的账号从「规划」开始，没做过的从首页开始 */
async function restart() {
  let assessed = false
  try { assessed = !!(await client.get(`/profiles/${userStore.userId}/radar`)).data?.assessed } catch { /* 按未测评处理 */ }
  const from = assessed ? STEPS.findIndex((x) => x.target === 'gen-route') : 0
  await router.push(assessed ? '/learn' : '/')
  index.value = from; scrolledFor = -1; save()
}
defineExpose({ restart })

watch(() => [userStore.userId, isMobile.value], () => { index.value = -1; maybeStart() })
watch(() => route.fullPath, () => { scrolledFor = -1 })
onMounted(() => {
  maybeStart()
  document.addEventListener('click', onClick, true)
  raf = requestAnimationFrame(tick)
  window.addEventListener('tc-guide-restart', restart)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  document.removeEventListener('click', onClick, true)
  window.removeEventListener('tc-guide-restart', restart)
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.gt-root { position: fixed; inset: 0; z-index: 3000; pointer-events: none; }
.gt-block { position: fixed; background: rgba(8, 22, 36, .62); pointer-events: auto; }
.gt-block.clear { background: transparent; }
.gt-ring {
  position: fixed; border-radius: 14px; pointer-events: none;
  box-shadow: 0 0 0 3px #fff, 0 0 0 7px rgba(91,149,201,.55);
  transition: top .18s ease, left .18s ease, width .18s ease, height .18s ease;
}
.gt-ring.pulse { animation: gt-pulse 1.5s ease-in-out infinite; }
@keyframes gt-pulse {
  0%, 100% { box-shadow: 0 0 0 3px #fff, 0 0 0 7px rgba(91,149,201,.55); }
  50% { box-shadow: 0 0 0 3px #fff, 0 0 0 14px rgba(91,149,201,.18); }
}

.gt-tip {
  position: fixed; left: 12px; right: 12px; pointer-events: auto;
  padding: 14px 16px 12px; border-radius: 16px; background: #fff; color: $color-text;
  box-shadow: 0 18px 44px rgba(8,22,36,.35);
  animation: gt-in .22s ease both;
}
@keyframes gt-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.gt-arrow {
  position: absolute; width: 24px; height: 12px; overflow: hidden;
  &::before { content: ''; position: absolute; left: 4px; width: 16px; height: 16px; background: #fff; transform: rotate(45deg); }
}
.gt-tip.float { bottom: auto; }
.gt-tip.below .gt-arrow { top: -12px; &::before { top: 5px; } }
.gt-tip.above .gt-arrow { bottom: -12px; &::before { top: -9px; } }
.gt-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.gt-count { font-size: 12px; font-weight: 800; color: #fff; background: $color-primary; border-radius: 999px; padding: 2px 8px; }
.gt-stage { font-size: 13px; font-weight: 700; color: $blue-500; }
.gt-skip { margin-left: auto; border: 0; background: transparent; color: $color-text-muted; font-size: 13px; padding: 4px; cursor: pointer; }
.gt-text { font-size: 15.5px; line-height: 1.6; }
.gt-foot { display: flex; justify-content: flex-end; margin-top: 10px; }
.gt-next {
  min-width: 96px; height: 40px; border: 0; border-radius: 12px; cursor: pointer;
  background: linear-gradient(135deg, $color-primary-mid, $color-primary); color: #fff; font-size: 15px; font-weight: 700;
}
.gt-hint { margin-top: 6px; font-size: 12.5px; color: $blue-500; font-weight: 600; }

/* 等待提示放在顶栏下方、且不拦截点击：学员此时要自己操作页面（答测评题、等模型生成），
   放底部会压住「下一题」「发送」这类底部按钮 */
.gt-wait {
  position: fixed; left: 12px; right: 12px; z-index: 3000; pointer-events: none;
  top: calc(62px + env(safe-area-inset-top));
  display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 14px;
  background: rgba(19,52,80,.94); color: #fff; font-size: 14px;
  box-shadow: 0 10px 26px rgba(8,22,36,.28);
  span { flex: 1; min-width: 0; }
  button { pointer-events: auto; flex-shrink: 0; border: 0; background: rgba(255,255,255,.14); color: #fff; border-radius: 8px; padding: 5px 10px; font-size: 13px; }
}
.gt-dot { width: 8px; height: 8px; border-radius: 50%; background: $blue-300; animation: gt-blink 1.2s ease-in-out infinite; flex-shrink: 0; }
@keyframes gt-blink { 50% { opacity: .3; } }
</style>
