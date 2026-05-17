<template>
  <div class="issues-view">
    <div v-if="loadingIssues" class="loading">Loading issues…</div>
    <div v-else class="issues-content">
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

      <div v-if="selectedIssueId" class="details-panel">
        <div class="panel-header">
          <h3>Issue #{{ selectedIssueId }}</h3>
          <router-link :to="closeRoute" class="close-btn" title="Back to list">✕</router-link>
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
            <select v-model="selectedIssue.severity" @change="updateField('severity')">
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
                class="link-btn"
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
                <button class="btn-action btn-resolve" @click="setStatus('resolved')">Resolve</button>
                <button class="btn-action btn-dismiss" @click="setStatus('dismissed')">Dismiss</button>
              </template>
              <template v-else>
                <button class="btn-action btn-reopen" @click="setStatus('open')">Reopen</button>
              </template>
              <button class="btn-action btn-delete" @click="onDeleteIssue">Delete</button>
            </div>
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
          <button class="create-issue-btn" @click="showCreateIssueModal = true">Create Issue</button>
        </div>
      </div>

      <CreateIssueModal
        v-if="showCreateIssueModal"
        :selectedNoteIds="selectedNoteIds"
        :sessionId="session.id"
        @created="onIssueCreated"
        @close="showCreateIssueModal = false"
      />
    </div>
  </div>
</template>

<script>
import { listIssues, updateIssue as apiUpdateIssue, deleteIssue as apiDeleteIssue, getIssueNotes } from '../api/issues.js'
import { listNotes } from '../api/notes.js'
import CreateIssueModal from '../components/CreateIssueModal.vue'
import MarkdownView from '../components/MarkdownView.vue'

const FILTER_OPTIONS = [
  { value: 'all', label: 'all' },
  { value: 'open', label: 'open' },
  { value: 'resolved', label: 'resolved' },
  { value: 'dismissed', label: 'dismissed' },
]

export default {
  name: 'IssuesView',
  components: { CreateIssueModal, MarkdownView },
  props: {
    session: Object,
  },
  data() {
    return {
      issues: [],
      orphanNotes: [],
      issueNotes: [],
      loadingIssues: true,
      selectedNoteIds: [],
      showCreateIssueModal: false,
      filterOptions: FILTER_OPTIONS,
      titleBeforeEdit: '',
      editingDescription: false,
      descriptionDraft: '',
      descriptionBeforeEdit: '',
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
  },
  watch: {
    selectedIssueId(id) {
      this.titleBeforeEdit = ''
      this.editingDescription = false
      this.descriptionDraft = ''
      this.descriptionBeforeEdit = ''
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
        console.error('Failed to load:', e.message)
      } finally {
        this.loadingIssues = false
      }
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
        console.error('Failed to update description:', e.message)
      }
    },
    async updateField(field) {
      if (!this.selectedIssue) return
      const value = this.selectedIssue[field]
      if (field === 'title' && (typeof value !== 'string' || value.trim() === '')) {
        this.selectedIssue.title = this.titleBeforeEdit
        return
      }
      try {
        const updates = {}
        updates[field] = value
        const updated = await apiUpdateIssue(this.session.id, this.selectedIssueId, updates)
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, updated)
      } catch (e) {
        console.error('Failed to update:', e.message)
      }
    },
    async setStatus(newStatus) {
      if (!this.selectedIssue) return
      try {
        const updated = await apiUpdateIssue(this.session.id, this.selectedIssueId, { status: newStatus })
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, updated)
      } catch (e) {
        console.error('Failed to update status:', e.message)
      }
    },
    async onDeleteIssue() {
      if (!confirm('Delete this issue?')) return
      try {
        await apiDeleteIssue(this.session.id, this.selectedIssueId)
        this.issues = this.issues.filter((i) => i.id !== this.selectedIssueId)
        this.$router.push(this.closeRoute)
      } catch (e) {
        console.error('Failed to delete:', e.message)
      }
    },
    onIssueCreated(issue) {
      this.issues.push(issue)
      this.orphanNotes = this.orphanNotes.filter((n) => !this.selectedNoteIds.includes(n.id))
      this.selectedNoteIds = []
      this.showCreateIssueModal = false
    },
    formatDate(isoString) {
      return new Date(isoString).toLocaleDateString()
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

.issues-content {
  display: grid;
  grid-template-columns: minmax(200px, 300px) 1fr minmax(200px, 300px);
  gap: 1px;
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

.details-panel,
.orphan-panel {
  border-left: 1px solid var(--border);
}

.no-selection-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 18px;
  color: var(--text-muted);
  padding: 0 4px;
  text-decoration: none;
  line-height: 1;
}

.close-btn:hover {
  color: var(--text);
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

.detail-row label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-muted);
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

.link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 11px;
  font-weight: 500;
  color: var(--primary);
  cursor: pointer;
  text-transform: none;
}

.link-btn:hover {
  text-decoration: underline;
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
  padding: 6px 4px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  background: var(--bg-surface);
  color: var(--text);
  white-space: nowrap;
}

.btn-resolve {
  border-color: var(--status-success);
  color: var(--status-success);
}

.btn-resolve:hover {
  background: var(--status-success);
  color: white;
}

.btn-dismiss {
  border-color: var(--text-muted);
  color: var(--text-muted);
}

.btn-dismiss:hover {
  background: var(--text-muted);
  color: white;
}

.btn-reopen:hover {
  background: var(--bg-hover);
}

.btn-delete {
  border-color: var(--danger);
  color: var(--danger);
}

.btn-delete:hover {
  background: var(--danger);
  color: white;
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

.create-issue-btn {
  padding: 6px 12px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.create-issue-btn:hover {
  background: var(--primary-hover);
}
</style>
