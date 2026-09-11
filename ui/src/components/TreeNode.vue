<template>
  <div class="tree-node">
    <div
      class="tree-item"
      :class="{ 'tree-file': node.isFile, 'tree-dir': !node.isFile, 'tree-active': isActive }"
      @click="node.isFile ? select() : toggle()"
    >
      <span class="tree-icon" :title="isActive ? 'Open in the viewer' : null">{{ icon }}</span>
      <span class="tree-name">{{ node.name }}</span>
      <template v-if="node.isFile && node.fileData">
        <span
          v-if="node.fileData.max_severity"
          class="sev-badge"
          :class="'sev-' + node.fileData.max_severity"
          :title="severityTitle"
        >{{ node.fileData.max_severity }}</span>
        <span v-if="node.fileData.todos_count" class="badge-todo-count" title="TODOs">{{ node.fileData.todos_count }}</span>
        <span v-if="node.fileData.notes_count" class="badge-note-count" title="Notes">{{ node.fileData.notes_count }}</span>
        <span v-if="!['empty', 'unreviewable'].includes(node.fileData.status)" class="pct" :title="pctTitle">{{ filePct }}%</span>
        <span
          class="status-dot"
          :class="'status-' + node.fileData.status"
          :title="statusTitle"
        ></span>
      </template>
      <span v-else-if="!node.isFile && node.rollup" class="pct" :title="dirPctTitle">{{ dirPct }}%</span>
    </div>
    <div v-if="!node.isFile && expanded" class="tree-children">
      <TreeNode
        v-for="child in node.children"
        :key="child.name"
        :node="child"
        :currentFile="currentFile"
        @file-selected="$emit('file-selected', $event)"
      />
    </div>
  </div>
</template>

<script>
export default {
  name: 'TreeNode',
  props: {
    node: Object,
    currentFile: String,
  },
  emits: ['file-selected'],
  data() {
    return { expanded: true }
  },
  computed: {
    isActive() {
      return this.node.isFile && this.node.path === this.currentFile
    },
    icon() {
      if (!this.node.isFile) return this.expanded ? '📂' : '📁'
      return this.isActive ? '👁️' : '📄'
    },
    statusTitle() {
      const s = this.node.fileData?.status
      if (s === 'reviewed') return 'Fully reviewed'
      if (s === 'partial') return 'Partially reviewed'
      if (s === 'not_viewed') return 'Not viewed'
      if (s === 'empty') return 'Empty file'
      if (s === 'unreviewable') return 'Too large or binary; excluded from coverage'
      return 'No countable lines'
    },
    filePct() {
      return Math.round((this.node.fileData?.coverage || 0) * 100)
    },
    pctTitle() {
      const d = this.node.fileData
      if (!d) return ''
      return `${d.reviewed_lines}/${d.countable_lines} lines reviewed`
    },
    dirPct() {
      const r = this.node.rollup
      return r && r.countable > 0 ? Math.round((r.reviewed / r.countable) * 100) : 0
    },
    dirPctTitle() {
      const r = this.node.rollup
      if (!r) return ''
      return `${r.reviewed}/${r.countable} lines \u00b7 ${r.reviewedFiles}/${r.files} files reviewed`
    },
    severityTitle() {
      const sev = this.node.fileData?.max_severity
      if (!sev) return ''
      return `Highest severity open issue in this file: ${sev}`
    },
  },
  methods: {
    toggle() {
      this.expanded = !this.expanded
    },
    select() {
      this.$emit('file-selected', this.node.path)
    },
  },
}
</script>

<style scoped>
.tree-item {
  display: flex;
  align-items: center;
  padding: 3px 8px;
  font-size: 13px;
  cursor: pointer;
  gap: 4px;
  user-select: none;
}

.tree-item:hover {
  background: var(--bg-hover);
}

.tree-active {
  background: var(--bg-active-file) !important;
  font-weight: 600;
  /* inset rather than a border so the accent costs no horizontal space */
  box-shadow: inset 3px 0 0 var(--primary);
}

.tree-children {
  padding-left: 14px;
}

.tree-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.pct {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-reviewed   { background: var(--status-success); }
.status-partial    { background: var(--status-warning); }
.status-not_viewed { background: var(--bg-base); }
.status-empty      { background: transparent; border: 1px dashed var(--text-faint); }
.status-unreviewable { background: transparent; border: 1px solid var(--text-muted); }

.badge-todo-count,
.badge-note-count {
  font-size: 10px;
  border-radius: 3px;
  padding: 0 3px;
  line-height: 1.4;
  flex-shrink: 0;
}

.badge-todo-count {
  background: var(--badge-todo-bg);
  color: var(--badge-todo-text);
}

.badge-note-count {
  background: var(--bg-gutter);
  color: var(--text-muted);
  border: 1px solid var(--border);
}

.sev-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.3px;
  padding: 0 4px;
  border-radius: 3px;
  color: white;
  line-height: 1.4;
  flex-shrink: 0;
}

.sev-P0 { background: var(--severity-p0); }
.sev-P1 { background: var(--severity-p1); }
.sev-P2 { background: var(--severity-p2); }
</style>
