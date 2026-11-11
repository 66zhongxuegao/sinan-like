/**
 * 订单详情「六阶段文档入口」的纯逻辑（R01）。
 *
 * 只做三件事，且都不依赖组件实例，便于用真实接口数据直接回归：
 *   1) orderStagesForDisplay —— 当前阶段置顶，其余按契约 order 排列
 *   2) countDocs / countDelivered —— 交付物总数与已投递数（口径：只有 submitted 才算已投递）
 *   3) currentStageDocCode —— 当前阶段的定位交付物 code（「填写当前阶段文档」按阶段定位）
 *   4) workbenchRoute —— 产出与投递路径，带交付物 code
 *
 * 阶段与文档字段全部来自 `GET /practice/orders/{id}/journey`（口径来源 tripcraft/contracts/stages.py），
 * 本模块**不**内置阶段表、不写死任何 phase id 或 deliverable code。
 */

export interface DocItem {
  code: string
  title: string
  submitted: boolean
  version: number
}

export interface StageLike {
  id: string
  order: number
  state?: string
  deliverables?: DocItem[]
}

/** 当前阶段置顶；当前阶段为空（订单已完成 / 未加载）时按 order 升序 */
export function orderStagesForDisplay<T extends StageLike>(stages: T[], currentStageId: string): T[] {
  const list = [...(stages || [])]
  list.sort((a, b) => {
    const ac = a.id === currentStageId ? 0 : 1
    const bc = b.id === currentStageId ? 0 : 1
    if (ac !== bc) return ac - bc
    return a.order - b.order
  })
  return list
}

export function countDocs(stages: StageLike[]): number {
  return (stages || []).reduce((n, s) => n + (s.deliverables || []).length, 0)
}

export function countDelivered(stages: StageLike[]): number {
  return (stages || []).reduce(
    (n, s) => n + (s.deliverables || []).filter((d) => d.submitted).length,
    0,
  )
}

/**
 * 当前阶段的「定位交付物」：先取该阶段第一份未投递的文档，全投完则取第一份。
 * 用于「去产出与投递」按阶段定位；阶段没有文档（如行中服务）时返回空串，
 * 由调用方退回不带 code 的工作台首页。
 */
export function currentStageDocCode(stage: StageLike | null | undefined): string {
  const docs = stage?.deliverables || []
  if (!docs.length) return ''
  const pending = docs.find((d) => !d.submitted)
  return (pending || docs[0]).code
}

/** `/practice/orders/{id}/deliverables?code={code}`；code 为空时不带查询串 */
export function workbenchRoute(orderId: string, code = ''): string {
  const base = `/practice/orders/${orderId}/deliverables`
  return code ? `${base}?code=${code}` : base
}
