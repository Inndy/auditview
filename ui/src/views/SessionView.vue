<template>
  <div class="session-view-wrap">
    <div v-if="loadingSession" class="loading-full">Loading session…</div>
    <div v-else-if="sessionError" class="error-full">{{ sessionError }}</div>
    <template v-else>
      <SessionHeader
        :session="session"
        :coverage="coverage"
        :skipComments="skipComments"
        @skip-comments-change="skipComments = $event"
        @show-help="showHelp = true"
      />
      <div class="session-layout">
        <FileTree
          ref="fileTree"
          :sessionId="id"
          @file-selected="openFile"
        />
        <CodeViewer
          ref="codeViewer"
          :sessionId="id"
          :filePath="currentFile"
          :skipComments="skipComments"
          @notes-updated="onNotesUpdated"
          @lines-marked="refreshCoverage"
          @file-reloaded="onFileReloaded"
          @show-help="showHelp = true"
        />
        <div class="right-panels">
          <NotePanel
            :notes="currentNotes"
            :sessionId="id"
            @note-updated="onNoteUpdated"
            @note-deleted="onNoteDeleted"
          />
          <OrphanPanel
            :notes="currentNotes"
            :sessionId="id"
            @note-updated="onNoteUpdated"
            @note-deleted="onNoteDeleted"
          />
          <CheckpointPanel :sessionId="id" ref="checkpointPanel" @reverted="onReverted" />
        </div>
      </div>
      <KeyboardHelpModal :visible="showHelp" @close="showHelp = false" />
    </template>
  </div>
</template>

<script>
import { listSessions } from '../api/sessions.js'
import { getCoverage } from '../api/coverage.js'
import SessionHeader from '../components/SessionHeader.vue'
import FileTree from '../components/FileTree.vue'
import CodeViewer from '../components/CodeViewer.vue'
import NotePanel from '../components/NotePanel.vue'
import OrphanPanel from '../components/OrphanPanel.vue'
import CheckpointPanel from '../components/CheckpointPanel.vue'
import KeyboardHelpModal from '../components/KeyboardHelpModal.vue'

export default {
  name: 'SessionView',
  components: {
    SessionHeader,
    FileTree,
    CodeViewer,
    NotePanel,
    OrphanPanel,
    CheckpointPanel,
    KeyboardHelpModal,
  },
  data() {
    return {
      id: this.$route.params.id,
      session: null,
      coverage: null,
      loadingSession: true,
      sessionError: null,
      currentFile: null,
      currentNotes: [],
      skipComments: false,
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
    openFile(path) {
      this.currentFile = path
      this.currentNotes = []
    },
    onNotesUpdated(notes) {
      this.currentNotes = notes
    },
    async refreshCoverage() {
      try {
        this.coverage = await getCoverage(this.id)
      } catch { }
    },
    onFileReloaded() {
      this.$refs.fileTree?.refresh()
      this.refreshCoverage()
    },
    onNoteUpdated(updated) {
      const idx = this.currentNotes.findIndex((n) => n.id === updated.id)
      if (idx !== -1) this.currentNotes.splice(idx, 1, updated)
    },
    onNoteDeleted(id) {
      this.currentNotes = this.currentNotes.filter((n) => n.id !== id)
    },
    onReverted() {
      this.$refs.fileTree?.refresh()
      this.refreshCoverage()
      this.currentNotes = []
      this.$refs.codeViewer?.reload()
    },
  },
}
</script>

<style scoped>
.session-view-wrap {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.session-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.loading-full,
.error-full {
  padding: 40px;
  font-size: 14px;
  color: #888;
}

.error-full {
  color: #842029;
}
</style>
