<template>
  <div v-if="store.isAuthenticated" ref="rootRef" class="um">
    <button class="um-btn" type="button" :aria-expanded="open ? 'true' : 'false'" @click="open = !open">
      <span class="um-avatar">{{ avatarChar }}</span>
      <span class="um-name">{{ store.displayName || store.username }}</span>
      <span class="um-chev" />
    </button>

    <transition name="um-menu-anim">
      <div v-if="open" class="um-menu" @click.stop>
        <div class="um-head">
          <span class="um-avatar lg">{{ avatarChar }}</span>
          <div class="um-head-txt">
            <div class="um-hd-name">{{ store.displayName || store.username }}</div>
            <div class="um-hd-sub">@{{ store.username }} · {{ store.userId }}</div>
          </div>
        </div>
        <div class="um-scope" :class="store.isDemo ? 'demo' : 'real'">
          {{ store.dataScopeLabel }}
        </div>

        <div class="um-divider" />
        <button class="um-item" type="button" @click="openDialog">
          <SIcon name="user" :size="16" /><span>个人资料</span>
          <i class="um-on">可编辑</i>
        </button>
        <button class="um-item" type="button" @click="goProfile">
          <SIcon name="chart" :size="16" /><span>学情画像</span>
          <SIcon name="right" :size="14" class="um-arrow" />
        </button>
        <div class="um-divider" />
        <div class="um-group-label">数据看板</div>
        <button class="um-item" type="button" @click="goDashboard('team')">
          <SIcon name="users" :size="16" /><span>团队看板</span>
          <i class="um-on">实时</i>
        </button>
        <button class="um-item" type="button" @click="goDashboard('ops')">
          <SIcon name="chart" :size="16" /><span>运营看板</span>
          <i class="um-on">全量</i>
        </button>
        <div class="um-divider" />
        <button class="um-item danger" type="button" :disabled="leaving" @click="doLogout">
          <SIcon name="lock" :size="16" /><span>{{ leaving ? '正在退出…' : '退出登录' }}</span>
        </button>
      </div>
    </transition>

    <!-- 个人资料：编辑并保存到服务端（PATCH /auth/profile） -->
    <teleport to="body">
      <div v-if="dialog" class="um-mask" @click.self="closeDialog">
        <div class="um-dialog" role="dialog" aria-label="个人资料">
          <div class="ud-head">
            <span class="ud-title">个人资料</span>
            <button class="ud-close" type="button" title="关闭" @click="closeDialog"><SIcon name="x" :size="16" /></button>
          </div>

          <div v-if="msg" class="ud-alert ok"><SIcon name="check" :size="15" /><span>{{ msg }}</span></div>
          <div v-if="err" class="ud-alert bad"><SIcon name="warn" :size="15" /><span>{{ err }}</span></div>

          <div class="ud-grid">
            <label class="ud-field">
              <span class="ul">显示名</span>
              <input v-model="form.display_name" class="ui" type="text" maxlength="40" placeholder="同事与客户看到的名字" />
            </label>
            <label class="ud-field">
              <span class="ul">所属公司 / 门店</span>
              <input v-model="form.company" class="ui" type="text" maxlength="80" placeholder="例如：司南礼客定制旅行" />
            </label>
            <label class="ud-field">
              <span class="ul">手机号</span>
              <input v-model="form.phone" class="ui" type="text" maxlength="32" placeholder="仅本人可见" />
            </label>
            <label class="ud-field">
              <span class="ul">邮箱</span>
              <input v-model="form.email" class="ui" type="text" maxlength="80" placeholder="用于接收通知" />
            </label>
            <label class="ud-field wide">
              <span class="ul">个人简介</span>
              <textarea v-model="form.bio" class="ui ta" rows="3" maxlength="200"
                placeholder="擅长线路 / 语种 / 从业年限等" />
            </label>
          </div>

          <div class="ud-meta">
            <span>账号 <b>@{{ store.username }}</b></span>
            <span>用户 ID <b>{{ store.userId }}</b></span>
            <span>数据口径 <b>{{ store.dataScopeLabel }}</b></span>
            <span v-if="store.profile?.created_at">注册于 <b>{{ fmtAt(store.profile.created_at) }}</b></span>
            <span v-if="store.profile?.last_login_at">最近登录 <b>{{ fmtAt(store.profile.last_login_at) }}</b></span>
          </div>

          <div class="ud-foot">
            <button class="ud-btn ghost" type="button" :disabled="saving" @click="closeDialog">取消</button>
            <button class="ud-btn" type="button" :disabled="saving || !dirty" @click="save">
              <SIcon v-if="saving" name="refresh" :size="14" class="spin" />
              <span>{{ saving ? '保存中…' : '保存资料' }}</span>
            </button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import { useUserStore, type ProfilePatch } from '@/stores/user'

/**
 * 右上角用户菜单（R12）：个人资料（可编辑保存）+ 学情画像入口 + 退出登录。
 * 身份全部来自服务端会话（stores/user.ts）；未登录时组件不渲染任何内容。
 */

const router = useRouter()
const store = useUserStore()

const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)
const dialog = ref(false)
const saving = ref(false)
const leaving = ref(false)
const msg = ref('')
const err = ref('')

const form = reactive<Required<ProfilePatch>>({
  display_name: '', company: '', phone: '', email: '', bio: '',
})

const avatarChar = computed(() => (store.displayName || store.username || '?').slice(0, 1).toUpperCase())

function fillForm() {
  const p = store.profile
  form.display_name = p?.display_name || ''
  form.company = p?.company || ''
  form.phone = p?.phone || ''
  form.email = p?.email || ''
  form.bio = p?.bio || ''
}

const dirty = computed(() => {
  const p = store.profile
  if (!p) return false
  return form.display_name !== (p.display_name || '')
    || form.company !== (p.company || '')
    || form.phone !== (p.phone || '')
    || form.email !== (p.email || '')
    || form.bio !== (p.bio || '')
})

function fmtAt(v: string): string {
  const s = String(v || '').replace('T', ' ')
  return s.slice(0, 16)
}

function openDialog() {
  open.value = false
  msg.value = ''
  err.value = ''
  fillForm()
  dialog.value = true
}

function closeDialog() {
  if (saving.value) return
  dialog.value = false
}

function goProfile() {
  open.value = false
  void router.push('/profile')
}

function goDashboard(view: 'team' | 'ops') {
  open.value = false
  void router.push({ path: '/dashboard', query: { view } })
}

async function save() {
  if (saving.value || !dirty.value) return
  saving.value = true
  msg.value = ''
  err.value = ''
  try {
    await store.updateProfile({
      display_name: form.display_name.trim(),
      company: form.company.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      bio: form.bio.trim(),
    })
    msg.value = '个人资料已保存'
  } catch (e: any) {
    const d = e?.response?.data?.detail
    err.value = typeof d === 'string' && d ? d
      : (e?.response ? `保存失败（HTTP ${e.response.status}），请重试` : '暂时无法连接，资料未保存，请稍后重试')
  } finally {
    saving.value = false
  }
}

async function doLogout() {
  if (leaving.value) return
  leaving.value = true
  try {
    await store.logout()
  } finally {
    leaving.value = false
    open.value = false
  }
}

function onDocClick(e: MouseEvent) {
  if (!open.value) return
  const el = e.target as Node | null
  if (el && rootRef.value && !rootRef.value.contains(el)) open.value = false
}

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (dialog.value) closeDialog()
  else open.value = false
}

/** 会话资料变化（登录/恢复/保存）后同步表单基线 */
watch(() => store.profile, () => { if (!dialog.value) fillForm() }, { deep: true })

onMounted(() => {
  fillForm()
  document.addEventListener('mousedown', onDocClick)
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.um { position: relative; }
.um-btn { display: flex; align-items: center; gap: 8px; padding: 4px 12px 4px 5px; border: 1px solid $color-border;
  border-radius: 999px; background: #fff; cursor: pointer; transition: border-color .15s ease, box-shadow .15s ease; }
.um-btn:hover { border-color: $color-primary; box-shadow: $shadow-card; }
.um-avatar { width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
  background: linear-gradient(135deg, $color-primary, $color-primary-light); color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: $fs-body; font-weight: 700; }
.um-avatar.lg { width: 40px; height: 40px; font-size: $fs-list; }
.um-name { font-size: $fs-body; font-weight: 600; color: $color-text; max-width: 140px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.um-chev { width: 7px; height: 7px; border-right: 1.5px solid $color-text-secondary; border-bottom: 1.5px solid $color-text-secondary;
  transform: rotate(45deg) translateY(-2px); }

.um-menu { position: absolute; top: calc(100% + 8px); right: 0; width: 276px; background: #fff;
  border: 1px solid $color-border; border-radius: 12px; box-shadow: 0 16px 40px rgba(16,32,56,.18);
  padding: 8px; z-index: 60; }
.um-head { display: flex; align-items: center; gap: 10px; padding: 6px 8px 8px; }
.um-head-txt { min-width: 0; }
.um-hd-name { font-size: $fs-body; font-weight: 700; color: $color-text; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.um-hd-sub { margin-top: 2px; font-size: $fs-badge; color: $color-text-muted; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.um-scope { margin: 0 8px 6px; display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: $fs-badge; font-weight: 700; }
.um-scope.real { color: $color-success; background: #e5f7ee; }
.um-scope.demo { color: #b3730f; background: #fdf3e3; }
.um-divider { height: 1px; background: $color-border; margin: 5px 4px; }
.um-item { width: 100%; display: flex; align-items: center; gap: 10px; padding: 10px; border: none; background: transparent;
  border-radius: 8px; font-size: $fs-body; color: $color-text; cursor: pointer; text-align: left; }
.um-item:hover { background: $color-primary-softer; }
.um-group-label { padding: 6px 10px 2px; font-size: 11.5px; font-weight: 700; letter-spacing: 1.2px; color: #9aa8bb; }
.um-item.danger { color: $color-danger; }
.um-item.danger:hover { background: #fdecec; }
.um-item:disabled { opacity: .6; cursor: default; }
.um-item svg { color: currentColor; flex-shrink: 0; }
.um-on { margin-left: auto; font-style: normal; font-size: $fs-badge; color: $color-primary; background: $color-primary-soft;
  border-radius: 999px; padding: 1px 7px; }
.um-arrow { margin-left: auto; color: $color-text-muted; }
.um-menu-anim-enter-active, .um-menu-anim-leave-active { transition: opacity .16s ease, transform .16s ease; }
.um-menu-anim-enter-from, .um-menu-anim-leave-to { opacity: 0; transform: translateY(-6px); }

.um-mask { position: fixed; inset: 0; z-index: 3000; background: rgba(16,32,56,.34); display: flex;
  align-items: center; justify-content: center; padding: 24px; }
.um-dialog { width: 100%; max-width: 560px; background: #fff; border-radius: $radius-lg; box-shadow: $shadow-deep;
  padding: 20px 22px 18px; max-height: 90vh; overflow-y: auto; }
.ud-head { display: flex; align-items: center; justify-content: space-between; }
.ud-title { font-size: 20px; font-weight: 800; }
.ud-close { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border: none;
  background: transparent; color: $color-text-muted; border-radius: 8px; cursor: pointer; }
.ud-close:hover { background: $color-primary-softer; color: $color-primary; }

.ud-alert { display: flex; align-items: flex-start; gap: 8px; margin-top: 14px; padding: 9px 12px; border-radius: $radius-md;
  font-size: $fs-meta; line-height: 1.6; }
.ud-alert.ok { color: #0f7a4d; background: #eafaf1; border: 1px solid #ccecd9; }
.ud-alert.bad { color: #b32d2d; background: #fdecec; border: 1px solid #f7cfcf; }

.ud-grid { margin-top: 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.ud-field { display: flex; flex-direction: column; gap: 6px; }
.ud-field.wide { grid-column: 1 / -1; }
.ul { font-size: $fs-meta; font-weight: 600; color: $color-text-secondary; }
.ui { width: 100%; height: 40px; padding: 0 12px; font-size: $fs-body; color: $color-text; background: #fff;
  border: 1px solid $color-border-strong; border-radius: $radius-md; outline: none; font-family: inherit;
  transition: border-color .15s ease, box-shadow .15s ease; }
.ui:focus { border-color: $color-primary; box-shadow: 0 0 0 3px rgba(37,119,227,.12); }
.ui.ta { height: auto; padding: 10px 12px; line-height: 1.7; resize: vertical; }

.ud-meta { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 12px 14px; border-radius: $radius-md;
  background: $color-bg; border: 1px solid $color-border; font-size: $fs-meta; color: $color-text-secondary; }
.ud-meta b { color: $color-text; font-weight: 700; }

.ud-foot { margin-top: 18px; display: flex; justify-content: flex-end; gap: 10px; }
.ud-btn { display: inline-flex; align-items: center; gap: 7px; padding: 10px 20px; border: none; border-radius: 999px;
  cursor: pointer; font-size: $fs-body; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, $color-primary, $color-primary-dark); box-shadow: 0 6px 16px rgba(37,119,227,.24); }
.ud-btn:disabled { cursor: default; background: linear-gradient(135deg, #9dc0ee, #86aee6); box-shadow: none; }
.ud-btn.ghost { background: #fff; color: $color-text-secondary; border: 1px solid $color-border; box-shadow: none; }
.ud-btn.ghost:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.spin { animation: umSpin .9s linear infinite; }
@keyframes umSpin { to { transform: rotate(360deg); } }
</style>
