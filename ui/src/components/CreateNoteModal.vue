<template>
  <div class="modal-overlay" v-if="visible" @click.self="cancel" @keydown="onDialogKeydown">
    <div ref="dialog" class="modal-box" role="dialog" aria-modal="true" aria-labelledby="note-dialog-title" tabindex="-1">
      <h3 id="note-dialog-title">{{ isTodo ? 'Add TODO' : 'Add Note' }} — lines {{ startLine }}–{{ endLine }}</h3>
      <textarea
        ref="textarea"
        v-model="content"
        aria-label="Note content"
        placeholder="Enter note content…"
        @keydown.esc.stop="cancel"
        @keydown.ctrl.enter.stop.prevent="submit"
        @keydown.meta.enter.stop.prevent="submit"
      ></textarea>
      <div class="modal-actions">
        <button data-modal-cancel @click="cancel">Cancel</button>
        <button :disabled="submitting" @click="pickIssue">Add to Issue Instead</button>
        <button class="btn-primary" data-modal-confirm @click="submit" :disabled="!content.trim() || submitting">
          {{ submitting ? 'Submitting…' : 'Submit' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { openDialog, restoreDialogFocus, trapDialogFocus } from '../utils/dialogFocus.js'

export default {
  name: 'CreateNoteModal',
  props: {
    visible: { type: Boolean, default: false },
    isTodo: { type: Boolean, default: false },
    startLine: { type: Number, default: null },
    endLine: { type: Number, default: null },
    initialContent: { type: String, default: '' },
    submitting: { type: Boolean, default: false },
  },
  emits: ['submit', 'cancel', 'pick-issue'],
  data() {
    return { content: '' }
  },
  watch: {
    visible(val) {
      if (val) {
        this.content = this.initialContent
        openDialog(this, 'textarea')
      } else {
        restoreDialogFocus(this)
      }
    },
  },
  beforeUnmount() {
    restoreDialogFocus(this)
  },
  methods: {
    onDialogKeydown(event) {
      trapDialogFocus(this, event)
    },
    submit() {
      if (!this.content.trim() || this.submitting) return
      this.$emit('submit', { content: this.content, is_todo: this.isTodo })
    },
    pickIssue() {
      this.$emit('pick-issue', { content: this.content, is_todo: this.isTodo })
    },
    cancel() {
      this.content = ''
      this.$emit('cancel')
    },
  },
}
</script>
