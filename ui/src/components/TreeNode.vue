<template>
  <div class="tree-node">
    <div
      class="tree-item"
      :class="{ 'tree-file': node.isFile, 'tree-dir': !node.isFile, 'tree-active': isActive }"
      @click="node.isFile ? select() : toggle()"
    >
      <span class="tree-icon">{{ node.isFile ? '📄' : (expanded ? '📂' : '📁') }}</span>
      <span class="tree-name">{{ node.name }}</span>
      <CoverageBar v-if="node.isFile && node.fileData" :coverage="node.fileData.coverage" />
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
import CoverageBar from './CoverageBar.vue'

export default {
  name: 'TreeNode',
  components: { CoverageBar },
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
</style>
