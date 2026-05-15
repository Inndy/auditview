<template>
  <div class="panel-section" v-if="orphanNotes.length > 0">
    <h3>Orphaned Notes</h3>
    <NoteCard
      v-for="note in orphanNotes"
      :key="note.id"
      :note="note"
      :sessionId="sessionId"
      @updated="$emit('note-updated', $event)"
      @deleted="$emit('note-deleted', $event)"
      @jump="$emit('jump', $event)"
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
  computed: {
    orphanNotes() {
      return this.notes.filter((n) => n.is_orphaned)
    },
  },
}
</script>
