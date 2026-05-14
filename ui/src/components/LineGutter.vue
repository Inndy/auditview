<template>
  <td
    class="gutter-cell"
    :class="{ 'gutter-selected': isInRange }"
    @mousedown.prevent="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
    @touchstart.prevent="onTouchStart"
  >{{ lineNo }}</td>
</template>

<script>
export default {
  name: 'LineGutter',
  props: {
    lineNo: { type: Number, required: true },
    isInRange: { type: Boolean, default: false },
  },
  emits: ['drag-start', 'drag-move', 'drag-end', 'touch-drag-start'],
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
    onTouchStart() {
      this.$emit('touch-drag-start', this.lineNo)
    },
  },
}
</script>
