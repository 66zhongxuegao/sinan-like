/* 标准案例的人工操作路径（逐步说明）——**说明，不是自动播放剧本**。

 * 【为什么重写】旧 frontend/src/demo/beats.ts 是一份自动播放剧本：每一步用
 * `d.clickText(['画像'], { optional: true })` 这种 optional 调用，元素找不到就 `return false`，
 * 调用点不看返回值继续走下一步（driver.ts 里 `if (!opt?.optional) console.warn(...)` 只打印警告）。
 * 结果是演示看着"走完了"，实际什么都没点到 —— 失败被静默跳过，属于伪造链路，已删除。

 * 新方案的边界：
 *   1. 这里**没有**执行函数，不做 DOM 自动点击；页面按这份清单渲染逐步说明。
 *   2. 每一步都标注 `page`（在哪个真实页面操作）与 `server`（该步的服务端证据来自哪个真实接口）。
 *   3. 阶段清单只来自后端 `GET /scenario/cases` 的 `stage_plan.substeps`；
 *      `STAGE_ENTRY` 只是「契约阶段 id → 入口页面」的映射，**不是**第二套阶段定义。
 *   4. 后端出现 STAGE_ENTRY 里没有的阶段 id 时**不静默兜底**：`buildGuide` 把它列进
 *      `missingStageIds`，页面显示可见错误（对照 tripcraft/contracts/stages.py 核对）。
 *   5. 步骤是否完成不在这里判断：只显示后端 gate 的结果（ok / 待完成原因原样透出）。
 */

import type { OrderState, StageEntry } from './scenarioApi'

export interface GuideEntry {
  /** 稳定 id：直接沿用后端子步骤 id，便于和 gate.checks 对照。 */
  id: string
  stageId: string
  step: string
  title: string
  hint: string
  /** 该步要在哪个真实页面/入口完成（产品页面，不是本页）。 */
  page: string
  route: string
  /** 服务端状态来源（真实接口路径）。 */
  server: string
  deliverable: string
}

/**
 * 阶段入口映射。key 只允许用冻结契约 tripcraft/contracts/stages.py v1 的六个阶段 id：
 *   pre1_requirement / pre2_plan / pre3_quote / pre4_notice / on_trip / post_trip
 * 这里只登记「用户去哪个真实页面做这一步」，不复制阶段名与步骤（那些都来自后端 stage_plan）。
 */
export const STAGE_ENTRY: Record<string, { page: string; route: string }> = {
  pre1_requirement: { page: '消息中心（接单）→ 订单管理打开该单发起首呼', route: '/practice/messages' },
  pre2_plan: { page: '订单管理 → 打开该单 → 产出与投递（行程方案）', route: '/practice/orders' },
  pre3_quote: { page: '订单管理 → 打开该单 → 产出与投递（报价与合同）', route: '/practice/orders' },
  pre4_notice: { page: '订单管理 → 打开该单 → 产出与投递（出团通知书）', route: '/practice/orders' },
  on_trip: { page: '订单管理 → 打开该单 → 产出与投递 / 聊天界面', route: '/practice/im' },
  post_trip: { page: '订单管理 → 打开该单 → 成本与结算 / 订单评分复盘；画像在学情画像', route: '/practice/orders' },
}

export interface GuideBuild {
  entries: GuideEntry[]
  /** 后端返回了 STAGE_ENTRY 未登记的阶段 id：页面必须显式报错，不许拿默认文案冒充。 */
  missingStageIds: string[]
}

/**
 * 由后端 stage_plan 组装逐步说明。
 * 不使用任何本地兜底清单：stage_plan 为空就直接返回空数组，由页面报错。
 *
 * 注意（诚实边界）：后端的 gate.checks 用**中文标签**（如 `deliverable:需求确认单`），
 * 而 stage_plan 里交付物是**英文 id**（如 `requirement_sheet`），两者没有可靠的对应关系，
 * 因此这里不做「第几步 = 哪条 gate check」的猜测；每步的服务端判定统一由订单状态表原样展示。
 */
export function buildGuide(stagePlan: StageEntry[], order: OrderState | null): GuideBuild {
  const hasOrder = !!order
  const entries: GuideEntry[] = []
  const missingStageIds: string[] = []
  for (const stage of stagePlan || []) {
    const entry = STAGE_ENTRY[stage.id]
    if (!entry) {
      // 不静默兜底：记下来让页面报错
      missingStageIds.push(stage.id)
      continue
    }
    for (const sub of stage.substeps || []) {
      entries.push({
        id: sub.id,
        stageId: stage.id,
        step: sub.step,
        title: `${stage.name} · ${sub.name}`,
        hint: sub.hint,
        page: entry.page,
        route: entry.route,
        server: hasOrder
          ? `scenario/orders/{id}/state · stage=${stage.id} · step=${sub.step}`
          : `（未选订单）scenario/orders/{id}/state · stage=${stage.id} · step=${sub.step}`,
        deliverable: sub.deliverable,
      })
    }
  }
  return { entries, missingStageIds }
}

/** 当前订单的服务端逐步状态：直接透出后端 gate，不在前端做二次推断。 */
export function gateRows(order: OrderState | null): Array<{
  action: string
  label: string
  where: string
  ok: boolean
  reason: string
}> {
  const checks = order?.gate?.checks || []
  return checks.map((c) => ({
    action: c.action,
    label: c.label,
    where: c.where,
    ok: !!c.ok,
    reason: c.reason,
  }))
}
