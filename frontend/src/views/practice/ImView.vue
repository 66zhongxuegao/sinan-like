<template>
  <div class="im" :class="{ wide: infoOpen }">
    <!-- 左：会话与联系人 -->
    <aside class="col side card">
      <div class="side-head">
        <span class="side-title">会话</span>
        <button class="icon-btn" title="发起群聊" @click="newGroupDlg = true"><SIcon name="plus" :size="13" /></button>
      </div>

      <div class="sec-lbl">群聊 · 单聊</div>
      <div v-for="s in sessions" :key="s.session_id" class="row-item"
        :class="{ on: activeId === s.session_id }" @click="openSession(s.session_id)">
        <span class="av" :class="{ unread: hasNew(s) }" :style="{ background: avatarColor(s.name) }">
          {{ s.name.slice(0, 1) }}<i v-if="hasNew(s)" class="dot-av" />
        </span>
        <div class="ri-mid">
          <div class="ri-name">
            {{ s.name }}
            <span class="ri-order">{{ s.customer }}{{ s.destination ? ' · ' + s.destination : '' }}</span>
            <span v-if="s.locked" class="ri-lock">待添加</span>
            <span v-else-if="!s.present" class="ri-lock soft">未到阶段</span>
          </div>
          <div class="ri-last">{{ preview(s) }}</div>
        </div>
        <i v-if="hasNew(s)" class="dot-new" />
      </div>
      <div v-if="!sessions.length" class="empty-sm">本单暂无会话</div>

      <div class="sec-lbl">通讯录</div>
      <div v-for="c in openContacts" :key="c.contact_id" class="row-item ct">
        <span class="av sm" :style="{ background: avatarColor(c.name) }">{{ c.name.slice(0, 1) }}</span>
        <div class="ri-mid">
          <div class="ri-name">{{ c.name }}<span class="tag">{{ c.kind }}</span></div>
          <div class="ri-last">来自{{ c.source }}</div>
        </div>
        <button class="mini" :disabled="busy" @click.stop="addContact(c)">添加</button>
      </div>
      <div v-if="!openContacts.length" class="empty-sm">该加的都在通讯录里了</div>
      <div v-for="c in lockedContacts" :key="c.contact_id" class="row-item ct dim">
        <span class="av sm" :style="{ background: '#c3ccd8' }"><SIcon name="lock" :size="12" /></span>
        <div class="ri-mid">
          <div class="ri-name">{{ c.kind }}<span class="tag">{{ c.source }}</span></div>
          <div class="ri-last">{{ c.note }}</div>
        </div>
      </div>
    </aside>

    <!-- 中：会话 -->
    <section class="col main card">
      <div class="m-head">
        <div class="mh-l">
          <span class="mh-name">{{ active.name }}</span>
          <span class="mh-kind">{{ active.kind }}</span>
          <span class="mh-type">{{ conversationTypeLabel }}</span>
          <span class="mh-members" @click="infoOpen = !infoOpen">{{ active.members.length }} 位成员</span>
          <span v-if="active.order_id" class="mh-order link" @click="openOrder(active.order_id)">
            订单 {{ active.order_id }}
          </span>
        </div>
        <div class="mh-r">
          <button v-if="active.kind === '客户' && active.order_id" class="icon-btn" title="语音通话"
            @click="callCustomer"><SIcon name="phone" :size="13" /></button>
          <button class="icon-btn" :title="(active.code || '').startsWith('dm-') ? '备注' : '改群名'"
            :disabled="!active.session_id" @click="renameOrRemark">
            <SIcon name="filetext" :size="13" />
          </button>
          <button v-if="active.code !== 'ticket'" class="icon-btn" title="邀请成员" :disabled="!active.session_id" @click="openInvite">
            <SIcon name="plus" :size="13" />
          </button>
        </div>
      </div>

      <div v-if="active.locked" class="lock-bar">
        <SIcon name="lock" :size="13" />
        <span>{{ active.lock_hint || '请先添加对方联系方式，再加入该群' }}</span>
        <button v-if="lockTarget" class="mini" @click="addContact(lockTarget)">去添加</button>
      </div>
      <div v-else-if="!active.present" class="lock-bar soft">
        <SIcon name="clock" :size="13" /><span>订单尚未进入该阶段，暂无人回应</span>
      </div>

      <div class="msgs" ref="msgsEl">
        <div v-if="!active.messages.length" class="empty">暂无消息</div>
        <template v-for="(m, i) in active.messages" :key="i">
          <div v-if="m.kind === 'system'" class="sys-msg">{{ m.text }}</div>
          <div v-else class="row" :class="m.role">
            <span class="av clickable" title="点头像添加联系人"
              :style="{ background: avatarColor(m.from) }" @click.stop="onAvatar(m)">{{ m.from.slice(0, 1) }}</span>
            <div class="body">
              <div class="meta"><span class="who">{{ m.from }}</span><span class="time">{{ m.time }}</span></div>

              <div v-if="m.kind === 'card'" class="card-msg">
                <div class="cm-head">
                  <SIcon name="filetext" :size="15" />
                  <span class="cm-title">{{ m.payload.title || m.text }}</span>
                  <span class="cm-tag">交付物</span>
                </div>
                <div class="cm-meta">{{ m.payload.deliverable_id }} · 发给{{ m.payload.target }}</div>
                <p class="cm-ex">{{ m.payload.excerpt }}</p>
                <div v-if="(m.payload.files || []).length" class="cm-files">
                  附件：{{ (m.payload.files || []).join('、') }}
                </div>
                <button class="cm-open" @click="openDeliverable(m.payload.deliverable_id)">打开产出与投递</button>
              </div>

              <div v-else-if="m.kind === 'file'" class="file-msg">
                <SIcon name="clip" :size="14" />
                <a v-if="m.payload.file_id" class="fm-name"
                  :href="fileUrl(m.payload.file_id)" target="_blank">{{ m.payload.filename || m.text }}</a>
                <span v-else class="fm-name">{{ m.payload.filename || m.text }}</span>
                <span class="fm-size">{{ m.payload.size || '' }}</span>
              </div>

              <div v-else class="bubble">{{ m.text }}</div>
            </div>
          </div>
        </template>
        <div v-if="replying" class="row">
          <span class="av" :style="{ background: avatarColor(active.kind) }">{{ (active.members[1] || '?').slice(0, 1) }}</span>
          <div class="body"><div class="bubble typing">对方正在输入…</div></div>
        </div>
      </div>

      <div v-if="reacted.length" class="reacted">
        <span class="rc-label">本次回应已覆盖考点</span>
        <span v-for="sp in reacted" :key="sp" class="rc-chip">{{ sp }}</span>
        <button class="rc-close" @click="reacted = []">×</button>
      </div>
      <div v-if="notice" class="notice">{{ notice }}</div>
      <div v-if="avatarPick" class="avatar-card">
        <div class="ac-head">
          <span class="av sm" :style="{ background: avatarColor(avatarPick.name) }">
            {{ avatarPick.name.slice(0, 1) }}
          </span>
          <div class="ac-mid">
            <span class="ac-name">{{ avatarPick.name }}</span>
            <span class="ac-hint">
              {{ avatarPick.added ? ('备注：' + (avatarPick.remark || '未设置'))
                : (avatarPick.contact ? ('来源：' + avatarPick.contact.source) : '暂无联系方式') }}
            </span>
          </div>
        </div>
        <div class="ac-acts">
          <button v-if="avatarPick.contact && !avatarPick.added" class="mini"
            :disabled="busy" @click="addContact(avatarPick.contact)">添加联系人</button>
          <button v-if="avatarPick.added" class="mini" @click="openRemark(avatarPick.mine)">
            修改备注
          </button>
          <button class="mini" @click="avatarPick = null">关闭</button>
        </div>
      </div>

      <div class="input">
        <div v-if="active.conversation_type === 'hub'" class="target-row">
          <span class="target-label">订单</span>
          <select v-model="currentOrderId" class="target-select">
            <option v-for="o in orders" :key="o.order_id" :value="o.order_id">
              {{ o.order_id }} · {{ o.customer }} · {{ o.destination }}
            </option>
            <option v-if="!orders.length" value="">暂无订单</option>
          </select>
        </div>
        <div v-if="active.conversation_type === 'hub' || active.conversation_type === 'group'" class="target-row">
          <span class="target-label">本次找</span>
          <select v-model="targetRole" class="target-select">
            <option value="">自动判断</option>
            <option value="地接社">地接社</option>
            <option value="酒店">酒店</option>
            <option value="车队">车队</option>
            <option value="导游">司导档期（地接统筹）</option>
          </select>
        </div>
        <div class="tools">
          <button class="tool voice-tool" :class="{ on: voiceListening }"
            :disabled="!canSend" @click="toggleVoiceInput">
            <SIcon name="mic" :size="13" />{{ voiceProcessing ? '识别中…' : voiceListening ? '结束语音' : '语音输入' }}
          </button>
          <button class="tool" :disabled="!canSend" @click="sendMenu = !sendMenu">
            <SIcon name="plus" :size="13" />发送
          </button>
          <template v-if="sendMenu">
            <button class="tool" :disabled="!canSend" @click="openDeliverableDlg">
              <SIcon name="filetext" :size="13" />本单交付物
            </button>
            <button class="tool" :disabled="!canSend" @click="pickFile">
              <SIcon name="clip" :size="13" />文件
            </button>
          </template>
          <input ref="fileInput" type="file" class="hidden-file" @change="onPickFile" />
        </div>
        <textarea v-model="draft" class="ipt" rows="2"
          :placeholder="canSend ? '在群里发消息…（Enter 发送，Shift+Enter 换行）' : (active.conversation_type === 'hub' && !orderForSend ? '请先选择订单' : '还不能在这里发言')"
          :disabled="!canSend" @keydown.enter.exact.prevent="send" />
        <button class="tc-btn send" :disabled="!canSend" @click="send">
          <SIcon name="right" :size="13" /> 发送
        </button>
      </div>
    </section>

    <!-- 右：会话信息 -->
    <aside v-if="infoOpen" class="col info card">
      <div class="info-title">会话信息</div>
      <div class="info-row"><span>类型</span><b>{{ active.kind || '—' }}</b></div>
      <div class="info-row"><span>订单</span><b>{{ active.order_id || '—' }}</b></div>
      <div class="info-row"><span>成员</span><b>{{ active.members.length }} 位</b></div>
      <div class="info-title mt">成员</div>
      <div v-for="m in active.members" :key="m" class="mem clickable" @click="onAvatar({ from: m })">
        <span class="av sm" :style="{ background: avatarColor(m) }">{{ m.slice(0, 1) }}</span>
        <span class="mem-name">{{ m }}</span>
      </div>
      <button class="mini wide" :disabled="!active.session_id" @click="openInvite">邀请已添加的联系人</button>
      <div class="info-title mt">通讯录</div>
      <div v-for="c in addedContacts" :key="c.contact_id" class="mem">
        <span class="dot" /><span class="mem-name">{{ c.display || c.name }}</span>
        <span class="tag">{{ c.kind }}</span>
        <button class="mini" @click.stop="openRemark(c)">备注</button>
      </div>
    </aside>

    <!-- 弹窗：拉群 -->
    <div v-if="newGroupDlg" class="mask" @click.self="newGroupDlg = false">
      <div class="dlg card" @click.stop>
        <div class="dlg-title">拉群</div>
        <div class="dlg-row"><label>群名</label><input v-model="groupName" class="ipt" placeholder="如：浙江 5 天 · 客户群" /></div>
        <div class="dlg-row top"><label>成员</label>
          <div class="pick">
            <label v-for="c in addedContacts" :key="c.contact_id" class="pick-row">
              <input type="checkbox" :value="c.name" v-model="groupMembers" />
              <span>{{ c.display || c.name }}</span><span class="tag">{{ c.kind }}</span>
            </label>
            <div v-if="!addedContacts.length" class="empty-sm">暂无已添加的联系人</div>
          </div>
        </div>
        <div class="dlg-foot">
          <button class="tc-btn ghost" @click="newGroupDlg = false">取消</button>
          <button class="tc-btn" :disabled="busy" @click="createGroup">创建群聊</button>
        </div>
      </div>
    </div>

    <!-- 弹窗：备注 -->
    <div v-if="remarkDlg" class="mask" @click.self="remarkDlg = false">
      <div class="dlg card" @click.stop>
        <div class="dlg-title">备注</div>
        <div class="dlg-row"><label>备注名</label>
          <input v-model="remarkTo" class="ipt" maxlength="16"
            :placeholder="remarkTarget?.name || '为该联系人设置备注名'" />
        </div>
        <div class="dlg-foot">
          <button class="tc-btn ghost" @click="remarkDlg = false">取消</button>
          <button class="tc-btn" :disabled="busy" @click="doRemark">保存</button>
        </div>
      </div>
    </div>

    <!-- 弹窗：改名 -->
    <div v-if="renameDlg" class="mask" @click.self="renameDlg = false">
      <div class="dlg card" @click.stop>
        <div class="dlg-title">修改群名</div>
        <div class="dlg-row"><label>群名</label><input v-model="renameTo" class="ipt" maxlength="20" /></div>
        <div class="dlg-foot">
          <button class="tc-btn ghost" @click="renameDlg = false">取消</button>
          <button class="tc-btn" :disabled="busy" @click="doRename">保存</button>
        </div>
      </div>
    </div>

    <!-- 弹窗：邀请成员 -->
    <div v-if="inviteDlg" class="mask" @click.self="inviteDlg = false">
      <div class="dlg card" @click.stop>
        <div class="dlg-title">邀请成员</div>
        <div class="pick">
          <label v-for="c in invitable" :key="c.contact_id" class="pick-row">
            <input type="checkbox" :value="c.name" v-model="inviteNames" />
            <span>{{ c.display || c.name }}</span><span class="tag">{{ c.kind }}</span>
          </label>
          <div v-if="!invitable.length" class="empty-sm">没有可邀请的人（先加联系方式）</div>
        </div>
        <div class="dlg-foot">
          <button class="tc-btn ghost" @click="inviteDlg = false">取消</button>
          <button class="tc-btn" :disabled="busy" @click="doInvite">加入群聊</button>
        </div>
      </div>
    </div>

    <!-- 弹窗：发送交付物 -->
    <div v-if="docDlg" class="mask" @click.self="docDlg = false">
      <div class="dlg card" @click.stop>
        <div class="dlg-title">发送交付物到本会话</div>
        <div class="pick">
          <label v-for="d in deliverables" :key="d.deliverable_id" class="pick-row">
            <input type="radio" :value="d.deliverable_id" v-model="docPick" />
            <span>{{ d.title }}</span>
            <span class="tag">{{ d.submitted ? '已提交 V' + (d.version || 1) : '未提交' }}</span>
          </label>
          <div v-if="!deliverables.length" class="empty-sm">本单暂无交付物</div>
        </div>
        <div class="dlg-foot">
          <button class="tc-btn ghost" @click="docDlg = false">取消</button>
          <button class="tc-btn" :disabled="!docPick || busy" @click="sendDeliverable">发送</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'
import { usePracticeStore } from '@/stores/practice'

const route = useRoute()
const router = useRouter()
const practice = usePracticeStore()

const rooms = ref<any[]>([])
const contacts = ref<any[]>([])          // 还能加谁（按最近在跟的一单给的目录）
const mine = ref<any[]>([])              // 我的通讯录（跨订单只有一份）
const groupOrderId = ref('')
const orders = ref<any[]>([])
const currentOrderId = ref('')
const sendMenu = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const activeId = ref('')
const draft = ref('')
const targetRole = ref('')
const replying = ref(false)
const reacted = ref<string[]>([])
const notice = ref('')
const busy = ref(false)
const infoOpen = ref(true)
const voiceListening = ref(false)
const voiceProcessing = ref(false)
let voiceWs: WebSocket | null = null
let voiceStream: MediaStream | null = null
let voiceCtx: AudioContext | null = null
let voiceProc: ScriptProcessorNode | null = null
let voiceBase = ''
let voiceFinal = ''
let voiceResetTimer = 0

const newGroupDlg = ref(false)
const groupName = ref('')
const groupMembers = ref<string[]>([])
const remarkDlg = ref(false)
const remarkTo = ref('')
const remarkTarget = ref<any>(null)
const renameDlg = ref(false)
const renameTo = ref('')
const inviteDlg = ref(false)
const inviteNames = ref<string[]>([])
const docDlg = ref(false)
const docPick = ref('')
const deliverables = ref<any[]>([])


const BLANK = { session_id: '', name: '未选择会话', kind: '', members: [], messages: [],
  locked: false, present: false, order_id: '', require_contact: '', lock_hint: '' }
const sessions = computed(() => rooms.value)
const pendingContacts = computed(() => contacts.value.filter((c) => c.available && !c.added))
const active = computed<any>(() => rooms.value.find((r) => r.session_id === activeId.value) || BLANK)
const conversationTypeLabel = computed(() => {
  if (active.value.code === 'ticket') return '固定窗口'
  const t = active.value.conversation_type
  if (t === 'hub') return '资源协作群'
  if (t === 'dm') return '单聊'
  if (t === 'group') return '群聊'
  return '会话'
})
const orderForSend = computed(() => active.value.order_id || currentOrderId.value || practice.activeOrderId || '')
const addedContacts = computed(() => mine.value)
const openContacts = computed(() => contacts.value.filter((c) => c.available && !c.added))
const lockedContacts = computed(() => contacts.value.filter((c) => !c.available && !c.added))
const canSend = computed(() => !!active.value.session_id && active.value.present
  && !active.value.locked && !replying.value
  && (active.value.conversation_type !== 'hub' || !!orderForSend.value))
const lockTarget = computed(() => openContacts.value.find((c) => c.kind === active.value.require_contact))
const invitable = computed(() => active.value.code === 'ticket' ? [] : addedContacts.value
  .filter((c) => !(active.value.members || []).includes(c.name))
  .filter((c) => !(active.value.conversation_type === 'hub' && c.kind === '客户')))

const PALETTE = ['#2577e3', '#12a76a', '#7a5af8', '#e08a1e', '#e0567a', '#0ea5b7']
function avatarColor(key: string) {
  let h = 0
  for (const ch of key || ' ') h = (h * 31 + ch.charCodeAt(0)) % 997
  return PALETTE[h % PALETTE.length]
}
function safeParse(raw: any) {
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  try { return JSON.parse(raw) } catch { return {} }
}
function preview(s: any) {
  const list = s.messages || []
  const m = list[list.length - 1]
  if (!m) return s.locked ? '请先添加对方联系方式' : '暂无消息'
  const who = m.role === 'me' ? '我：' : ''
  const body = m.kind === 'card' ? '[交付物]' : m.kind === 'file' ? '[文件]' : (m.text || '')
  return who + String(body).slice(0, 18)
}

function parseRooms(list: any[]) {
  return (list || []).map((g) => ({
    ...g,
    messages: (g.messages || []).map((m: any) => ({
      from: m.sender, role: m.role, time: (m.created_at || '').slice(11, 16),
      text: m.content, kind: m.kind || 'text', payload: safeParse(m.payload),
      raw_id: m.msg_id, file_id: safeParse(m.payload).file_id || '',
    })),
  }))
}

let lastQuerySession = ''
async function loadRooms() {
  try {
    // 资源群按当前订单创建；单聊和自建群仍像真实聊天软件一样混排。
    const oid = currentOrderId.value || practice.activeOrderId || ''
    const want = String(route.query.session || '')
    // 深链参数只在它真正变化时应用一次。不能每次轮询都强制切回 want，
    // 否则用户手动选择另一个会话后，15 秒轮询会把人拽回原窗口。
    const queryChanged = want !== lastQuerySession
    lastQuerySession = want
    const r = (await client.get('/practice/im/sessions',
      { params: { order_id: oid, session: want } })).data
    rooms.value = parseRooms(r)
    const target = queryChanged && want ? rooms.value.find((g) => g.session_id === want) : null
    if (target) {
      activeId.value = target.session_id
      if (target.order_id && currentOrderId.value !== target.order_id) {
        currentOrderId.value = target.order_id
      }
    } else if (!rooms.value.some((g) => g.session_id === activeId.value)) {
      activeId.value = (rooms.value.find((g) => g.present && !g.locked) || rooms.value[0] || {}).session_id || ''
    }
    if (activeId.value) markSeen(activeId.value)
  } catch { rooms.value = [] }
}

async function loadContactCatalog(oid: string) {
  if (!oid) { contacts.value = []; mine.value = []; return }
  const r = (await client.get('/practice/im/contacts', { params: { order_id: oid } })).data
  contacts.value = (r.contacts || []).map((c: any) => ({ ...c, order_id: oid }))
  mine.value = r.mine || []
}

async function loadContacts() {
  try {
    const list = (await client.get('/practice/orders')).data || []
    orders.value = list
    const wantedOrder = String(route.query.order || '')
    const oid = (list.find((o: any) => o.order_id === wantedOrder)
      || list.find((o: any) => o.order_id === currentOrderId.value)
      || list.find((o: any) => o.order_id === practice.activeOrderId)
      || list.find((o: any) => o.stage_index < 7) || list[0] || {}).order_id || ''
    const before = currentOrderId.value
    currentOrderId.value = oid
    groupOrderId.value = oid
    if (before === oid) await loadContactCatalog(oid)
  } catch {
    orders.value = []
    contacts.value = []
    mine.value = []
  }
}

watch(currentOrderId, async (oid) => {
  if (!oid) return
  groupOrderId.value = oid
  try { await loadContactCatalog(oid) } catch { contacts.value = [] }
  await loadRooms()
})
async function reload() {
  notice.value = ''
  await loadContacts()
  await loadRooms()
}

async function addContact(c: any) {
  busy.value = true
  notice.value = ''
  try {
    const r = (await client.post('/practice/im/contacts',
      { order_id: c.order_id, kind: c.kind })).data
    await reload()
    if (c.kind === '客户') {
      await router.push({ path: '/practice/orders/' + c.order_id + '/deliverables',
                          query: { code: 'requirement_sheet' } })
      return
    }
    activeId.value = r.session_id
    notice.value = `已添加「${c.name}」，可以单聊或拉进群了`
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '添加失败'
  } finally { busy.value = false }
}

const avatarPick = ref<any>(null)

function onAvatar(m: any) {
  const name = String(m?.from || '')
  const mineHit = mine.value.find((c) => (c.display || c.name) === name || c.name === name)
  const contact = contacts.value.find((c) => c.name === name && !c.added)
  avatarPick.value = { name, contact: contact || null, added: !!mineHit, mine: mineHit || null,
                       remark: mineHit?.remark || '' }
}

function openRemark(c: any) {
  if (!c) return
  remarkTarget.value = c
  remarkTo.value = c.remark || ''
  remarkDlg.value = true
}

async function doRemark() {
  if (!remarkTarget.value) return
  busy.value = true
  try {
    await client.patch(`/practice/im/contacts/${remarkTarget.value.contact_id}`,
                       { remark: remarkTo.value })
    remarkDlg.value = false
    avatarPick.value = null
    await loadRooms()
    await loadContacts()
    notice.value = '备注已保存'
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '备注失败'
  } finally { busy.value = false }
}

function seenKey(sid: string) { return 'im_seen_' + sid }
function hasNew(s: any) {
  const list = s.messages || []
  const last = list[list.length - 1]
  if (!last || !last.raw_id) return false
  return Number(last.raw_id) > Number(localStorage.getItem(seenKey(s.session_id)) || 0)
}
function markSeen(sid: string) {
  const s = rooms.value.find((r) => r.session_id === sid)
  const list = (s?.messages || [])
  const last = list[list.length - 1]
  if (last?.raw_id) localStorage.setItem(seenKey(sid), String(last.raw_id))
}
const msgsEl = ref<HTMLElement | null>(null)
function scrollMsgsToEnd() {
  nextTick(() => { const el = msgsEl.value; if (el) el.scrollTop = el.scrollHeight })
}
function openOrder(orderId: string) {
  if (orderId) router.push(`/practice/orders/${orderId}`)
}
function openSession(sid: string) {
  if (voiceListening.value || voiceProcessing.value) stopVoiceInput()
  activeId.value = sid
  targetRole.value = ''
  notice.value = ''
  markSeen(sid)
  scrollMsgsToEnd()
}

const VOICE_LANGS: Record<string, string> = {
  '中文': 'zh-CN', English: 'en-US', 日本語: 'ja-JP', 한국어: 'ko-KR',
  Français: 'fr-FR', Deutsch: 'de-DE', Español: 'es-ES', Русский: 'ru-RU',
  Italiano: 'it-IT', Português: 'pt-PT', 'Tiếng Việt': 'vi-VN',
  'Bahasa Indonesia': 'id-ID', ไทย: 'th-TH', Türkçe: 'tr-TR',
}

function attachVoiceTranscript(text: string) {
  const piece = String(text || '').trim()
  if (!piece) return
  voiceFinal = [voiceFinal, piece].filter(Boolean).join(' ')
  draft.value = [voiceBase, voiceFinal].filter(Boolean).join(' ')
}

function stopVoiceMic() {
  try { voiceProc?.disconnect() } catch { /* ignore */ }
  voiceStream?.getTracks().forEach((track) => track.stop())
  try { voiceCtx?.close() } catch { /* ignore */ }
  voiceProc = null
  voiceStream = null
  voiceCtx = null
}

function resetVoiceInput(delay = 0) {
  if (voiceResetTimer) window.clearTimeout(voiceResetTimer)
  voiceResetTimer = window.setTimeout(() => {
    stopVoiceMic()
    try { voiceWs?.close() } catch { /* ignore */ }
    voiceWs = null
    voiceListening.value = false
    voiceProcessing.value = false
  }, delay)
}

async function startVoiceMic() {
  try {
    voiceStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    voiceCtx = new AudioContext({ sampleRate: 16000 })
    const source = voiceCtx.createMediaStreamSource(voiceStream)
    voiceProc = voiceCtx.createScriptProcessor(2048, 1, 1)
    const mute = voiceCtx.createGain()
    mute.gain.value = 0
    voiceProc.onaudioprocess = (event) => {
      if (!voiceWs || voiceWs.readyState !== WebSocket.OPEN) return
      const input = event.inputBuffer.getChannelData(0)
      const pcm = new Int16Array(input.length)
      for (let i = 0; i < input.length; i++) {
        const value = Math.max(-1, Math.min(1, input[i]))
        pcm[i] = value < 0 ? value * 0x8000 : value * 0x7fff
      }
      let binary = ''
      const bytes = new Uint8Array(pcm.buffer)
      for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)) as number[])
      }
      voiceWs.send(JSON.stringify({ type: 'audio', audio: btoa(binary) }))
    }
    source.connect(voiceProc)
    voiceProc.connect(mute)
    mute.connect(voiceCtx.destination)
    voiceListening.value = true
    voiceProcessing.value = false
  } catch {
    notice.value = '麦克风未授权或不可用，请检查权限'
    resetVoiceInput()
  }
}

function startVoiceInput() {
  notice.value = ''
  voiceBase = draft.value.trim()
  voiceFinal = ''
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const lang = VOICE_LANGS[String(active.value.language || '中文')] || 'zh-CN'
  voiceWs = new WebSocket(proto + '://' + location.host + '/api/voice/dictation?lang=' + encodeURIComponent(lang))
  voiceProcessing.value = true
  voiceWs.onmessage = async (event) => {
    let msg: any
    try { msg = JSON.parse(event.data) } catch { return }
    if (msg.type === 'ready') await startVoiceMic()
    else if (msg.type === 'transcript') attachVoiceTranscript(msg.text)
    else if (msg.type === 'error') {
      notice.value = msg.message || '语音识别失败'
      resetVoiceInput()
    }
  }
  voiceWs.onerror = () => {
    notice.value = '语音识别通道连接失败'
    resetVoiceInput()
  }
  voiceWs.onclose = () => {
    voiceListening.value = false
    voiceProcessing.value = false
    voiceWs = null
  }
}

function stopVoiceInput() {
  if (!voiceListening.value && !voiceProcessing.value) return
  voiceListening.value = false
  voiceProcessing.value = true
  stopVoiceMic()
  try {
    if (voiceWs?.readyState === WebSocket.OPEN) voiceWs.send(JSON.stringify({ type: 'stop' }))
  } catch { /* ignore */ }
  resetVoiceInput(8000)
}

function toggleVoiceInput() {
  if (voiceListening.value) { stopVoiceInput(); return }
  if (voiceProcessing.value) {
    try { voiceWs?.close() } catch { /* ignore */ }
    resetVoiceInput()
    return
  }
  startVoiceInput()
}

async function send() {
  if (voiceListening.value) stopVoiceInput()
  if (voiceProcessing.value) {
    notice.value = '语音识别中，请稍等识别结果填入输入框'
    return
  }
  const t = draft.value.trim()
  if (!t || !canSend.value) return
  const sid = activeId.value
  draft.value = ''
  replying.value = true
  notice.value = ''
  try {
    const r = (await client.post(`/practice/im/sessions/${sid}/messages`,
      { sender: '我', role: 'me', content: t,
        order_id: orderForSend.value,
        target_role: targetRole.value })).data
    reacted.value = r.reacted || []
    await loadRooms()
    await loadContacts()
    scrollMsgsToEnd()
    if (r.reply && r.reply.locked) notice.value = r.reply.content
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '发送失败'
    draft.value = t
  } finally { replying.value = false }
}

async function sendCard(payload: any) {
  if (!active.value.session_id) return
  busy.value = true
  try {
    await client.post(`/practice/im/sessions/${active.value.session_id}/messages`,
      { sender: '我', role: 'me', content: `【${payload.title}】已发送`, kind: 'card', payload,
        order_id: orderForSend.value, target_role: targetRole.value })
    await loadRooms()
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '发送失败'
  } finally { busy.value = false }
}

async function openDeliverableDlg() {
  docPick.value = ''
  try {
    const r = (await client.get(`/practice/orders/${active.value.order_id}/deliverables`)).data
    deliverables.value = r.items || r.deliverables || []
  } catch { deliverables.value = [] }
  docDlg.value = true
}

async function sendDeliverable() {
  const d = deliverables.value.find((x) => x.deliverable_id === docPick.value)
  if (!d) return
  let excerpt = ''
  try {
    const r = (await client.get(
      `/practice/orders/${active.value.order_id}/deliverables/${d.deliverable_id}`)).data
    excerpt = (r.rendered || '').slice(0, 200)
  } catch {}
  await sendCard({ deliverable_id: d.deliverable_id, title: d.title,
    target: active.value.name, files: [], excerpt })
  docDlg.value = false
  notice.value = '交付物已作为卡片发到本会话'
}

function pickFile() {
  sendMenu.value = false
  fileInput.value?.click()
}

async function onPickFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  busy.value = true
  try {
    const buf = await f.arrayBuffer()
    let bin = ''
    const bytes = new Uint8Array(buf)
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)) as number[])
    }
    const up = (await client.post('/deliverables/files', {
      filename: f.name, mime: f.type || 'application/octet-stream',
      data_b64: btoa(bin), order_id: orderForSend.value,
      deliverable_id: '',
    })).data
    await client.post(`/practice/im/sessions/${active.value.session_id}/messages`,
      { sender: '我', role: 'me', content: f.name, kind: 'file',
        order_id: orderForSend.value, target_role: targetRole.value,
        payload: { filename: f.name, size: Math.max(1, Math.round(f.size / 1024)) + ' KB',
                   file_id: up.file_id } })
    await loadRooms()
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '文件发送失败'
  } finally {
    busy.value = false
    input.value = ''
  }
}

async function createGroup() {
  busy.value = true
  notice.value = ''
  try {
    const first = mine.value.find((c) => (c.display || c.name) === groupMembers.value[0]
      || c.name === groupMembers.value[0])
    groupOrderId.value = first?.order_id || groupOrderId.value
    const r = (await client.post('/practice/im/sessions', {
      order_id: groupOrderId.value, name: groupName.value.trim() || '旅行小群',
      kind: '群聊', members: groupMembers.value,
    })).data
    newGroupDlg.value = false
    groupName.value = ''
    groupMembers.value = []
    await reload()
    activeId.value = r.session_id
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '创建失败'
  } finally { busy.value = false }
}

function openRename() { renameTo.value = active.value.name; renameDlg.value = true }

function renameOrRemark() {
  const code = String(active.value.code || '')
  if (code.startsWith('dm-')) {
    const kind = code.slice(3)
    const c = mine.value.find((x) => x.kind === kind)
    openRemark(c || { contact_id: '', name: active.value.name, remark: '' })
    return
  }
  openRename()
}

async function doRename() {
  busy.value = true
  try {
    await client.post(`/practice/im/sessions/${active.value.session_id}/rename`,
      { name: renameTo.value })
    renameDlg.value = false
    await loadRooms()
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '改名失败'
  } finally { busy.value = false }
}

function openInvite() { inviteNames.value = []; inviteDlg.value = true }

async function doInvite() {
  if (!inviteNames.value.length) { inviteDlg.value = false; return }
  busy.value = true
  try {
    const r = (await client.post(`/practice/im/sessions/${active.value.session_id}/members`,
      { names: inviteNames.value })).data
    inviteDlg.value = false
    await loadRooms()
    if (r.message) notice.value = r.message
  } catch (e: any) {
    notice.value = e?.response?.data?.detail || '邀请失败'
  } finally { busy.value = false }
}

function fileUrl(fid: string) {
  const base = (client.defaults as any).baseURL || ''
  return `${base}/deliverables/files/${fid}`
}

function callCustomer() {
  router.push(`/practice/orders/${active.value.order_id}/call`)
}

function openDeliverable(id: string) {
  router.push(`/practice/orders/${active.value.order_id}/deliverables?code=${id}`)
}

let poll = 0
function pickFromQuery() {
  const want = String(route.query.session || '')
  if (want && rooms.value.some((x) => x.session_id === want)) {
    activeId.value = want
    markSeen(want)
  }
}

onMounted(async () => {
  try { await reload() } catch {}
  pickFromQuery()                       // 从「发送方案」跳过来时直接打开那位客户的会话
  poll = window.setInterval(loadRooms, 15000)
})
watch(() => [route.query.session, route.query.order], () => { reload() })
watch(() => [active.value.session_id, active.value.messages.length], () => scrollMsgsToEnd())
onUnmounted(() => { if (voiceListening.value || voiceProcessing.value) stopVoiceInput(); if (poll) clearInterval(poll) })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.im { display: grid; grid-template-columns: 326px minmax(0, 1fr); gap: 12px; max-width: 1320px; align-items: start; }
.im.wide { grid-template-columns: 326px minmax(0, 1fr) 268px; }
.voice-tool.on { color: #fff; background: #e0567a; border-color: #e0567a; animation: voicePulse 1.1s ease-in-out infinite; }
@keyframes voicePulse { 0%,100% { box-shadow: 0 0 0 0 rgba(224,86,122,.28); } 50% { box-shadow: 0 0 0 7px rgba(224,86,122,0); } }
.col { display: flex; flex-direction: column; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; box-shadow: $shadow-card; }

.side { padding: 10px; max-height: 660px; overflow-y: auto; }
.side-head { display: flex; align-items: center; gap: 6px; }
.order-sel { flex: 1; height: 32px; border: 1px solid $color-border; border-radius: 6px; padding: 0 8px; font-size: 14px; outline: none; }
.order-sel:focus { border-color: $color-primary; }
.icon-btn { width: 32px; height: 32px; flex-shrink: 0; border: 1px solid $color-border; background: #fff; border-radius: 6px; color: $color-text-secondary; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.icon-btn:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.icon-btn:disabled { opacity: .45; cursor: default; }

.sec-lbl { font-size: 14px; color: $color-text-muted; margin: 12px 4px 6px; }
.row-item { display: flex; align-items: center; gap: 10px; padding: 8px 9px; border-radius: 8px; cursor: pointer; }
.row-item:hover { background: $color-primary-softer; }
.row-item.on { background: $color-primary-soft; }
.row-item.ct { cursor: default; }
.row-item.dim { opacity: .62; }
.av { position: relative; width: 34px; height: 34px; border-radius: 9px; color: #fff; font-size: 16px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.av.sm { width: 27px; height: 27px; border-radius: 8px; font-size: 14px; }
.ri-mid { min-width: 0; flex: 1; }
.ri-name { font-size: 17px; font-weight: 600; display: flex; align-items: center; gap: 7px; min-width: 0; white-space: nowrap; overflow: hidden; }
.ri-last { font-size: 15px; color: $color-text-muted; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ri-lock { font-size: 13px; font-weight: 500; color: $color-warning; background: #fdf3e6; border-radius: 4px; padding: 1px 5px; }
.ri-lock.soft { color: $color-text-muted; background: #f1f3f6; }
.tag { font-size: 13px; color: $color-text-secondary; background: #f1f4f8; border-radius: 4px; padding: 1px 6px; font-weight: 500; }
.ri-order { font-size: 14.5px; color: $color-text-muted; white-space: nowrap; }
.av.unread { box-shadow: 0 0 0 2px #fff, 0 0 0 4px $color-primary; }
.dot-av { position: absolute; top: -2px; right: -2px; width: 9px; height: 9px; border-radius: 50%; background: #2577e3; border: 1.5px solid #fff; }
.dot-new { width: 8px; height: 8px; border-radius: 50%; background: #2577e3; flex-shrink: 0; }
.hidden-file { display: none; }
.clickable { cursor: pointer; }
.mem.clickable:hover { background: $color-primary-softer; border-radius: 6px; }
.avatar-card { margin: 10px 16px 0; border: 1px solid $color-primary; border-radius: 10px; background: #fff; padding: 10px 12px; box-shadow: 0 10px 26px rgba(37,119,227,0.16); }
.ac-head { display: flex; align-items: center; gap: 9px; }
.ac-mid { display: flex; flex-direction: column; }
.ac-name { font-size: 15px; font-weight: 700; }
.ac-hint { font-size: 13.5px; color: $color-text-muted; }
.ac-acts { display: flex; gap: 8px; margin-top: 9px; }

.main { min-height: 660px; max-height: 660px; }
.m-head { display: flex; align-items: center; justify-content: space-between; padding: 13px 16px; border-bottom: 1px solid $color-border; }
.mh-l { display: flex; align-items: center; gap: 9px; min-width: 0; }
.mh-name { font-size: 19px; font-weight: 700; }
.mh-kind { font-size: 14.5px; color: $color-primary; background: $color-primary-soft; border-radius: 4px; padding: 1px 7px; }
.mh-kind { font-size: 14.5px; color: $color-primary; background: $color-primary-soft; border-radius: 4px; padding: 1px 7px; }
.mh-type { font-size: 13.5px; color: $color-text-secondary; background: #f1f5fa; border-radius: 4px; padding: 1px 7px; }
.mh-order.link { cursor: pointer; color: $color-primary; text-decoration: underline; text-underline-offset: 3px; }
.target-row { display: flex; align-items: center; gap: 9px; font-size: 14px; color: $color-text-secondary; }
.target-label { flex: 0 0 auto; font-weight: 600; }
.target-select { border: 1px solid $color-border; border-radius: 6px; padding: 5px 8px; font: inherit; color: $color-text; background: #fff; outline: none; }
.target-select:focus { border-color: $color-primary; }
.mh-members { font-size: 14.5px; color: $color-text-muted; cursor: pointer; }
.mh-members:hover { color: $color-primary; }
.mh-order { font-size: 14.5px; color: $color-text-muted; }
.mh-r { display: flex; gap: 6px; }

.lock-bar { display: flex; align-items: center; gap: 8px; font-size: 15px; color: $color-warning; background: #fdf7ee; padding: 9px 16px; }
.lock-bar.soft { color: $color-text-secondary; background: #f7f9fc; }
.lock-bar .mini { margin-left: auto; }

.msgs { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.sys-msg { align-self: center; font-size: 13.5px; color: $color-text-muted; background: #f4f6f9; border-radius: 999px; padding: 3px 12px; }
.row { display: flex; gap: 9px; }
.row .body { max-width: 78%; }
.meta { display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }
.who { font-size: 15px; color: $color-text-secondary; }
.time { font-size: 14px; color: $color-text-muted; }
.bubble { background: #f4f6f9; border-radius: 0 8px 8px 8px; padding: 10px 13px; font-size: 17px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.row.me { flex-direction: row-reverse; }
.row.me .body { display: flex; flex-direction: column; align-items: flex-end; }
.row.me .meta { flex-direction: row-reverse; }
.row.me .bubble { background: $color-primary; color: #fff; border-radius: 8px 0 8px 8px; }
.bubble.typing { color: $color-text-muted; background: #f4f6f9; }

.card-msg { border: 1px solid $color-border; border-left: 3px solid $color-primary; border-radius: 8px; padding: 10px 12px; background: #fff; max-width: 420px; }
.cm-head { display: flex; align-items: center; gap: 6px; }
.cm-title { font-size: 17px; font-weight: 700; }
.cm-tag { margin-left: auto; font-size: 13px; color: $color-primary; background: $color-primary-soft; border-radius: 4px; padding: 1px 6px; }
.cm-meta { font-size: 13.5px; color: $color-text-muted; margin: 5px 0; }
.cm-ex { font-size: 15.5px; color: $color-text-secondary; margin: 0 0 7px; white-space: pre-wrap; max-height: 76px; overflow: hidden; }
.cm-files { font-size: 13.5px; color: $color-text-muted; margin-bottom: 6px; }
.cm-open { font-size: 14px; color: $color-primary; background: $color-primary-soft; border: none; border-radius: 6px; padding: 5px 10px; cursor: pointer; }

.file-msg { display: inline-flex; align-items: center; gap: 8px; background: #f4f6f9; border-radius: 8px; padding: 10px 12px; font-size: 15px; }
.fm-name { color: $color-primary; }
.fm-size { font-size: 13.5px; color: $color-text-muted; }

.reacted { display: flex; align-items: center; gap: 8px; padding: 9px 16px 0; flex-wrap: wrap; }
.rc-label { font-size: 13.5px; color: $color-text-muted; }
.rc-chip { font-size: 13.5px; color: $color-success; background: #e8f7ee; border-radius: 4px; padding: 2px 7px; }
.rc-close { border: none; background: none; color: $color-text-muted; cursor: pointer; }
.notice { margin: 10px 16px 0; font-size: 15px; color: $color-primary; background: $color-primary-softer; border-radius: 8px; padding: 8px 11px; }

.input { border-top: 1px solid $color-border; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.tools { display: flex; gap: 8px; }
.tool { display: inline-flex; align-items: center; gap: 5px; font-size: 14px; color: $color-text-secondary; background: #fff; border: 1px solid $color-border; border-radius: 6px; padding: 4px 10px; cursor: pointer; }
.tool:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.tool:disabled { opacity: .45; cursor: default; }
.ipt { border: 1px solid $color-border; border-radius: 8px; padding: 8px 10px; font-size: 15px; resize: none; outline: none; font-family: inherit; }
.ipt:focus { border-color: $color-primary; }
.send { align-self: flex-end; display: inline-flex; align-items: center; gap: 5px; }

.info { padding: 14px; gap: 6px; max-height: 660px; overflow-y: auto; }
.info-title { font-size: 15px; font-weight: 700; margin-bottom: 6px; }
.info-title.mt { margin-top: 14px; }
.info-row { display: flex; justify-content: space-between; font-size: 15.5px; color: $color-text-secondary; padding: 4px 0; }
.info-row b { color: $color-text; font-weight: 600; }
.mem { display: flex; align-items: center; gap: 9px; padding: 6px 0; font-size: 16px; }
.mem-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: $color-success; }
.mini { font-size: 14px; border: 1px solid $color-border; background: #fff; color: $color-text-secondary; border-radius: 6px; padding: 4px 9px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.mini:disabled { opacity: .5; cursor: default; }
.mini.wide { width: 100%; margin-top: 8px; }

.mask { position: fixed; inset: 0; background: rgba(16, 26, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 24px; }
.dlg { width: 400px; padding: 20px 22px; max-height: 86vh; overflow-y: auto; }
.dlg-title { font-size: 16.5px; font-weight: 800; margin-bottom: 14px; }
.dlg-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.dlg-row.top { align-items: flex-start; }
.dlg-row.top .pick { border: 1px solid $color-border; border-radius: 8px; padding: 6px 8px; max-height: 220px; overflow-y: auto; }
.pick-row input { flex-shrink: 0; }
.pick-row .tag { margin-left: auto; flex-shrink: 0; }
.dlg-row label { width: 52px; font-size: 15px; color: $color-text-secondary; flex-shrink: 0; }
.dlg-row .ipt { flex: 1; }
.dlg-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }
.pick { flex: 1; max-height: 240px; overflow-y: auto; }
.pick-row { display: flex; align-items: center; gap: 8px; font-size: 15px; padding: 6px 2px; cursor: pointer; }
.pick-row > span:not(.tag) { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.empty { text-align: center; color: $color-text-muted; font-size: 15px; padding: 40px; }
.empty-sm { text-align: center; color: $color-text-muted; font-size: 14px; padding: 10px; }
</style>
