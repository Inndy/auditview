<template>
  <div class="session-view-wrap">
    <Splitpanes class="session-layout" @resized="onResized">
      <Pane :size="sizes[0]" :min-size="10">
        <FileTree
          ref="fileTree"
          :sessionId="id"
          :currentFile="currentFile"
          @file-selected="openFile"
        />
      </Pane>
      <Pane :size="sizes[1]" :min-size="30">
        <CodeViewer
          ref="codeViewer"
          :sessionId="id"
          :filePath="currentFile"
          :wrapLines="wrapLines"
          @notes-updated="onNotesUpdated"
          @lines-marked="onLinesMarked"
          @file-reloaded="onFileReloaded"
          @show-help="$emit('show-help')"
        />
      </Pane>
      <Pane :size="sizes[2]" :min-size="12">
        <div class="right-panels">
          <NotePanel
            :notes="currentNotes"
            :sessionId="id"
            @note-updated="onNoteUpdated"
            @note-deleted="onNoteDeleted"
            @jump="onNoteJump"
          />
          <OrphanPanel
            :notes="currentNotes"
            :sessionId="id"
            @note-updated="onNoteUpdated"
            @note-deleted="onNoteDeleted"
            @jump="onNoteJump"
          />
        </div>
      </Pane>
    </Splitpanes>
    <KeyboardHelpModal :visible="showHelp" @close="showHelp = false" />
  </div>
</template>

<script>
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import { getCoverage } from '../api/coverage.js'
import FileTree from '../components/FileTree.vue'
import CodeViewer from '../components/CodeViewer.vue'
import NotePanel from '../components/NotePanel.vue'
import OrphanPanel from '../components/OrphanPanel.vue'
import KeyboardHelpModal from '../components/KeyboardHelpModal.vue'

const LAYOUT_STORAGE_KEY = 'auditview:layout:panes'
const DEFAULT_SIZES = [18, 60, 22]

function loadSizes() {
  try {
    const raw = localStorage.getItem(LAYOUT_STORAGE_KEY)
    if (!raw) return [...DEFAULT_SIZES]
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length !== 3) return [...DEFAULT_SIZES]
    if (!parsed.every((n) => typeof n === 'number' && n > 0 && n < 100)) return [...DEFAULT_SIZES]
    const sum = parsed.reduce((a, b) => a + b, 0)
    if (Math.abs(sum - 100) > 1) return [...DEFAULT_SIZES]
    return parsed
  } catch {
    return [...DEFAULT_SIZES]
  }
}

export default {
  name: 'CodeView',
  components: {
    Splitpanes,
    Pane,
    FileTree,
    CodeViewer,
    NotePanel,
    OrphanPanel,
    KeyboardHelpModal,
  },
  props: {
    session: Object,
    coverage: Object,
    wrapLines: Boolean,
  },
  emits: ['wrap-lines-change', 'show-help', 'coverage-refreshed'],
  data() {
    return {
      id: this.$route.params.id,
      currentFile: null,
      currentNotes: [],
      showHelp: false,
      pendingJump: null,
      sizes: loadSizes(),
    }
  },
  mounted() {
    const { file, line, endLine } = this.$route.query
    if (file) this.currentFile = file
    if (line) this.pendingJump = { start: parseInt(line), end: parseInt(endLine || line) }
    this._keyHandler = this.onKeyDown.bind(this)
    document.addEventListener('keydown', this._keyHandler)
  },
  beforeUnmount() {
    document.removeEventListener('keydown', this._keyHandler)
  },
  watch: {
    '$route.query'({ file, line, endLine }) {
      if (file) this.currentFile = file
      this.pendingJump = line ? { start: parseInt(line), end: parseInt(endLine || line) } : null
    },
  },
  methods: {
    openFile(path) {
      this.currentFile = path
      this.currentNotes = []
      const q = this.$route.query
      if (q.file !== path || q.line != null || q.endLine != null) {
        const next = { ...q, file: path }
        delete next.line
        delete next.endLine
        this.$router.replace({ query: next })
      }
    },
    onNotesUpdated(notes) {
      this.currentNotes = notes
      if (this.pendingJump) {
        const { start, end } = this.pendingJump
        this.pendingJump = null
        this.$nextTick(() => this.$refs.codeViewer?.jumpToRange(start, end))
      }
    },
    onLinesMarked({ filePath, countable, reviewed }) {
      this.$refs.fileTree?.updateFile(filePath, { countable_lines: countable, reviewed_lines: reviewed })
      this.refreshCoverage()
    },
    async refreshCoverage() {
      try {
        this.$emit('coverage-refreshed', await getCoverage(this.id))
      } catch { /* non-critical, stale coverage is acceptable */ }
    },
    onFileReloaded() {
      this.$refs.fileTree?.refresh()
      this.refreshCoverage()
    },
    onNoteUpdated(updated) {
      const idx = this.currentNotes.findIndex((n) => n.id === updated.id)
      if (idx !== -1) this.currentNotes.splice(idx, 1, updated)
    },
    onNoteDeleted(id) {
      this.currentNotes = this.currentNotes.filter((n) => n.id !== id)
    },
    onNoteJump(note) {
      this.$refs.codeViewer?.jumpToRange(note.start_line, note.end_line)
    },
    onResized(payload) {
      const panes = payload?.panes
      if (!Array.isArray(panes) || panes.length !== 3) return
      const next = panes.map((p) => p.size)
      this.sizes = next
      try {
        localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(next))
      } catch { /* storage full / disabled — non-critical */ }
    },
    onKeyDown(e) {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return
      if (document.querySelector('.modal-overlay')) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        this.$refs.fileTree?.selectNext()
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        this.$refs.fileTree?.selectPrev()
      }
    },
  },
}
</script>

<style scoped>
.session-view-wrap {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}

.session-layout {
  flex: 1;
  overflow: hidden;
}

.loading-full,
.error-full {
  padding: 40px;
  font-size: 14px;
  color: var(--text-muted);
}

.error-full {
  color: var(--badge-orphan-text);
}

:deep(.splitpanes__splitter) {
  position: relative;
  width: 5px;
  background: var(--border);
  cursor: col-resize;
  transition: background 0.15s;
}

:deep(.splitpanes__splitter:hover) {
  background: var(--text-muted);
}

:deep(.splitpanes__pane) {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

:deep(.splitpanes__pane) > * {
  flex: 1;
  min-height: 0;
}
</style>
