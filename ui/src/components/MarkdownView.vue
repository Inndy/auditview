<template>
  <div class="markdown-view" v-html="html"></div>
</template>

<script>
import { renderMarkdown } from '../markdown.js'

export default {
  name: 'MarkdownView',
  props: {
    source: {
      type: String,
      default: '',
    },
  },
  computed: {
    html() {
      return renderMarkdown(this.source)
    },
  },
}
</script>

<style scoped>
.markdown-view {
  font-size: 13px;
  line-height: 1.55;
  color: var(--text);
  overflow-wrap: break-word;
  word-break: break-word;
}

.markdown-view :deep(> :first-child) { margin-top: 0; }
.markdown-view :deep(> :last-child) { margin-bottom: 0; }

.markdown-view :deep(p) {
  margin: 0 0 8px 0;
}

.markdown-view :deep(h1),
.markdown-view :deep(h2),
.markdown-view :deep(h3),
.markdown-view :deep(h4),
.markdown-view :deep(h5),
.markdown-view :deep(h6) {
  margin: 14px 0 6px 0;
  font-weight: 600;
  line-height: 1.3;
}
.markdown-view :deep(h1) { font-size: 16px; }
.markdown-view :deep(h2) { font-size: 15px; }
.markdown-view :deep(h3) { font-size: 14px; }
.markdown-view :deep(h4),
.markdown-view :deep(h5),
.markdown-view :deep(h6) { font-size: 13px; }

.markdown-view :deep(ul),
.markdown-view :deep(ol) {
  margin: 0 0 8px 0;
  padding-left: 22px;
}
.markdown-view :deep(ul) { list-style: disc; }
.markdown-view :deep(ol) { list-style: decimal; }
.markdown-view :deep(li) {
  margin: 2px 0;
}
.markdown-view :deep(li > ul),
.markdown-view :deep(li > ol) {
  margin: 2px 0;
}
.markdown-view :deep(li > p) {
  margin: 0 0 4px 0;
}

.markdown-view :deep(strong) { font-weight: 600; }
.markdown-view :deep(em) { font-style: italic; }
.markdown-view :deep(del) { text-decoration: line-through; }

.markdown-view :deep(a) {
  color: var(--primary);
  text-decoration: underline;
}
.markdown-view :deep(a:hover) {
  text-decoration: none;
}

.markdown-view :deep(code) {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.9em;
  background: var(--bg-hover);
  padding: 1px 5px;
  border-radius: 3px;
}

.markdown-view :deep(pre) {
  background: var(--bg-hover);
  padding: 10px 12px;
  border-radius: 4px;
  overflow-x: auto;
  margin: 0 0 10px 0;
  font-size: 12px;
  line-height: 1.45;
}
.markdown-view :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: inherit;
  border-radius: 0;
}

.markdown-view :deep(blockquote) {
  margin: 0 0 10px 0;
  padding: 2px 10px;
  border-left: 3px solid var(--border);
  color: var(--text-muted);
}
.markdown-view :deep(blockquote > :last-child) { margin-bottom: 0; }

.markdown-view :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 14px 0;
}

.markdown-view :deep(table) {
  border-collapse: collapse;
  margin: 0 0 10px 0;
  display: block;
  overflow-x: auto;
  max-width: 100%;
}
.markdown-view :deep(thead) {
  background: var(--bg-hover);
}
.markdown-view :deep(th),
.markdown-view :deep(td) {
  border: 1px solid var(--border);
  padding: 5px 9px;
  font-size: 12px;
  text-align: left;
  vertical-align: top;
}
.markdown-view :deep(th) {
  font-weight: 600;
}

.markdown-view :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 4px;
}

.markdown-view :deep(kbd) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.85em;
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 3px;
  background: var(--bg-surface);
}
</style>
