<template>
  <div class="issues-view">
    <div class="placeholder">Issues view coming soon…</div>
  </div>
</template>

<script>
export default {
  name: 'IssuesView',
  props: {
    session: Object,
    coverage: Object,
    skipComments: Boolean,
    wrapLines: Boolean,
  },
}
</script>

<style scoped>
.issues-view {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-muted);
  font-size: 14px;
}
</style>
