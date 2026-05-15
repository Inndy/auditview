<template>
  <div class="session-view-wrap">
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
        :wrapLines="wrapLines"
        @notes-updated="onNotesUpdated"
        @lines-marked="onLinesMarked"
        @file-reloaded="onFileReloaded"
        @show-help="$emit('show-help')"
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
  </div>
</template>

<script>
import { getCoverage } from '../api/coverage.js'
import FileTree from '../components/FileTree.vue'
import CodeViewer from '../components/CodeViewer.vue'
import NotePanel from '../components/NotePanel.vue'
import OrphanPanel from '../components/OrphanPanel.vue'
import CheckpointPanel from '../components/CheckpointPanel.vue'
import KeyboardHelpModal from '../components/KeyboardHelpModal.vue'

export default {
  name: 'CodeView',
  components: {
    FileTree,
    CodeViewer,
    NotePanel,
    OrphanPanel,
    CheckpointPanel,
    KeyboardHelpModal,
  },
  props: {
    session: Object,
    coverage: Object,
    skipComments: Boolean,
    wrapLines: Boolean,
  },
  emits: ['skip-comments-change', 'wrap-lines-change', 'show-help'],
  data() {
    return {
      id: this.$route.params.id,
      currentFile: null,
      currentNotes: [],
      showHelp: false,
    }
  },
  mounted() {
    const fileParam = this.$route.query.file
    if (fileParam) {
      this.currentFile = fileParam
    }
  },
  watch: {
    '$route.query.file'(newFile) {
      if (newFile) {
        this.currentFile = newFile
      }
    },
  },
  methods: {
    openFile(path) {
      this.currentFile = path
      this.currentNotes = []
    },
    onNotesUpdated(notes) {
      this.currentNotes = notes
    },
    onLinesMarked({ filePath, countable, reviewed }) {
      this.$refs.fileTree?.updateFile(filePath, { countable_lines: countable, reviewed_lines: reviewed })
      this.refreshCoverage()
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
  height: 100dvh;
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
