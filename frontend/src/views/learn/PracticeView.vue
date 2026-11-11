<template>
  <div class="prac-learn">
    <div class="card head">
      <div><div class="t">练题</div>
        <div class="d">按技能点练习。题目来自数据基座（选择题 + 简答题），答题结果写回掌握度。</div></div>
      <span class="chip">数据基座生成中</span>
    </div>
    <div class="card tip">
      练习题正在后台按 61 个技能点生成（每点含 2 道选择 + 1 道简答，带答案与解析）。
      生成完成后，这里会按你的薄弱技能点优先推题。
    </div>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.prac-learn { width: 100%; max-width: 960px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; padding: 20px 22px; }
.head { display: flex; justify-content: space-between; align-items: flex-start; }
.head .t { font-size: 22px; font-weight: 800; }
.head .d { margin-top: 6px; font-size: 15px; color: $color-text-secondary; }
.chip { font-size: 15.5px; background: $color-primary-soft; color: $color-primary; padding: 3px 12px; border-radius: 999px; }
.tip { font-size: 15px; line-height: 1.9; color: $color-text-secondary; }
</style>