<template>
  <div class="session-view-wrap">
    <div v-if="loadingSession" class="loading-full">Loading session…</div>
    <div v-else-if="sessionError" class="error-full">{{ sessionError }}</div>
    <template v-else>
      <SessionHeader
        :session="session"
        :coverage="coverage"
        :wrapLines="wrapLines"
        @wrap-lines-change="setWrapLines($event)"
        @show-help="showHelp = true"
        @show-settings="showSettings = true"
      />
      <div class="nav-tabs">
        <router-link :to="`/sessions/${id}/code`" class="nav-tab" active-class="active">Code</router-link>
        <router-link :to="`/sessions/${id}/issues`" class="nav-tab" active-class="active">Issues</router-link>
        <div v-if="currentFile" class="nav-file" :title="currentFile">
          <span class="nav-file-icon">👁️</span>
          <span v-if="currentFileDir" class="nav-file-dir">{{ currentFileDir }}</span>
          <span v-if="currentFileDir" class="nav-file-sep">/</span>
          <span class="nav-file-name">{{ currentFileName }}</span>
        </div>
      </div>
      <router-view
        :session="session"
        :coverage="coverage"
        :wrapLines="wrapLines"
        @wrap-lines-change="setWrapLines($event)"
        @show-help="showHelp = true"
        @coverage-refreshed="coverage = $event"
      />
      <KeyboardHelpModal :visible="showHelp" @close="showHelp = false" />
      <SessionSettings
        :visible="showSettings"
        :session="session"
        @close="showSettings = false"
        @changed="onSettingsChanged"
      />
    </template>
  </div>
</template>

<script>
import { listSessions } from '../api/sessions.js'
import { getCoverage } from '../api/coverage.js'
import SessionHeader from '../components/SessionHeader.vue'
import KeyboardHelpModal from '../components/KeyboardHelpModal.vue'
import SessionSettings from '../components/SessionSettings.vue'
import { getBoolPref, setBoolPref } from '../prefs.js'

export default {
  name: 'SessionView',
  components: {
    SessionHeader,
    KeyboardHelpModal,
    SessionSettings,
  },
  data() {
    return {
      id: this.$route.params.id,
      session: null,
      coverage: null,
      loadingSession: true,
      sessionError: null,
      wrapLines: getBoolPref('wrapLines'),
      showHelp: false,
      showSettings: false,
    }
  },
  computed: {
    // The route query is where CodeView records the open file, so the header
    // stays in sync with the viewer (and with a pasted deep link) for free.
    currentFile() {
      return this.$route.query.file || null
    },
    // The trailing separator is a sibling span rather than part of this
    // string: `.nav-file-dir` is RTL so the ellipsis lands at the start, and a
    // trailing '/' is a bidi-neutral that would be flipped to the far left.
    currentFileDir() {
      const parts = (this.currentFile || '').split('/')
      return parts.length > 1 ? parts.slice(0, -1).join('/') : ''
    },
    currentFileName() {
      const parts = (this.currentFile || '').split('/')
      return parts[parts.length - 1]
    },
  },
  mounted() {
    this.loadSession()
  },
  methods: {
    setWrapLines(val) {
      this.wrapLines = val
      setBoolPref('wrapLines', val)
    },
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
    async onSettingsChanged(updated) {
      if (updated) this.session = updated
      try {
        this.coverage = await getCoverage(this.id)
      } catch (e) {
        this.sessionError = e.message
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

.nav-file {
  display: flex;
  align-items: center;
  align-self: center;
  min-width: 0;
  margin-left: 16px;
  font-family: 'Fira Mono', 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}

.nav-file-icon {
  flex-shrink: 0;
  margin-right: 6px;
  font-size: 11px;
}

/* Shrink the directory from its left so the file name stays readable. */
.nav-file-dir {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
  color: var(--text-dim);
}

.nav-file-sep {
  flex-shrink: 0;
  color: var(--text-dim);
}

.nav-file-name {
  flex-shrink: 0;
  white-space: nowrap;
  color: var(--text);
  font-weight: 600;
}

.nav-tab {
  flex-shrink: 0;
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
