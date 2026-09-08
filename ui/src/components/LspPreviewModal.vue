<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-box lsp-preview">
      <h3>
        <span class="ext-badge">external</span>
        {{ shortPath }}
      </h3>
      <div class="path-full" :title="path">{{ path }}</div>

      <div v-if="loading" class="loading">Loading…</div>
      <div v-else-if="error" class="error-msg">{{ error }}</div>
      <table v-else class="preview-table">
        <tbody>
          <tr v-for="l in lines" :key="l.line_no" :class="{ target: l.line_no === line }">
            <td class="pv-gutter">{{ l.line_no }}</td>
            <td class="pv-code"><code>{{ l.content }}</code></td>
          </tr>
        </tbody>
      </table>

      <div class="not-reviewable">
        Outside the session root — read-only, and not counted towards review
        coverage.
      </div>

      <div class="modal-actions">
        <button data-modal-cancel @click="$emit('close')">Close</button>
      </div>
    </div>
  </div>
</template>

<script>
import { getPreview } from '../api/lsp.js'

export default {
  name: 'LspPreviewModal',
  props: {
    sessionId: [String, Number],
    path: { type: String, required: true },
    line: { type: Number, default: 1 },
  },
  emits: ['close'],
  data() {
    return {
      loading: true,
      error: null,
      lines: [],
      startLine: 1,
      totalLines: 0,
    }
  },
  computed: {
    shortPath() {
      const parts = this.path.split('/').filter(Boolean)
      return parts.slice(-2).join('/') || this.path
    },
  },
  mounted() {
    this.load()
  },
  methods: {
    async load() {
      try {
        const data = await getPreview(this.sessionId, this.path, this.line)
        this.lines = data.lines || []
        this.startLine = data.start_line
        this.totalLines = data.total_lines
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
        this.$nextTick(() => {
          this.$el.querySelector('tr.target')?.scrollIntoView({ block: 'center' })
        })
      }
    },
  },
}
</script>

<style scoped>
.lsp-preview {
  width: 760px;
  max-width: 92vw;
}

.ext-badge {
  display: inline-block;
  padding: 1px 6px;
  margin-right: 8px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border: 1px solid var(--border-mid);
  border-radius: 3px;
  color: var(--text-muted);
}

.path-full {
  font-family: monospace;
  font-size: 11px;
  color: var(--text-faint);
  word-break: break-all;
  margin-bottom: 10px;
}

.loading {
  padding: 20px 0;
  color: var(--text-faint);
  font-size: 13px;
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  max-height: 420px;
  display: block;
  overflow: auto;
  background: var(--bg-surface2);
  border: 1px solid var(--border);
  border-radius: 4px;
}

.pv-gutter {
  width: 1%;
  padding: 0 10px 0 8px;
  text-align: right;
  font-family: monospace;
  font-size: 12px;
  color: var(--text-faint);
  user-select: none;
  vertical-align: top;
}

.pv-code {
  padding: 0;
  font-family: monospace;
  font-size: 12px;
  white-space: pre;
}

tr.target {
  background: var(--bg-hover, var(--bg-surface));
}

tr.target .pv-gutter {
  color: var(--primary);
  font-weight: bold;
}

.not-reviewable {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.error-msg {
  padding: 10px;
  font-size: 12px;
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
  border-radius: 4px;
}
</style>
