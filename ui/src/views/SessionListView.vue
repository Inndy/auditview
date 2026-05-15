<template>
  <div class="session-list-page">
    <div class="page-header">
      <div>
        <h1>auditview</h1>
        <div v-if="config" class="server-root" title="Audit root">{{ config.root_path }}</div>
      </div>
      <button class="dark-btn" :title="darkMode ? 'Switch to light mode' : 'Switch to dark mode'" @click="onToggleDark">{{ darkMode ? '☀️' : '🌙' }}</button>
    </div>
    <div v-if="error" class="error-msg">{{ error }}</div>

    <div class="create-session-form">
      <h2>New Session</h2>
      <div class="form-group">
        <label>Label</label>
        <input v-model="form.label" type="text" placeholder="e.g. First pass" />
      </div>
      <div class="form-group">
        <label>Exclusion patterns <span class="label-hint">(gitignore syntax, one per line)</span></label>
        <textarea v-model="form.exclusion_patterns" rows="3" placeholder="*.log&#10;build/"></textarea>
      </div>
      <button class="btn-primary" @click="submitCreate" :disabled="creating">
        {{ creating ? 'Creating…' : 'Create Session' }}
      </button>
    </div>

    <div class="session-list">
      <h2>Sessions</h2>
      <div v-if="loading">Loading…</div>
      <div v-else-if="sessions.length === 0" class="empty">No sessions yet.</div>
      <table v-else>
        <thead>
          <tr>
            <th>ID</th>
            <th>Label</th>
            <th>Created</th>
            <th>MCP</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.id" :class="{ 'mcp-active-row': s.id === mcpSessionId }">
            <td>{{ s.id }}</td>
            <td>{{ s.label }}</td>
            <td>{{ s.created_at }}</td>
            <td>
              <button
                class="mcp-btn"
                :class="{ active: s.id === mcpSessionId }"
                :title="s.id === mcpSessionId ? 'Deactivate MCP target' : 'Set as MCP target'"
                @click="toggleMcpSession(s.id)"
              >{{ s.id === mcpSessionId ? '⬡ active' : '⬡ inactive' }}</button>
            </td>
            <td>
              <router-link :to="`/sessions/${s.id}/code`" class="nav-link">Code</router-link>
              <router-link :to="`/sessions/${s.id}/issues`" class="nav-link">Issues</router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { listSessions, createSession } from '../api/sessions.js'
import { getConfig, setMcpSession, clearMcpSession } from '../api/config.js'
import { isDark, toggleDark } from '../darkMode.js'

export default {
  name: 'SessionListView',
  data() {
    return {
      sessions: [],
      config: null,
      mcpSessionId: null,
      loading: true,
      error: null,
      creating: false,
      darkMode: isDark(),
      form: {
        label: '',
        exclusion_patterns: '',
      },
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
        const [sessions, config] = await Promise.all([listSessions(), getConfig()])
        this.sessions = sessions
        this.config = config
        this.mcpSessionId = config.mcp_session ? config.mcp_session.id : null
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    async submitCreate() {
      if (!this.form.label) {
        this.error = 'Label is required.'
        return
      }
      this.creating = true
      this.error = null
      try {
        const s = await createSession({
          label: this.form.label,
          exclusion_patterns: this.form.exclusion_patterns,
        })
        this.sessions.push(s)
        this.form = { label: '', exclusion_patterns: '' }
      } catch (e) {
        this.error = e.message
      } finally {
        this.creating = false
      }
    },
    async toggleMcpSession(id) {
      try {
        if (this.mcpSessionId === id) {
          await clearMcpSession()
          this.mcpSessionId = null
        } else {
          const res = await setMcpSession(id)
          this.mcpSessionId = res.mcp_session ? res.mcp_session.id : null
        }
      } catch (e) {
        this.error = e.message
      }
    },
    onToggleDark() {
      toggleDark()
      this.darkMode = isDark()
    },
  },
}
</script>

<style scoped>
.session-list-page {
  max-width: 860px;
  margin: 40px auto;
  padding: 0 20px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 32px;
}

h1 {
  font-size: 28px;
}

.server-root {
  font-size: 12px;
  color: var(--text-muted);
  font-family: monospace;
  margin-top: 4px;
}

h2 {
  font-size: 18px;
  margin-bottom: 16px;
}

.dark-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 20px;
  padding: 0;
  line-height: 1;
  margin-top: 4px;
}

.create-session-form {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 20px;
  margin-bottom: 32px;
}

.form-group {
  margin-bottom: 14px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}

.label-hint {
  font-weight: 400;
  color: var(--text-muted);
}

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  font-family: inherit;
  background: var(--bg-surface);
  color: var(--text);
}

.session-list {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 20px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th {
  text-align: left;
  padding: 8px;
  border-bottom: 2px solid var(--border);
  font-weight: 600;
}

td {
  padding: 8px;
  border-bottom: 1px solid var(--border-light);
}

.error-msg {
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
  border: 1px solid var(--danger);
  border-radius: 4px;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 13px;
}

.empty {
  color: var(--text-muted);
  font-size: 13px;
}

.mcp-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  cursor: pointer;
  color: var(--text-muted);
  min-width: 6em;
}

.mcp-btn.active {
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

.mcp-active-row {
  background: var(--bg-hover);
}

.nav-link {
  display: inline-block;
  margin-right: 8px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--primary);
  text-decoration: none;
  border: 1px solid var(--border);
  border-radius: 3px;
}

.nav-link:hover {
  background: var(--bg-surface);
}
</style>
