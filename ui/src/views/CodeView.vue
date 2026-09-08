<template>
  <div class="session-view-wrap">
    <Splitpanes class="session-layout" @resized="onResized">
      <Pane :size="sizes[0]" :min-size="10" :class="{ 'pane-focused': padActive && focusedPane === 'tree' }">
        <FileTree
          ref="fileTree"
          :sessionId="id"
          :currentFile="currentFile"
          @file-selected="openFile"
        />
      </Pane>
      <Pane :size="sizes[1]" :min-size="30" :class="{ 'pane-focused': padActive && focusedPane === 'code' }">
        <CodeViewer
          ref="codeViewer"
          :sessionId="id"
          :filePath="currentFile"
          :wrapLines="wrapLines"
          @notes-updated="onNotesUpdated"
          @lines-marked="onLinesMarked"
          @file-reloaded="onFileReloaded"
          @selection-change="onSelectionChange"
          @goto-location="onGotoLocation"
        />
      </Pane>
      <Pane :size="sizes[2]" :min-size="12" :class="{ 'pane-focused': padActive && focusedPane === 'notes' }">
        <div class="right-panels">
          <NotePanel
            ref="notePanel"
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
  </div>
</template>

<script>
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import { getCoverage } from '../api/coverage.js'
import { sseClient } from '../api/events.js'
import { debounce } from '../utils/debounce.js'
import FileTree from '../components/FileTree.vue'
import CodeViewer from '../components/CodeViewer.vue'
import NotePanel from '../components/NotePanel.vue'
import OrphanPanel from '../components/OrphanPanel.vue'
import { setTargets, clearTargets } from '../input/actions.js'
import { gamepad } from '../input/gamepad.js'

// vue-router keeps a monotonically increasing `position` in each history entry's
// state. Reading it live is how JUMP_BACK knows whether the entry behind this one
// is still inside the review view: anything at or below the position CodeView
// mounted on belongs to whatever came before — the session list, an issue, or
// another site when the view was opened by a deep link.
function historyPosition() {
  const pos = window.history.state?.position
  return typeof pos === 'number' ? pos : null
}

const PANES = ['tree', 'code', 'notes']
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
  },
  props: {
    session: Object,
    coverage: Object,
    wrapLines: Boolean,
  },
  emits: ['wrap-lines-change', 'show-help', 'coverage-refreshed'],
  computed: {
    padActive() {
      return gamepad.status.value === 'connected'
    },
  },
  data() {
    return {
      id: this.$route.params.id,
      currentFile: null,
      currentNotes: [],
      focusedPane: 'code',
      pendingJump: null,
      sizes: loadSizes(),
    }
  },
  mounted() {
    this._historyFloor = historyPosition()
    const { file, line, endLine } = this.$route.query
    if (file) this.currentFile = file
    if (line) this.pendingJump = { start: parseInt(line), end: parseInt(endLine || line) }
    this.registerInputTargets()
    this._debouncedCoverage = debounce(() => this.refreshCoverage(), 250)
    this._sseUnsub = sseClient.on('file_changed', () => this._debouncedCoverage())
  },
  beforeUnmount() {
    clearTargets()
    this._sseUnsub?.()
    this._debouncedCoverage?.cancel()
  },
  watch: {
    // The route is the only way a jump reaches the viewer, including one the view
    // wrote itself — so this has to be idempotent rather than flag-guarded: a
    // cursor move replaces the query, and re-applying that as a jump would fight
    // the cursor (and, being ordering-dependent, would sometimes swallow the next
    // real jump instead).
    '$route.query'({ file, line, endLine }) {
      const jump = line ? { start: parseInt(line), end: parseInt(endLine || line) } : null
      if (file && file !== this.currentFile) {
        // A different file: the jump has to wait for the load, and lands in
        // onNotesUpdated once the new content is on screen.
        this.currentFile = file
        this.pendingJump = jump
        return
      }
      this.pendingJump = null
      const viewer = this.$refs.codeViewer
      if (!jump || !viewer) return
      // Already there — which is exactly the case for the route write a cursor
      // move just caused.
      if (viewer.rangeMin === jump.start && viewer.rangeMax === jump.end) return
      this.$nextTick(() => viewer.jumpToRange(jump.start, jump.end))
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
    onSelectionChange({ start, end }) {
      if (!this.currentFile) return
      const q = this.$route.query
      const wantLine = start != null ? String(start) : undefined
      const wantEnd = end != null && end !== start ? String(end) : undefined
      if (
        q.file === this.currentFile &&
        (q.line ?? undefined) === wantLine &&
        (q.endLine ?? undefined) === wantEnd
      ) return
      const next = { ...q, file: this.currentFile }
      if (wantLine == null) delete next.line; else next.line = wantLine
      if (wantEnd == null) delete next.endLine; else next.endLine = wantEnd
      this.$router.replace({ query: next })
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
      this.refreshCoverage()
    },
    onNoteUpdated(updated) {
      const idx = this.currentNotes.findIndex((n) => n.id === updated.id)
      if (idx !== -1) this.currentNotes.splice(idx, 1, updated)
    },
    onNoteDeleted(id) {
      this.currentNotes = this.currentNotes.filter((n) => n.id !== id)
    },
    // A definition target, always through the route and always a push — a
    // same-file jump too, because that is the one that throws away your place
    // most cheaply. The entry left behind holds the line the jump started from
    // (CodeViewer moved the cursor there before asking), so Back, Ctrl-O, and a
    // mouse's back button all return to it. Everything else in this view —
    // opening a file, moving the cursor — still replaces, which is what keeps
    // arrow-key file browsing from burying the jump list under a hundred entries.
    onGotoLocation({ filePath, line }) {
      const next = { ...this.$route.query, file: filePath, line: String(line) }
      delete next.endLine
      this.$router.push({ query: next })
    },
    // Ctrl-O / Ctrl-I. Both no-op rather than refuse when there is nowhere to go,
    // so the key stays swallowed: an action that declines to run hands Ctrl-O
    // back to the browser, which opens a file picker over the review.
    jumpBack() {
      const pos = historyPosition()
      if (pos === null || this._historyFloor === null || pos <= this._historyFloor) return
      this.$router.back()
    },
    jumpForward() {
      this.$router.forward()
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
    registerInputTargets() {
      setTargets({
        viewer: this.$refs.codeViewer,
        tree: this.$refs.fileTree,
        view: this,
      })
    },
    navFocusedPane(delta) {
      if (this.focusedPane === 'tree') {
        if (delta > 0) this.$refs.fileTree?.selectNext()
        else this.$refs.fileTree?.selectPrev()
      } else if (this.focusedPane === 'notes') {
        this.$refs.notePanel?.moveFocus(delta)
      } else {
        this.$refs.codeViewer?.moveCursor(delta)
      }
    },
    activateFocusedPane() {
      if (this.focusedPane === 'tree') this.focusedPane = 'code'
      else if (this.focusedPane === 'notes') this.$refs.notePanel?.activateFocused()
      else this.$refs.codeViewer?.markSelected()
    },
    cycleFocusedPane(delta) {
      const i = PANES.indexOf(this.focusedPane)
      this.focusedPane = PANES[(i + delta + PANES.length) % PANES.length]
    },
    scrollFocusedPane(px) {
      let el
      if (this.focusedPane === 'tree') el = this.$el.querySelector('.tree-root')
      else if (this.focusedPane === 'notes') el = this.$el.querySelector('.right-panels')
      else el = this.$refs.codeViewer?.scrollContainer()
      if (el) el.scrollTop += px
    },
    toggleWrap() {
      this.$emit('wrap-lines-change', !this.wrapLines)
    },
    requestHelp() {
      this.$emit('show-help')
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

.pane-focused {
  box-shadow: inset 0 0 0 2px var(--status-success);
}

:deep(.splitpanes__pane) > * {
  flex: 1;
  min-height: 0;
}
</style>
