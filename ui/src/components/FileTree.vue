<template>
  <div class="file-tree-sidebar">
    <div class="file-tree-header">
      <strong>Files</strong>
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
    }
  },
  computed: {
    tree() {
      return buildTree(this.files)
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
  border-bottom: 1px solid #e0e0e0;
  font-size: 13px;
}

.tree-loading,
.tree-error {
  padding: 10px 12px;
  font-size: 12px;
  color: #888;
}

.tree-root {
  overflow-y: auto;
  flex: 1;
}

</style>
