<template>
  <span class="sse-indicator" :class="'sse-' + status" :title="'Live updates: ' + status">
    <span class="sse-dot">●</span>
    <span class="sse-label">{{ label }}</span>
  </span>
</template>

<script>
import { sseClient } from '../api/events.js'

const LABELS = {
  connected: 'Live',
  connecting: 'Connecting…',
  disconnected: 'Offline',
  shutdown: 'Server stopped',
}

export default {
  name: 'SSEStatusIndicator',
  computed: {
    status() {
      return sseClient.status.value
    },
    label() {
      return LABELS[this.status] || this.status
    },
  },
}
</script>

<style scoped>
.sse-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  user-select: none;
}

.sse-dot {
  font-size: 10px;
  line-height: 1;
}

.sse-connected    { color: var(--status-success); }
.sse-connecting   { color: var(--status-warning); }
.sse-disconnected { color: var(--status-error); }
.sse-shutdown     { color: var(--text-faint); }
</style>
