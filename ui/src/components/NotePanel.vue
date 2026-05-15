<template>
  <div class="panel-section">
    <h3>Notes</h3>
    <div v-if="liveNotes.length === 0" class="empty-msg">No notes for this file.</div>
    <NoteCard
      v-for="note in liveNotes"
      :key="note.id"
      :note="note"
      :sessionId="sessionId"
      @updated="$emit('note-updated', $event)"
      @deleted="$emit('note-deleted', $event)"
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
  emits: ['note-updated', 'note-deleted'],
  computed: {
    liveNotes() {
      return this.notes.filter((n) => !n.is_orphaned)
    },
  },
}
</script>

<style scoped>
.empty-msg {
  font-size: 12px;
  color: var(--text-faint);
}
</style>
