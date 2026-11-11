<template>
  <div class="entry">
    <div class="orders">
      <div v-for="o in ORDERS" :key="o.order_id" class="order card" @click="open(o)">
        <div class="o-top">
          <span class="o-id">{{ o.order_id }}</span>
          <span class="o-cust">{{ o.customer }} · {{ o.destination }}</span>
          <span class="o-tag" :class="o.status === '正常' ? 'ok' : 'bad'">{{ o.status }}</span>
        </div>
        <div class="o-foot">
          <span class="stage">{{ o.stage_name }}</span>
          <span class="go">查看评分 <SIcon name="right" :size="12" /></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import { onMounted, ref } from 'vue'
import client from '@/api/client'

const router = useRouter()
const ORDERS = ref<any[]>([])
function open(o: any) { router.push(`/practice/orders/${o.order_id}/score`) }
onMounted(async () => {
  try { ORDERS.value = (await client.get('/practice/orders')).data } catch { ORDERS.value = [] }
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.entry { width: 100%; max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.orders { display: flex; flex-direction: column; gap: 10px; }
.order { padding: 15px 18px; cursor: pointer; transition: all .16s ease; }
.order:hover { border-color: $color-primary; box-shadow: $shadow-hover; transform: translateY(-2px); }
.o-top { display: flex; align-items: center; gap: 12px; }
.o-id { font-family: ui-monospace, monospace; font-size: 15px; color: #e04b4b; font-weight: 600; }
.o-cust { font-size: 15.5px; font-weight: 600; }
.o-tag { margin-left: auto; font-size: 14px; padding: 2px 9px; border-radius: 4px; }
.o-tag.ok { background: #e8f7ee; color: #12a76a; }
.o-tag.bad { background: #fdeceb; color: #e04b4b; }
.o-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
.stage { font-size: 14px; color: $color-text-secondary; }
.go { display: inline-flex; align-items: center; gap: 3px; font-size: 14px; color: $color-primary; }
</style>