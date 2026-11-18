import { onBeforeUnmount, ref } from 'vue'

/** 与全局样式一致的窄屏断点：≤900px 走移动端应用壳。 */
export const MOBILE_QUERY = '(max-width: 900px)'

/** 响应式判断当前是否为移动端视口（随窗口尺寸/旋转实时更新）。 */
export function useIsMobile() {
  const mq = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(MOBILE_QUERY) : null
  const isMobile = ref(!!mq?.matches)
  const onChange = (e: MediaQueryListEvent) => { isMobile.value = e.matches }
  mq?.addEventListener?.('change', onChange)
  onBeforeUnmount(() => mq?.removeEventListener?.('change', onChange))
  return isMobile
}
