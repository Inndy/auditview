<template>
  <div class="file-tree-sidebar">
    <div class="file-tree-header">
      <strong>Files</strong>
      <label class="hide-reviewed-label">
        <input type="checkbox" v-model="hideReviewed" />
        Hide reviewed
      </label>
    </div>
    <div v-if="loading" class="tree-loading">Loading…</div>
    <div v-else-if="error" class="tree-error">{{ error }}</div>
    <div v-else class="tree-root">
      <TreeNode
        v-for="node in tree"
        :key="node.name"
        :node="node"
        :currentFile="currentFile"
        @file-selected="onFileSelected"
      />
    </div>
  </div>
</template>

<script>
import { listFiles } from '../api/files.js'
import TreeNode from './TreeNode.vue'

function buildTree(files) {
  const root = []
  for (const f of files) {
    const parts = f.rel_path.split('/')
    let nodes = root
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i]
      const isFile = i === parts.length - 1
      let existing = nodes.find((n) => n.name === name)
      if (!existing) {
        existing = {
          name,
          isFile,
          children: isFile ? null : [],
          fileData: isFile ? f : null,
          path: parts.slice(0, i + 1).join('/'),
        }
        nodes.push(existing)
      }
      if (!isFile) nodes = existing.children
    }
  }
  return root
}

export default {
  name: 'FileTree',
  components: { TreeNode },
  props: {
    sessionId: [String, Number],
  },
  emits: ['file-selected'],
  data() {
    return {
      files: [],
      loading: true,
      error: null,
      currentFile: null,
      hideReviewed: false,
    }
  },
  computed: {
    filteredFiles() {
      if (!this.hideReviewed) return this.files
      return this.files.filter((f) => f.status !== 'reviewed')
    },
    tree() {
      return buildTree(this.filteredFiles)
    },
  },
  mounted() {
    this.load()
  },
  methods: {
    async load() {
      this.loading = true
      this.error = null
      try {
        this.files = await listFiles(this.sessionId)
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    onFileSelected(path) {
      this.currentFile = path
      this.$emit('file-selected', path)
    },
    refresh() {
      return this.load()
    },
    updateFile(path, { countable_lines, reviewed_lines }) {
      const f = this.files.find((f) => f.rel_path === path)
      if (!f) return
      f.countable_lines = countable_lines
      f.reviewed_lines = reviewed_lines
      f.coverage = countable_lines > 0 ? reviewed_lines / countable_lines : 0.0
      if (countable_lines === 0) f.status = 'empty'
      else if (reviewed_lines === 0) f.status = 'not_viewed'
      else if (reviewed_lines >= countable_lines) f.status = 'reviewed'
      else f.status = 'partial'
    },
  },
}
</script>

<style scoped>
.file-tree-sidebar {
  display: flex;
  flex-direction: column;
}

.file-tree-header {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-mid);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.hide-reviewed-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: normal;
  color: var(--text-dim);
  cursor: pointer;
  margin-left: auto;
  white-space: nowrap;
}

.tree-loading,
.tree-error {
  padding: 10px 12px;
  font-size: 12px;
  color: var(--text-muted);
}

.tree-root {
  overflow-y: auto;
  flex: 1;
}

</style>
