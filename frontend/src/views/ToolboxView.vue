<template>
  <div class="tb">
    <section class="tool card">
      <div class="tool-head">
        <span class="tool-ic" style="color:#2577e3;background:#eaf3fe"><SIcon name="route" :size="18" /></span>
        <div class="tool-meta">
          <div class="tool-name">路线查询 · 驾车 / 步行 / 骑行 / 公交</div>
        </div>
      </div>
      <div class="tb-body">
        <aside class="panel">
        <div class="modes">
          <button v-for="m in MODES" :key="m.key" class="mode"
            :class="{ on: mode === m.key }" @click="mode = m.key">
            <SIcon :name="m.icon" :size="14" />{{ m.label }}
          </button>
        </div>

        <div class="fld">
          <label class="lb"><i class="pin from" />起点</label>
          <div class="ac-wrap">
            <input v-model="from" class="ipt" placeholder="打几个字，会像地图 App 一样给候选"
              @input="tips('from')" @focus="tips('from')" @keydown.enter="query" />
            <div v-if="sug.for === 'from' && sug.items.length" class="ac-list">
              <div v-for="(t, i) in sug.items" :key="i" class="ac-item"
                @mousedown.prevent="pick(t, 'from')">
                <span class="ac-name">{{ t.name }}</span>
                <span class="ac-sub">{{ t.district || t.city }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="fld">
          <label class="lb"><i class="pin via" />途经点</label>
          <div v-for="(w, i) in waypoints" :key="i" class="wp">
            <div class="ac-wrap">
              <input v-model="waypoints[i]" class="ipt" :placeholder="'第 ' + (i + 1) + ' 个途经点'"
                @input="tips('via', i)" @focus="tips('via', i)" />
              <div v-if="sug.for === 'via' && sug.index === i && sug.items.length" class="ac-list">
                <div v-for="(t, k) in sug.items" :key="k" class="ac-item"
                  @mousedown.prevent="pick(t, 'via', i)">
                  <span class="ac-name">{{ t.name }}</span>
                  <span class="ac-sub">{{ t.district || t.city }}</span>
                </div>
              </div>
            </div>
            <button class="rm" @click="waypoints.splice(i, 1)"><SIcon name="x" :size="12" /></button>
          </div>
          <button class="add" @click="waypoints.push('')">
            <SIcon name="plus" :size="12" />添加途经点
          </button>
        </div>

        <div class="fld">
          <label class="lb"><i class="pin to" />终点</label>
          <div class="ac-wrap">
            <input v-model="to" class="ipt" placeholder="如 萧山机场"
              @input="tips('to')" @focus="tips('to')" @keydown.enter="query" />
            <div v-if="sug.for === 'to' && sug.items.length" class="ac-list">
              <div v-for="(t, i) in sug.items" :key="i" class="ac-item"
                @mousedown.prevent="pick(t, 'to')">
                <span class="ac-name">{{ t.name }}</span>
                <span class="ac-sub">{{ t.district || t.city }}</span>
              </div>
            </div>
          </div>
        </div>

        <button class="tc-btn go" :disabled="busy || !from.trim() || !to.trim()" @click="query">
          {{ busy ? '规划中…' : '查询路线' }}
        </button>

        <div v-if="route && !route.error" class="result">
          <div class="r-main">
            <span class="r-km">{{ (route.distance_m / 1000).toFixed(1) }} km</span>
            <span class="r-min">约 {{ Math.round(route.duration_s / 60) }} 分钟</span>
            <span v-if="route.note" class="r-note">{{ route.note }}</span>
          </div>
          <div v-if="route.mode === 'transit' && alts.length" class="alts">
            <div v-for="(a, i) in alts" :key="i" class="alt" :class="{ on: i === altIndex }"
              @click="altIndex = i">
              <span class="alt-name">{{ a.label }}</span>
              <span class="alt-sum">{{ a.summary }}<template v-if="a.transfer"> · 换乘 {{ a.transfer }} 次</template></span>
              <span class="alt-num">
                {{ Math.round(a.duration_s / 60) }} 分钟
                <template v-if="a.cost"> · ¥{{ a.cost }}</template>
                · 步行 {{ a.walking_m }} m
              </span>
            </div>
          </div>
          <div v-if="route.mode === 'transit' && curSteps.length" class="steps">
            <div v-for="(st, i) in curSteps" :key="i" class="step" :class="st.type">
              <span class="st-dot"><SIcon :name="stepIcon(st)" :size="12" /></span>
              <div class="st-mid">
                <span class="st-line">
                  <b v-if="st.type !== 'walk'">{{ st.kind }}</b>{{ st.line || st.label }}
                </span>
                <span v-if="st.type !== 'walk'" class="st-sub">
                  {{ st.from_stop }} 上车 → {{ st.to_stop }} 下车
                  <template v-if="st.via">· 经 {{ st.via }} 站</template>
                  <template v-if="st.start_time">· 运营 {{ st.start_time }}–{{ st.end_time }}</template>
                </span>
                <span v-if="st.duration_s" class="st-sub">
                  约 {{ Math.round(st.duration_s / 60) }} 分钟 ·
                  {{ (st.distance_m / 1000).toFixed(1) }} km
                </span>
              </div>
            </div>
            <div v-if="curAlt && curAlt.cost" class="st-cost">
              票价约 {{ curAlt.cost }} 元 · 全程步行 {{ curAlt.walking_m }} 米
            </div>
          </div>
          <template v-else>
            <div v-for="(l, i) in route.legs" :key="i" class="r-leg">
              {{ l.from }} → {{ l.to }}：{{ (l.distance_m / 1000).toFixed(1) }} km /
              {{ Math.round(l.duration_s / 60) }} 分钟
            </div>
          </template>
        </div>
        <div v-else-if="route?.error" class="bad">{{ route.error }}</div>
      </aside>

      <section class="map">
        <span class="map-tag"><SIcon name="map" :size="12" /> 地图</span>
        <img v-if="mapSrc && !mapError" :src="mapSrc" class="map-img" @error="mapError = true"
          alt="路线地图" />
        <div v-if="mapError" class="map-empty">地图暂不可用（可能超出配额），右侧路线数据仍然有效。</div>
        <div v-if="!mapSrc" class="map-empty">填好起点和终点，点「查询路线」就会把路线画在地图上。</div>
      </section>
      </div>
    </section>

    <div class="tools-grid">
      <section class="tool card">
        <div class="tool-head"><span class="tool-ic" style="color:#2577e3;background:#eaf3fe"><SIcon name="sun" :size="18" /></span><div class="tool-meta"><div class="tool-name">天气 · 选日期看预报</div></div></div>
        <div class="mini-row-in">
          <input v-model="city" class="ipt sm" placeholder="城市，如 杭州市" @keydown.enter="getWeather" />
          <input v-model="weatherDate" type="date" class="ipt sm" />
          <button class="mini-btn" :disabled="busy" @click="getWeather">查</button>
        </div>
        <div v-if="weather && !weather.error" class="mini-out">
          <template v-if="weather.daily">
            {{ weather.city }} {{ weatherDate }}：{{ weather.daily.temp_min }}~{{ weather.daily.temp_max }}℃ · 降水 {{ weather.daily.precipitation }}mm
          </template>
          <template v-else>
            {{ weather.city }}　当前 {{ weather.current?.temperature_2m }}℃　降水 {{ weather.current?.precipitation }}mm
          </template>
        </div>
        <div v-else-if="weather?.error" class="mini-out bad">{{ weather.error }}</div>
      </section>

      <section class="tool card">
        <div class="tool-head"><span class="tool-ic" style="color:#12a76a;background:#e8f7ee"><SIcon name="calc" :size="18" /></span><div class="tool-meta"><div class="tool-name">汇率 · 输入金额直接换算</div></div></div>
        <div class="mini-row-in">
          <select v-model="fxBase" class="ipt sm">
            <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
          </select>
          <button class="mini-btn" :disabled="busy" @click="getFx">查</button>
        </div>
        <div class="fx-calc">
          <input v-model.number="fxAmount" type="number" class="ipt sm" placeholder="金额" />
          <span class="fx-eq">{{ fxBase }} =</span>
          <span class="fx-out">{{ fxResult }}</span>
        </div>
        <div v-if="fx && !fx.error" class="fx-grid">
          <div v-for="(v, k) in fxTop" :key="k" class="fx-cell">
            <span class="fx-c">{{ k }}</span><span class="fx-v">{{ Number(v).toFixed(4) }}</span>
          </div>
        </div>
      </section>

      <section class="tool card">
        <div class="tool-head"><span class="tool-ic" style="color:#7a5af8;background:#f1edfe"><SIcon name="route" :size="18" /></span><div class="tool-meta"><div class="tool-name">行程核验 · 绕路与折返</div></div></div>
        <div class="mini-row-in">
          <input v-model="stops" class="ipt sm" placeholder="顿号分隔：机场、石林、古城"
            @keydown.enter="checkItinerary" />
          <button class="mini-btn" :disabled="busy" @click="checkItinerary">核验</button>
        </div>
        <div v-if="itin && !itin.error" class="itin-out">
          <div class="itin-ok" :class="itin.ok ? 'ok' : 'bad'">{{ itin.ok ? '路线可行' : '存在折返' }}</div>
          <div class="itin-sum">总 {{ (itin.total_distance_m / 1000).toFixed(1) }} km · {{ Math.round(itin.total_duration_s / 60) }} 分钟</div>
          <div v-if="itin.resolved?.length" class="itin-stops">{{ itin.resolved.join(' → ') }}</div>
          <div v-for="(s, i) in itin?.issues || []" :key="i" class="itin-issue">{{ s }}</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'

const MODES = [
  { key: 'driving', label: '驾车', icon: 'route' },
  { key: 'walking', label: '步行', icon: 'pin' },
  { key: 'bicycling', label: '骑行', icon: 'compass' },
  { key: 'transit', label: '公交', icon: 'layers' },
]
const CURRENCIES = ['CNY', 'USD', 'EUR', 'JPY', 'GBP', 'KRW', 'THB', 'SGD', 'HKD']

const mode = ref('driving')
const from = ref('杭州西湖')
const to = ref('萧山机场')
const waypoints = ref<string[]>([])
const route = ref<any>(null)
const mapSrc = ref('')
const mapError = ref(false)
const busy = ref(false)

const city = ref('杭州市')
const weatherDate = ref('')
const fxAmount = ref(100)
const stops = ref('')
const fxBase = ref('CNY')
const weather = ref<any>(null)
const fx = ref<any>(null)
const itin = ref<any>(null)

const fxResult = computed(() => {
  const rates = fx.value?.rates || {}
  const first = Object.entries(rates)[0]
  if (!first) return '—'
  return (Number(fxAmount.value || 0) * Number(first[1])).toFixed(2) + ' ' + first[0]
})
const fxTop = computed(() => {
  const r = fx.value?.rates || {}
  return Object.fromEntries(Object.entries(r).slice(0, 6))
})
const base = (client.defaults as any).baseURL || ''

const altIndex = ref(0)
const alts = computed<any[]>(() => (route.value?.extra?.alternatives || []))
const curAlt = computed<any>(() => alts.value[altIndex.value] || null)
const curSteps = computed<any[]>(() => curAlt.value?.steps || route.value?.extra?.steps || [])

const sug = ref<{ for: string; index: number; items: any[] }>({ for: '', index: -1, items: [] })
let tipTimer = 0
let tipSeq = 0

function tips(field: 'from' | 'to' | 'via', index = -1) {
  const val = field === 'from' ? from.value : field === 'to' ? to.value : (waypoints.value[index] || '')
  window.clearTimeout(tipTimer)
  tipSeq += 1
  const seq = tipSeq
  if (!val.trim()) { sug.value = { for: '', index: -1, items: [] }; return }
  tipTimer = window.setTimeout(async () => {
    try {
      const r = (await client.get('/tools/poi/tips', { params: { q: val.trim() } })).data
      if (seq !== tipSeq) return                    // 只认最后一次输入的结果
      sug.value = { for: field, index, items: r.tips || [] }
    } catch { sug.value = { for: '', index: -1, items: [] } }
  }, 280)
}

function pick(t: any, field: 'from' | 'to' | 'via', index = -1) {
  if (field === 'from') from.value = t.name
  else if (field === 'to') to.value = t.name
  else waypoints.value[index] = t.name
  sug.value = { for: '', index: -1, items: [] }
}

function stepIcon(st: any) {
  if (st.type === 'walk') return 'pin'
  if (st.kind === '地铁') return 'layers'
  if (st.kind === '铁路') return 'route'
  return 'compass'
}

function mapUrl() {
  const params = new URLSearchParams({ origin: from.value.trim(), destination: to.value.trim(),
    mode: mode.value, waypoints: waypoints.value.filter((w) => w.trim()).join(',') })
  return `${base}/tools/map?${params.toString()}`
}

async function query() {
  if (!from.value.trim() || !to.value.trim()) return
  busy.value = true
  route.value = null
  mapError.value = false
  try {
    const wps = waypoints.value.filter((w) => w.trim())
    const r = (await client.get('/tools/route', {
      params: { origin: from.value.trim(), destination: to.value.trim(), mode: mode.value,
                waypoints: wps.join(',') } })).data
    route.value = r
    altIndex.value = 0
    if (!r.error) mapSrc.value = mapUrl()      // 只有查成功才换图，避免错误参数把地图刷没
  } catch (e: any) {
    route.value = { error: e?.response?.data?.detail || '查询失败' }
  } finally { busy.value = false }
}

async function getWeather() {
  if (!city.value.trim()) return
  busy.value = true
  try { weather.value = (await client.get('/tools/weather', { params: { city: city.value.trim(), date: weatherDate.value || undefined } })).data }
  catch (e: any) { weather.value = { error: e?.response?.data?.detail || '查询失败' } }
  finally { busy.value = false }
}

async function getFx() {
  busy.value = true
  try { fx.value = (await client.get('/tools/fx', { params: { base: fxBase.value } })).data }
  catch (e: any) { fx.value = { error: e?.response?.data?.detail || '查询失败' } }
  finally { busy.value = false }
}

async function checkItinerary() {
  const list = stops.value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
  if (list.length < 2) { itin.value = { error: '至少写两个行程点' }; return }
  busy.value = true
  try { itin.value = (await client.post('/tools/itinerary/check', { stops: list })).data }
  catch (e: any) { itin.value = { error: e?.response?.data?.detail || '核验失败' } }
  finally { busy.value = false }
}

onMounted(() => { query() })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.tb { width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; max-width: 1320px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; box-shadow: $shadow-card; }

.tb-body { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 12px; align-items: start; margin-top: 12px; }
.panel { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.modes { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.mode { display: inline-flex; flex-direction: column; align-items: center; gap: 3px; font-size: 13.5px;
  border: 1px solid $color-border; background: #fff; border-radius: 8px; padding: 7px 0;
  color: $color-text-secondary; cursor: pointer; }
.mode.on { border-color: $color-primary; color: $color-primary; background: $color-primary-softer; font-weight: 600; }
.fld { display: flex; flex-direction: column; gap: 5px; }
.lb { font-size: 14px; color: $color-text-secondary; display: flex; align-items: center; gap: 5px; }
.pin { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.pin.from { background: #12a76a; }
.pin.via { background: #e08a1e; }
.pin.to { background: #e04b4b; }
.ipt { width: 100%; height: 34px; border: 1px solid $color-border; border-radius: 6px; padding: 0 10px;
  font-size: 15px; outline: none; }
.ipt:focus { border-color: $color-primary; }
.wp { display: flex; gap: 6px; align-items: center; }
.rm { border: none; background: none; color: $color-text-muted; cursor: pointer; }
.add { align-self: flex-start; display: inline-flex; align-items: center; gap: 4px; font-size: 14px;
  color: $color-primary; background: none; border: none; cursor: pointer; padding: 2px 0; }
.go { height: 36px; }
.result { border-top: 1px dashed $color-border; padding-top: 10px; display: flex; flex-direction: column; gap: 5px; }
.r-main { display: flex; align-items: baseline; gap: 8px; }
.r-km { font-size: 21px; font-weight: 800; color: $color-primary; }
.r-min { font-size: 14px; color: $color-text-secondary; }
.r-note { font-size: 13.5px; color: $color-warning; }
.r-leg { font-size: 14px; color: $color-text-secondary; }
.bad { color: $color-danger; font-size: 14px; }
.ok { color: $color-success; }

.ac-wrap { position: relative; }
.ac-list { position: absolute; left: 0; right: 0; top: 38px; z-index: 20; background: #fff;
  border: 1px solid $color-border; border-radius: 8px; box-shadow: 0 12px 30px rgba(16,32,56,0.14);
  max-height: 240px; overflow-y: auto; }
.ac-item { display: flex; flex-direction: column; gap: 2px; padding: 7px 10px; cursor: pointer; }
.ac-item:hover { background: $color-primary-softer; }
.ac-name { font-size: 15px; }
.ac-sub { font-size: 13px; color: $color-text-muted; }
.alts { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.alt { display: flex; flex-direction: column; gap: 3px;
  border: 1px solid $color-border; border-radius: 8px; padding: 7px 9px; cursor: pointer; }
.alt.on { border-color: $color-primary; background: $color-primary-softer; }
.alt-name { font-size: 16px; font-weight: 700; color: $color-primary; }
.alt-sum { font-size: 15px; color: $color-text-secondary; }
.alt-num { font-size: 13.5px; color: $color-text-muted; }
.steps { display: flex; flex-direction: column; gap: 8px; }
.step { display: flex; gap: 8px; align-items: flex-start; }
.st-dot { width: 22px; height: 22px; border-radius: 50%; background: $color-primary-soft; color: $color-primary;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.step.walk .st-dot { background: #f2f5f9; color: $color-text-muted; }
.st-mid { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.st-line { font-size: 16px; }
.st-sub { font-size: 13.5px; color: $color-text-muted; }
.st-cost { font-size: 14px; color: $color-primary; background: $color-primary-softer; border-radius: 6px;
  padding: 5px 8px; }
.map { position: relative; overflow: hidden; min-height: 340px; max-height: 400px; display: flex; align-items: center; justify-content: center; background: #eef3f9; }
.map-tag { position: absolute; top: 12px; left: 12px; z-index: 3; display: inline-flex; align-items: center; gap: 5px; font-size: 15px; font-weight: 600; color: #fff; background: rgba(37,119,227,.9); border-radius: 7px; padding: 4px 12px; box-shadow: 0 4px 12px rgba(37,119,227,.25); }
.map-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.map-empty { font-size: 15px; color: $color-text-muted; padding: 40px; text-align: center; }

.tools-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
.tool { padding: 16px 18px; transition: transform .22s cubic-bezier(.34,1.56,.64,1), box-shadow .22s ease; animation: tc-rise .6s ease both; }
.tools-grid .tool:nth-child(2) { animation-delay: .08s; }
.tools-grid .tool:nth-child(3) { animation-delay: .16s; }
.tool:hover { transform: translateY(-3px); box-shadow: $shadow-hover; }
.tool-head { display: flex; align-items: center; gap: 11px; margin-bottom: 12px; }
.tool-meta { display: flex; flex-direction: column; gap: 2px; }
.tool-name { font-size: 19px; font-weight: 800; }
.tool-ic { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.mini-row-in { display: flex; gap: 6px; }
.ipt.sm { height: 34px; font-size: 15.5px; }
.mini-btn { white-space: nowrap; flex-shrink: 0; border: 1px solid $color-border; background: #fff; border-radius: 6px; padding: 0 12px;
  font-size: 14px; color: $color-primary; cursor: pointer; }
.mini-out { margin-top: 8px; font-size: 16px; color: $color-text-secondary; }
.fx-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 8px; }
.fx-cell { display: flex; justify-content: space-between; font-size: 14px; color: $color-text-secondary;
  background: $color-primary-softer; border-radius: 6px; padding: 4px 8px; }
.fx-c { color: $color-text-muted; }

@media (max-width: 1180px) {
  .tb-body { grid-template-columns: 1fr; }
  .mini-row { grid-template-columns: 1fr; }
}
.fx-calc { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.fx-eq { font-size: 14px; color: $color-text-muted; white-space: nowrap; }
.fx-out { font-size: 16px; font-weight: 800; color: $color-primary; }
.itin-out { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.itin-ok { font-size: 16.5px; font-weight: 800; }
.itin-ok.ok { color: #12a76a; }
.itin-ok.bad { color: #e04b4b; }
.itin-sum { font-size: 15px; color: $color-text-secondary; }
.itin-stops { font-size: 13.5px; color: $color-text-muted; line-height: 1.6; }
.itin-issue { font-size: 14px; color: #e04b4b; }
</style>
