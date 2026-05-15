<template>
  <div class="modal-overlay" v-if="visible" @click.self="$emit('close')">
    <div class="modal-box help-box">
      <div class="help-header">
        <h3>Keyboard Shortcuts</h3>
        <button class="btn-close" @click="$emit('close')">✕</button>
      </div>
      <table class="help-table">
        <tbody>
          <tr><td class="key">m</td><td>Mark / unmark selected lines</td></tr>
          <tr><td class="key">M</td><td>Mark / unmark entire file</td></tr>
          <tr><td class="key">u</td><td>Unmark selected lines</td></tr>
          <tr><td class="key">n</td><td>Add note on selection</td></tr>
          <tr><td class="key">t</td><td>Add TODO on selection</td></tr>
          <tr><td class="key">Esc</td><td>Clear selection</td></tr>
          <tr><td class="key">?</td><td>Show this help</td></tr>
        </tbody>
      </table>
      <p class="help-hint">Drag the line-number gutter to select a range.</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'KeyboardHelpModal',
  props: {
    visible: { type: Boolean, default: false },
  },
  emits: ['close'],
}
</script>

<style scoped>
.help-box {
  width: 360px;
}

.help-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.help-header h3 {
  font-size: 14px;
  margin: 0;
}

.btn-close {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-muted);
  padding: 0;
}

.help-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.help-table tr + tr td {
  border-top: 1px solid var(--border-light);
}

.help-table td {
  padding: 5px 4px;
}

.key {
  font-family: 'Fira Mono', 'Consolas', monospace;
  background: var(--bg-gutter);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 7px;
  font-size: 12px;
  white-space: nowrap;
  width: 1%;
}

.help-hint {
  margin-top: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
