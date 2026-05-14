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
  </div>
</template>

<script>
import SkipCommentsToggle from './SkipCommentsToggle.vue'

export default {
  name: 'SessionHeader',
  components: { SkipCommentsToggle },
  props: {
    session: { type: Object, required: true },
    coverage: { type: Object, default: null },
    skipComments: { type: Boolean, default: false },
  },
  emits: ['skip-comments-change'],
  computed: {
    coveragePct() {
      if (!this.coverage) return 0
      return Math.round((this.coverage.coverage || 0) * 100)
    },
  },
}
</script>

<style scoped>
.session-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 14px;
  background: #fff;
  border-bottom: 1px solid #ddd;
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
  color: #888;
  font-family: monospace;
}

.session-coverage {
  margin-left: auto;
  color: #555;
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
