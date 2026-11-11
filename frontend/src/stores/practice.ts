import { defineStore } from 'pinia'
import { ref } from 'vue'

const ACTIVE_ORDER_KEY = 'tc-active-order'

function readActiveOrder(): string {
  try { return sessionStorage.getItem(ACTIVE_ORDER_KEY) || '' } catch { return '' }
}

/** 实战模块的当前订单（供右下角进度条跨页面显示"这是哪个单"） */
export const usePracticeStore = defineStore('practice', () => {
  const activeOrderId = ref(readActiveOrder())
  function setActiveOrder(id: string) {
    if (!id || id === activeOrderId.value) return
    activeOrderId.value = id
    try { sessionStorage.setItem(ACTIVE_ORDER_KEY, id) } catch { /* 无痕模式忽略 */ }
  }
  return { activeOrderId, setActiveOrder }
})