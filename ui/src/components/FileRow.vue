<template>
  <div
    class="flat-row"
    :class="{ 'flat-active': isActive }"
    @click="$emit('click')"
  >
    <span class="flat-icon" :title="isActive ? 'Open in the viewer' : null">{{ isActive ? '👁️' : '📄' }}</span>
    <span class="flat-name">{{ basename }}</span>
    <span v-if="dirname" class="flat-dir">{{ dirname }}</span>
    <span class="flat-spacer"></span>
    <span
      v-if="file.open_issue_count"
      class="issue-count"
      :title="`${file.open_issue_count} open issue${file.open_issue_count === 1 ? '' : 's'}`"
    >{{ file.open_issue_count }}</span>
    <span
      v-if="file.max_severity"
      class="sev-badge"
      :class="'sev-' + file.max_severity"
      :title="`Highest severity open issue: ${file.max_severity}`"
    >{{ file.max_severity }}</span>
    <span v-if="file.todos_count" class="badge-todo-count" title="TODOs">{{ file.todos_count }}</span>
    <span v-if="file.notes_count" class="badge-note-count" title="Notes">{{ file.notes_count }}</span>
    <span v-if="!['empty', 'unreviewable'].includes(file.status)" class="pct" :title="pctTitle">{{ pct }}%</span>
    <span
      class="status-dot"
      :class="'status-' + file.status"
      :title="statusTitle"
    ></span>
  </div>
</template>

<script>
export default {
  name: 'FileRow',
  props: {
    file: { type: Object, required: true },
    isActive: { type: Boolean, default: false },
  },
  emits: ['click'],
  computed: {
    basename() {
      const parts = this.file.rel_path.split('/')
      return parts[parts.length - 1]
    },
    dirname() {
      const parts = this.file.rel_path.split('/')
      if (parts.length <= 1) return ''
      return parts.slice(0, -1).join('/') + '/'
    },
    pct() {
      return Math.round((this.file.coverage || 0) * 100)
    },
    pctTitle() {
      return `${this.file.reviewed_lines}/${this.file.countable_lines} lines reviewed`
    },
    statusTitle() {
      const s = this.file.status
      if (s === 'reviewed') return 'Fully reviewed'
      if (s === 'partial') return 'Partially reviewed'
      if (s === 'not_viewed') return 'Not viewed'
      if (s === 'empty') return 'Empty file'
      if (s === 'unreviewable') return 'Too large or binary; excluded from coverage'
      return 'No countable lines'
    },
  },
}
</script>

<style scoped>
.flat-row {
  display: flex;
  align-items: center;
  padding: 3px 8px;
  font-size: 13px;
  cursor: pointer;
  gap: 4px;
  user-select: none;
  min-width: 0;
}

.flat-row:hover {
  background: var(--bg-hover);
}

.flat-active {
  background: var(--bg-active-file) !important;
  font-weight: 600;
  /* inset rather than a border so the accent costs no horizontal space */
  box-shadow: inset 3px 0 0 var(--primary);
}

.flat-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.flat-name {
  flex-shrink: 0;
  white-space: nowrap;
}

.flat-dir {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
  font-size: 11px;
  color: var(--text-dim);
  font-weight: normal;
}

.flat-spacer {
  flex: 1;
  min-width: 4px;
}

.pct {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.issue-count {
  font-size: 10px;
  font-weight: 700;
  border-radius: 3px;
  padding: 0 4px;
  line-height: 1.4;
  background: var(--bg-gutter);
  color: var(--text);
  border: 1px solid var(--border);
  flex-shrink: 0;
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
</style>
