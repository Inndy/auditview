<template>
  <div class="code-viewer-main" ref="container" style="position:relative">
    <div class="sse-indicator" :class="'sse-' + sseStatus" :title="'Live updates: ' + sseStatus">●</div>
    <div v-if="!filePath" class="no-file">Select a file from the tree.</div>
    <div v-else-if="loading" class="no-file">Loading…</div>
    <div v-else-if="error" class="no-file error-text">{{ error }}</div>
    <template v-else>
      <table
        class="code-table"
        @mouseleave="onTableMouseLeave"
        @touchstart="onTouchStart"
      >
        <tbody>
          <LineRow
            v-for="line in lines"
            :key="line.line_no"
            :line="line"
            :isSelected="isInRange(line.line_no)"
            @drag-start="onDragStart"
            @drag-move="onDragMove"
            @drag-end="onDragEnd"
          />
        </tbody>
      </table>
    </template>

    <CreateNoteModal
      :visible="showModal"
      :isTodo="modalIsTodo"
      :startLine="selectedRange.start"
      :endLine="selectedRange.end"
      @submit="onNoteSubmit"
      @cancel="showModal = false"
    />

    <Teleport to="body">
      <div v-if="selectionFromTouch && rangeMin !== null && !showModal" class="touch-action-bar">
        <button class="touch-btn" @click="touchMark">Mark</button>
        <button class="touch-btn" @click="touchUnmark">Unmark</button>
        <button class="touch-btn" @click="touchTodo">Todo</button>
        <button class="touch-btn" @click="touchNote">Note</button>
        <button class="touch-btn touch-btn-close" @click="clearSelection">✕</button>
      </div>
    </Teleport>
  </div>
</template>

<script>
import { getFile } from '../api/files.js'
import { markLines } from '../api/lines.js'
import { createNote } from '../api/notes.js'
import { SSEClient } from '../api/events.js'
import LineRow from './LineRow.vue'
import CreateNoteModal from './CreateNoteModal.vue'

const EXT_LANG = {
  py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript',
  tsx: 'typescript', vue: 'xml', html: 'html', css: 'css', scss: 'scss',
  json: 'json', md: 'markdown', sh: 'bash', bash: 'bash', go: 'go',
  rs: 'rust', c: 'c', cpp: 'cpp', h: 'c', java: 'java', rb: 'ruby',
  yaml: 'yaml', yml: 'yaml', toml: 'ini', sql: 'sql', xml: 'xml',
}

function highlightFile(hljs, path, lines) {
  const ext = path.split('.').pop().toLowerCase()
  const lang = EXT_LANG[ext]
  const src = lines.map((l) => l.content).join('\n')
  if (lang && hljs.getLanguage(lang)) {
    return hljs.highlight(src, { language: lang }).value
  }
  return hljs.highlightAuto(src).value
}

function splitHighlightedLines(html) {
  const lines = []
  const openSpans = []
  let cur = ''
  let i = 0
  while (i < html.length) {
    if (html[i] === '\n') {
      lines.push(cur + openSpans.map(() => '</span>').join(''))
      cur = openSpans.join('')
      i++
    } else if (html.startsWith('</span>', i)) {
      cur += '</span>'
      openSpans.pop()
      i += 7
    } else if (html[i] === '<') {
      const end = html.indexOf('>', i)
      const tag = html.slice(i, end + 1)
      cur += tag
      openSpans.push(tag)
      i = end + 1
    } else {
      cur += html[i++]
    }
  }
  if (cur) lines.push(cur + openSpans.map(() => '</span>').join(''))
  return lines
}

export default {
  name: 'CodeViewer',
  components: { LineRow, CreateNoteModal },
  props: {
    sessionId: [String, Number],
    filePath: { type: String, default: null },
    skipComments: { type: Boolean, default: false },
  },
  emits: ['notes-updated', 'lines-marked', 'file-reloaded', 'show-help'],
  data() {
    return {
      lines: [],
      notes: [],
      selectedRange: { start: null, end: null },
      dragStart: null,
      showModal: false,
      modalIsTodo: false,
      loading: false,
      error: null,
      sseStatus: 'disconnected',
      isTouchDevice: false,
      selectionFromTouch: false,
    }
  },
  computed: {
    rangeMin() {
      if (this.selectedRange.start === null) return null
      return Math.min(this.selectedRange.start, this.selectedRange.end ?? this.selectedRange.start)
    },
    rangeMax() {
      if (this.selectedRange.start === null) return null
      return Math.max(this.selectedRange.start, this.selectedRange.end ?? this.selectedRange.start)
    },
  },
  watch: {
    filePath(newPath) {
      if (newPath) {
        this.selectedRange = { start: null, end: null }
        this.loadFile(newPath)
      }
    },
    skipComments() {
      if (this.filePath) this.loadFile(this.filePath)
    },
  },
  mounted() {
    this.isTouchDevice = window.matchMedia('(hover: none) and (pointer: coarse)').matches
    this._touchDetectHandler = () => {
      this.isTouchDevice = true
      window.removeEventListener('touchstart', this._touchDetectHandler)
    }
    window.addEventListener('touchstart', this._touchDetectHandler, { passive: true })

    this._keyHandler = this.onKeyDown.bind(this)
    document.addEventListener('keydown', this._keyHandler)
    this._mouseUpHandler = this.onDocMouseUp.bind(this)
    document.addEventListener('mouseup', this._mouseUpHandler)

    this._sse = new SSEClient(this.sessionId)
    this._sse.on('status', ({ status }) => {
      this.sseStatus = status
    })
    this._sse.on('file_changed', (data) => {
      if (data.rel_path === this.filePath) {
        this.loadFile(this.filePath).then(() => {
          this.$emit('file-reloaded')
        })
      }
    })
    this._sse.connect()

    if (this.filePath) {
      this.loadFile(this.filePath)
    }
  },
  beforeUnmount() {
    document.removeEventListener('keydown', this._keyHandler)
    document.removeEventListener('mouseup', this._mouseUpHandler)
    window.removeEventListener('touchstart', this._touchDetectHandler)
    if (this._docTouchMove) document.removeEventListener('touchmove', this._docTouchMove)
    if (this._docTouchEnd) document.removeEventListener('touchend', this._docTouchEnd)
    if (this._sse) this._sse.disconnect()
  },
  methods: {
    async loadFile(path) {
      this.loading = true
      this.error = null
      try {
        const data = await getFile(this.sessionId, path, this.skipComments)
        const hljs = this.$hljs
        const highlightedLines = hljs
          ? splitHighlightedLines(highlightFile(hljs, path, data.lines))
          : data.lines.map((l) => this.escapeHtml(l.content))
        this.lines = data.lines.map((line, i) => ({
          ...line,
          highlightedContent: highlightedLines[i] ?? this.escapeHtml(line.content),
        }))
        this.notes = data.notes || []
        this.$emit('notes-updated', this.notes)
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },

    isInRange(lineNo) {
      if (this.rangeMin === null) return false
      return lineNo >= this.rangeMin && lineNo <= this.rangeMax
    },

    onDragStart(lineNo) {
      this.dragStart = lineNo
      this.selectedRange = { start: lineNo, end: lineNo }
      this.selectionFromTouch = false
    },

    onDragMove(lineNo) {
      if (this.dragStart !== null) {
        this.selectedRange = { start: this.dragStart, end: lineNo }
      }
    },

    onDragEnd(lineNo) {
      if (this.dragStart !== null) {
        this.selectedRange = { start: this.dragStart, end: lineNo }
        this.dragStart = null
      }
    },

    onDocMouseUp() {
      this.dragStart = null
    },

    onTableMouseLeave() {
    },

    lineNoFromPoint(x, y) {
      const el = document.elementFromPoint(x, y)
      const tr = el?.closest('tr')
      if (!tr) return null
      const gutter = tr.querySelector('.gutter-cell')
      if (!gutter) return null
      const n = parseInt(gutter.textContent, 10)
      return isNaN(n) ? null : n
    },

    onTouchStart(e) {
      const touch = e.touches[0]
      const target = document.elementFromPoint(touch.clientX, touch.clientY)
      if (!target?.closest('.gutter-cell')) return
      e.preventDefault()
      const lineNo = this.lineNoFromPoint(touch.clientX, touch.clientY)
      if (lineNo === null) return

      this.dragStart = lineNo
      this.selectedRange = { start: lineNo, end: lineNo }
      this.selectionFromTouch = true

      this._docTouchMove = (ev) => {
        ev.preventDefault()
        const t = ev.touches[0]
        const ln = this.lineNoFromPoint(t.clientX, t.clientY)
        if (ln !== null) this.onDragMove(ln)
      }
      this._docTouchEnd = (ev) => {
        ev.preventDefault()  // suppresses synthesized mousedown/click
        document.removeEventListener('touchmove', this._docTouchMove)
        document.removeEventListener('touchend', this._docTouchEnd)
        const t = ev.changedTouches[0]
        const ln = this.lineNoFromPoint(t.clientX, t.clientY)
        this.onDragEnd(ln ?? this.selectedRange.end ?? this.selectedRange.start)
        this.selectionFromTouch = true
      }
      document.addEventListener('touchmove', this._docTouchMove, { passive: false })
      document.addEventListener('touchend', this._docTouchEnd, { passive: false })
    },

    clearSelection() {
      this.selectedRange = { start: null, end: null }
      this.selectionFromTouch = false
    },

    async touchMark() {
      await this.markSelected()
      this.clearSelection()
    },

    async touchUnmark() {
      await this.unmarkSelected()
      this.clearSelection()
    },

    touchTodo() {
      this.modalIsTodo = true
      this.showModal = true
    },

    touchNote() {
      this.modalIsTodo = false
      this.showModal = true
    },

    selectedRangeLines() {
      if (this.rangeMin === null) return []
      return this.lines.filter(
        (l) => l.line_no >= this.rangeMin && l.line_no <= this.rangeMax,
      )
    },

    onKeyDown(e) {
      if (this.showModal) return
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return

      const key = e.key

      if (key === '?') {
        e.preventDefault()
        this.$emit('show-help')
        return
      }

      if (key === 'Escape') {
        this.clearSelection()
        return
      }

      if (key === 'M') {
        e.preventDefault()
        this.markWholeFile()
        return
      }

      if (key === 'U') {
        e.preventDefault()
        this.unmarkWholeFile()
        return
      }

      if (this.rangeMin === null) return

      if (key === 'm') {
        e.preventDefault()
        this.markSelected()
      } else if (key === 'u') {
        e.preventDefault()
        this.unmarkSelected()
      } else if (key === 't') {
        e.preventDefault()
        this.modalIsTodo = true
        this.showModal = true
      } else if (key === 'n') {
        e.preventDefault()
        this.modalIsTodo = false
        this.showModal = true
      }
    },

    async markWholeFile() {
      if (this.lines.length === 0) return
      const countable = this.lines.filter((l) => l.is_countable)
      const allReviewed = countable.length > 0 && countable.every((l) => l.is_reviewed)
      await this.doMark(this.lines, !allReviewed)
    },

    async unmarkWholeFile() {
      if (this.lines.length === 0) return
      await this.doMark(this.lines, false)
    },

    async markSelected() {
      const rangeLines = this.selectedRangeLines()
      if (rangeLines.length === 0) return
      const countable = rangeLines.filter((l) => l.is_countable)
      const allReviewed = countable.length > 0 && countable.every((l) => l.is_reviewed)
      const reviewed = !allReviewed
      await this.doMark(rangeLines, reviewed)
    },

    async unmarkSelected() {
      const rangeLines = this.selectedRangeLines()
      if (rangeLines.length === 0) return
      await this.doMark(rangeLines, false)
    },

    async doMark(rangeLines, reviewed) {
      try {
        await markLines(this.sessionId, {
          file_path: this.filePath,
          lines: rangeLines.map((l) => ({
            line_hash: l.line_hash,
            context_hash: l.context_hash,
            line_no: l.line_no,
          })),
          reviewed,
        })
        for (const l of rangeLines) {
          l.is_reviewed = reviewed
        }
        const countable = this.lines.filter((l) => l.is_countable).length
        const reviewedCount = this.lines.filter((l) => l.is_countable && l.is_reviewed).length
        this.$emit('lines-marked', {
          filePath: this.filePath,
          countable,
          reviewed: reviewedCount,
        })
      } catch (e) {
        console.error('markLines error:', e.message)
      }
    },

    async onNoteSubmit({ content, is_todo }) {
      this.showModal = false
      try {
        const note = await createNote(this.sessionId, {
          file_path: this.filePath,
          start_line: this.rangeMin,
          end_line: this.rangeMax,
          content,
          is_todo,
        })
        this.notes.push(note)
        this.$emit('notes-updated', this.notes)
      } catch (e) {
        console.error('createNote error:', e.message)
      }
    },

    reload() {
      if (this.filePath) this.loadFile(this.filePath)
    },

    escapeHtml(str) {
      return (str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
    },
  },
}
</script>

<style scoped>
.sse-indicator {
  position: absolute;
  top: 6px;
  right: 8px;
  font-size: 10px;
  line-height: 1;
  pointer-events: none;
}

.sse-connected    { color: #4caf50; }
.sse-connecting   { color: #ff9800; }
.sse-disconnected { color: #e53935; }

.no-file {
  padding: 40px;
  color: #aaa;
  font-size: 14px;
}

.error-text {
  color: #842029;
}

.touch-action-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 8px;
  padding: 10px 16px;
  padding-bottom: calc(10px + env(safe-area-inset-bottom));
  background: var(--bg-surface);
  border-top: 1px solid var(--border-mid);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.15);
  z-index: 200;
}

.touch-btn {
  flex: 1;
  min-height: 44px;
  border: 1px solid var(--border-mid);
  border-radius: 6px;
  background: var(--bg-surface2);
  color: var(--text);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.touch-btn:active {
  background: var(--bg-selected);
}

.touch-btn-close {
  flex: 0 0 44px;
  color: var(--text-muted);
}
</style>
