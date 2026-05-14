<template>
  <tr
    :class="{
      reviewed: line.is_reviewed,
      selected: isSelected,
    }"
    @mousedown.prevent="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
  >
    <LineGutter
      :lineNo="line.line_no"
      :isInRange="isSelected"
      @drag-start="(n) => $emit('drag-start', n)"
      @drag-move="(n) => $emit('drag-move', n)"
      @drag-end="(n) => $emit('drag-end', n)"
      @touch-drag-start="(n) => $emit('touch-drag-start', n)"
    />
    <td class="code-cell">
      <code v-html="line.highlightedContent || escapeHtml(line.content)"></code>
    </td>
  </tr>
</template>

<script>
import LineGutter from './LineGutter.vue'

function escapeHtml(str) {
  return (str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

export default {
  name: 'LineRow',
  components: { LineGutter },
  props: {
    line: { type: Object, required: true },
    isSelected: { type: Boolean, default: false },
  },
  emits: ['drag-start', 'drag-move', 'drag-end', 'touch-drag-start'],
  methods: {
    escapeHtml,
    onMouseDown(e) {
      this.$emit('drag-start', this.line.line_no)
      e.preventDefault()
    },
    onMouseMove(e) {
      if (e.buttons === 1) {
        this.$emit('drag-move', this.line.line_no)
      }
    },
    onMouseUp() {
      this.$emit('drag-end', this.line.line_no)
    },
  },
}
</script>
