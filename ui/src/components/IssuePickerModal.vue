<template>
  <div class="modal-overlay" @click.self="$emit('cancel')" @keydown="onDialogKeydown">
    <div ref="dialog" class="modal-box issue-picker" role="dialog" aria-modal="true" aria-labelledby="issue-picker-title" tabindex="-1">
      <h3 id="issue-picker-title">Add to Issue — lines {{ startLine }}–{{ endLine }}</h3>

      <div v-if="loading" class="loading">Loading issues…</div>
      <template v-else>
        <div v-if="!creatingNew" class="issue-list-section">
          <div v-if="issues.length === 0" class="empty">No open issues yet.</div>
          <div v-else class="issue-list">
            <button
              v-for="issue in issues"
              :key="issue.id"
              class="issue-row"
              :class="{ selected: selectedId === issue.id }"
              @click="selectedId = issue.id"
            >
              <span class="severity-badge" :class="'severity-' + issue.severity">{{ issue.severity }}</span>
              <span class="issue-title">{{ issue.title }}</span>
            </button>
          </div>
          <button class="btn-link" @click="creatingNew = true">+ Create new issue</button>
        </div>

        <div v-else class="new-issue-form">
          <div class="form-row">
            <label for="issue-picker-name">Title</label>
            <input id="issue-picker-name" v-model="newTitle" type="text" ref="newTitleInput" placeholder="Short summary…" />
          </div>
          <div class="form-row">
            <label for="issue-picker-severity">Severity</label>
            <select id="issue-picker-severity" v-model="newSeverity">
              <option value="P0">P0 - Critical</option>
              <option value="P1">P1 - High</option>
              <option value="P2">P2 - Medium</option>
            </select>
          </div>
          <button class="btn-link" @click="creatingNew = false">← Pick existing issue</button>
        </div>
      </template>

      <div v-if="error" class="error-msg" role="alert">{{ error }}</div>

      <div class="modal-actions">
        <button data-modal-cancel @click="$emit('cancel')">Cancel</button>
        <button class="btn-primary" data-modal-confirm @click="submit" :disabled="!canSubmit || submitting">
          {{ submitting ? 'Saving…' : 'Add to Issue' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { listIssues, createIssue } from '../api/issues.js'
import { openDialog, restoreDialogFocus, trapDialogFocus } from '../utils/dialogFocus.js'

export default {
  name: 'IssuePickerModal',
  props: {
    sessionId: [String, Number],
    startLine: Number,
    endLine: Number,
  },
  emits: ['picked', 'cancel'],
  data() {
    return {
      issues: [],
      loading: true,
      creatingNew: false,
      selectedId: null,
      newTitle: '',
      newSeverity: 'P2',
      submitting: false,
      error: null,
    }
  },
  computed: {
    canSubmit() {
      if (this.creatingNew) return this.newTitle.trim().length > 0
      return this.selectedId !== null
    },
  },
  mounted() {
    openDialog(this)
    this.load()
  },
  beforeUnmount() {
    restoreDialogFocus(this)
  },
  watch: {
    creatingNew(val) {
      if (val) {
        this.$nextTick(() => this.$refs.newTitleInput?.focus())
      }
    },
  },
  methods: {
    onDialogKeydown(event) {
      trapDialogFocus(this, event)
    },
    async load() {
      this.loading = true
      try {
        this.issues = await listIssues(this.sessionId, 'open')
        if (this.issues.length === 0) {
          this.creatingNew = true
        }
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    async submit() {
      if (!this.canSubmit) return
      this.submitting = true
      this.error = null
      try {
        let issueId = this.selectedId
        if (this.creatingNew) {
          const issue = await createIssue(this.sessionId, this.newTitle.trim(), this.newSeverity)
          issueId = issue.id
        }
        this.$emit('picked', { issue_id: issueId })
      } catch (e) {
        this.error = e.message
      } finally {
        this.submitting = false
      }
    },
  },
}
</script>

<style scoped>
.issue-picker {
  width: 520px;
}

.loading,
.empty {
  padding: 16px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

.issue-list {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 4px;
  margin-bottom: 8px;
}

.issue-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  border: none;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-surface);
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
}

.issue-row:last-child {
  border-bottom: none;
}

.issue-row:hover {
  background: var(--bg-hover);
}

.issue-row.selected {
  background: var(--bg-selected);
  color: var(--text);
}

.severity-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  color: var(--on-solid);
  flex-shrink: 0;
}

.severity-P0 { background: var(--severity-p0); }
.severity-P1 { background: var(--severity-p1); }
.severity-P2 { background: var(--severity-p2); }

.issue-title {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.new-issue-form {
  margin-bottom: 8px;
}

.form-row {
  margin-bottom: 12px;
}

.form-row label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-dim);
}

.form-row input,
.form-row select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  background: var(--bg-surface);
  color: var(--text);
}

.error-msg {
  margin-top: 8px;
  padding: 8px;
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
  border-radius: 4px;
  font-size: 12px;
}
</style>
