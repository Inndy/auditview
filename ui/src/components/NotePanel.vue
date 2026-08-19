<template>
  <div class="panel-section">
    <h3>Notes</h3>
    <div v-if="lostEdits.length" class="lost-edits-banner">
      <div v-for="e in lostEdits" :key="e.id" class="lost-edit-row">
        <span>Note for lines {{ e.startLine }}–{{ e.endLine }} was deleted in another tab.</span>
        <button class="btn-sm" @click="dismissLost(e.id)">Dismiss</button>
      </div>
    </div>
    <div v-if="liveNotes.length === 0" class="empty-msg">No notes for this file.</div>
    <NoteCard
      v-for="(note, i) in liveNotes"
      :key="note.id"
      :note="note"
      :sessionId="sessionId"
      :focused="i === focusedIndex"
      @updated="$emit('note-updated', $event)"
      @deleted="$emit('note-deleted', $event)"
      @jump="$emit('jump', $event)"
      @edit-started="onEditStarted"
      @edit-ended="onEditEnded"
    />
  </div>
</template>

<script>
import NoteCard from './NoteCard.vue'

export default {
  name: 'NotePanel',
  components: { NoteCard },
  props: {
    notes: { type: Array, default: () => [] },
    sessionId: { type: [String, Number], required: true },
  },
  emits: ['note-updated', 'note-deleted', 'jump'],
  data() {
    return {
      editingTargets: {},
      lostEdits: [],
      focusedIndex: -1,
    }
  },
  computed: {
    liveNotes() {
      return this.notes.filter((n) => !n.is_orphaned)
    },
  },
  watch: {
    liveNotes(list) {
      if (this.focusedIndex >= list.length) this.focusedIndex = list.length - 1
    },
    notes(newNotes) {
      const present = new Set(newNotes.map((n) => n.id))
      for (const id of Object.keys(this.editingTargets)) {
        const numId = Number(id)
        if (!present.has(numId)) {
          if (!this.lostEdits.find((e) => e.id === numId)) {
            this.lostEdits.push({ id: numId, ...this.editingTargets[id] })
          }
          delete this.editingTargets[id]
        }
      }
    },
  },
  methods: {
    moveFocus(delta) {
      const n = this.liveNotes.length
      if (n === 0) return
      const next = this.focusedIndex === -1
        ? (delta > 0 ? 0 : n - 1)
        : Math.max(0, Math.min(n - 1, this.focusedIndex + delta))
      this.focusedIndex = next
      this.$nextTick(() => {
        this.$el.querySelectorAll('.note-card')[next]?.scrollIntoView({ block: 'nearest' })
      })
    },
    activateFocused() {
      const note = this.liveNotes[this.focusedIndex]
      if (note) this.$emit('jump', note)
    },
    onEditStarted({ id, startLine, endLine }) {
      this.editingTargets[id] = { startLine, endLine }
    },
    onEditEnded(id) {
      delete this.editingTargets[id]
    },
    dismissLost(id) {
      this.lostEdits = this.lostEdits.filter((e) => e.id !== id)
    },
  },
}
</script>

<style scoped>
.empty-msg {
  font-size: 12px;
  color: var(--text-faint);
}

.lost-edits-banner {
  margin-bottom: 6px;
}

.lost-edit-row {
  padding: 6px 8px;
  border: 1px solid var(--status-warning, #c08000);
  border-radius: 4px;
  background: var(--badge-todo-bg, #4a3a10);
  color: var(--badge-todo-text, #ffc857);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
</style>
