<template>
  <div class="panel-section">
    <h3>Checkpoints</h3>
    <div class="cp-create">
      <input
        v-model="newLabel"
        class="cp-label-input"
        placeholder="Label (optional)"
        @keydown.enter="createCheckpoint"
      />
      <button class="btn-primary cp-create-btn" @click="createCheckpoint" :disabled="creating">
        {{ creating ? '…' : 'Save' }}
      </button>
    </div>
    <div v-if="loading" class="empty-msg">Loading…</div>
    <div v-else-if="error" class="error-msg">{{ error }}</div>
    <div v-else-if="checkpoints.length === 0" class="empty-msg">No checkpoints.</div>
    <div v-else class="checkpoint-list">
      <div v-for="cp in checkpoints" :key="cp.id" class="checkpoint-item">
        <div class="cp-label">{{ cp.label }}</div>
        <div class="cp-time">{{ cp.created_at }}</div>
        <button class="btn-danger cp-revert" @click="revert(cp.id)" :disabled="reverting === cp.id">
          {{ reverting === cp.id ? '…' : 'Revert' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { listCheckpoints, createCheckpoint, revertCheckpoint } from '../api/checkpoints.js'

export default {
  name: 'CheckpointPanel',
  props: {
    sessionId: [String, Number],
  },
  emits: ['reverted', 'created'],
  data() {
    return {
      checkpoints: [],
      loading: true,
      error: null,
      reverting: null,
      creating: false,
      newLabel: '',
    }
  },
  mounted() {
    this.load()
  },
  methods: {
    async load() {
      this.loading = true
      this.error = null
      try {
        this.checkpoints = await listCheckpoints(this.sessionId)
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    async createCheckpoint() {
      this.creating = true
      this.error = null
      try {
        await createCheckpoint(this.sessionId, this.newLabel.trim() || 'manual')
        this.newLabel = ''
        await this.load()
        this.$emit('created')
      } catch (e) {
        this.error = e.message
      } finally {
        this.creating = false
      }
    },
    async revert(cid) {
      this.reverting = cid
      try {
        await revertCheckpoint(this.sessionId, cid)
        await this.load()
        this.$emit('reverted')
      } catch (e) {
        this.error = e.message
      } finally {
        this.reverting = null
      }
    },
  },
}
</script>

<style scoped>
.checkpoint-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}

.checkpoint-item {
  background: var(--bg-surface);
  border: 1px solid var(--border-mid);
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.cp-label {
  flex: 1;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cp-time {
  color: var(--text-muted);
  font-size: 10px;
}

.cp-revert {
  padding: 2px 8px;
  font-size: 11px;
}

.cp-create {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.cp-label-input {
  flex: 1;
  font-size: 12px;
  padding: 3px 6px;
  border: 1px solid var(--border-mid);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text);
  min-width: 0;
}

.cp-label-input:focus {
  outline: none;
  border-color: var(--primary);
}

.cp-create-btn {
  padding: 3px 10px;
  font-size: 12px;
}

.empty-msg {
  font-size: 12px;
  color: var(--text-muted);
}

.error-msg {
  font-size: 12px;
  color: var(--badge-orphan-text);
}
</style>
