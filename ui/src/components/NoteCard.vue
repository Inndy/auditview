<template>
  <div class="note-card">
    <div class="note-meta" @click="$emit('jump', note)" title="Jump to lines">
      Lines {{ note.start_line }}–{{ note.end_line }}
      <span v-if="note.is_todo" class="badge badge-todo">TODO</span>
      <span v-if="note.is_orphaned" class="badge badge-orphan">orphan</span>
      <span class="note-actions">
        <button class="btn-icon" title="Edit" @click.stop="startEdit">✏️</button>
        <button class="btn-icon" title="Delete" @click.stop="remove">🗑️</button>
      </span>
      <span class="note-time">{{ note.created_at }}</span>
    </div>

    <template v-if="editing">
      <textarea v-model="editContent" class="edit-textarea" rows="3"></textarea>
      <div class="edit-actions">
        <label class="todo-toggle">
          <input type="checkbox" v-model="editIsTodo" /> TODO
        </label>
        <button class="btn-sm btn-primary" @click="save" :disabled="!editContent.trim()">Save</button>
        <button class="btn-sm" @click="editing = false">Cancel</button>
      </div>
    </template>
    <div v-else class="note-content">{{ note.content }}</div>

    <div v-if="note.is_orphaned && note.snapshot_text" class="note-snapshot">
      <details>
        <summary>Original snapshot</summary>
        <pre>{{ note.snapshot_text }}</pre>
      </details>
    </div>
  </div>
</template>

<script>
import { updateNote, deleteNote } from '../api/notes.js'

export default {
  name: 'NoteCard',
  props: {
    note: { type: Object, required: true },
    sessionId: { type: [String, Number], required: true },
  },
  emits: ['updated', 'deleted', 'jump'],
  data() {
    return {
      editing: false,
      editContent: '',
      editIsTodo: false,
    }
  },
  methods: {
    startEdit() {
      this.editContent = this.note.content
      this.editIsTodo = this.note.is_todo
      this.editing = true
    },
    async save() {
      try {
        const updated = await updateNote(this.sessionId, this.note.id, {
          content: this.editContent,
          is_todo: this.editIsTodo,
        })
        this.editing = false
        this.$emit('updated', updated)
      } catch (e) {
        console.error('updateNote error:', e.message)
      }
    },
    async remove() {
      try {
        await deleteNote(this.sessionId, this.note.id)
        this.$emit('deleted', this.note.id)
      } catch (e) {
        console.error('deleteNote error:', e.message)
      }
    },
  },
}
</script>

<style scoped>
.note-meta {
  cursor: pointer;
}

.note-meta:hover {
  color: var(--primary);
}

.note-time {
  float: right;
  font-size: 10px;
  color: var(--text-faint);
}

.note-actions {
  margin-left: 4px;
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  font-size: 12px;
  opacity: 0.5;
}

.btn-icon:hover {
  opacity: 1;
}

.edit-textarea {
  width: 100%;
  margin-top: 6px;
  padding: 6px;
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  resize: vertical;
  font-family: inherit;
  background: var(--bg-surface);
  color: var(--text);
}

.edit-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.todo-toggle {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 3px;
  flex: 1;
}

.btn-sm {
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 3px;
  border: 1px solid var(--border);
  cursor: pointer;
  background: var(--bg-surface);
  color: var(--text);
}

.btn-sm.btn-primary {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.note-snapshot {
  margin-top: 6px;
  font-size: 11px;
}

.note-snapshot pre {
  background: var(--bg-gutter);
  padding: 6px;
  border-radius: 3px;
  overflow-x: auto;
  font-size: 11px;
  margin-top: 4px;
}
</style>
