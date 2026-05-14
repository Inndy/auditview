<template>
  <td
    class="gutter-cell"
    :class="{ 'gutter-selected': isInRange }"
    @mousedown.prevent="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
  >{{ lineNo }}</td>
</template>

<script>
export default {
  name: 'LineGutter',
  props: {
    lineNo: { type: Number, required: true },
    isInRange: { type: Boolean, default: false },
  },
  emits: ['drag-start', 'drag-move', 'drag-end'],
  methods: {
    onMouseDown(e) {
      this.$emit('drag-start', this.lineNo)
      e.preventDefault()
    },
    onMouseMove(e) {
      if (e.buttons === 1) {
        this.$emit('drag-move', this.lineNo)
      }
    },
    onMouseUp() {
      this.$emit('drag-end', this.lineNo)
    },
  },
}
</script>
