<template>
  <div class="bridge-page">
    <header class="bh">
      <div class="bh-l">
        <button class="back" @click="back">学习地图</button>
        <h1>文化桥 · 十大客源国共通点</h1>
      </div>
      <p class="bh-sub">先找到我们和客人的共通点，再谈差异。沟通、餐食、行程节奏都能从这里找切入角度。</p>
    </header>

    <div class="body">
      <aside class="list">
        <button v-for="b in list" :key="b.code" class="item" :class="{ on: b.code === current }"
                @click="open(b.code)">
          <span class="dot" />
          <span class="nm">{{ b.name }}</span>
          <span class="ct">{{ b.point_count }} 个共通点</span>
        </button>
      </aside>

      <section v-if="detail" class="detail">
        <div class="dh">
          <h2>{{ detail.name }}</h2>
          <span class="lang">{{ detail.language }}</span>
        </div>
        <p class="sum">{{ detail.summary }}</p>

        <div class="pts">
          <article v-for="(p, i) in detail.points" :key="i" class="pt">
            <div class="pt-h"><span class="idx">{{ i + 1 }}</span>{{ p.point }}</div>
            <div class="cmp">
              <div class="side cn"><b>中国这边</b>{{ p.china }}</div>
              <div class="side them"><b>{{ detail.country }}这边</b>{{ p.theirs }}</div>
            </div>
            <div class="use"><b>怎么用</b>{{ p.use }}</div>
          </article>
        </div>

        <div v-if="detail.pitfalls && detail.pitfalls.length" class="pits">
          <b>容易踩的坑</b>
          <ul><li v-for="(x, i) in detail.pitfalls" :key="i">{{ x }}</li></ul>
        </div>
      </section>

      <section v-else class="empty">选择左侧的任意一座文化桥。</section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '@/api/client'

interface Point { point: string; china: string; theirs: string; use: string }
interface Bridge { code: string; name: string; country: string; language: string;
  summary: string; points: Point[]; pitfalls: string[]; point_count: number }

const route = useRoute()
const router = useRouter()
const list = ref<Bridge[]>([])
const detail = ref<Bridge | null>(null)
const current = ref('')

async function open(code: string) {
  current.value = code
  try {
    detail.value = (await client.get(`/learn/culture-bridges/${code}`)).data
    router.replace(`/learn/bridge/${code}`)
  } catch { detail.value = null }
}

function back() { router.push('/learn') }

onMounted(async () => {
  try {
    list.value = (await client.get('/learn/culture-bridges')).data
    const code = String(route.params.code || '') || list.value[0]?.code || ''
    if (code) await open(code)
  } catch { list.value = [] }
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.bridge-page { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.bh { padding: 20px 28px 12px; }
.bh-l { display: flex; align-items: center; gap: 14px; }
.back { border: 1px solid #d8e2f0; background: #fff; border-radius: 10px; padding: 6px 14px;
  font-size: 14px; color: $color-text-secondary; cursor: pointer; }
.back:hover { border-color: #2577e3; color: #2577e3; }
h1 { font-size: 22px; margin: 0; }
.bh-sub { margin: 10px 0 0; font-size: 14px; color: $color-text-secondary; }
.body { flex: 1; display: flex; gap: 18px; padding: 0 28px 24px; overflow: hidden; }
.list { width: 232px; flex: none; overflow: auto; display: flex; flex-direction: column; gap: 8px; }
.item { display: flex; align-items: center; gap: 8px; text-align: left; cursor: pointer;
  border: 1px solid #e4ebf5; background: #fff; border-radius: 12px; padding: 10px 12px; }
.item:hover { border-color: #b9d3f5; }
.item.on { border-color: #2577e3; background: #f2f7ff; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #0ea5b7; flex: none; }
.nm { font-size: 14px; font-weight: 600; }
.ct { margin-left: auto; font-size: 12px; color: $color-text-secondary; }
.detail { flex: 1; overflow: auto; background: #fff; border: 1px solid #e4ebf5; border-radius: 16px; padding: 22px 26px; }
.dh { display: flex; align-items: baseline; gap: 12px; }
.dh h2 { margin: 0; font-size: 20px; }
.lang { font-size: 12px; color: #0ea5b7; background: #e9f8fa; border-radius: 999px; padding: 2px 10px; }
.sum { margin: 10px 0 18px; font-size: 15px; color: #33475f; line-height: 1.7; }
.pts { display: flex; flex-direction: column; gap: 14px; }
.pt { border: 1px solid #e8eef7; border-radius: 12px; padding: 14px 16px; }
.pt-h { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px; }
.idx { width: 22px; height: 22px; border-radius: 50%; background: #eef4ff; color: #2577e3;
  font-size: 12px; display: inline-flex; align-items: center; justify-content: center; }
.cmp { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0; }
.side { font-size: 13.5px; line-height: 1.65; border-radius: 10px; padding: 10px 12px; }
.side b { display: block; font-size: 12px; margin-bottom: 4px; }
.cn { background: #f6f9ff; color: #2c4a6b; } .cn b { color: #2577e3; }
.them { background: #f4fbf7; color: #2c5a44; } .them b { color: #12a76a; }
.use { font-size: 13.5px; background: #fff8ec; color: #6b4a12; border-radius: 10px; padding: 10px 12px; line-height: 1.65; }
.use b { display: block; font-size: 12px; color: #c77700; margin-bottom: 4px; }
.pits { margin-top: 18px; font-size: 13.5px; color: #8a4b3f; background: #fdf4f2; border-radius: 12px; padding: 12px 16px; }
.pits b { display: block; margin-bottom: 6px; }
.pits ul { margin: 0; padding-left: 18px; } .pits li { line-height: 1.7; }
.empty { flex: 1; display: flex; align-items: center; justify-content: center; color: $color-text-secondary; }
</style>