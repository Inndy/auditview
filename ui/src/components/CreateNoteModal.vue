<template>
  <div class="modal-overlay" v-if="visible" @click.self="cancel">
    <div class="modal-box">
      <h3>{{ isTodo ? 'Add TODO' : 'Add Note' }} — lines {{ startLine }}–{{ endLine }}</h3>
      <textarea
        ref="textarea"
        v-model="content"
        placeholder="Enter note content…"
        @keydown.esc.stop="cancel"
      ></textarea>
      <div class="modal-actions">
        <button @click="cancel">Cancel</button>
        <button class="btn-primary" @click="submit" :disabled="!content.trim()">Submit</button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'CreateNoteModal',
  props: {
    visible: { type: Boolean, default: false },
    isTodo: { type: Boolean, default: false },
    startLine: { type: Number, default: null },
    endLine: { type: Number, default: null },
  },
  emits: ['submit', 'cancel'],
  data() {
    return { content: '' }
  },
  watch: {
    visible(val) {
      if (val) {
        this.content = ''
        this.$nextTick(() => {
          this.$refs.textarea?.focus()
        })
      }
    },
  },
  methods: {
    submit() {
      if (!this.content.trim()) return
      this.$emit('submit', { content: this.content, is_todo: this.isTodo })
      this.content = ''
    },
    cancel() {
      this.content = ''
      this.$emit('cancel')
    },
  },
}
</script>
