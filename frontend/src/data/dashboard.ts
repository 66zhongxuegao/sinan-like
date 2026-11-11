/**
 * 数据看板 · 聚合指标与埋点口径
 *
 * 当前为纯前端演示数据：页面所有数字都从本文件派生，接入真实数据时
 * 只需要把下面的聚合结果替换为接口返回值，组件与视觉不用改。
 *
 * 埋点事件约定（后端/前端上报同名事件即可复算全部指标）：
 *   app.open            — 打开应用（会话级）
 *   learn.sp_open       — 进入技能点
 *   learn.sp_done       — 完成技能点
 *   practice.enter      — 进入实战
 *   practice.submit     — 提交方案
 *   score.published     — 评分发布
 *   score.appeal        — 评分申诉
 *   feedback.thumb_down — 点踩
 *   ai.question_review  — AI 出题专家复核
 *   ai.score_pair       — AI / 专家评分对照
 */

export type Tone = 'blue' | 'cyan' | 'amber' | 'rose' | 'violet'

export interface KpiItem {
  id: string
  label: string
  value: number
  decimals?: number
  unit?: string
  delta: number
  deltaUnit: 'pct' | 'pt' | 'count'
  note: string
  series: number[]
  color: string
}

export interface TrendSeries {
  name: string
  color: string
  data: number[]
  axis?: 'left' | 'right'
  dashed?: boolean
}

export interface RadarAxis {
  label: string
  team: number
  base: number
}

export interface FunnelStep {
  label: string
  short: string
  value: number
  color: string
}

export interface MemberRow {
  name: string
  avatar: string
  progress: number
  score: number
  active: string
  state: 'top' | 'steady' | 'watch' | 'risk'
}

export interface FeedItem {
  time: string
  actor: string
  text: string
  tag: string
  tone: Tone
}

export interface DonutItem {
  label: string
  value: number
  color: string
}

export interface QualityRow {
  label: string
  value: number
  target: number
  note: string
}

export interface RiskRow {
  label: string
  count: number
  level: 'high' | 'mid' | 'low'
  note: string
}

export interface MetricSpec {
  metric: string
  formula: string
  events: string
}

/* ────────────────────────── 团队看板 ────────────────────────── */

export const teamKpis: KpiItem[] = [
  {
    id: 'dau', label: '今日活跃学员', value: 32, unit: '/ 48', delta: 12.5, deltaUnit: 'pct',
    note: '较上周同期', color: '#2f7fe8',
    series: [21, 24, 22, 27, 26, 29, 32],
  },
  {
    id: 'completion', label: '训练完成率', value: 77.6, decimals: 1, unit: '%', delta: 6.4, deltaUnit: 'pt',
    note: '周环比提升', color: '#10a99a',
    series: [68, 71, 69, 73, 74, 76, 77.6],
  },
  {
    id: 'score', label: '平均能力评分', value: 82.4, decimals: 1, delta: 2.6, deltaUnit: 'pt',
    note: '满分 100 分', color: '#e89a2b',
    series: [78.2, 79.1, 78.8, 80.2, 81.1, 81.9, 82.4],
  },
  {
    id: 'qualified', label: '达标学员', value: 33, unit: '人', delta: 4.2, deltaUnit: 'pt',
    note: '达标率 68.8%', color: '#7c6ad6',
    series: [26, 27, 29, 28, 31, 32, 33],
  },
]

export const teamTrendLabels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export const teamTrendSeries: TrendSeries[] = [
  { name: '训练发起', color: '#2f7fe8', data: [21, 24, 19, 28, 26, 18, 20] },
  { name: '训练完成', color: '#10a99a', data: [15, 18, 14, 21, 20, 15, 18] },
]

export const teamRadar: RadarAxis[] = [
  { label: '需求洞察', team: 88, base: 79 },
  { label: '行程设计', team: 84, base: 77 },
  { label: '资源整合', team: 76, base: 73 },
  { label: '报价控制', team: 81, base: 74 },
  { label: '沟通转化', team: 90, base: 81 },
  { label: '风险合规', team: 75, base: 76 },
]

export const teamFunnel: FunnelStep[] = [
  { label: '进入学习', short: '进入学习', value: 48, color: '#2f7fe8' },
  { label: '完成技能点', short: '技能点', value: 44, color: '#4a86e8' },
  { label: '进入实战', short: '进入实战', value: 39, color: '#10a99a' },
  { label: '提交方案', short: '提交方案', value: 35, color: '#e89a2b' },
  { label: '评分达标', short: '评分达标', value: 33, color: '#7c6ad6' },
]

export const teamMembers: MemberRow[] = [
  { name: '林知夏', avatar: '林', progress: 92, score: 91, active: '12 分钟前', state: 'top' },
  { name: '陈牧野', avatar: '陈', progress: 86, score: 88, active: '2 小时前', state: 'steady' },
  { name: '苏晚晴', avatar: '苏', progress: 74, score: 84, active: '昨天', state: 'steady' },
  { name: '周予安', avatar: '周', progress: 61, score: 79, active: '2 天前', state: 'watch' },
  { name: '何星河', avatar: '何', progress: 48, score: 72, active: '4 天前', state: 'risk' },
  { name: '许清和', avatar: '许', progress: 37, score: 68, active: '6 天前', state: 'risk' },
]

export const teamRisks: RiskRow[] = [
  { label: '连续 3 天未训练', count: 6, level: 'high', note: '流失风险' },
  { label: '报价控制低于 60 分', count: 4, level: 'mid', note: '能力短板' },
  { label: '方案提交超时', count: 2, level: 'low', note: '流程阻塞' },
]

export const teamFeed: FeedItem[] = [
  { time: '10:42', actor: '林知夏', text: '提交「日本关西亲子 7 日」方案', tag: '方案提交', tone: 'blue' },
  { time: '10:36', actor: '陈牧野', text: '能力评分 88 分，进入达标区间', tag: '评分达标', tone: 'cyan' },
  { time: '10:18', actor: '教研组', text: 'AI 出题抽检 12 道，通过 11 道', tag: '题目抽检', tone: 'violet' },
  { time: '09:52', actor: '苏晚晴', text: '完成「多国签证风险」技能点', tag: '技能完成', tone: 'cyan' },
  { time: '09:31', actor: '系统', text: '何星河连续 3 天未活跃，触发预警', tag: '流失预警', tone: 'rose' },
]

/* ────────────────────────── 运营看板 ────────────────────────── */

export const opsKpis: KpiItem[] = [
  {
    id: 'users', label: '累计注册学员', value: 2846, delta: 318, deltaUnit: 'count',
    note: '本月新增', color: '#2f7fe8',
    series: [2410, 2502, 2588, 2661, 2735, 2790, 2846],
  },
  {
    id: 'dau', label: '今日活跃', value: 1032, delta: 8.6, deltaUnit: 'pct',
    note: '日活 / 周活 49.0%', color: '#10a99a',
    series: [742, 786, 834, 845, 903, 947, 994, 1032],
  },
  {
    id: 'retention', label: '次日留存', value: 61.2, decimals: 1, unit: '%', delta: 3.1, deltaUnit: 'pt',
    note: '7 日留存 42.8%', color: '#e89a2b',
    series: [54.2, 55.1, 56.8, 57.4, 58.9, 59.6, 61.2],
  },
  {
    id: 'completion', label: '训练完成率', value: 74.3, decimals: 1, unit: '%', delta: 5.2, deltaUnit: 'pt',
    note: '本月 18,420 人次', color: '#7c6ad6',
    series: [66, 68, 67, 70, 71, 72, 74.3],
  },
  {
    id: 'qualified', label: '能力达标率', value: 63.5, decimals: 1, unit: '%', delta: 2.4, deltaUnit: 'pt',
    note: '目标 60%', color: '#e05a78',
    series: [58.2, 59.4, 60.1, 61.3, 61.8, 62.6, 63.5],
  },
]

export const opsTrendLabels = [
  '10/05', '10/06', '10/07', '10/08', '10/09', '10/10', '10/11',
  '10/12', '10/13', '10/14', '10/15', '10/16', '10/17', '10/18',
]

export const opsTrendSeries: TrendSeries[] = [
  { name: '活跃学员', color: '#2f7fe8', data: [742, 768, 801, 786, 834, 862, 845, 890, 921, 903, 947, 968, 994, 1032] },
  { name: '新增学员', color: '#10a99a', axis: 'right', data: [18, 22, 24, 19, 21, 26, 23, 20, 25, 22, 27, 24, 21, 26] },
]

export const opsFunnel: FunnelStep[] = [
  { label: '注册学员', short: '注册', value: 2846, color: '#2f7fe8' },
  { label: '完成激活', short: '激活', value: 2412, color: '#4a86e8' },
  { label: '首次实战', short: '首战', value: 1985, color: '#10a99a' },
  { label: '提交方案', short: '提交', value: 1612, color: '#e89a2b' },
  { label: '评分达标', short: '达标', value: 1088, color: '#7c6ad6' },
  { label: '复训进阶', short: '复训', value: 742, color: '#e05a78' },
]

export const retentionCurve = [
  { label: 'D1', value: 61.2 },
  { label: 'D3', value: 52.4 },
  { label: 'D7', value: 42.8 },
  { label: 'D14', value: 34.1 },
  { label: 'D30', value: 28.5 },
]

export const scoreBands = [
  { label: '<60', value: 228, pct: 8, color: '#e05a78' },
  { label: '60-69', value: 541, pct: 19, color: '#e89a2b' },
  { label: '70-79', value: 882, pct: 31, color: '#2f7fe8' },
  { label: '80-89', value: 797, pct: 28, color: '#10a99a' },
  { label: '90+', value: 398, pct: 14, color: '#7c6ad6' },
]

export const channelMix: DonutItem[] = [
  { label: '院校合作', value: 1195, color: '#2f7fe8' },
  { label: '社会招募', value: 769, color: '#10a99a' },
  { label: '行业协会', value: 512, color: '#e89a2b' },
  { label: '内部转介', value: 370, color: '#7c6ad6' },
]

export const heatDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
export const heatHours = ['08', '09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19']

export const heatValues: number[][] = [
  [18, 26, 42, 55, 38, 22, 34, 58, 66, 52, 40, 24],
  [22, 30, 48, 61, 44, 26, 38, 63, 72, 58, 45, 28],
  [20, 34, 52, 68, 50, 30, 42, 70, 78, 62, 48, 32],
  [24, 38, 56, 72, 54, 34, 46, 74, 82, 66, 52, 36],
  [28, 42, 62, 78, 60, 38, 50, 80, 88, 72, 58, 40],
  [14, 20, 32, 44, 52, 58, 62, 66, 60, 48, 34, 20],
  [12, 18, 28, 38, 46, 52, 56, 58, 52, 42, 30, 18],
]

export const qualityRows: QualityRow[] = [
  { label: 'AI 出题合格率', value: 91.4, target: 90, note: '专家盲评通过' },
  { label: '人机评分一致率', value: 84.2, target: 80, note: '±1 分口径' },
  { label: '高优错误闭环率', value: 92.1, target: 90, note: '7 日内修复' },
  { label: '回归集通过率', value: 96.8, target: 95, note: '版本门禁' },
  { label: '专家盲评覆盖率', value: 88.6, target: 85, note: '双人独立评审' },
]

export const opsRisks: RiskRow[] = [
  { label: '高流失风险', count: 37, level: 'high', note: '7 天未活跃且进度 < 40%' },
  { label: '连续低分', count: 23, level: 'mid', note: '连续 2 次低于 60 分' },
  { label: '方案提交超时', count: 15, level: 'low', note: '超过 72 小时未提交' },
  { label: '评分申诉待处理', count: 12, level: 'low', note: '含 2 条红线申诉' },
]

export const opsFeed: FeedItem[] = [
  { time: '10:44', actor: '平台', text: '今日活跃突破 1,000，日活 / 周活达 49.0%', tag: '活跃里程碑', tone: 'cyan' },
  { time: '10:39', actor: '华东组', text: '24 名学员完成本周训练任务', tag: '团队完成', tone: 'blue' },
  { time: '10:21', actor: '质控组', text: '处理评分申诉 1 条，维持原判', tag: '申诉处理', tone: 'violet' },
  { time: '10:05', actor: '系统', text: 'AI 评分与专家评分对照 86 份，一致率 84.2%', tag: '评分校准', tone: 'cyan' },
  { time: '09:48', actor: '系统', text: '识别高流失风险学员 37 人，已推送运营', tag: '风险预警', tone: 'rose' },
]

/* ────────────────────────── 口径说明 ────────────────────────── */

export const metricSpecs: MetricSpec[] = [
  { metric: '今日活跃学员（DAU）', formula: '当日产生任一学习 / 实战事件的去重学员数', events: 'app.open · learn.sp_open · practice.enter' },
  { metric: '训练完成率', formula: '完成训练人次 ÷ 发起训练人次', events: 'practice.submit ÷ learn.sp_open' },
  { metric: '平均能力评分', formula: '当期已发布评分的算术平均值（满分 100）', events: 'score.published' },
  { metric: '能力达标率', formula: '平均能力评分 ≥ 80 分的学员数 ÷ 有评分学员数', events: 'score.published' },
  { metric: '次日 / 7 日留存', formula: '注册后第 1 / 7 天再次产生活跃事件的学员占比', events: 'app.open（按注册日期分群）' },
  { metric: '核心转化漏斗', formula: '注册 → 激活 → 首次实战 → 提交方案 → 评分达标 → 复训', events: 'practice.enter · practice.submit · score.published' },
  { metric: 'AI 出题合格率', formula: '专家判定合格的 AI 题目数 ÷ 抽检题目数', events: 'ai.question_review' },
  { metric: '人机评分一致率', formula: 'AI 与专家评分绝对一致或相差 1 分以内的样本占比', events: 'ai.score_pair' },
  { metric: '高优错误闭环率', formula: '7 日内完成修复并通过回归的高优错误数 ÷ 确认高优错误数', events: 'feedback.thumb_down · score.appeal' },
  { metric: '学习时段热力', formula: '按星期 × 小时聚合的活跃事件次数', events: 'app.open · practice.enter' },
]