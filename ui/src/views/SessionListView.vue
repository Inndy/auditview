<template>
  <div class="session-list-page">
    <h1>auditview</h1>
    <div v-if="error" class="error-msg">{{ error }}</div>

    <div class="create-session-form">
      <h2>New Session</h2>
      <div class="form-group">
        <label>Label</label>
        <input v-model="form.label" type="text" placeholder="e.g. First pass" />
      </div>
      <div class="form-group">
        <label>Root path</label>
        <input v-model="form.root_path" type="text" placeholder="/home/user/myproject" />
      </div>
      <div class="form-group">
        <label>Exclusion patterns (gitignore syntax, one per line)</label>
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
            <th>Root path</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.id">
            <td>{{ s.id }}</td>
            <td>{{ s.label }}</td>
            <td><code>{{ s.root_path }}</code></td>
            <td>{{ s.created_at }}</td>
            <td><a :href="'/sessions/' + s.id" @click.prevent="openSession(s.id)">Open</a></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { listSessions, createSession } from '../api/sessions.js'

export default {
  name: 'SessionListView',
  data() {
    return {
      sessions: [],
      loading: true,
      error: null,
      creating: false,
      form: {
        label: '',
        root_path: '',
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
        this.sessions = await listSessions()
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    async submitCreate() {
      if (!this.form.label || !this.form.root_path) {
        this.error = 'Label and root path are required.'
        return
      }
      this.creating = true
      this.error = null
      try {
        const s = await createSession({
          label: this.form.label,
          root_path: this.form.root_path,
          exclusion_patterns: this.form.exclusion_patterns,
        })
        this.sessions.push(s)
        this.form = { label: '', root_path: '', exclusion_patterns: '' }
      } catch (e) {
        this.error = e.message
      } finally {
        this.creating = false
      }
    },
    openSession(id) {
      this.$router.push(`/sessions/${id}`)
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

h1 {
  font-size: 28px;
  margin-bottom: 32px;
}

h2 {
  font-size: 18px;
  margin-bottom: 16px;
}

.create-session-form {
  background: #fff;
  border: 1px solid #ddd;
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

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 13px;
  font-family: inherit;
}

.session-list {
  background: #fff;
  border: 1px solid #ddd;
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
  border-bottom: 2px solid #ddd;
  font-weight: 600;
}

td {
  padding: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.error-msg {
  background: #f8d7da;
  color: #842029;
  border: 1px solid #f5c2c7;
  border-radius: 4px;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 13px;
}

.empty {
  color: #888;
  font-size: 13px;
}
</style>
