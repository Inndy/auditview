<template>
  <tr
    :data-line-no="line.line_no"
    :class="{
      reviewed: line.is_reviewed,
      selected: isSelected,
      cursor: isCursor,
      anchor: isAnchor,
    }"
    @mousedown.prevent="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
  >
    <LineGutter
      :lineNo="line.line_no"
      :isInRange="isSelected"
      :severity="severity"
      @drag-start="(n) => $emit('drag-start', n)"
      @drag-move="(n) => $emit('drag-move', n)"
      @drag-end="(n) => $emit('drag-end', n)"
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
    isCursor: { type: Boolean, default: false },
    isAnchor: { type: Boolean, default: false },
    severity: { type: String, default: null },
  },
  emits: ['drag-start', 'drag-move', 'drag-end'],
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
