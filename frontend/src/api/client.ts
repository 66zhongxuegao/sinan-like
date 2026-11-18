import axios from 'axios'

const client = axios.create({ baseURL: '/api', timeout: 300000 })

/**
 * 同一时刻的相同 GET 请求合并成一次（只合并「正在进行中」的请求，不做缓存，数据不会变旧）。
 * 典型场景：订单页本身和右下角/顶栏的流程进度组件同时请求
 * /practice/orders/{id}/journey、/gates；公网经隧道访问时每多一次请求就多一轮约 200ms 往返。
 */
const inflight = new Map<string, Promise<any>>()
const rawGet = client.get.bind(client)
client.get = ((url: string, config?: any) => {
  // 带取消信号或特殊响应类型的请求不合并，保持原样
  if (config?.signal || config?.responseType) return rawGet(url, config)
  const key = url + (config?.params ? '?' + JSON.stringify(config.params) : '')
  const hit = inflight.get(key)
  if (hit) return hit
  const p = rawGet(url, config).finally(() => inflight.delete(key))
  inflight.set(key, p)
  return p
}) as typeof client.get

export default client
