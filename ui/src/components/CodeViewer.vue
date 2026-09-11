<template>
  <div class="code-viewer-main" :class="{ 'wrap-lines': wrapLines }" ref="container" style="position:relative">
    <div v-if="!filePath" class="no-file">Select a file from the tree.</div>
    <div v-else-if="loading" class="no-file">Loading…</div>
    <div v-else-if="error" class="no-file error-text">{{ error }}</div>
    <div v-else-if="fileBlocked" class="no-file file-blocked">
      <span v-if="fileBlocked.reason === 'binary'">Binary file — not renderable as text.</span>
      <span v-else>File is large ({{ Math.round(fileBlocked.size / 1024) }} KB) and may be slow to load.</span>
      <button class="load-anyway-btn" @click="loadFile(filePath, { force: true })"><span><u>L</u>oad anyway</span></button>
    </div>
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
            @symbol-click="onSymbolClick"
            @symbol-hover="onSymbolHover"
          />
        </tbody>
      </table>
    </template>

    <div v-if="actionError" class="action-error" @click="actionError = null">{{ actionError }}</div>

    <CreateNoteModal
      :visible="showModal"
      :isTodo="modalIsTodo"
      :startLine="rangeMin"
      :endLine="rangeMax"
      @submit="onNoteSubmit"
      :initialContent="noteDraft"
      :submitting="noteSubmitting"
      @pick-issue="onPickIssue"
      @cancel="cancelNoteModal"
    />
    <LspPreviewModal
      v-if="previewTarget"
      :sessionId="sessionId"
      :path="previewTarget.path"
      :line="previewTarget.line"
      @close="previewTarget = null"
    />
    <IssuePickerModal
      v-if="showIssuePicker"
      :sessionId="sessionId"
      :startLine="rangeMin"
      :endLine="rangeMax"
      @picked="onIssuePicked"
      @cancel="cancelIssuePicker"
    />
  </div>
</template>

<script>
import { getFile } from '../api/files.js'
import { markLines } from '../api/lines.js'
import { createNote } from '../api/notes.js'
import { sseClient } from '../api/events.js'
import { gamepad } from '../input/gamepad.js'
import LineRow from './LineRow.vue'
import CreateNoteModal from './CreateNoteModal.vue'
import IssuePickerModal from './IssuePickerModal.vue'
import LspPreviewModal from './LspPreviewModal.vue'
import { getDefinition } from '../api/lsp.js'
import { columnFromPoint, wordRangeAt, rangeForColumns } from '../utils/textPosition.js'
import { highlightSource } from '../highlight.js'
import { lineIdentity, relocateLine } from '../utils/lineAnchor.js'

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
  components: { LineRow, CreateNoteModal, IssuePickerModal, LspPreviewModal },
  props: {
    sessionId: [String, Number],
    filePath: { type: String, default: null },
    wrapLines: { type: Boolean, default: false },
  },
  emits: ['notes-updated', 'lines-marked', 'file-reloaded', 'selection-change',
          'goto-location'],
  data() {
    return {
      lines: [],
      notes: [],
      cursorLine: null,
      anchorLine: null,
      dragStart: null,
      showModal: false,
      modalIsTodo: false,
      noteDraft: '',
      noteSubmitting: false,
      showIssuePicker: false,
      pendingNote: null,
      loading: false,
      error: null,
      fileBlocked: null,
      actionError: null,
      previewTarget: null,
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
    this._mouseUpHandler = this.onDocMouseUp.bind(this)
    document.addEventListener('mouseup', this._mouseUpHandler)

    this._sseFileUnsub = sseClient.on('file_changed', async (data) => {
      if (data.rel_path !== this.filePath) return
      const anchor = this.captureViewAnchor()
      // Load quietly only when there is a rendered view worth holding still. With
      // nothing on screen (a blocked or errored file) the placeholder is honest.
      await this.loadFile(this.filePath, { quiet: anchor !== null })
      // The user may have opened another file while the reload was in flight; that
      // load wins (loadFile's token discards this one) and the anchor is moot.
      if (data.rel_path !== this.filePath) return
      await this.$nextTick()
      this.restoreViewAnchor(anchor)
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
    this.clearSymbolHighlight()
    document.removeEventListener('mouseup', this._mouseUpHandler)
    this._sseFileUnsub?.()
    this._sseAnnoUnsub?.()
  },
  methods: {
    async loadFile(path, { force = false, quiet = false } = {}) {
      const token = ++this._loadToken
      // A quiet load leaves the current rows rendered instead of swapping in the
      // "Loading…" placeholder, so a watcher-driven reload does not collapse the
      // scroll container to zero height and flash the view back to the top.
      if (!quiet) this.loading = true
      this.error = null
      this.fileBlocked = null
      try {
        const data = await getFile(this.sessionId, path, { force })
        if (token !== this._loadToken) return
        const hljs = this.$hljs
        const highlightedLines = hljs
          ? splitHighlightedLines(highlightSource(hljs, path, data.lines.map((l) => l.content).join('\n')))
          : data.lines.map((l) => this.escapeHtml(l.content))
        this.lines = data.lines.map((line, i) => ({
          ...line,
          highlightedContent: highlightedLines[i] ?? this.escapeHtml(line.content),
        }))
        this.notes = data.notes || []
        this.$emit('notes-updated', this.notes)
      } catch (e) {
        if (token !== this._loadToken) return
        if (e.blocked) {
          this.fileBlocked = { reason: e.reason, size: e.size }
        } else {
          this.error = e.message
        }
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

    gotoFileEdge(edge) {
      if (this.lines.length === 0) return
      const line = edge === 'first' ? this.lines[0] : this.lines[this.lines.length - 1]
      this.cursorLine = line.line_no
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

    jumpUnreviewed(direction) {
      if (this.lines.length === 0) return
      const idxByLineNo = new Map()
      this.lines.forEach((l, i) => idxByLineNo.set(l.line_no, i))
      let idx
      if (this.cursorLine === null) {
        idx = direction > 0 ? -1 : this.lines.length
      } else {
        idx = idxByLineNo.get(this.cursorLine) ?? 0
      }
      let i = idx + direction
      while (i >= 0 && i < this.lines.length) {
        const l = this.lines[i]
        if (l.is_countable && !l.is_reviewed) {
          this.cursorLine = l.line_no
          this.scrollCursorIntoView()
          return
        }
        i += direction
      }
    },

    movePage(direction) {
      const container = this.$refs.container
      if (!container || this.lines.length === 0) return
      const probe = container.querySelector('tr[data-line-no]')
      const lineH = probe?.getBoundingClientRect().height || 18
      const rows = Math.max(1, Math.floor(container.clientHeight / lineH / 2))
      this.moveCursor(rows * direction)
    },

    cursorToViewportEdge(edge) {
      const container = this.$refs.container
      if (!container) return
      const rows = container.querySelectorAll('tr[data-line-no]')
      const cRect = container.getBoundingClientRect()
      let pick = null
      for (const tr of rows) {
        const r = tr.getBoundingClientRect()
        if (r.bottom < cRect.top || r.top > cRect.bottom) continue
        if (edge === 'top') { pick = tr; break }
        pick = tr
      }
      if (pick) {
        this.cursorLine = parseInt(pick.getAttribute('data-line-no'), 10)
      }
    },

    alignCursor(where) {
      if (this.cursorLine === null) return
      this.$nextTick(() => {
        const el = this.$refs.container?.querySelector(`[data-line-no="${this.cursorLine}"]`)
        el?.scrollIntoView({ block: where })
      })
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
      this.clearSymbolHighlight()
    },

    selectedRangeLines() {
      if (this.rangeMin === null) return []
      return this.lines.filter(
        (l) => l.line_no >= this.rangeMin && l.line_no <= this.rangeMax,
      )
    },

    clearSelection() {
      this.cursorLine = null
      this.anchorLine = null
    },

    openNoteModal(isTodo) {
      this.modalIsTodo = isTodo
      this.noteDraft = ''
      this.pendingNote = null
      this.showModal = true
    },

    cancelNoteModal() {
      this.noteDraft = ''
      this.pendingNote = null
      this.showModal = false
    },

    cancelIssuePicker() {
      this.showIssuePicker = false
      this.showModal = true
    },

    scrollContainer() {
      return this.$refs.container || null
    },

    // Snapshot enough of the current view to put it back after the content is
    // replaced: the identity of one anchor line plus where it sat in the
    // viewport. Must be called while the old rows are still in the DOM.
    captureViewAnchor() {
      const container = this.$refs.container
      if (!container || this.lines.length === 0) return null
      const containerTop = container.getBoundingClientRect().top

      const cursorLine = this.cursorLine
      let row = cursorLine !== null
        ? container.querySelector(`tr[data-line-no="${cursorLine}"]`)
        : null
      const onCursor = row !== null
      if (!row) {
        // No cursor to anchor on — use the topmost row still touching the
        // viewport so a plain scrolled-to position survives the reload too.
        for (const tr of container.querySelectorAll('tr[data-line-no]')) {
          if (tr.getBoundingClientRect().bottom > containerTop) { row = tr; break }
        }
      }
      if (!row) return null

      const ident = lineIdentity(this.lines, parseInt(row.getAttribute('data-line-no'), 10))
      if (!ident) return null
      return {
        ident,
        // Offset of the anchor row from the top of the viewport. Negative when
        // the row is scrolled off the top edge, which is worth keeping: it is
        // what holds the view still when the cursor is out of sight.
        offsetY: row.getBoundingClientRect().top - containerTop,
        scrollLeft: container.scrollLeft,
        onCursor,
        cursorLine,
        selectionAnchor: onCursor && this.anchorLine !== null
          ? lineIdentity(this.lines, this.anchorLine)
          : null,
      }
    },

    // Put the view back where captureViewAnchor() found it. Best-effort: if the
    // anchor line is gone from the new content, or something moved the cursor
    // while the reload was in flight, leave the view alone.
    restoreViewAnchor(anchor) {
      const container = this.$refs.container
      if (!anchor || !container || this.lines.length === 0) return
      // A deliberate jump — a note click, `?line=` in the URL, go-to-definition —
      // landed during the reload. That outranks restoring where we used to be.
      if (this.cursorLine !== anchor.cursorLine) return

      const lineNo = relocateLine(this.lines, anchor.ident)
      if (lineNo === null) return

      if (anchor.onCursor) {
        this.cursorLine = lineNo
        this.anchorLine = relocateLine(this.lines, anchor.selectionAnchor)
      }

      const row = container.querySelector(`tr[data-line-no="${lineNo}"]`)
      if (!row) return
      // Nudge by the difference rather than assigning an absolute scrollTop, so
      // container padding and any sticky chrome stay out of the arithmetic. The
      // browser clamps at the ends of a file that has since grown or shrunk.
      const top = row.getBoundingClientRect().top - container.getBoundingClientRect().top
      container.scrollTop += top - anchor.offsetY
      container.scrollLeft = anchor.scrollLeft
    },

    // --- symbol navigation ----------------------------------------------
    //
    // Ctrl/Cmd+click rather than plain click, because plain click is the
    // line-range drag. The click is also what makes this possible at all: it
    // carries an exact column, which the line-only cursor cannot.
    async onSymbolClick({ lineNo, clientX, clientY, cell }) {
      this.clearSymbolHighlight()
      const character = columnFromPoint(cell, clientX, clientY)
      if (character === null) return
      // Put the line cursor on the clicked line before the request goes out. The
      // cursor is what CodeView writes into the URL, so by the time a target comes
      // back the entry being left behind already records where the jump started —
      // one navigation, no second write racing the push. No scroll: the line was
      // just clicked, so it is on screen.
      this.cursorLine = lineNo
      this.anchorLine = null
      let result
      try {
        result = await getDefinition(this.sessionId, {
          filePath: this.filePath, line: lineNo, character,
        })
      } catch (e) {
        this.actionError = `Definition lookup failed: ${e.message}`
        return
      }
      if (result.reason === 'disabled') {
        this.actionError = 'Symbol navigation is off — restart with --lsp to enable it.'
        return
      }
      if (result.reason === 'no_provider') {
        this.actionError = `No language server configured for ${result.detail}`
        return
      }
      const target = result.in_root[0]
      if (target) {
        this.$emit('goto-location', { filePath: target.file_path, line: target.line })
        return
      }
      // Definitions in a dependency or a stdlib are the common case, not an
      // edge one, so say something useful instead of nothing.
      const external = result.out_of_root[0]
      if (external) {
        this.previewTarget = { path: external.path, line: external.line }
        return
      }
      this.actionError = 'No definition found'
    },

    onSymbolHover(payload) {
      if (payload === null) {
        this.clearSymbolHighlight()
        return
      }
      if (!window.CSS || !CSS.highlights) return
      const { lineNo, clientX, clientY, cell } = payload
      const line = this.lines.find((l) => l.line_no === lineNo)
      const col = columnFromPoint(cell, clientX, clientY)
      if (!line || col === null) {
        this.clearSymbolHighlight()
        return
      }
      const bounds = wordRangeAt(line.content, col)
      if (bounds === null) {
        this.clearSymbolHighlight()
        return
      }
      const range = rangeForColumns(cell, bounds[0], bounds[1])
      if (range === null) {
        this.clearSymbolHighlight()
        return
      }
      // The Custom Highlight API decorates a Range without inserting nodes, so
      // the highlighted markup from hljs is left exactly as rendered.
      CSS.highlights.set('lsp-symbol', new Highlight(range))
    },

    clearSymbolHighlight() {
      if (window.CSS && CSS.highlights) CSS.highlights.delete('lsp-symbol')
    },

    async markWholeFile() {
      if (this.lines.length === 0) return
      const countable = this.lines.filter((l) => l.is_countable)
      const allReviewed = countable.length > 0 && countable.every((l) => l.is_reviewed)
      await this.doMark(countable, !allReviewed)
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
      await this.doMark(reviewed ? countable : rangeLines, reviewed)
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
        gamepad.rumble()
      } catch (e) {
        this.actionError = `Failed to mark lines: ${e.message}`
      }
    },

    async onNoteSubmit({ content, is_todo }) {
      if (this.noteSubmitting) return
      this.noteDraft = content
      this.noteSubmitting = true
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
        this.noteDraft = ''
        this.showModal = false
      } catch (e) {
        this.actionError = `Failed to create note: ${e.message}`
      } finally {
        this.noteSubmitting = false
      }
    },

    onPickIssue({ content, is_todo }) {
      this.noteDraft = content
      this.pendingNote = { content, is_todo }
      this.showModal = false
      this.showIssuePicker = true
    },

    async onIssuePicked({ issue_id }) {
      if (this.noteSubmitting) return
      this.showIssuePicker = false
      const pending = this.pendingNote || { content: '', is_todo: false }
      this.noteSubmitting = true
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
        this.pendingNote = null
        this.noteDraft = ''
      } catch (e) {
        this.actionError = `Failed to create note: ${e.message}`
        this.showModal = true
      } finally {
        this.noteSubmitting = false
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

.file-blocked {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-start;
}

.load-anyway-btn {
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
  background: var(--bg-elevated, #2a2a2a);
  color: var(--text-base, #ccc);
  border: 1px solid var(--border, #555);
  border-radius: 4px;
}

.load-anyway-btn:hover {
  background: var(--bg-hover, #3a3a3a);
}

.action-error {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
  border: 1px solid var(--danger);
  border-radius: 4px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
  z-index: 10;
  white-space: nowrap;
}
</style>
