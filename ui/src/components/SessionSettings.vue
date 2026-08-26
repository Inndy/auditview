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

      <div v-if="preview" class="preview">
        <p v-if="!preview.purge_files.length" class="preview-none">
          Nothing to purge — no tracked file falls outside these patterns.
        </p>
        <template v-else>
          <p class="preview-lead" :class="{ 'preview-warn': preview.at_risk_count }">
            <template v-if="preview.at_risk_count">
              ⚠ {{ preview.at_risk_count }} of {{ preview.purge_files.length }}
              {{ preview.purge_files.length === 1 ? 'file' : 'files' }} carry review
              progress that will be destroyed:
              {{ preview.total_reviewed_lines }} reviewed
              {{ preview.total_reviewed_lines === 1 ? 'line' : 'lines' }},
              {{ preview.total_notes }} {{ preview.total_notes === 1 ? 'note' : 'notes' }},
              {{ preview.total_todos }} {{ preview.total_todos === 1 ? 'todo' : 'todos' }}.
            </template>
            <template v-else>
              {{ preview.purge_files.length }}
              {{ preview.purge_files.length === 1 ? 'file' : 'files' }} will be purged.
              None carry review progress — safe to proceed.
            </template>
          </p>
          <ul class="preview-list">
            <li v-for="f in preview.purge_files" :key="f.rel_path"
                :class="{ 'at-risk': f.reviewed_lines || f.notes_count || f.todos_count }">
              <code>{{ f.rel_path }}</code>
              <span v-if="f.reviewed_lines || f.notes_count || f.todos_count" class="preview-badges">
                <span v-if="f.reviewed_lines">{{ f.reviewed_lines }} reviewed</span>
                <span v-if="f.notes_count">{{ f.notes_count }} note{{ f.notes_count === 1 ? '' : 's' }}</span>
                <span v-if="f.todos_count">{{ f.todos_count }} todo{{ f.todos_count === 1 ? '' : 's' }}</span>
              </span>
            </li>
          </ul>
        </template>
        <p v-if="preview.orphan_paths.length" class="preview-note">
          {{ preview.orphan_paths.length }}
          {{ preview.orphan_paths.length === 1 ? 'file is' : 'files are' }} missing from
          disk and will be orphaned, not purged — their notes stay recoverable.
        </p>
      </div>

      <div class="settings-actions">
        <button class="btn-sm" @click="reloadIgnores" :disabled="busy">
          {{ busy === 'reload' ? 'Reloading…' : 'Reload ignore rules' }}
        </button>
        <span class="spacer"></span>
        <button class="btn-sm" @click="close">Cancel</button>
        <button class="btn-primary" @click="save" :disabled="busy">
          {{ saveLabel }}
        </button>
      </div>

      <p v-if="status" class="settings-status">{{ status }}</p>
    </div>
  </div>
</template>

<script>
import { updateSession, previewPurge } from '../api/sessions.js'
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
      preview: null,
    }
  },
  computed: {
    saveLabel() {
      if (this.busy === 'save') return 'Saving…'
      if (this.busy === 'preview') return 'Checking…'
      if (this.purge && this.preview === null) return 'Preview purge'
      return 'Save & rescan'
    },
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
      this.preview = null
    },
    // Any change to what would be purged invalidates the preview the user
    // approved, so Save drops back to previewing rather than firing blind.
    patterns() {
      this.preview = null
    },
    purge() {
      this.preview = null
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
    async loadPreview() {
      this.busy = 'preview'
      this.error = null
      this.status = null
      try {
        this.preview = await previewPurge(this.session.id, { exclusion_patterns: this.patterns })
      } catch (e) {
        this.error = e.message || 'Could not work out what would be purged'
      } finally {
        this.busy = null
      }
    },
    async save() {
      // Purge is irreversible, so it always goes through a preview first. Only a
      // preview showing review progress at risk asks for an extra confirmation —
      // purging files nobody has reviewed is not worth a dialog.
      if (this.purge) {
        if (this.preview === null) {
          await this.loadPreview()
          return
        }
        if (this.preview.at_risk_count && !window.confirm(
          `Purge will permanently delete review progress on ${this.preview.at_risk_count} file(s): ` +
          `${this.preview.total_reviewed_lines} reviewed line(s), ${this.preview.total_notes} note(s), ` +
          `${this.preview.total_todos} todo(s).\n\nThis cannot be undone. Continue?`
        )) return
      }

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

.preview {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-base, transparent);
}

.preview-lead,
.preview-none,
.preview-note {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-muted);
}

.preview-warn {
  color: var(--sev-p1, #c1121f);
  font-weight: 600;
}

.preview-note {
  margin-top: 8px;
}

.preview-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  max-height: 160px;
  overflow-y: auto;
  font-size: 12px;
}

.preview-list li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
}

.preview-list code {
  overflow-wrap: anywhere;
}

.preview-list li.at-risk code {
  font-weight: 600;
}

.preview-badges {
  margin-left: auto;
  display: flex;
  gap: 6px;
  white-space: nowrap;
  color: var(--sev-p1, #c1121f);
}

.settings-status {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
