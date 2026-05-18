<template>
  <div class="file-tree-sidebar">
    <div class="file-tree-header">
      <strong>Files</strong>
      <div class="view-toggle" role="group" aria-label="View mode">
        <button
          type="button"
          class="view-btn"
          :class="{ 'is-active': viewMode === 'tree' }"
          title="Tree view"
          @click="viewMode = 'tree'"
        >📁</button>
        <button
          type="button"
          class="view-btn"
          :class="{ 'is-active': viewMode === 'flat' }"
          title="Flat list, sorted by severity"
          @click="viewMode = 'flat'"
        >📋</button>
      </div>
      <label class="hide-reviewed-label" title="Hide reviewed or empty files">
        <input type="checkbox" v-model="hideReviewed" />
        Hide done
      </label>
    </div>
    <div v-if="loading" class="tree-loading">Loading…</div>
    <div v-else-if="error" class="tree-error">{{ error }}</div>
    <div v-else class="tree-root">
      <template v-if="viewMode === 'tree'">
        <TreeNode
          v-for="node in tree"
          :key="node.name"
          :node="node"
          :currentFile="currentFile"
          @file-selected="onFileSelected"
        />
      </template>
      <template v-else>
        <FileRow
          v-for="f in flatList"
          :key="f.rel_path"
          :file="f"
          :isActive="f.rel_path === currentFile"
          @click="onFileSelected(f.rel_path)"
        />
      </template>
    </div>
  </div>
</template>

<script>
import { rescanSession } from '../api/files.js'
import { sseClient } from '../api/events.js'
import { debounce } from '../utils/debounce.js'
import TreeNode from './TreeNode.vue'
import FileRow from './FileRow.vue'
import { getBoolPref, setBoolPref, getPref, setPref } from '../prefs.js'

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

const SEV_RANK = { P0: 0, P1: 1, P2: 2 }

export default {
  name: 'FileTree',
  components: { TreeNode, FileRow },
  props: {
    sessionId: [String, Number],
    currentFile: { type: String, default: null },
  },
  emits: ['file-selected'],
  data() {
    const savedMode = getPref('viewMode', 'tree')
    return {
      files: [],
      loading: true,
      error: null,
      hideReviewed: getBoolPref('hideReviewed'),
      viewMode: savedMode === 'flat' ? 'flat' : 'tree',
    }
  },
  watch: {
    hideReviewed(val) {
      setBoolPref('hideReviewed', val)
    },
    viewMode(val) {
      setPref('viewMode', val)
    },
    currentFile() {
      this.$nextTick(() => {
        const el = this.$el.querySelector('.tree-active, .flat-active')
        el?.scrollIntoView({ block: 'nearest' })
      })
    },
  },
  computed: {
    filteredFiles() {
      if (!this.hideReviewed) return this.files
      return this.files.filter((f) => f.status !== 'reviewed' && f.status !== 'empty')
    },
    tree() {
      return buildTree(this.filteredFiles)
    },
    flatList() {
      const arr = [...this.filteredFiles]
      arr.sort((a, b) => {
        const sa = a.max_severity ? SEV_RANK[a.max_severity] : 99
        const sb = b.max_severity ? SEV_RANK[b.max_severity] : 99
        if (sa !== sb) return sa - sb
        const ia = a.open_issue_count || 0
        const ib = b.open_issue_count || 0
        if (ia !== ib) return ib - ia
        const aa = (a.todos_count || 0) + (a.notes_count || 0)
        const bb = (b.todos_count || 0) + (b.notes_count || 0)
        if (aa !== bb) return bb - aa
        return a.rel_path.localeCompare(b.rel_path)
      })
      return arr
    },
    orderedPaths() {
      if (this.viewMode === 'flat') return this.flatList.map((f) => f.rel_path)
      const out = []
      const walk = (nodes) => {
        for (const n of nodes) {
          if (n.isFile) out.push(n.path)
          else if (n.children) walk(n.children)
        }
      }
      walk(this.tree)
      return out
    },
  },
  mounted() {
    this.load()
    this._debouncedRefresh = debounce(() => this.load({ silent: true }), 250)
    this._sseUnsubAnno = sseClient.on('annotation_changed', () => this._debouncedRefresh())
    this._sseUnsubFile = sseClient.on('file_changed', () => this._debouncedRefresh())
  },
  beforeUnmount() {
    this._sseUnsubAnno?.()
    this._sseUnsubFile?.()
    this._debouncedRefresh?.cancel()
  },
  methods: {
    async load({ silent = false } = {}) {
      if (!silent) this.loading = true
      this.error = null
      try {
        this.files = await rescanSession(this.sessionId)
      } catch (e) {
        if (!silent) this.error = e.message
      } finally {
        if (!silent) this.loading = false
      }
    },
    onFileSelected(path) {
      this.$emit('file-selected', path)
    },
    selectNext() {
      const list = this.orderedPaths
      if (list.length === 0) return
      const idx = list.indexOf(this.currentFile)
      const next = idx === -1 ? 0 : Math.min(list.length - 1, idx + 1)
      if (list[next] !== this.currentFile) this.$emit('file-selected', list[next])
    },
    selectPrev() {
      const list = this.orderedPaths
      if (list.length === 0) return
      const idx = list.indexOf(this.currentFile)
      const prev = idx === -1 ? list.length - 1 : Math.max(0, idx - 1)
      if (list[prev] !== this.currentFile) this.$emit('file-selected', list[prev])
    },
    refresh() {
      return this.load({ silent: true })
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

.view-toggle {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

.view-btn {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 13px;
  line-height: 1.2;
  cursor: pointer;
  color: var(--text-dim);
  filter: grayscale(1) opacity(0.55);
}

.view-btn:hover {
  background: var(--bg-hover);
  filter: grayscale(0) opacity(0.85);
}

.view-btn.is-active {
  background: var(--bg-active-file);
  border-color: var(--border);
  filter: none;
}

.hide-reviewed-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: normal;
  color: var(--text-dim);
  cursor: pointer;
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
