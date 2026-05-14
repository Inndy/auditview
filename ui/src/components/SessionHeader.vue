<template>
  <div class="session-header">
    <div class="session-title">
      <strong>{{ session.label }}</strong>
      <span class="session-path">{{ session.root_path }}</span>
    </div>
    <div class="session-coverage">
      <span v-if="coverage">
        {{ coveragePct }}% ({{ coverage.total_reviewed_lines }}/{{ coverage.total_countable_lines }} lines)
      </span>
      <span v-if="coverage && !coverage.supports_checkpoints" class="warn-badge">No checkpoints</span>
    </div>
    <SkipCommentsToggle :modelValue="skipComments" @change="$emit('skip-comments-change', $event)" />
    <label class="wrap-lines-toggle">
      <input type="checkbox" :checked="wrapLines" @change="$emit('wrap-lines-change', $event.target.checked)" />
      Wrap lines
    </label>
    <button class="dark-btn" :title="darkMode ? 'Switch to light mode' : 'Switch to dark mode'" @click="toggleDark">{{ darkMode ? '☀️' : '🌙' }}</button>
    <button class="help-btn" title="Keyboard shortcuts (?)" @click="$emit('show-help')">?</button>
  </div>
</template>

<script>
import SkipCommentsToggle from './SkipCommentsToggle.vue'
import { isDark, toggleDark } from '../darkMode.js'

export default {
  name: 'SessionHeader',
  components: { SkipCommentsToggle },
  props: {
    session: { type: Object, required: true },
    coverage: { type: Object, default: null },
    skipComments: { type: Boolean, default: false },
    wrapLines: { type: Boolean, default: false },
  },
  emits: ['skip-comments-change', 'wrap-lines-change', 'show-help'],
  data() {
    return { darkMode: isDark() }
  },
  methods: {
    toggleDark() {
      toggleDark()
      this.darkMode = isDark()
    },
  },
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

.dark-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
}

.help-btn {
  background: #f0f0f0;
  border: 1px solid #ccc;
  border-radius: 50%;
  width: 22px;
  height: 22px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  color: #555;
  flex-shrink: 0;
}

.help-btn:hover {
  background: #e0e0e0;
}

.warn-badge {
  background: #fff3cd;
  color: #856404;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  margin-left: 8px;
}
</style>
