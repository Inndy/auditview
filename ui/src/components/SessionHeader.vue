<template>
  <div class="session-header">
    <router-link to="/" class="back-btn" title="Back to session list">&#8592;</router-link>
    <div class="session-title">
      <strong>{{ session.label }}</strong>
      <span class="session-path">{{ session.root_path }}</span>
    </div>
    <div class="session-coverage">
      <span v-if="coverage">
        {{ coveragePct }}% ({{ coverage.total_reviewed_lines }}/{{ coverage.total_countable_lines }} lines)
      </span>
    </div>
    <label class="wrap-lines-toggle">
      <input type="checkbox" :checked="wrapLines" @change="$emit('wrap-lines-change', $event.target.checked)" />
      Wrap lines
    </label>
    <DarkModeToggle style="font-size: 16px" />
    <button class="help-btn" title="Keyboard shortcuts (?)" @click="$emit('show-help')">?</button>
  </div>
</template>

<script>
import DarkModeToggle from './DarkModeToggle.vue'

export default {
  name: 'SessionHeader',
  components: { DarkModeToggle },
  props: {
    session: { type: Object, required: true },
    coverage: { type: Object, default: null },
    wrapLines: { type: Boolean, default: false },
  },
  emits: ['wrap-lines-change', 'show-help'],
  computed: {
    coveragePct() {
      if (!this.coverage) return 0
      return Math.round((this.coverage.coverage || 0) * 100)
    },
  },
}
</script>

<style scoped>
.wrap-lines-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}

.session-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 14px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  font-size: 13px;
}

.session-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.session-path {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
}

.session-coverage {
  margin-left: auto;
  color: var(--text-dim);
}

.help-btn {
  background: var(--border-light);
  border: 1px solid var(--border);
  border-radius: 50%;
  width: 22px;
  height: 22px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  color: var(--text-dim);
  flex-shrink: 0;
}

.help-btn:hover {
  background: var(--border-mid);
}

.back-btn {
  color: var(--text-muted);
  text-decoration: none;
  font-size: 16px;
  line-height: 1;
  flex-shrink: 0;
  padding: 2px 4px;
}

.back-btn:hover {
  color: var(--text);
}
</style>
