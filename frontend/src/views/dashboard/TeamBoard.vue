<template>
  <div class="board">
    <div class="db-kpis">
      <article v-for="(k, i) in teamKpis" :key="k.id" class="db-card db-kpi" :class="{ accent: i === 0 }" :style="{ '--i': i }">
        <div class="db-kpi-top">
          <span class="db-kpi-label">{{ k.label }}</span>
          <span class="db-delta" :class="k.delta >= 0 ? 'up' : 'down'">{{ deltaText(k.delta, k.deltaUnit) }}</span>
        </div>
        <div class="db-kpi-val">
          <DCount :value="k.value" :decimals="k.decimals ?? 0" />
          <span class="db-kpi-unit">{{ k.unit }}</span>
        </div>
        <div class="db-kpi-foot">
          <span class="db-kpi-hint">{{ k.note }}</span>
          <DSpark :data="k.series" :color="i === 0 ? '#ffffff' : k.color" />
        </div>
      </article>
    </div>

    <div class="db-grid">
      <article class="db-card span-7" :style="{ '--i': 0 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">训练趋势</h3>
            <p class="db-card-sub">训练发起 vs 完成 · 近 7 天</p>
          </div>
          <div class="db-legend">
            <span class="db-legend-item"><i style="background: #5b9dff" />训练发起</span>
            <span class="db-legend-item"><i style="background: #2fe3c8" />训练完成</span>
          </div>
        </div>
        <DTrend :labels="teamTrendLabels" :series="teamTrendSeries" />
        <div class="db-stat-strip">
          <div><span>7 日发起</span><b>156</b></div>
          <div><span>7 日完成</span><b>121</b></div>
          <div><span>完成率</span><b>77.6%</b></div>
        </div>
        <div class="db-insight">
          <SIcon name="sparkle" :size="14" />
          <span>周四为训练高峰，<b>28 人次发起</b>；周末完成率回升至 90%，建议把复盘任务放到周一。</span>
        </div>
      </article>

      <article class="db-card span-5" :style="{ '--i': 1 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">团队能力雷达</h3>
            <p class="db-card-sub">六个核心维度 · 团队均值 vs 平台基线</p>
          </div>
          <span class="db-badge">满分 100</span>
        </div>
        <DRadar :axes="teamRadar" />
        <div class="db-legend" style="justify-content: center; margin-top: -2px">
          <span class="db-legend-item"><i style="background: #5b9dff" />团队均值</span>
          <span class="db-legend-item"><i class="dash" />平台基线</span>
        </div>
        <div class="db-insight warn">
          <SIcon name="warn" :size="14" />
          <span>短板：<b>风险合规 75 分</b>，低于平台基线；资源整合 76 分同样偏低。</span>
        </div>
      </article>
    </div>

    <div class="db-grid">
      <article class="db-card span-4" :style="{ '--i': 0 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">学习漏斗</h3>
            <p class="db-card-sub">本周 48 名学员 · 环节转化</p>
          </div>
          <span class="db-badge">68.8% 达标</span>
        </div>
        <DFunnel :steps="teamFunnel" />
        <div class="db-mini-list">
          <div class="db-mini-row"><span>进入实战 → 提交方案</span><b>−4 人</b></div>
          <div class="db-mini-row"><span>提交方案 → 评分达标</span><b>−2 人</b></div>
        </div>
        <div class="db-insight">
          <SIcon name="target" :size="14" />
          <span>从「提交方案」到「评分达标」流失 <b>2 人</b>，集中在报价与合规项。</span>
        </div>
      </article>

      <article class="db-card span-4" :style="{ '--i': 1 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">成员进度</h3>
            <p class="db-card-sub">按训练完成度排序</p>
          </div>
          <span class="db-badge">6 / 48</span>
        </div>
        <div class="db-members">
          <div v-for="(m, i) in teamMembers" :key="m.name" class="db-member" :style="{ '--i': i }">
            <span class="db-avatar">{{ m.avatar }}</span>
            <div class="db-member-info">
              <div class="db-member-top">
                <span class="db-member-name">{{ m.name }}</span>
                <span class="db-member-active">{{ m.active }}</span>
              </div>
              <div class="db-progress"><i :style="{ width: `${m.progress}%` }" /></div>
            </div>
            <span class="db-member-score">{{ m.score }}</span>
            <i class="db-state" :class="m.state" />
          </div>
        </div>
      </article>

      <article class="db-card span-4" :style="{ '--i': 2 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">风险预警</h3>
            <p class="db-card-sub">需要本周跟进的事项</p>
          </div>
          <span class="db-badge">12 项</span>
        </div>
        <div class="db-risks">
          <div v-for="r in teamRisks" :key="r.label" class="db-risk">
            <span class="db-risk-mark" :class="r.level" />
            <div class="db-risk-txt">
              <div class="db-risk-name">{{ r.label }}</div>
              <div class="db-risk-note">{{ r.note }}</div>
            </div>
            <span class="db-risk-count">{{ r.count }}<small>人</small></span>
          </div>
        </div>
        <div class="db-insight warn">
          <SIcon name="warn" :size="14" />
          <span>建议：对 <b>何星河、许清和</b> 安排一次一对一回访。</span>
        </div>
      </article>
    </div>

    <article class="db-card span-12" :style="{ '--i': 3 }">
      <div class="db-card-hd">
        <div>
          <h3 class="db-card-title">训练动态</h3>
          <p class="db-card-sub">最近 5 条关键事件 · 实时滚动</p>
        </div>
        <span class="db-badge">LIVE</span>
      </div>
      <div class="db-feed">
        <div v-for="e in teamFeed" :key="`${e.time}-${e.actor}`" class="db-feed-row">
          <span class="db-feed-time">{{ e.time }}</span>
          <span class="db-feed-actor">{{ e.actor }}</span>
          <span class="db-feed-text">{{ e.text }}</span>
          <span class="db-feed-tag" :class="`tone-${e.tone}`">{{ e.tag }}</span>
        </div>
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
import DCount from '@/components/dashboard/DCount.vue'
import DSpark from '@/components/dashboard/DSpark.vue'
import DTrend from '@/components/dashboard/DTrend.vue'
import DRadar from '@/components/dashboard/DRadar.vue'
import DFunnel from '@/components/dashboard/DFunnel.vue'
import SIcon from '@/components/SIcon.vue'
import {
  teamFunnel, teamFeed, teamKpis, teamMembers, teamRadar, teamRisks,
  teamTrendLabels, teamTrendSeries,
} from '@/data/dashboard'

function deltaText(v: number, unit: 'pct' | 'pt' | 'count'): string {
  if (unit === 'count') return `${v >= 0 ? '+' : '−'}${Math.abs(v)}`
  const arrow = v >= 0 ? '▲' : '▼'
  const tail = unit === 'pct' ? '%' : ' pt'
  return `${arrow} ${Math.abs(v)}${tail}`
}
</script>

<style scoped>
.board { display: block; }
</style>