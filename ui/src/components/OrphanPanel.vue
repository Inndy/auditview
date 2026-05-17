<template>
  <div class="panel-section" v-if="orphanNotes.length > 0 || lostEdits.length > 0">
    <h3>Orphaned Notes</h3>
    <div v-if="lostEdits.length" class="lost-edits-banner">
      <div v-for="e in lostEdits" :key="e.id" class="lost-edit-row">
        <span>Orphan note for lines {{ e.startLine }}–{{ e.endLine }} was deleted in another tab.</span>
        <button class="btn-sm" @click="dismissLost(e.id)">Dismiss</button>
      </div>
    </div>
    <NoteCard
      v-for="note in orphanNotes"
      :key="note.id"
      :note="note"
      :sessionId="sessionId"
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
  name: 'OrphanPanel',
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
    }
  },
  computed: {
    orphanNotes() {
      return this.notes.filter((n) => n.is_orphaned)
    },
  },
  watch: {
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
