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
    <td class="code-cell" ref="cell">
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
  emits: ['drag-start', 'drag-move', 'drag-end', 'symbol-click', 'symbol-hover'],
  methods: {
    escapeHtml,
    onMouseDown(e) {
      // Ctrl/Cmd+click means "go to definition", so it must not also begin a
      // line-range drag. preventDefault still runs in both branches: it is
      // what suppresses native text selection over .code-cell, which has no
      // user-select: none of its own.
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) {
        this.$emit('symbol-click', {
          lineNo: this.line.line_no,
          clientX: e.clientX,
          clientY: e.clientY,
          cell: this.$refs.cell,
        })
        return
      }
      this.$emit('drag-start', this.line.line_no)
    },
    onMouseMove(e) {
      if (e.ctrlKey || e.metaKey) {
        this.$emit('symbol-hover', {
          lineNo: this.line.line_no,
          clientX: e.clientX,
          clientY: e.clientY,
          cell: this.$refs.cell,
        })
        return
      }
      this.$emit('symbol-hover', null)
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
