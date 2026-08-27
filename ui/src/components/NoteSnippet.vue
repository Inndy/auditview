<template>
  <div class="note-snippet">
    <div class="snippet-header">
      <router-link class="snippet-loc" :to="codeRoute" title="Open in code view">
        {{ note.file_path }}:{{ note.start_line }}<span v-if="note.end_line !== note.start_line">–{{ note.end_line }}</span>
      </router-link>
      <span v-if="note.is_todo" class="badge badge-todo">TODO</span>
      <span v-if="note.is_orphaned" class="badge badge-orphan" :title="orphanTitle">outdated</span>
    </div>

    <div v-if="note.content" class="snippet-note">{{ note.content }}</div>
    <div v-else class="snippet-note snippet-note-empty">(no note text)</div>

    <div v-if="note.snapshot_text" class="snippet-code" :class="{ collapsed: collapsible && !expanded }">
      <pre><code v-html="highlighted"></code></pre>
    </div>
    <button v-if="collapsible" class="snippet-toggle" @click="expanded = !expanded">
      {{ expanded ? 'Show less' : `Show all ${lineCount} lines` }}
    </button>
  </div>
</template>

<script>
import { highlightSource } from '../highlight.js'

const COLLAPSE_AFTER_LINES = 20

export default {
  name: 'NoteSnippet',
  props: {
    note: { type: Object, required: true },
    sessionId: { type: [Number, String], required: true },
  },
  data() {
    return { expanded: false }
  },
  computed: {
    codeRoute() {
      const file = encodeURIComponent(this.note.file_path)
      return `/sessions/${this.sessionId}/code?file=${file}&line=${this.note.start_line}&endLine=${this.note.end_line}`
    },
    lineCount() {
      return this.note.snapshot_text ? this.note.snapshot_text.split('\n').length : 0
    },
    collapsible() {
      return this.lineCount > COLLAPSE_AFTER_LINES
    },
    highlighted() {
      return highlightSource(this.$hljs, this.note.file_path, this.note.snapshot_text || '')
    },
    orphanTitle() {
      return 'The file changed after this note was made — the snippet below is the original text, not the current file.'
    },
  },
}
</script>

<style scoped>
.note-snippet {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-surface);
  margin-bottom: 10px;
  overflow: hidden;
}

.snippet-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--bg-gutter);
  border-bottom: 1px solid var(--border-light);
}

.snippet-loc {
  font-family: monospace;
  font-size: 12px;
  color: var(--link);
  text-decoration: none;
  overflow-wrap: anywhere;
}

.snippet-loc:hover {
  text-decoration: underline;
}

.badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}

.badge-todo {
  background: var(--badge-todo-bg);
  color: var(--badge-todo-text);
}

.badge-orphan {
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
  cursor: help;
}

.snippet-note {
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.snippet-note-empty {
  color: var(--text-faint);
  font-style: italic;
}

.snippet-code {
  border-top: 1px solid var(--border-light);
  overflow-x: auto;
}

.snippet-code.collapsed {
  max-height: 20em;
  overflow-y: hidden;
  mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
}

.snippet-code pre {
  margin: 0;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
}

.snippet-toggle {
  display: block;
  width: 100%;
  padding: 4px;
  border: none;
  border-top: 1px solid var(--border-light);
  background: var(--bg-gutter);
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
}

.snippet-toggle:hover {
  color: var(--text);
  background: var(--bg-hover);
}
</style>
