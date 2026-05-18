<template>
  <div class="code-viewer-main" :class="{ 'wrap-lines': wrapLines }" ref="container" style="position:relative">
    <div v-if="!filePath" class="no-file">Select a file from the tree.</div>
    <div v-else-if="loading" class="no-file">Loading…</div>
    <div v-else-if="error" class="no-file error-text">{{ error }}</div>
    <template v-else>
      <table class="code-table" @mouseleave="onTableMouseLeave">
        <tbody>
          <LineRow
            v-for="line in lines"
            :key="line.line_no"
            :line="line"
            :isSelected="isInRange(line.line_no)"
            :isCursor="line.line_no === cursorLine"
            :isAnchor="line.line_no === anchorLine"
            :severity="lineSeverityMap[line.line_no] || null"
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
      :startLine="rangeMin"
      :endLine="rangeMax"
      @submit="onNoteSubmit"
      @pick-issue="onPickIssue"
      @cancel="showModal = false"
    />
    <IssuePickerModal
      v-if="showIssuePicker"
      :sessionId="sessionId"
      :startLine="rangeMin"
      :endLine="rangeMax"
      @picked="onIssuePicked"
      @cancel="showIssuePicker = false"
    />
  </div>
</template>

<script>
import { getFile } from '../api/files.js'
import { markLines } from '../api/lines.js'
import { createNote } from '../api/notes.js'
import { sseClient } from '../api/events.js'
import LineRow from './LineRow.vue'
import CreateNoteModal from './CreateNoteModal.vue'
import IssuePickerModal from './IssuePickerModal.vue'

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
  components: { LineRow, CreateNoteModal, IssuePickerModal },
  props: {
    sessionId: [String, Number],
    filePath: { type: String, default: null },
    wrapLines: { type: Boolean, default: false },
  },
  emits: ['notes-updated', 'lines-marked', 'file-reloaded', 'show-help', 'selection-change'],
  data() {
    return {
      lines: [],
      notes: [],
      cursorLine: null,
      anchorLine: null,
      dragStart: null,
      showModal: false,
      modalIsTodo: false,
      showIssuePicker: false,
      pendingNote: null,
      loading: false,
      error: null,
    }
  },
  computed: {
    rangeMin() {
      if (this.cursorLine === null) return null
      const a = this.anchorLine ?? this.cursorLine
      return Math.min(a, this.cursorLine)
    },
    rangeMax() {
      if (this.cursorLine === null) return null
      const a = this.anchorLine ?? this.cursorLine
      return Math.max(a, this.cursorLine)
    },
    selectionRange() {
      return [this.rangeMin, this.rangeMax]
    },
    lineSeverityMap() {
      const RANK = { P0: 3, P1: 2, P2: 1, NONE: 0 }
      const map = {}
      for (const note of this.notes) {
        if (note.is_orphaned) continue
        const sev = note.issue_id ? (note.issue_severity || 'NONE') : 'NONE'
        for (let ln = note.start_line; ln <= note.end_line; ln++) {
          if (!map[ln] || RANK[sev] > RANK[map[ln]]) {
            map[ln] = sev
          }
        }
      }
      return map
    },
  },
  watch: {
    filePath(newPath) {
      if (newPath) {
        this.cursorLine = null
        this.anchorLine = null
        this.dragStart = null
        this.loadFile(newPath)
      }
    },
    selectionRange: {
      handler([start, end]) {
        this.$emit('selection-change', { start, end })
      },
    },
  },
  created() {
    this._loadToken = 0
  },
  mounted() {
    this._keyHandler = this.onKeyDown.bind(this)
    document.addEventListener('keydown', this._keyHandler)
    this._mouseUpHandler = this.onDocMouseUp.bind(this)
    document.addEventListener('mouseup', this._mouseUpHandler)

    this._sseFileUnsub = sseClient.on('file_changed', async (data) => {
      if (data.rel_path !== this.filePath) return
      await this.loadFile(this.filePath)
      this.$emit('file-reloaded')
    })

    this._sseAnnoUnsub = sseClient.on('annotation_changed', (data) => {
      if (!this.filePath || data.kind !== 'note') return
      if (data.action === 'delete') {
        if (data.file_path && data.file_path !== this.filePath) return
        const before = this.notes.length
        this.notes = this.notes.filter((n) => n.id !== data.id)
        if (this.notes.length !== before) this.$emit('notes-updated', this.notes)
        return
      }
      const note = data.note
      if (!note || note.file_path !== this.filePath) return
      const idx = this.notes.findIndex((n) => n.id === note.id)
      if (idx === -1) this.notes.push(note)
      else this.notes.splice(idx, 1, note)
      this.$emit('notes-updated', this.notes)
    })

    if (this.filePath) {
      this.loadFile(this.filePath)
    }
  },
  beforeUnmount() {
    document.removeEventListener('keydown', this._keyHandler)
    document.removeEventListener('mouseup', this._mouseUpHandler)
    this._sseFileUnsub?.()
    this._sseAnnoUnsub?.()
  },
  methods: {
    async loadFile(path) {
      const token = ++this._loadToken
      this.loading = true
      this.error = null
      try {
        const data = await getFile(this.sessionId, path)
        if (token !== this._loadToken) return
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
        if (token !== this._loadToken) return
        this.error = e.message
      } finally {
        if (token === this._loadToken) this.loading = false
      }
    },

    jumpToRange(start, end) {
      this.cursorLine = end
      this.anchorLine = start !== end ? start : null
      this.$nextTick(() => {
        const el = this.$refs.container?.querySelector(`[data-line-no="${start}"]`)
        el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      })
    },

    isInRange(lineNo) {
      if (this.rangeMin === null) return false
      return lineNo >= this.rangeMin && lineNo <= this.rangeMax
    },

    onDragStart(lineNo) {
      this.dragStart = lineNo
      this.cursorLine = lineNo
      this.anchorLine = null
    },

    onDragMove(lineNo) {
      if (this.dragStart === null) return
      this.cursorLine = lineNo
      this.anchorLine = lineNo === this.dragStart ? null : this.dragStart
    },

    onDragEnd(lineNo) {
      if (this.dragStart === null) return
      this.cursorLine = lineNo
      this.anchorLine = lineNo === this.dragStart ? null : this.dragStart
      this.dragStart = null
    },

    moveCursor(delta) {
      if (this.lines.length === 0) return
      const first = this.lines[0].line_no
      const last = this.lines[this.lines.length - 1].line_no
      let n
      if (this.cursorLine === null) {
        n = first
      } else {
        n = Math.max(first, Math.min(last, this.cursorLine + delta))
      }
      this.cursorLine = n
      this.scrollCursorIntoView()
    },

    jumpEmpty(direction) {
      if (this.lines.length === 0) return
      const idxByLineNo = new Map()
      this.lines.forEach((l, i) => idxByLineNo.set(l.line_no, i))
      let idx
      if (this.cursorLine === null) {
        idx = direction > 0 ? -1 : this.lines.length
      } else {
        idx = idxByLineNo.get(this.cursorLine) ?? 0
      }
      const isEmpty = (i) => this.lines[i].content.trim() === ''
      let i = idx + direction
      while (i >= 0 && i < this.lines.length && isEmpty(i)) i += direction
      while (i >= 0 && i < this.lines.length) {
        if (isEmpty(i)) {
          this.cursorLine = this.lines[i].line_no
          this.scrollCursorIntoView()
          return
        }
        i += direction
      }
      const fallback = direction > 0
        ? this.lines[this.lines.length - 1].line_no
        : this.lines[0].line_no
      this.cursorLine = fallback
      this.scrollCursorIntoView()
    },

    toggleAnchor() {
      if (this.cursorLine === null) {
        if (this.lines.length === 0) return
        this.cursorLine = this.lines[0].line_no
        this.scrollCursorIntoView()
      }
      if (this.anchorLine === this.cursorLine) {
        this.anchorLine = null
      } else {
        this.anchorLine = this.cursorLine
      }
    },

    scrollCursorIntoView() {
      if (this.cursorLine === null) return
      this.$nextTick(() => {
        const el = this.$refs.container?.querySelector(`[data-line-no="${this.cursorLine}"]`)
        el?.scrollIntoView({ block: 'nearest' })
      })
    },

    onDocMouseUp() {
      this.dragStart = null
    },

    onTableMouseLeave() {
    },

    selectedRangeLines() {
      if (this.rangeMin === null) return []
      return this.lines.filter(
        (l) => l.line_no >= this.rangeMin && l.line_no <= this.rangeMax,
      )
    },

    onKeyDown(e) {
      if (this.showModal) return
      if (document.querySelector('.modal-overlay')) return
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return

      const key = e.key

      if (key === '?') {
        e.preventDefault()
        this.$emit('show-help')
        return
      }

      if (key === 'Escape') {
        this.cursorLine = null
        this.anchorLine = null
        return
      }

      if (key === 'j') {
        e.preventDefault()
        this.moveCursor(1)
        return
      }

      if (key === 'k') {
        e.preventDefault()
        this.moveCursor(-1)
        return
      }

      if (key === '{') {
        e.preventDefault()
        this.jumpEmpty(-1)
        return
      }

      if (key === '}') {
        e.preventDefault()
        this.jumpEmpty(1)
        return
      }

      if (key === 'v' || key === ' ') {
        e.preventDefault()
        this.toggleAnchor()
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
      this.anchorLine = null
    },

    async unmarkSelected() {
      const rangeLines = this.selectedRangeLines()
      if (rangeLines.length === 0) return
      await this.doMark(rangeLines, false)
      this.anchorLine = null
    },

    async doMark(rangeLines, reviewed) {
      try {
        const resp = await markLines(this.sessionId, {
          file_path: this.filePath,
          lines: rangeLines.map((l) => ({
            line_hash: l.line_hash,
            context_hash: l.context_hash,
            line_no: l.line_no,
          })),
          reviewed,
        })
        const acceptedKeys = new Set(
          (resp.accepted || []).map((a) => `${a.line_hash}|${a.context_hash}|${a.line_no}`),
        )
        const useResp = resp.accepted !== undefined
        for (const l of rangeLines) {
          if (!useResp || acceptedKeys.has(`${l.line_hash}|${l.context_hash}|${l.line_no}`)) {
            l.is_reviewed = reviewed
          }
        }
        if (resp.rejected && resp.rejected.length > 0) {
          console.warn('markLines: server rejected', resp.rejected)
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
        if (!this.notes.some((n) => n.id === note.id)) this.notes.push(note)
        this.$emit('notes-updated', this.notes)
        this.anchorLine = null
      } catch (e) {
        console.error('createNote error:', e.message)
      }
    },

    onPickIssue({ content, is_todo }) {
      this.pendingNote = { content, is_todo }
      this.showModal = false
      this.showIssuePicker = true
    },

    async onIssuePicked({ issue_id }) {
      this.showIssuePicker = false
      const pending = this.pendingNote || { content: '', is_todo: false }
      this.pendingNote = null
      try {
        const note = await createNote(this.sessionId, {
          file_path: this.filePath,
          start_line: this.rangeMin,
          end_line: this.rangeMax,
          content: pending.content,
          is_todo: pending.is_todo,
          issue_id,
        })
        if (!this.notes.some((n) => n.id === note.id)) this.notes.push(note)
        this.$emit('notes-updated', this.notes)
        this.anchorLine = null
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
.no-file {
  padding: 40px;
  color: var(--text-faint);
  font-size: 14px;
}

.error-text {
  color: var(--badge-orphan-text);
}
</style>
