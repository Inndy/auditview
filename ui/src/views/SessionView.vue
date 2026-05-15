<template>
  <div class="session-view-wrap">
    <div v-if="loadingSession" class="loading-full">Loading session…</div>
    <div v-else-if="sessionError" class="error-full">{{ sessionError }}</div>
    <template v-else>
      <SessionHeader
        :session="session"
        :coverage="coverage"
        :skipComments="skipComments"
        :wrapLines="wrapLines"
        @skip-comments-change="skipComments = $event"
        @wrap-lines-change="wrapLines = $event; localStorage.setItem('wrapLines', $event)"
        @show-help="showHelp = true"
      />
      <div class="nav-tabs">
        <router-link :to="`/sessions/${id}/code`" class="nav-tab" active-class="active">Code</router-link>
        <router-link :to="`/sessions/${id}/issues`" class="nav-tab" active-class="active">Issues</router-link>
      </div>
      <router-view
        :session="session"
        :coverage="coverage"
        :skipComments="skipComments"
        :wrapLines="wrapLines"
        @skip-comments-change="skipComments = $event"
        @wrap-lines-change="wrapLines = $event; localStorage.setItem('wrapLines', $event)"
        @show-help="showHelp = true"
      />
      <KeyboardHelpModal :visible="showHelp" @close="showHelp = false" />
    </template>
  </div>
</template>

<script>
import { listSessions } from '../api/sessions.js'
import { getCoverage } from '../api/coverage.js'
import SessionHeader from '../components/SessionHeader.vue'
import KeyboardHelpModal from '../components/KeyboardHelpModal.vue'

export default {
  name: 'SessionView',
  components: {
    SessionHeader,
    KeyboardHelpModal,
  },
  data() {
    return {
      id: this.$route.params.id,
      session: null,
      coverage: null,
      loadingSession: true,
      sessionError: null,
      skipComments: false,
      wrapLines: localStorage.getItem('wrapLines') === 'true',
      showHelp: false,
    }
  },
  mounted() {
    this.loadSession()
  },
  methods: {
    async loadSession() {
      this.loadingSession = true
      this.sessionError = null
      try {
        const sessions = await listSessions()
        const sid = parseInt(this.id)
        this.session = sessions.find((s) => s.id === sid)
        if (!this.session) {
          this.sessionError = `Session ${this.id} not found.`
          return
        }
        this.coverage = await getCoverage(this.id)
      } catch (e) {
        this.sessionError = e.message
      } finally {
        this.loadingSession = false
      }
    },
  },
}
</script>

<style scoped>
.session-view-wrap {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}

.nav-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  padding: 0 20px;
}

.nav-tab {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  text-decoration: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.nav-tab:hover {
  color: var(--text);
}

.nav-tab.active {
  color: var(--text);
  border-bottom-color: var(--primary);
}

.loading-full,
.error-full {
  padding: 40px;
  font-size: 14px;
  color: var(--text-muted);
}

.error-full {
  color: var(--badge-orphan-text);
}
</style>
