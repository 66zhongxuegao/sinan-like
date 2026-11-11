<template>
  <div class="md" v-html="html" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = withDefaults(defineProps<{ text?: string }>(), { text: '' })

const html = computed(() => {
  // GFM（表格 / 删除线 / 任务列表）+ breaks：交付物里大量单换行，不开启会挤成一段
  const raw = marked.parse(props.text || '', {
    async: false, gfm: true, breaks: true, pedantic: false,
  }) as string
  // 宽表格（逐日行程有 7-8 列）单独包一层，横向滚动而不是把列挤到换行
  const wrapped = raw
    .replace(/<table>/g, '<div class="md-table"><table>')
    .replace(/<\/table>/g, '</table></div>')
  return DOMPurify.sanitize(wrapped, { ADD_ATTR: ['target', 'rel'] })
})
</script>

<style lang="scss">
@use '@/styles/tokens.scss' as *;

.md {
  font-size: 15.5px;
  line-height: 1.85;
  color: $color-text;
  word-break: break-word;

  > :first-child { margin-top: 0; }

  h1, h2, h3, h4 { margin: 18px 0 8px; font-weight: 700; line-height: 1.5; color: $color-text; }
  h1 { font-size: 20px; letter-spacing: -.2px; }
  h2 { font-size: 16px; padding-bottom: 6px; border-bottom: 1px solid $color-border; }
  h3 { font-size: 16.5px; }
  h4 { font-size: 15.5px; color: $color-text-secondary; }

  p { margin: 8px 0; }
  ul, ol { margin: 8px 0 8px 22px; }
  ol { list-style: decimal; }
  ul { list-style: disc; }
  li { margin: 4px 0; }
  li > ul, li > ol { margin: 4px 0 4px 18px; }
  li::marker { color: $color-text-muted; }

  /* 任务列表（- [ ] / - [x]） */
  li:has(> input[type='checkbox']) { list-style: none; margin-left: -18px; }
  li > input[type='checkbox'] { margin-right: 6px; vertical-align: -2px; accent-color: $color-primary; }

  strong { color: $color-text; font-weight: 700; }
  em { color: $color-text-secondary; }
  del { color: $color-text-muted; }
  mark { background: #fff3c4; padding: 0 3px; border-radius: 3px; }
  a { color: $color-primary; text-decoration: none; }
  a:hover { text-decoration: underline; }

  code {
    background: #f2f4f7; border-radius: 4px; padding: 1px 5px;
    font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 15.5px;
  }
  pre {
    background: #f7f8fa; border: 1px solid $color-border; border-radius: 8px;
    padding: 12px 14px; overflow-x: auto; line-height: 1.6;
    code { background: none; padding: 0; }
  }
  blockquote {
    margin: 10px 0; padding: 8px 14px; border-left: 3px solid $color-primary-light;
    background: $color-primary-softer; color: $color-text-secondary; border-radius: 0 6px 6px 0;
    p { margin: 4px 0; }
  }

  /* 表格：单独滚动容器，列宽按内容撑开，不再挤压换行 */
  .md-table { margin: 12px 0; overflow-x: auto; border: 1px solid $color-border; border-radius: 8px; }
  .md-table > table { margin: 0; }
  table { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 15px; }
  th, td { border-right: 1px solid $color-border; border-bottom: 1px solid $color-border;
    padding: 8px 12px; text-align: left; vertical-align: top; min-width: 76px; white-space: normal; }
  th:last-child, td:last-child { border-right: none; }
  tr:last-child td { border-bottom: none; }
  th { background: #fafbfc; font-weight: 600; color: $color-text-secondary; white-space: nowrap; }

  hr { border: none; border-top: 1px solid $color-border; margin: 16px 0; }
  img { max-width: 100%; border-radius: 8px; }

  .refs { margin-top: 16px; padding-top: 10px; border-top: 1px dashed $color-border-strong; font-size: 15.5px; color: $color-text-muted; }
}
</style>
