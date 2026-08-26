<template>
  <div class="modal-overlay" v-if="visible" @click.self="close">
    <div class="modal-box settings-box">
      <div class="settings-header">
        <h3>Session Settings</h3>
        <button class="btn-icon" @click="close">✕</button>
      </div>

      <div v-if="error" class="error-msg">{{ error }}</div>

      <div class="form-group">
        <label>Exclusion patterns <span class="label-hint">(gitignore syntax, one per line)</span></label>
        <textarea v-model="patterns" rows="6" placeholder="*.log&#10;build/"></textarea>
      </div>

      <label class="purge-toggle">
        <input type="checkbox" v-model="purge" />
        Purge newly excluded files from the database
      </label>
      <p class="purge-hint">
        Without this, a file that drops out of scope keeps its notes as
        <em>orphaned</em> — recoverable, but its stored snapshot still holds the
        original line text. Purging deletes those notes outright and reclaims the
        pages, which is the only way to get credentials out of the database.
        <strong>It cannot be undone.</strong>
        Files that are merely missing from disk are always orphaned, never purged.
      </p>

      <div class="settings-actions">
        <button class="btn-sm" @click="reloadIgnores" :disabled="busy">
          {{ busy === 'reload' ? 'Reloading…' : 'Reload ignore rules' }}
        </button>
        <span class="spacer"></span>
        <button class="btn-sm" @click="close">Cancel</button>
        <button class="btn-primary" @click="save" :disabled="busy">
          {{ busy === 'save' ? 'Saving…' : 'Save & rescan' }}
        </button>
      </div>

      <p v-if="status" class="settings-status">{{ status }}</p>
    </div>
  </div>
</template>

<script>
import { updateSession } from '../api/sessions.js'
import { rescanSession } from '../api/files.js'

export default {
  name: 'SessionSettings',
  props: {
    visible: { type: Boolean, default: false },
    session: { type: Object, required: true },
  },
  emits: ['close', 'changed'],
  data() {
    return {
      patterns: '',
      purge: false,
      busy: null,
      error: null,
      status: null,
    }
  },
  watch: {
    // A purge appends to exclusion_patterns server-side, so the textarea is only
    // safe to seed at open time — reusing a stale copy would silently revert it.
    visible(open) {
      if (!open) return
      this.patterns = this.session.exclusion_patterns || ''
      this.purge = false
      this.error = null
      this.status = null
    },
  },
  methods: {
    close() {
      if (this.busy) return
      this.$emit('close')
    },
    async reloadIgnores() {
      this.busy = 'reload'
      this.error = null
      this.status = null
      try {
        const files = await rescanSession(this.session.id, { force: true })
        this.status = `Rescanned — ${files.length} files tracked.`
        this.$emit('changed')
      } catch (e) {
        this.error = e.message || 'Rescan failed'
      } finally {
        this.busy = null
      }
    },
    async save() {
      if (this.purge && !window.confirm(
        'Purge deletes the notes on every newly excluded file and cannot be undone.\n\nContinue?'
      )) return

      this.busy = 'save'
      this.error = null
      this.status = null
      try {
        const updated = await updateSession(this.session.id, { exclusion_patterns: this.patterns })
        const files = await rescanSession(this.session.id, { force: true, purge: this.purge })
        this.status = `Saved — ${files.length} files tracked.`
        this.$emit('changed', updated)
        this.$emit('close')
      } catch (e) {
        this.error = e.message || 'Save failed'
      } finally {
        this.busy = null
      }
    },
  },
}
</script>

<style scoped>
.settings-box {
  width: 460px;
  max-width: 92vw;
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.settings-header h3 {
  margin: 0;
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  margin-bottom: 4px;
  font-size: 13px;
}

.label-hint {
  color: var(--text-muted);
  font-weight: normal;
}

.form-group textarea {
  width: 100%;
  box-sizing: border-box;
  font-family: var(--font-mono, monospace);
  font-size: 13px;
}

.purge-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}

.purge-hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-muted);
}

.settings-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}

.settings-actions .spacer {
  flex: 1;
}

.settings-status {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
