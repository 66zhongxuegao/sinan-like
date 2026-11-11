<template>
  <div class="call">
    <div class="c-head">
      <button class="back" @click="back"><SIcon name="back" :size="13" /> 返回订单</button>
      <span class="c-title">订单 {{ orderId }}</span>
      <div class="c-modes">
        <button class="mode" :class="{ on: mode === 'voice' }" :disabled="started" @click="mode = 'voice'">
          <SIcon name="wave" :size="12" /> 语音
        </button>
        <button class="mode" :class="{ on: mode === 'text' }" :disabled="started" @click="mode = 'text'">
          <SIcon name="chat" :size="12" /> 文字
        </button>
      </div>
      <span class="c-timer">{{ timer }}</span>
    </div>

    <div class="c-stage" :class="{ idle: !started }">
      <canvas ref="cvRef" class="viz" />
      <div class="c-topinfo">
        <div class="cc-name">{{ customer }}</div>
        <div class="cc-meta">
          <span class="cc-lang"><SIcon name="lang" :size="12" />{{ langLabel || '中文' }}</span>
          <span v-if="persona.nationality" class="cc-pd">
            {{ persona.nationality }} · {{ persona.gender }}<template v-if="persona.age"> · {{ persona.age }} 岁</template>
          </span>
          <span v-if="voiceName" class="cc-pd">音色 {{ voiceName }}</span>
        </div>
        <div class="cc-state"><i class="dot" :class="phase" />{{ stateText }}</div>
      </div>
      <button v-if="!started" class="c-start" @click="start" :disabled="dialing">
        <SIcon name="phone" :size="24" />
        <span>{{ dialing ? '接通中…' : '点击拨打' }}</span>
      </button>
    </div>

    <div class="c-controls">
      <button class="ctrl" :class="{ on: micOn }" @click="toggleMic" :disabled="!started">
        <SIcon name="mic" :size="20" />
        <span>{{ micOn ? '麦克风已开' : '开启麦克风' }}</span>
      </button>
      <button class="ctrl hang" @click="hangup">
        <SIcon name="x" :size="20" />
        <span>挂断</span>
      </button>
    </div>

    <div class="c-input card">
      <textarea v-model="draft" class="ipt" rows="2" :placeholder="inputHint"
        :disabled="!started || speaking" @keydown.enter.exact.prevent="send" />
      <button class="send" :disabled="!draft.trim() || !started || speaking" @click="send">发送</button>
    </div>

    <div class="c-transcript card">
      <div class="ct-head">
        <span>通话记录</span>
        <span v-if="mode === 'voice'" class="ct-hint">语音转写 · 实时</span>
      </div>
      <div class="ct-body">
        <div v-for="(m, i) in lines" :key="i" class="ct-row" :class="m.who">
          <span class="ct-who">{{ m.who === 'agent' ? customer : '我' }}</span>
          <span class="ct-text">{{ m.text }}<i v-if="m.interim" class="caret" /></span>
        </div>
        <div v-if="!lines.length" class="ct-empty">{{ started ? '客户正在接听…' : '点击「拨打」后接通' }}</div>
      </div>
    </div>
    <div v-if="error" class="err">{{ error }}</div>
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
const customer = ref('客户')
const sourceMarket = ref('')
const langLabel = ref('')                      // 这通电话对方说的语言
const persona = ref<any>({})                   // 同一份人设：国籍 / 性别 / 年龄
const voiceName = ref('')                      // 实际用的音色，便于核对人设与声音是否对应

type Line = { who: 'agent' | 'student'; text: string; interim?: boolean }
type Phase = 'idle' | 'agent' | 'student'

const cvRef = ref<HTMLCanvasElement | null>(null)
const phase = ref<Phase>('idle')
const started = ref(false)
const dialing = ref(false)
const speaking = ref(false)
const micOn = ref(false)
const lines = ref<Line[]>([])
const draft = ref('')
const error = ref('')
const seconds = ref(0)
const mode = ref<'voice' | 'text'>('voice')

const INPUT_RATE = 16000
const OUTPUT_RATE = 24000

let ws: WebSocket | null = null
let capCtx: AudioContext | null = null
let micStream: MediaStream | null = null
let proc: ScriptProcessorNode | null = null
let playCtx: AudioContext | null = null
let playHead = 0
let raf = 0
let level = 0
let tick = 0
let timerId = 0
let micData: Uint8Array | null = null
let analyser: AnalyserNode | null = null

const stateText = computed(() => {
  if (!started.value) return '等待拨打'
  if (speaking.value) return '客户正在说话'
  return '轮到你说话'
})
const inputHint = computed(() => {
  if (!started.value) return '先点击拨打'
  return mode.value === 'voice'
    ? '对着麦克风说话'
    : '输入你要讲的话，回车发送'
})
const timer = computed(() => {
  const total = Math.max(seconds.value, 0)
  return String(Math.floor(total / 60)).padStart(2, '0') + ':' + String(total % 60).padStart(2, '0')
})

async function loadOrder() {
  try {
    const o = (await client.get(`/practice/orders/${orderId.value}`)).data
    customer.value = o.customer
    sourceMarket.value = o.source_market || ''
    langLabel.value = o.language || '中文'
    if (o.persona) persona.value = o.persona
  } catch { error.value = '订单不存在' }
}

// ---------------- 语音模式 ----------------

async function startVoice() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/api/voice/realtime?order_id=${orderId.value}`)
  ws.onmessage = (e) => {
    let msg: any
    try { msg = JSON.parse(e.data) } catch { return }
    handleVoice(msg)
  }
  ws.onerror = () => { if (!started.value) error.value = '语音通道连接失败' }
  ws.onclose = () => { speaking.value = false; phase.value = 'idle' }
  await enableMic()
}

function handleVoice(msg: any) {
  switch (msg.type) {
    case 'ready':
      started.value = true
      dialing.value = false
      if (msg.language) langLabel.value = msg.language
      if (msg.persona) persona.value = msg.persona
      if (msg.voice) voiceName.value = msg.voice
      if (!timerId) timerId = window.setInterval(() => { seconds.value += 1 }, 1000)
      break
    case 'audio':
      if (msg.audio) enqueue(msg.audio)
      break
    case 'transcript':
      applyTranscript(msg.who, msg.text, msg.final)
      break
    case 'state':
      if (msg.value === 'speaking') { speaking.value = true; phase.value = 'agent' }
      else if (msg.value === 'listening') { speaking.value = false; phase.value = started.value ? 'student' : 'idle' }
      else if (msg.value === 'thinking') { speaking.value = false; phase.value = 'student' }
      break
    case 'error':
      error.value = msg.message || '语音通道异常'
      dialing.value = false
      break
    case 'closed':
      speaking.value = false
      break
  }
}

function applyTranscript(who: 'agent' | 'student', text: string, final: boolean) {
  if (!text) return
  const last = lines.value[lines.value.length - 1]
  if (last && last.who === who) {
    if (last.interim) {
      if (final) { last.text = text; last.interim = false } else { last.text = text }
    } else if (!final && last.text === text) return
    else if (final && last.text === text) return
    else lines.value.push({ who, text, interim: !final })
  } else {
    lines.value.push({ who, text, interim: !final })
  }
}

function b64(bytes: Uint8Array) {
  let s = ''
  const CH = 0x8000
  for (let i = 0; i < bytes.length; i += CH) {
    s += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + CH)) as number[])
  }
  return btoa(s)
}

function sendAudio(f32: Float32Array) {
  if (!ws || ws.readyState !== WebSocket.OPEN || !micOn.value) return
  const pcm = new Int16Array(f32.length)
  for (let i = 0; i < f32.length; i++) {
    const v = Math.max(-1, Math.min(1, f32[i]))
    pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff
  }
  ws.send(JSON.stringify({ type: 'audio', audio: b64(new Uint8Array(pcm.buffer)) }))
}

async function enableMic() {
  if (micOn.value) return
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    capCtx = new AudioContext({ sampleRate: INPUT_RATE })
    const src = capCtx.createMediaStreamSource(micStream)
    analyser = capCtx.createAnalyser()
    analyser.fftSize = 512
    micData = new Uint8Array(analyser.frequencyBinCount)
    src.connect(analyser)

    proc = capCtx.createScriptProcessor(2048, 1, 1)
    proc.onaudioprocess = (ev) => sendAudio(ev.inputBuffer.getChannelData(0))
    const mute = capCtx.createGain()
    mute.gain.value = 0
    src.connect(proc)
    proc.connect(mute)
    mute.connect(capCtx.destination)
    micOn.value = true
  } catch {
    micOn.value = false
    error.value = '麦克风未授权，可切换到「文字」模式继续'
  }
}

function enqueue(b64audio: string) {
  try {
    if (!playCtx) playCtx = new AudioContext()
    const raw = atob(b64audio)
    const bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
    const pcm = new Int16Array(bytes.buffer, 0, Math.floor(bytes.length / 2))
    const buf = playCtx.createBuffer(1, pcm.length, OUTPUT_RATE)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768
    const node = playCtx.createBufferSource()
    node.buffer = buf
    node.connect(playCtx.destination)
    const at = Math.max(playCtx.currentTime, playHead)
    node.start(at)
    playHead = at + buf.duration
    if (!speaking.value) { speaking.value = true; phase.value = 'agent' }
    if (playbackWatcher) clearTimeout(playbackWatcher)
    playbackWatcher = window.setTimeout(() => {
      speaking.value = false
      if (started.value) phase.value = 'student'
    }, Math.max(200, (playHead - (playCtx?.currentTime || 0)) * 1000) + 200)
  } catch { /* 忽略单帧解码失败 */ }
}
let playbackWatcher = 0

// ---------------- 文字模式 ----------------

async function startText() {
  const r = (await client.post(`/practice/orders/${orderId.value}/call`)).data
  sessionId = r.session_id
  lines.value = (r.lines || []).map((l: any) => ({ who: l.who, text: l.text }))
  onConnected()
}
let sessionId = ''

function onConnected() {
  started.value = true
  dialing.value = false
  if (!timerId) timerId = window.setInterval(() => { seconds.value += 1 }, 1000)
}

async function start() {
  if (started.value || dialing.value) return
  dialing.value = true
  error.value = ''
  try {
    if (mode.value === 'voice') await startVoice()
    else await startText()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '接通失败，请稍后重试'
    dialing.value = false
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || !started.value || speaking.value) return
  draft.value = ''
  if (mode.value === 'voice') {
    lines.value.push({ who: 'student', text })
    ws?.send(JSON.stringify({ type: 'text', text }))
    phase.value = 'agent'
    return
  }
  lines.value.push({ who: 'student', text })
  phase.value = 'agent'
  try {
    const r = (await client.post(`/practice/call/${sessionId}/messages`, { text })).data
    lines.value = (r.lines || lines.value).map((l: any) => ({ who: l.who, text: l.text }))
    phase.value = 'student'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '发送失败'
    phase.value = 'student'
  }
}

function toggleMic() {
  if (micOn.value) {
    micOn.value = false
    proc?.disconnect()
  } else {
    enableMic()
  }
}

async function hangup() {
  if (mode.value === 'voice' && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'stop' }))
    await new Promise((resolve) => window.setTimeout(resolve, 450))
  }
  if (sessionId) {
    try { await client.post('/practice/call/' + sessionId + '/end') } catch { /* ignore */ }
  }
  cleanupCall()
  router.push({ path: '/practice/im', query: { order: orderId.value } })
}

function cleanupCall() {
  try { ws?.close() } catch { /* ignore */ }
  proc?.disconnect()
  micStream?.getTracks().forEach((t) => t.stop())
  capCtx?.close()
  playCtx?.close()
  if (timerId) clearInterval(timerId)
}

function back() {
  cleanupCall()
  router.back()
}

// ---------------- 波形 ----------------

function targetLevel() {
  if (!started.value) return 0.05
  if (speaking.value || phase.value === 'agent') {
    return 0.55 + 0.35 * Math.abs(Math.sin(tick * 0.11)) * (0.6 + 0.4 * Math.sin(tick * 0.37))
  }
  if (phase.value === 'student' && micOn.value && analyser && micData) {
    analyser.getByteTimeDomainData(micData as any)
    let sum = 0
    for (let i = 0; i < micData.length; i++) { const v = (micData[i] - 128) / 128; sum += v * v }
    return Math.min(1, Math.sqrt(sum / micData.length) * 5)
  }
  if (phase.value === 'student') return 0.3 + 0.22 * Math.abs(Math.sin(tick * 0.13))
  return 0.08
}

function draw() {
  const cv = cvRef.value
  if (!cv) return
  const dpr = window.devicePixelRatio || 1
  const w = cv.clientWidth, h = cv.clientHeight
  if (cv.width !== w * dpr || cv.height !== h * dpr) { cv.width = w * dpr; cv.height = h * dpr }
  const ctx = cv.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  tick += 1
  const t = targetLevel()
  level += (t - level) * 0.12

  const cx = w / 2, cy = h / 2
  const isAgent = speaking.value || phase.value === 'agent'
  const main = isAgent ? '#e08a1e' : phase.value === 'student' ? '#2577e3' : '#9db6d6'
  const breathe = 0.5 + 0.5 * Math.sin(tick * 0.045)

  for (let k = 0; k < 3; k++) {
    const r = 112 + k * 22 + level * (10 + k * 12) + breathe * (3 + k * 2)
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.strokeStyle = main + (k === 0 ? '99' : k === 1 ? '59' : '33')
    ctx.lineWidth = 1 + (2 - k) * 0.6
    ctx.stroke()
  }

  const BARS = 72
  for (let i = 0; i < BARS; i++) {
    const a = (i / BARS) * Math.PI * 2 - Math.PI / 2
    const wave = Math.abs(Math.sin(i * 0.7 + tick * 0.15)) * Math.abs(Math.sin(i * 0.23 - tick * 0.09))
    const amp = level * (18 + 34 * wave)
    const r0 = 96
    const x0 = cx + Math.cos(a) * r0, y0 = cy + Math.sin(a) * r0
    const x1 = cx + Math.cos(a) * (r0 + 4 + amp), y1 = cy + Math.sin(a) * (r0 + 4 + amp)
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1)
    ctx.strokeStyle = main + (amp > 26 ? 'ee' : '88')
    ctx.lineWidth = 2.6; ctx.lineCap = 'round'; ctx.stroke()
  }

  const grad = ctx.createRadialGradient(cx, cy, 6, cx, cy, 92)
  grad.addColorStop(0, main + 'aa')
  grad.addColorStop(0.55, main + '33')
  grad.addColorStop(1, main + '00')
  ctx.beginPath(); ctx.arc(cx, cy, 92, 0, Math.PI * 2)
  ctx.fillStyle = grad; ctx.fill()

  raf = requestAnimationFrame(draw)
}

onMounted(() => { loadOrder(); raf = requestAnimationFrame(draw) })
watch(orderId, () => {
  lines.value = []; started.value = false; seconds.value = 0; error.value = ''
  if (timerId) clearInterval(timerId); timerId = 0
  loadOrder()
})
onUnmounted(() => {
  cancelAnimationFrame(raf)
  if (timerId) clearInterval(timerId)
  if (playbackWatcher) clearTimeout(playbackWatcher)
  try { ws?.close() } catch { /* ignore */ }
  proc?.disconnect()
  micStream?.getTracks().forEach((t) => t.stop())
  capCtx?.close()
  playCtx?.close()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.call { width: 100%; max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.c-head { display: flex; align-items: center; gap: 14px; }
.back { display: inline-flex; align-items: center; gap: 4px; border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 6px 14px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.c-title { font-size: 16.5px; font-weight: 800; }
.c-modes { display: flex; gap: 4px; background: #eef3fa; border-radius: 999px; padding: 3px; }
.mode { display: inline-flex; align-items: center; gap: 5px; border: none; background: transparent; border-radius: 999px; padding: 5px 14px; font-size: 15.5px; color: $color-text-secondary; cursor: pointer; }
.mode.on { background: #fff; color: $color-primary; font-weight: 700; box-shadow: 0 2px 6px rgba(16,32,56,0.10); }
.mode:disabled { opacity: .55; cursor: default; }
.c-timer { margin-left: auto; font-family: ui-monospace, monospace; font-size: 16.5px; color: $color-primary; font-weight: 700; }

.c-stage {
  position: relative; height: 420px; border-radius: $radius-lg; overflow: hidden;
  background: radial-gradient(circle at 50% 45%, #ffffff 0%, #eaf3fe 55%, #dbeafe 100%);
  border: 1px solid $color-border;
}
.viz { position: absolute; inset: 0; width: 100%; height: 100%; }
.c-topinfo { position: absolute; left: 0; right: 0; top: 26px; display: flex; flex-direction: column;
  align-items: center; gap: 14px; pointer-events: none; }
.cc-name { font-size: 22px; font-weight: 800; color: $color-text; letter-spacing: 2px; line-height: 1.2; }
.cc-meta { display: inline-flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center; min-height: 24px; }
.cc-lang { display: inline-flex; align-items: center; gap: 5px; padding: 3px 11px; border-radius: 999px;
  font-size: 14.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft; border: 1px solid #d8e7fa; }
.cc-pd { font-size: 14.5px; color: $color-text-muted; }
.cc-state { display: inline-flex; align-items: center; gap: 7px; font-size: 15.5px; color: $color-text-secondary;
  background: rgba(255, 255, 255, 0.82); border-radius: 999px; padding: 3px 12px; }
.cc-state .dot { width: 7px; height: 7px; border-radius: 50%; background: #b9c9dd; }
.cc-state .dot.agent { background: #e08a1e; animation: pulse 1.1s ease-in-out infinite; }
.cc-state .dot.student { background: #2577e3; animation: pulse 1.1s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }

.c-start {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; cursor: pointer;
  width: 148px; height: 148px; border-radius: 50%; border: none;
  background: linear-gradient(135deg, #2577e3, #1a63c4); color: #fff;
  box-shadow: 0 14px 34px rgba(37,119,227,0.42);
  font-size: 15px; font-weight: 700;
}
.c-start:hover { filter: brightness(1.06); }
.c-start:disabled { opacity: .75; cursor: default; }
.c-start span { font-size: 15.5px; }

.c-controls { display: flex; gap: 14px; justify-content: center; }
.ctrl {
  display: inline-flex; flex-direction: column; align-items: center; gap: 6px; cursor: pointer;
  width: 96px; padding: 12px 0; border-radius: 14px; border: 1px solid $color-border; background: #fff;
  font-size: 15px; color: $color-text-secondary;
}
.ctrl:hover { border-color: $color-primary; color: $color-primary; }
.ctrl.on { background: $color-primary-soft; border-color: $color-primary; color: $color-primary; }
.ctrl:disabled { opacity: .6; cursor: default; }
.ctrl.hang { color: #e04b4b; }
.ctrl.hang:hover { border-color: #e04b4b; background: #fdeceb; }

.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.c-input { display: flex; gap: 10px; padding: 12px; align-items: flex-end; }
.ipt { flex: 1; border: 1px solid $color-border; border-radius: 8px; padding: 9px 12px; font-size: 15px; font-family: inherit; line-height: 1.6; resize: vertical; outline: none; }
.ipt:focus { border-color: $color-primary; }
.send { border: none; cursor: pointer; border-radius: 8px; padding: 10px 20px; font-size: 15px; font-weight: 700; color: #fff; background: linear-gradient(135deg, #2577e3, #1a63c4); }
.send:disabled { opacity: .5; cursor: default; }

.ct-head { display: flex; align-items: baseline; gap: 10px; padding: 12px 16px; font-size: 15.5px; font-weight: 700; border-bottom: 1px solid $color-border; }
.ct-hint { font-size: 15px; font-weight: 400; color: $color-text-muted; }
.ct-body { padding: 12px 16px; max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.ct-row { display: flex; gap: 10px; font-size: 15px; line-height: 1.7; }
.ct-who { flex-shrink: 0; width: 56px; font-weight: 700; color: $color-text-secondary; }
.ct-row.agent .ct-who { color: #d98324; }
.ct-row.student .ct-who { color: $color-primary; }
.ct-text { flex: 1; }
.caret { display: inline-block; width: 6px; height: 13px; background: $color-primary; margin-left: 3px; vertical-align: -2px; animation: blink 1s steps(2) infinite; }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
.ct-empty { text-align: center; color: $color-text-muted; font-size: 15.5px; padding: 20px; }
.err { color: #e04b4b; font-size: 15.5px; }
</style>
