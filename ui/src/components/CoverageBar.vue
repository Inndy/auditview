<template>
  <div class="coverage-bar-wrap" :title="`${pct}% reviewed`">
    <div class="coverage-bar-fill" :style="{ width: pct + '%' }"></div>
  </div>
</template>

<script>
export default {
  name: 'CoverageBar',
  props: {
    coverage: {
      type: Number,
      default: 0,
    },
  },
  computed: {
    pct() {
      return Math.round((this.coverage || 0) * 100)
    },
  },
}
</script>
