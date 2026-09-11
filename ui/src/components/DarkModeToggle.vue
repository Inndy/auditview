<template>
  <button
    class="dark-mode-toggle"
    :aria-label="dark ? 'Switch to light mode' : 'Switch to dark mode'"
    :title="dark ? 'Switch to light mode' : 'Switch to dark mode'"
    @click="toggle"
  >{{ dark ? '☀️' : '🌙' }}</button>
</template>

<script>
import { isDark, toggleDark } from '../darkMode.js'

export default {
  name: 'DarkModeToggle',
  data() {
    return { dark: isDark() }
  },
  methods: {
    toggle() {
      toggleDark()
      this.dark = isDark()
    },
  },
}
</script>

<style scoped>
.dark-mode-toggle {
  background: none;
  border: none;
  cursor: pointer;
  font-size: inherit;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
}
</style>
