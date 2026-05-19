<template>
  <span class="sse-indicator" :class="'sse-' + status" :title="'Live updates: ' + status">
    <span class="sse-dot">●</span>
    <span class="sse-label">{{ label }}</span>
    <button v-if="status === 'shutdown'" class="sse-reconnect" @click="reconnect">Reconnect</button>
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
  methods: {
    reconnect() {
      sseClient._shutdownAt = null;
      sseClient._scheduleRetry(1000, 'connecting');
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

.sse-reconnect {
  margin-left: 4px;
  padding: 1px 6px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--bg-surface);
  color: var(--text-muted);
  cursor: pointer;
}

.sse-reconnect:hover {
  background: var(--bg-hover);
}
</style>
