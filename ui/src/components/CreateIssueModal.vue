<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h3>Create Issue from {{ selectedNoteIds.length }} Note(s)</h3>
        <button class="btn-icon" @click="$emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <div v-if="error" class="form-error" role="alert">{{ error }}</div>
        <div class="form-group">
          <label>Issue Title</label>
          <input v-model="title" type="text" placeholder="e.g., SQL injection vulnerability" />
        </div>

        <div class="form-group">
          <label>Severity</label>
          <select v-model="severity">
            <option value="P0">P0 - Critical</option>
            <option value="P1">P1 - High</option>
            <option value="P2">P2 - Medium</option>
          </select>
        </div>

        <div class="form-group">
          <label>Description <span class="hint">(markdown, optional)</span></label>
          <textarea
            v-model="description"
            rows="5"
            placeholder="Optional details — supports markdown"
          ></textarea>
        </div>

        <div class="notes-preview">
          <h4>Selected Notes</h4>
          <div class="notes-list">
            <div v-for="noteId of selectedNoteIds" :key="noteId" class="note-preview">
              <span class="note-id">#{{ noteId }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button data-modal-cancel @click="$emit('close')">Cancel</button>
        <button class="btn-primary" data-modal-confirm @click="create" :disabled="!title.trim() || creating">
          {{ creating ? 'Creating…' : 'Create Issue' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { createIssue } from '../api/issues.js'

export default {
  name: 'CreateIssueModal',
  props: {
    selectedNoteIds: Array,
    sessionId: Number,
  },
  emits: ['created', 'close'],
  data() {
    return {
      title: '',
      severity: 'P2',
      description: '',
      creating: false,
      error: null,
    }
  },
  methods: {
    async create() {
      if (!this.title.trim()) return

      this.creating = true
      this.error = null
      try {
        const issue = await createIssue(
          this.sessionId,
          this.title.trim(),
          this.severity,
          this.selectedNoteIds,
          this.description,
        )
        this.$emit('created', issue)
      } catch (e) {
        this.error = e.message
      } finally {
        this.creating = false
      }
    },
  },
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  width: 90%;
  max-width: 500px;
  display: flex;
  flex-direction: column;
  max-height: 90vh;
  overflow: hidden;
}

.modal-header {
  padding: 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text);
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  background: var(--bg-surface);
  color: var(--text);
  font-family: inherit;
}

.form-group textarea {
  resize: vertical;
  min-height: 80px;
  font-family: var(--font-mono, ui-monospace, monospace);
}

.form-group label .hint {
  font-weight: 400;
  color: var(--text-muted);
  font-size: 11px;
  margin-left: 4px;
}
.form-error {
  margin-bottom: 16px;
  color: var(--badge-orphan-text);
  font-size: 13px;
}

.notes-preview {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border-light);
}

.notes-preview h4 {
  margin: 0 0 12px 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.notes-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.note-preview {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--bg-selected);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 12px;
}

.note-id {
  color: var(--text-muted);
  font-family: monospace;
}

.modal-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

</style>
