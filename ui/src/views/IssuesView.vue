<template>
  <div class="issues-view">
    <div v-if="loadingIssues" class="loading">Loading issues…</div>
    <div v-else class="issues-content">
      <div class="issues-panel">
        <div class="panel-header">
          <h3>Issues</h3>
          <div class="filters">
            <button
              v-for="st in ['open', 'resolved', 'dismissed']"
              :key="st"
              class="filter-btn"
              :class="{ active: statusFilter === st }"
              @click="statusFilter = statusFilter === st ? null : st"
            >{{ st }}</button>
          </div>
        </div>
        <div v-if="filteredIssues.length === 0" class="empty">No issues.</div>
        <div v-else class="issues-list">
          <div
            v-for="issue in filteredIssues"
            :key="issue.id"
            class="issue-item"
            :class="{ selected: selectedIssueId === issue.id }"
            @click="selectIssue(issue.id)"
          >
            <div class="issue-header">
              <span class="severity-badge" :class="'severity-' + issue.severity">{{ issue.severity }}</span>
              <span class="title">{{ issue.title }}</span>
            </div>
            <div class="issue-meta">{{ issue.status }} • {{ formatDate(issue.created_at) }}</div>
          </div>
        </div>
      </div>

      <div v-if="selectedIssueId" class="details-panel">
        <div class="panel-header">
          <h3>Issue #{{ selectedIssueId }}</h3>
          <button class="close-btn" @click="selectedIssueId = null">✕</button>
        </div>
        <div v-if="selectedIssue" class="issue-details">
          <div class="detail-row">
            <label>Title</label>
            <input v-model="selectedIssue.title" @blur="updateIssue('title')" type="text" />
          </div>
          <div class="detail-row">
            <label>Severity</label>
            <select v-model="selectedIssue.severity" @change="updateIssue('severity')">
              <option value="P0">P0</option>
              <option value="P1">P1</option>
              <option value="P2">P2</option>
            </select>
          </div>
          <div class="detail-row">
            <label>Status</label>
            <select v-model="selectedIssue.status" @change="updateIssue('status')">
              <option value="open">Open</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>
          </div>
          <div class="detail-row">
            <button class="delete-btn" @click="deleteIssue">Delete Issue</button>
          </div>

          <div class="notes-section">
            <h4>Attached Notes</h4>
            <div v-if="issueNotes.length === 0" class="empty-notes">No notes attached.</div>
            <div v-else class="notes-list">
              <router-link
                v-for="note in issueNotes"
                :key="note.id"
                :to="`/sessions/${session.id}/code?file=${encodeURIComponent(note.file_path)}`"
                class="note-item note-link"
              >
                <div class="note-file">{{ note.file_path }}:{{ note.start_line }}</div>
                <div class="note-content">{{ note.content }}</div>
              </router-link>
            </div>
          </div>
        </div>
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
            :class="{ selected: selectedNoteIds.has(note.id) }"
            @click="toggleNoteSelection(note.id)"
          >
            <input type="checkbox" :checked="selectedNoteIds.has(note.id)" class="note-checkbox" />
            <div class="note-info">
              <div class="note-file">{{ note.file_path }}:{{ note.start_line }}-{{ note.end_line }}</div>
              <div class="note-content">{{ note.content }}</div>
            </div>
          </div>
        </div>

        <div v-if="selectedNoteIds.size > 0" class="action-bar">
          <span>{{ selectedNoteIds.size }} selected</span>
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
import { listIssues, updateIssue, deleteIssue, getIssueNotes } from '../api/issues.js'
import { listNotes } from '../api/notes.js'
import CreateIssueModal from '../components/CreateIssueModal.vue'

export default {
  name: 'IssuesView',
  components: { CreateIssueModal },
  props: {
    session: Object,
  },
  data() {
    return {
      issues: [],
      orphanNotes: [],
      issueNotes: [],
      loadingIssues: true,
      statusFilter: null,
      selectedIssueId: null,
      selectedNoteIds: new Set(),
      showCreateIssueModal: false,
    }
  },
  computed: {
    filteredIssues() {
      if (!this.statusFilter) return this.issues
      return this.issues.filter((i) => i.status === this.statusFilter)
    },
    selectedIssue() {
      return this.issues.find((i) => i.id === this.selectedIssueId)
    },
  },
  mounted() {
    this.load()
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
        this.orphanNotes = notes.filter((n) => !n.issue_id)
      } catch (e) {
        console.error('Failed to load:', e.message)
      } finally {
        this.loadingIssues = false
      }
    },
    selectIssue(id) {
      if (this.selectedIssueId === id) {
        this.selectedIssueId = null
        this.issueNotes = []
      } else {
        this.selectedIssueId = id
        this.loadIssueNotes(id)
      }
    },
    async loadIssueNotes(issueId) {
      try {
        this.issueNotes = await getIssueNotes(this.session.id, issueId)
      } catch (e) {
        console.error('Failed to load issue notes:', e.message)
      }
    },
    toggleNoteSelection(noteId) {
      if (this.selectedNoteIds.has(noteId)) {
        this.selectedNoteIds.delete(noteId)
      } else {
        this.selectedNoteIds.add(noteId)
      }
      this.$forceUpdate()
    },
    async updateIssue(field) {
      try {
        const updates = {}
        updates[field] = this.selectedIssue[field]
        const updated = await updateIssue(this.session.id, this.selectedIssueId, updates)
        const idx = this.issues.findIndex((i) => i.id === this.selectedIssueId)
        if (idx !== -1) this.issues.splice(idx, 1, updated)
      } catch (e) {
        console.error('Failed to update:', e.message)
      }
    },
    async deleteIssue() {
      if (!confirm('Delete this issue?')) return
      try {
        await deleteIssue(this.session.id, this.selectedIssueId)
        this.issues = this.issues.filter((i) => i.id !== this.selectedIssueId)
        this.selectedIssueId = null
      } catch (e) {
        console.error('Failed to delete:', e.message)
      }
    },
    onIssueCreated(issue) {
      this.issues.push(issue)
      this.selectedNoteIds.clear()
      this.orphanNotes = this.orphanNotes.filter((n) => !this.selectedNoteIds.has(n.id))
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
  background: var(--bg);
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
  grid-template-columns: 300px 1fr 300px;
  gap: 1px;
  flex: 1;
  overflow: hidden;
  background: var(--border);
}

.issues-panel,
.details-panel,
.orphan-panel {
  background: var(--bg);
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
  background: var(--bg);
  color: var(--text-muted);
  cursor: pointer;
}

.filter-btn.active {
  background: var(--accent, #4a9eff);
  color: white;
  border-color: var(--accent, #4a9eff);
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
}

.issue-item:hover,
.note-item:hover {
  background: var(--bg-highlight, rgba(74, 158, 255, 0.05));
}

.issue-item.selected,
.note-item.selected {
  background: var(--bg-highlight, rgba(74, 158, 255, 0.1));
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

.severity-P0 {
  background: var(--severity-p0);
}

.severity-P1 {
  background: var(--severity-p1);
}

.severity-P2 {
  background: var(--severity-p2);
}

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
}

.details-panel {
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 18px;
  color: var(--text-muted);
  padding: 0 4px;
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
.detail-row select {
  width: 100%;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
  font-family: inherit;
}

.delete-btn {
  width: 100%;
  padding: 8px;
  border: 1px solid var(--danger);
  border-radius: 4px;
  background: transparent;
  color: var(--danger);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.delete-btn:hover {
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
  background: var(--bg-highlight, rgba(74, 158, 255, 0.05));
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
  background: var(--accent, #4a9eff);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.create-issue-btn:hover {
  opacity: 0.9;
}
</style>
