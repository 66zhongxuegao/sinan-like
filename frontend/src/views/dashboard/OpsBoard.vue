<template>
  <div class="board">
    <div class="db-kpis five">
      <article v-for="(k, i) in opsKpis" :key="k.id" class="db-card db-kpi" :class="{ accent: i === 0 }" :style="{ '--i': i }">
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
          <DSpark :data="k.series" :color="i === 0 ? '#ffffff' : k.color" :width="88" />
        </div>
      </article>
    </div>

    <div class="db-grid">
      <article class="db-card span-7" :style="{ '--i': 0 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">增长与活跃</h3>
            <p class="db-card-sub">活跃学员 vs 新增学员 · 近 14 天</p>
          </div>
          <div class="db-legend">
            <span class="db-legend-item"><i style="background: #5b9dff" />活跃学员</span>
            <span class="db-legend-item"><i style="background: #2fe3c8" />新增学员</span>
          </div>
        </div>
        <DTrend :labels="opsTrendLabels" :series="opsTrendSeries" />
        <div class="db-insight">
          <SIcon name="sparkle" :size="14" />
          <span>今日活跃 <b>1,032</b>，日活 / 周活 49.0%；新增学员中院校合作渠道贡献最高。</span>
        </div>
      </article>

      <article class="db-card span-5" :style="{ '--i': 1 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">核心转化漏斗</h3>
            <p class="db-card-sub">注册 → 复训 · 全量学员</p>
          </div>
          <span class="db-badge">整体转化 26.1%</span>
        </div>
        <DFunnel :steps="opsFunnel" />
        <div class="db-insight warn">
          <SIcon name="warn" :size="14" />
          <span>注册到激活达 <b>84.8%</b>，但到评分达标累计流失 <b>61.8%</b>，是运营主攻点。</span>
        </div>
      </article>
    </div>

    <div class="db-grid">
      <article class="db-card span-4" :style="{ '--i': 0 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">留存曲线</h3>
            <p class="db-card-sub">注册后关键节点留存率</p>
          </div>
          <span class="db-badge">D30 28.5%</span>
        </div>
        <div class="db-retention">
          <div v-for="(r, i) in retentionCurve" :key="r.label" class="db-ret">
            <span class="db-ret-val">{{ r.value }}%</span>
            <div class="db-ret-track">
              <i :style="{ height: `${r.value}%`, animationDelay: `${0.15 + i * 0.08}s` }" />
            </div>
            <span class="db-ret-label">{{ r.label }}</span>
          </div>
        </div>
        <div class="db-insight">
          <SIcon name="timer" :size="14" />
          <span>D7 后曲线趋稳，<b>首周实战完成</b>是留存分水岭。</span>
        </div>
      </article>

      <article class="db-card span-4" :style="{ '--i': 1 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">能力评分分布</h3>
            <p class="db-card-sub">全量学员 · 满分 100</p>
          </div>
          <span class="db-badge">均值 81.7</span>
        </div>
        <div class="db-scorebars">
          <div v-for="(b, i) in scoreBands" :key="b.label" class="db-scorebar">
            <span class="db-sb-val">{{ b.pct }}%</span>
            <div class="db-sb-track">
              <i :style="{ height: `${(b.pct / 31) * 100}%`, background: b.color, animationDelay: `${0.15 + i * 0.08}s` }" />
            </div>
            <span class="db-sb-label">{{ b.label }}</span>
          </div>
        </div>
        <div class="db-insight">
          <SIcon name="target" :size="14" />
          <span>70 分以上占 <b>73%</b>；低于 60 分的 228 人建议进入专项补强。</span>
        </div>
      </article>

      <article class="db-card span-4" :style="{ '--i': 2 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">学员来源</h3>
            <p class="db-card-sub">按获客渠道拆分</p>
          </div>
          <span class="db-badge">2,846 人</span>
        </div>
        <DDonut :items="channelMix" :size="150" center-label="学员" />
        <div class="db-insight">
          <SIcon name="users" :size="14" />
          <span>院校合作贡献 <b>42%</b>，是当前最稳定的获客来源。</span>
        </div>
      </article>
    </div>

    <div class="db-grid">
      <article class="db-card span-5" :style="{ '--i': 0 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">学习时段热力</h3>
            <p class="db-card-sub">星期 × 时段 · 活跃事件密度</p>
          </div>
          <span class="db-badge">周五下午峰值</span>
        </div>
        <DHeat :days="heatDays" :hours="heatHours" :values="heatValues" />
      </article>

      <article class="db-card span-4" :style="{ '--i': 1 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">内容与评分质量</h3>
            <p class="db-card-sub">AI 出题 / 评分校准 / 错误闭环</p>
          </div>
          <span class="db-badge">全部达标</span>
        </div>
        <div class="db-quality">
          <div v-for="q in qualityRows" :key="q.label" class="db-qrow">
            <div class="db-qhead"><span>{{ q.label }}</span><b>{{ q.value }}%</b></div>
            <div class="db-qbar" :style="{ '--target': `${q.target}%` }">
              <i :style="{ width: `${q.value}%` }" />
            </div>
            <div class="db-qfoot"><span>{{ q.note }}</span><span>目标 {{ q.target }}%</span></div>
          </div>
        </div>
      </article>

      <article class="db-card span-3" :style="{ '--i': 2 }">
        <div class="db-card-hd">
          <div>
            <h3 class="db-card-title">风险预警</h3>
            <p class="db-card-sub">本周待处理</p>
          </div>
        </div>
        <div class="db-risk-total"><b>87</b><span>项待跟进</span></div>
        <div class="db-risks">
          <div v-for="r in opsRisks" :key="r.label" class="db-risk">
            <span class="db-risk-mark" :class="r.level" />
            <div class="db-risk-txt">
              <div class="db-risk-name">{{ r.label }}</div>
              <div class="db-risk-note">{{ r.note }}</div>
            </div>
            <span class="db-risk-count">{{ r.count }}</span>
          </div>
        </div>
      </article>
    </div>

    <article class="db-card span-12" :style="{ '--i': 3 }">
      <div class="db-card-hd">
        <div>
          <h3 class="db-card-title">运营动态</h3>
          <p class="db-card-sub">全平台关键事件 · 实时</p>
        </div>
        <span class="db-badge">LIVE</span>
      </div>
      <div class="db-feed">
        <div v-for="e in opsFeed" :key="`${e.time}-${e.actor}`" class="db-feed-row">
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
import DFunnel from '@/components/dashboard/DFunnel.vue'
import DDonut from '@/components/dashboard/DDonut.vue'
import DHeat from '@/components/dashboard/DHeat.vue'
import SIcon from '@/components/SIcon.vue'
import {
  channelMix, heatDays, heatHours, heatValues, opsFeed, opsFunnel, opsKpis, opsRisks,
  opsTrendLabels, opsTrendSeries, qualityRows, retentionCurve, scoreBands,
} from '@/data/dashboard'

function deltaText(v: number, unit: 'pct' | 'pt' | 'count'): string {
  if (unit === 'count') return `${v >= 0 ? '+' : '−'}${Math.abs(v)}`
  const arrow = v >= 0 ? '▲' : '▼'
  const tail = unit === 'pct' ? '%' : ' pt'
  return `${arrow} ${Math.abs(v)}${tail}`
}
</script>

<style scoped>
.db-risk-total { display: flex; align-items: baseline; gap: 8px; margin: 2px 0 12px; }
.db-risk-total b { font-family: 'Bahnschrift', 'Microsoft YaHei', sans-serif; font-size: 38px; line-height: 1;
  letter-spacing: -1px; background: linear-gradient(120deg, #16223a, #e05a78); -webkit-background-clip: text;
  background-clip: text; color: transparent; }
.db-risk-total span { font-size: 11.5px; color: #8296b6; }
</style>