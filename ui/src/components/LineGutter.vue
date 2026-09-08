<template>
  <td
    class="gutter-cell"
    :class="{ 'gutter-selected': isInRange }"
    @mousedown.prevent="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
  ><span v-if="severity" class="severity-dot" :class="'severity-' + severity"></span>{{ lineNo }}</td>
</template>

<script>
export default {
  name: 'LineGutter',
  props: {
    lineNo: { type: Number, required: true },
    isInRange: { type: Boolean, default: false },
    severity: { type: String, default: null },
  },
  emits: ['drag-start', 'drag-move', 'drag-end'],
  methods: {
    onMouseDown(e) {
      e.preventDefault()
      // Ctrl/Cmd is the go-to-definition chord; there is no symbol in the
      // gutter, so swallow it rather than starting a drag.
      if (e.ctrlKey || e.metaKey) return
      this.$emit('drag-start', this.lineNo)
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

<style scoped>
.severity-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}

.severity-P0 {
  background: var(--severity-p0);
}

.severity-P1 {
  background: var(--severity-p1);
}

.severity-P2 {
  background: var(--severity-p2);
}

.severity-NONE {
  background: var(--severity-none);
}
</style>
