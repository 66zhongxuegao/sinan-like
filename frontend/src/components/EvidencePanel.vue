<template>
  <div v-if="rows.length" class="ev">
    <button class="ev-toggle" type="button" :aria-expanded="open ? 'true' : 'false'" @click="open = !open">
      <SIcon name="link" :size="12" />
      <span>{{ open ? '收起依据' : '展开依据' }}</span>
      <i class="ev-count">{{ rows.length }} 条</i>
      <i v-if="profileCount" class="ev-tag">含 {{ profileCount }} 条个性化</i>
    </button>
    <div v-if="open" class="ev-body">
      <p class="ev-hint">编号 + 来源名称：<b>P</b> 画像 · <b>M</b> 国别知识库 · <b>R</b> 评分标准 · <b>K</b> 技能知识库 ·
        <b>G</b> 技能图 · <b>W</b> 网络来源 · <b>H</b> 学习记录 · <b>O</b> 实战记录</p>
      <section v-for="g in groups" :key="g.name" class="ev-group">
        <h5>{{ g.name }}</h5>
        <div v-for="r in g.rows" :key="r.no" class="ev-row">
          <span class="ev-no" :class="'g-' + r.no[0]">{{ r.no }}</span>
          <div class="ev-main">
            <a v-if="r.url" class="ev-label" :href="r.url" target="_blank" rel="noopener noreferrer">{{ r.label }} ↗</a>
            <span v-else class="ev-label">{{ r.label }}</span>
            <span v-if="r.detail" class="ev-detail">{{ r.detail }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 讲义/回复下方可展开的「依据」。
 * 后端给的是 {no, group, label, detail, url}：编号 + 一眼能看懂来源的中文说明，网络来源带链接。
 * 兼容旧数据：历史消息里 evidence 还是字符串（如 "rubric:C2.1"），这里翻成能读的中文，不再直接露出机器编号。
 */
import { computed, ref } from 'vue'
import SIcon from '@/components/SIcon.vue'

interface Row { no: string; group: string; label: string; detail?: string; url?: string }

const props = defineProps<{ items?: Array<Row | string> }>()
const open = ref(false)

const GROUP_BY_PREFIX: Record<string, string> = {
  P: '学员画像', M: '国别知识库', R: '评分标准', K: '技能知识库', G: '技能图',
  W: '网络来源', H: '学习记录', O: '实战记录', D: '出题依据',
}

function legacy(s: string, i: number): Row {
  const t = String(s)
  const n = (p: string) => `${p}${i + 1}`
  if (t.startsWith('rubric:')) return { no: n('R'), group: '评分标准', label: `评分标准 · ${t.slice(7)}`, detail: 'M1–M5 五档行为锚点' }
  if (t.startsWith('bridge:')) return { no: n('R'), group: '评分标准', label: `文化桥 · ${t.slice(7)}` }
  if (t.startsWith('知识:')) return { no: n('K'), group: '技能知识库', label: `技能知识库 · ${t.slice(3).replace('·', ' · ')}` }
  if (t.startsWith('skill_graph:')) return { no: n('G'), group: '技能图', label: `技能图 · ${t.split(':')[1] || ''}` }
  if (t.startsWith('thread:')) return { no: n('H'), group: '学习记录', label: `本技能点对话 · ${t.slice(7)}` }
  if (t.startsWith('quiz:')) return { no: n('H'), group: '学习记录', label: `本技能点答题 · ${t.slice(5)}` }
  if (t.startsWith('mastery:')) return { no: n('H'), group: '学习记录', label: `当前掌握度 · ${t.slice(8)}` }
  if (t.startsWith('order:')) return { no: n('O'), group: '实战记录', label: `实战订单 · ${t.slice(6)}` }
  return { no: n('K'), group: '技能知识库', label: t }
}

const rows = computed<Row[]>(() => (props.items || []).map((x, i) => {
  if (typeof x === 'string') return legacy(x, i)
  return { ...x, group: x.group || GROUP_BY_PREFIX[String(x.no || '')[0]] || '其他' }
}))
const profileCount = computed(() => rows.value.filter((r) => r.no.startsWith('P') || r.no.startsWith('M')).length)
const groups = computed(() => {
  const order = ['学员画像', '国别知识库', '出题依据', '评分标准', '技能知识库', '技能图', '网络来源', '学习记录', '实战记录', '其他']
  const map = new Map<string, Row[]>()
  for (const r of rows.value) map.set(r.group, [...(map.get(r.group) || []), r])
  return order.filter((g) => map.has(g)).map((g) => ({ name: g, rows: map.get(g)! }))
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.ev { margin-top: 10px; }
.ev-toggle { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 4px 0;
  color: $color-primary; font-size: 14.5px; font-weight: 600; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.ev-count, .ev-tag { font-style: normal; font-size: 12.5px; font-weight: 600; border-radius: 999px; padding: 1px 8px; }
.ev-count { color: $color-text-secondary; background: $color-primary-soft; }
.ev-tag { color: #fff; background: $blue-500; }
.ev-body { margin-top: 6px; padding: 10px 12px 6px; border-radius: 12px; background: $color-primary-softer; border: 1px solid $color-border; }
.ev-hint { margin: 0 0 8px; font-size: 12.5px; line-height: 1.6; color: $color-text-muted; }
.ev-hint b { color: $color-primary; }
.ev-group { margin-bottom: 10px; }
.ev-group h5 { margin: 0 0 4px; font-size: 13px; font-weight: 700; color: $color-text-secondary; letter-spacing: .5px; }
.ev-row { display: flex; align-items: flex-start; gap: 9px; padding: 5px 0; }
.ev-no { flex-shrink: 0; min-width: 30px; text-align: center; font-size: 12.5px; font-weight: 800; line-height: 1;
  padding: 5px 6px; border-radius: 7px; color: #fff; background: $blue-700; }
.ev-no.g-P { background: $blue-500; }
.ev-no.g-M { background: #12a76a; }
.ev-no.g-W { background: #e08a1e; }
.ev-no.g-H, .ev-no.g-O { background: #6b7a90; }
.ev-no.g-D { background: $blue-450; }
.ev-main { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.ev-label { font-size: 14.5px; line-height: 1.55; color: $color-text; word-break: break-word; }
a.ev-label { color: $color-primary; text-decoration: underline; text-decoration-color: rgba(19,52,80,.3); text-underline-offset: 3px; }
.ev-detail { font-size: 13px; line-height: 1.55; color: $color-text-secondary; word-break: break-word; }
</style>
