<template>
  <div class="issues-view">
    <div v-if="loadingIssues" class="loading">Loading issues…</div>
    <div v-else-if="loadError" class="load-error">
      Failed to load issues: {{ loadError }}
      <button class="btn-link" @click="load">Retry</button>
    </div>
    <Splitpanes v-else class="issues-content" @resized="onResized">
      <Pane :size="sizes[0]" :min-size="12">
        <div class="issues-panel">
          <div class="panel-header">
            <h3>Issues</h3>
            <div class="filters">
              <router-link
                v-for="opt in filterOptions"
                :key="opt.value"
                class="filter-btn"
                :class="{ active: statusFilter === opt.value }"
                :to="filterRoute(opt.value)"
              >{{ opt.label }}</router-link>
            </div>
          </div>
          <div v-if="filteredIssues.length === 0" class="empty">No issues.</div>
          <div v-else class="issues-list">
            <router-link
              v-for="issue in filteredIssues"
              :key="issue.id"
              :to="issueRoute(issue.id)"
              class="issue-item"
              :class="{ selected: selectedIssueId === issue.id }"
            >
              <div class="issue-header">
                <span class="severity-badge" :class="'severity-' + issue.severity">{{ issue.severity }}</span>
                <span class="title">{{ issue.title }}</span>
              </div>
              <div class="issue-meta">
                <span class="status-pill" :class="'status-' + issue.status">{{ issue.status }}</span>
                <span class="meta-date">{{ formatDate(issue.created_at) }}</span>
              </div>
            </router-link>
          </div>
        </div>
      </Pane>
      <Pane :size="sizes[1]" :min-size="30">
        <div v-if="selectedIssueId" class="details-panel">
        <div class="panel-header">
          <h3>Issue #{{ selectedIssueId }}</h3>
          <div class="panel-header-actions">
            <button
              v-if="selectedIssueStale && !editTargetDeleted"
              class="stale-pill"
              title="Updated elsewhere while editing — click to refresh"
              @click="refreshSelected"
            >● Updated · Refresh</button>
            <router-link :to="closeRoute" class="btn btn-icon" title="Back to list">✕</router-link>
          </div>
        </div>
        <div v-if="editTargetDeleted" class="deleted-banner">
          This issue was deleted in another tab.
          <button class="btn-link" @click="dismissDeletedBanner">Dismiss</button>
        </div>
        <div v-if="editError" class="edit-error-banner">
          {{ editError }}
          <button class="btn-link" @click="editError = null">Dismiss</button>
        </div>
        <div v-if="selectedIssue" class="issue-details">
          <div class="detail-row">
            <label>Title</label>
            <input
              v-model="selectedIssue.title"
              @focus="rememberTitle"
              @blur="updateField('title')"
              type="text"
            />
          </div>
          <div class="detail-row">
            <label>Severity</label>
            <select v-model="selectedIssue.severity" @focus="rememberSeverity" @change="updateField('severity')">
              <option value="P0">P0</option>
              <option value="P1">P1</option>
              <option value="P2">P2</option>
            </select>
          </div>
          <div class="detail-row">
            <label class="label-with-action">
              Description
              <button
                v-if="!editingDescription"
                class="btn-link"
                @click="startEditDescription"
              >{{ selectedIssue.description ? 'Edit' : 'Add' }}</button>
            </label>
            <textarea
              v-if="editingDescription"
              ref="descriptionEditor"
              v-model="descriptionDraft"
              class="description-editor"
              rows="6"
              placeholder="Markdown supported"
              @blur="saveDescription"
              @keydown.esc="cancelEditDescription"
            ></textarea>
            <MarkdownView
              v-else-if="selectedIssue.description"
              class="description-rendered"
              :source="selectedIssue.description"
            />
            <div
              v-else
              class="description-empty"
              @click="startEditDescription"
            >No description.</div>
          </div>
          <div class="detail-row">
            <div class="field-label">
              <span class="field-label-text">Status</span>
              <span class="status-pill" :class="'status-' + selectedIssue.status">{{ selectedIssue.status }}</span>
            </div>
            <div class="status-actions">
              <template v-if="selectedIssue.status === 'open'">
                <button class="btn-action btn-outline-success" @click="setStatus('resolved')">Resolve</button>
                <button class="btn-action btn-outline-muted" @click="setStatus('dismissed')">Dismiss</button>
              </template>
              <template v-else>
                <button class="btn-action btn-ghost" @click="setStatus('open')">Reopen</button>
              </template>
              <button class="btn-action btn-outline-danger" @click="onDeleteIssue">Delete</button>
            </div>
          </div>

          <div v-if="selectedIssue.source || selectedIssue.closed_by" class="detail-row actor-row">
            <span v-if="selectedIssue.source" class="actor-field">Opened by <code>{{ selectedIssue.source }}</code></span>
            <span v-if="selectedIssue.closed_by" class="actor-field">Closed by <code>{{ selectedIssue.closed_by }}</code></span>
          </div>

          <div class="notes-section">
            <h4>Attached Notes</h4>
            <div v-if="issueNotes.length === 0" class="empty-notes">No notes attached.</div>
            <div v-else class="notes-list">
              <router-link
                v-for="note in issueNotes"
                :key="note.id"
                :to="`/sessions/${session.id}/code?file=${encodeURIComponent(note.file_path)}&line=${note.start_line}&endLine=${note.end_line}`"
                class="note-item note-link"
              >
                <div class="note-file">{{ note.file_path }}:{{ note.start_line }}</div>
                <div class="note-content">{{ note.content || '(no content)' }}</div>
              </router-link>
            </div>
          </div>
        </div>
        <div v-else class="empty">Issue not found.</div>
      </div>
        <div v-else class="details-panel no-selection">
          <div class="no-selection-hint">Select an issue to view details</div>
        </div>
      </Pane>
      <Pane :size="sizes[2]" :min-size="12">
        <div class="orphan-panel">
          <div class="panel-header">
            <h3>Standalone TODOs</h3>
            <span class="count">{{ orphanNotes.length }}</span>
          </div>
          <div v-if="orphanNotes.length === 0" class="empty">All notes are organized!</div>
          <div v-else class="notes-list">
            <div
              v-for="note in orphanNotes"
              :key="note.id"
              class="note-item"
              :class="{ selected: selectedNoteIds.includes(note.id) }"
              @click="toggleNoteSelection(note.id)"
            >
              <input type="checkbox" :checked="selectedNoteIds.includes(note.id)" class="note-checkbox" />
              <div class="note-info">
                <router-link
                  class="note-file note-file-link"
                  :to="`/sessions/${session.id}/code?file=${encodeURIComponent(note.file_path)}&line=${note.start_line}&endLine=${note.end_line}`"
                  @click.stop
                >{{ note.file_path }}:{{ note.start_line }}-{{ note.end_line }}</router-link>
                <div class="note-content">{{ note.content }}</div>
              </div>
            </div>
          </div>

          <div v-if="selectedNoteIds.length > 0" class="action-bar">
            <span>{{ selectedNoteIds.length }} selected</span>
            <div class="action-bar-btns">
              <button
                v-if="selectedIssueId"
                class="btn-outline-primary"
                :disabled="attaching"
                @click="attachSelectedToCurrentIssue"
              >{{ attaching ? 'Adding…' : `Add to #${selectedIssueId}` }}</button>
              <button class="btn-primary" @click="showCreateIssueModal = true">Create Issue</button>
            </div>
          </div>
        </div>
      </Pane>
    </Splitpanes>

    <CreateIssueModal
      v-if="showCreateIssueModal"
      :selectedNoteIds="selectedNoteIds"
      :sessionId="session.id"
      @created="onIssueCreated"
      @close="showCreateIssueModal = false"
    />
  </div>
</template>

<script>
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import { listIssues, updateIssue as apiUpdateIssue, deleteIssue as apiDeleteIssue, getIssueNotes, attachNoteToIssue } from '../api/issues.js'
import { listNotes } from '../api/notes.js'
import { sseClient } from '../api/events.js'
import CreateIssueModal from '../components/CreateIssueModal.vue'
import MarkdownView from '../components/MarkdownView.vue'

const FILTER_OPTIONS = [
  { value: 'all', label: 'all' },
  { value: 'open', label: 'open' },
  { value: 'resolved', label: 'resolved' },
  { value: 'dismissed', label: 'dismissed' },
]

const LAYOUT_STORAGE_KEY = 'auditview:layout:issues-panes'
const DEFAULT_SIZES = [22, 56, 22]

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
  name: 'IssuesView',
  components: { Splitpanes, Pane, CreateIssueModal, MarkdownView },
  props: {
    session: Object,
  },
  data() {
    return {
      issues: [],
      orphanNotes: [],
      issueNotes: [],
      loadingIssues: true,
      loadError: null,
      editError: null,
      selectedNoteIds: [],
      attaching: false,
      showCreateIssueModal: false,
      filterOptions: FILTER_OPTIONS,
      titleBeforeEdit: '',
      severityBeforeEdit: '',
      editingDescription: false,
      descriptionDraft: '',
      descriptionBeforeEdit: '',
      editTargetDeleted: false,
      selectedIssueStale: false,
      sizes: loadSizes(),
    }
  },
  computed: {
    statusFilter() {
      return this.$route.query.status ?? 'open'
    },
    selectedIssueId() {
      const id = this.$route.params.issueId
      return id ? parseInt(id) : null
    },
    filteredIssues() {
      if (this.statusFilter === 'all') return this.issues
      return this.issues.filter((i) => i.status === this.statusFilter)
    },
    selectedIssue() {
      return this.issues.find((i) => i.id === this.selectedIssueId)
    },
    closeRoute() {
      return { path: `/sessions/${this.session.id}/issues`, query: { status: this.statusFilter } }
    },
  },
  mounted() {
    this.load()
    this._sseUnsub = sseClient.on('annotation_changed', (data) => this.applyAnnotationEvent(data))
  },
  beforeUnmount() {
    this._sseUnsub?.()
  },
  watch: {
    selectedIssueId(id) {
      this.titleBeforeEdit = ''
      this.severityBeforeEdit = ''
      this.editingDescription = false
      this.descriptionDraft = ''
      this.descriptionBeforeEdit = ''
      this.editTargetDeleted = false
      this.selectedIssueStale = false
      this.editError = null
      if (id) {
        this.loadIssueNotes(id)
      } else {
        this.issueNotes = []
      }
    },
  },
  methods: {
    async load() {
      this.loadingIssues = true
      this.loadError = null
      try {
        const [issues, notes] = await Promise.all([
          listIssues(this.session.id),
          listNotes(this.session.id),
        ])
        this.issues = issues
        this.orphanNotes = notes.filter((n) => !n.issue_id && !n.is_orphaned)
        if (this.selectedIssueId) {
          this.loadIssueNotes(this.selectedIssueId)
        }
      } catch (e) {
        this.loadError = e.message
      } finally {
        this.loadingIssues = false
      }
    },

    applyAnnotationEvent(data) {
      if (data.kind === 'issue') {
        if (data.action === 'delete') {
          this.issues = this.issues.filter((i) => i.id !== data.id)
          if (data.id === this.selectedIssueId) this.editTargetDeleted = true
          return
        }
        const issue = data.issue
        if (!issue) return
        if (issue.id === this.selectedIssueId && this.editingDescription) {
          this.selectedIssueStale = true
          return
        }
        const idx = this.issues.findIndex((i) => i.id === issue.id)
        if (idx === -1) this.issues.push(issue)
        else this.issues.splice(idx, 1, issue)
        return
      }
      if (data.kind !== 'note') return
      if (data.action === 'delete') {
        this.issueNotes = this.issueNotes.filter((n) => n.id !== data.id)
        this.orphanNotes = this.orphanNotes.filter((n) => n.id !== data.id)
        return
      }
      const note = data.note
      if (!note) return
      const inSelectedIssue = this.selectedIssueId && note.issue_id === this.selectedIssueId
      const inOrphanList = !note.issue_id && !note.is_orphaned
      const aIdx = this.issueNotes.findIndex((n) => n.id === note.id)
      if (inSelectedIssue) {
        if (aIdx === -1) this.issueNotes.push(note)
        else this.issueNotes.splice(aIdx, 1, note)
      } else if (aIdx !== -1) {
        this.issueNotes.splice(aIdx, 1)
      }
      const oIdx = this.orphanNotes.findIndex((n) => n.id === note.id)
      if (inOrphanList) {
        if (oIdx === -1) this.orphanNotes.push(note)
        else this.orphanNotes.splice(oIdx, 1, note)
      } else if (oIdx !== -1) {
        this.orphanNotes.splice(oIdx, 1)
      }
    },

    async refreshSelected() {
      if (!this.selectedIssueId) return
      try {
        const issues = await listIssues(this.session.id)
        const fresh = issues.find((i) => i.id === this.selectedIssueId)
        if (!fresh) {
          this.editTargetDeleted = true
          this.selectedIssueStale = false
          return
        }
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, fresh)
        await this.loadIssueNotes(this.selectedIssueId)
        this.selectedIssueStale = false
      } catch (e) {
        console.warn('Failed to refresh selected issue:', e.message)
      }
    },

    dismissDeletedBanner() {
      this.editTargetDeleted = false
      this.$router.push(this.closeRoute)
    },
    async loadIssueNotes(issueId) {
      try {
        this.issueNotes = await getIssueNotes(this.session.id, issueId)
      } catch (e) {
        console.error('Failed to load issue notes:', e.message)
      }
    },
    issueRoute(id) {
      const query = this.statusFilter ? { status: this.statusFilter } : {}
      return { path: `/sessions/${this.session.id}/issues/${id}`, query }
    },
    filterRoute(value) {
      const path = this.selectedIssueId
        ? `/sessions/${this.session.id}/issues/${this.selectedIssueId}`
        : `/sessions/${this.session.id}/issues`
      return { path, query: { status: value } }
    },
    toggleNoteSelection(noteId) {
      const idx = this.selectedNoteIds.indexOf(noteId)
      if (idx !== -1) {
        this.selectedNoteIds.splice(idx, 1)
      } else {
        this.selectedNoteIds.push(noteId)
      }
    },
    rememberTitle() {
      this.titleBeforeEdit = this.selectedIssue?.title || ''
    },
    rememberSeverity() {
      this.severityBeforeEdit = this.selectedIssue?.severity || ''
    },
    startEditDescription() {
      if (!this.selectedIssue) return
      this.descriptionBeforeEdit = this.selectedIssue.description || ''
      this.descriptionDraft = this.descriptionBeforeEdit
      this.editingDescription = true
      this.$nextTick(() => this.$refs.descriptionEditor?.focus())
    },
    cancelEditDescription() {
      this.editingDescription = false
      this.descriptionDraft = ''
    },
    async saveDescription() {
      if (!this.editingDescription || !this.selectedIssue) return
      this.editingDescription = false
      const value = this.descriptionDraft
      if (value === this.descriptionBeforeEdit) return
      try {
        const updated = await apiUpdateIssue(
          this.session.id,
          this.selectedIssueId,
          { description: value },
        )
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, updated)
      } catch (e) {
        if (this.selectedIssue) this.selectedIssue.description = this.descriptionBeforeEdit
        this.editError = `Failed to save description: ${e.message}`
      }
    },
    async updateField(field) {
      if (!this.selectedIssue) return
      const value = this.selectedIssue[field]
      if (field === 'title' && (typeof value !== 'string' || value.trim() === '')) {
        this.selectedIssue.title = this.titleBeforeEdit
        return
      }
      const before = field === 'title' ? this.titleBeforeEdit : this.severityBeforeEdit
      try {
        const updates = {}
        updates[field] = value
        const updated = await apiUpdateIssue(this.session.id, this.selectedIssueId, updates)
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, updated)
      } catch (e) {
        if (this.selectedIssue) this.selectedIssue[field] = before
        this.editError = `Failed to update ${field}: ${e.message}`
      }
    },
    async setStatus(newStatus) {
      if (!this.selectedIssue) return
      const prevStatus = this.selectedIssue.status
      try {
        const updated = await apiUpdateIssue(this.session.id, this.selectedIssueId, { status: newStatus })
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, updated)
      } catch (e) {
        if (this.selectedIssue) this.selectedIssue.status = prevStatus
        this.editError = `Failed to update status: ${e.message}`
      }
    },
    async onDeleteIssue() {
      if (!confirm('Delete this issue?')) return
      try {
        const issueId = this.selectedIssueId
        await apiDeleteIssue(this.session.id, issueId)
        this.issues = this.issues.filter((i) => i.id !== issueId)
        this.$router.push(this.closeRoute)
      } catch (e) {
        console.error('Failed to delete:', e.message)
      }
    },
    onIssueCreated(issue) {
      if (!this.issues.some((i) => i.id === issue.id)) this.issues.push(issue)
      this.orphanNotes = this.orphanNotes.filter((n) => !this.selectedNoteIds.includes(n.id))
      this.selectedNoteIds = []
      this.showCreateIssueModal = false
    },
    async attachSelectedToCurrentIssue() {
      if (!this.selectedIssueId || this.selectedNoteIds.length === 0 || this.attaching) return
      const targetIssueId = this.selectedIssueId
      const noteIds = [...this.selectedNoteIds]
      this.attaching = true
      try {
        const results = await Promise.allSettled(
          noteIds.map((nid) => attachNoteToIssue(this.session.id, nid, targetIssueId)),
        )
        const failed = results.filter((r) => r.status === 'rejected')
        if (failed.length > 0) {
          this.editError = `Failed to attach ${failed.length} of ${noteIds.length} note(s): ${failed[0].reason?.message || 'Unknown error'}`
        }
        const reloadNotes = this.selectedIssueId === targetIssueId
        await this.load()
        if (reloadNotes) {
          await this.loadIssueNotes(targetIssueId)
        }
        this.selectedNoteIds = []
      } finally {
        this.attaching = false
      }
    },
    formatDate(isoString) {
      return new Date(isoString).toLocaleDateString()
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
  },
}
</script>

<style scoped>
.issues-view {
  display: flex;
  flex: 1;
  overflow: hidden;
  background: var(--bg-surface);
}

.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-muted);
}

.load-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex: 1;
  color: var(--badge-orphan-text);
  font-size: 13px;
}

.issues-content {
  flex: 1;
  overflow: hidden;
  background: var(--bg-base);
}

.issues-panel,
.details-panel,
.orphan-panel {
  background: var(--bg-surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;
}

.panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.panel-header .count {
  font-size: 12px;
  color: var(--text-muted);
}

.filters {
  display: flex;
  gap: 4px;
}

.filter-btn {
  padding: 4px 8px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--bg-surface);
  color: var(--text-muted);
  cursor: pointer;
  text-decoration: none;
  user-select: none;
}

.filter-btn:hover {
  background: var(--bg-hover);
}

.filter-btn.active {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

.empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
}

.issues-list,
.notes-list {
  flex: 1;
  overflow-y: auto;
}

.issue-item,
.note-item {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  user-select: none;
  color: var(--text);
  text-decoration: none;
  display: block;
}

.issue-item:hover,
.note-item:hover {
  background: var(--bg-hover);
}

.issue-item.selected,
.note-item.selected {
  background: var(--bg-selected);
}

.issue-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.severity-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  color: white;
}

.severity-P0 { background: var(--severity-p0); }
.severity-P1 { background: var(--severity-p1); }
.severity-P2 { background: var(--severity-p2); }

.title {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.issue-meta {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-pill {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.status-open {
  background: var(--badge-todo-bg);
  color: var(--badge-todo-text);
}

.status-resolved {
  background: var(--bg-reviewed);
  color: var(--status-success);
}

.status-dismissed {
  background: var(--bg-base);
  color: var(--text-muted);
}

.meta-date {
  margin-left: auto;
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

.no-selection-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
}

.issue-details {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.detail-row {
  margin-bottom: 16px;
}

.detail-row label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-muted);
}

.detail-row input,
.detail-row select,
.detail-row textarea {
  width: 100%;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  background: var(--bg-surface);
  color: var(--text);
  font-family: inherit;
}

.detail-row label.label-with-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.field-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.field-label-text {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

.actor-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.actor-field {
  font-size: 11px;
  color: var(--text-muted);
}

.actor-field code {
  font-size: 11px;
  color: var(--text-secondary, var(--text-muted));
}

.description-editor {
  resize: vertical;
  min-height: 96px;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
}

.description-rendered {
  padding: 8px 10px;
  border: 1px solid var(--border-light);
  border-radius: 4px;
  background: var(--bg-base);
}

.description-empty {
  padding: 8px 10px;
  border: 1px dashed var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-style: italic;
  cursor: pointer;
}

.description-empty:hover {
  background: var(--bg-hover);
}

.status-actions {
  display: flex;
  gap: 6px;
}

.btn-action {
  flex: 1;
  min-width: 0;
  padding-left: 4px;
  padding-right: 4px;
  font-size: 12px;
}

.notes-section {
  margin-top: 24px;
}

.notes-section h4 {
  margin: 0 0 12px 0;
  font-size: 12px;
  font-weight: 600;
}

.empty-notes {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 0;
}

.note-item {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.note-link {
  text-decoration: none;
  color: inherit;
  cursor: pointer;
}

.note-link:hover {
  background: var(--bg-hover);
}

.note-checkbox {
  margin-top: 2px;
  flex-shrink: 0;
}

.note-info {
  flex: 1;
  min-width: 0;
}

.note-file {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
  margin-bottom: 2px;
}

.note-file-link {
  text-decoration: none;
  display: block;
}

.note-file-link:hover {
  color: var(--primary);
}

.note-content {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.action-bar {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.action-bar-btns {
  display: flex;
  align-items: center;
  gap: 6px;
}

.deleted-banner {
  margin: 8px 12px 0 12px;
  padding: 8px 12px;
  border: 1px solid var(--status-warning, #c08000);
  border-radius: 4px;
  background: var(--badge-todo-bg, #4a3a10);
  color: var(--badge-todo-text, #ffc857);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.edit-error-banner {
  margin: 8px 12px 0 12px;
  padding: 8px 12px;
  border: 1px solid var(--danger);
  border-radius: 4px;
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stale-pill {
  padding: 2px 8px;
  border: 1px solid var(--status-warning, #c08000);
  border-radius: 10px;
  background: var(--badge-todo-bg, #4a3a10);
  color: var(--badge-todo-text, #ffc857);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}

.stale-pill:hover {
  filter: brightness(1.15);
}
</style>
