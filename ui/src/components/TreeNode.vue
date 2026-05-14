<template>
  <div class="tree-node">
    <div
      class="tree-item"
      :class="{ 'tree-file': node.isFile, 'tree-dir': !node.isFile, 'tree-active': isActive }"
      @click="node.isFile ? select() : toggle()"
    >
      <span class="tree-icon">{{ node.isFile ? '📄' : (expanded ? '📂' : '📁') }}</span>
      <span class="tree-name">{{ node.name }}</span>
      <template v-if="node.isFile && node.fileData">
        <span
          class="status-dot"
          :class="'status-' + node.fileData.status"
          :title="statusTitle"
        ></span>
        <span v-if="node.fileData.todos_count" class="badge-todo-count" title="TODOs">{{ node.fileData.todos_count }}</span>
        <span v-if="node.fileData.notes_count" class="badge-note-count" title="Notes">{{ node.fileData.notes_count }}</span>
      </template>
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
    statusTitle() {
      const s = this.node.fileData?.status
      if (s === 'reviewed') return 'Fully reviewed'
      if (s === 'partial') return 'Partially reviewed'
      if (s === 'not_viewed') return 'Not viewed'
      return 'No countable lines'
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

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-reviewed   { background: #4caf50; }
.status-partial    { background: #ff9800; }
.status-not_viewed { background: var(--border-mid); }
.status-empty      { display: none; }

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
</style>
