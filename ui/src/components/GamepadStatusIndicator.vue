<template>
  <router-link v-if="info" to="/gamepad" class="pad-indicator" :title="'Gamepad: ' + info.id">
    <span class="pad-dot">●</span>
    <span class="pad-label">Pad</span>
  </router-link>
</template>

<script>
import { gamepad } from '../input/gamepad.js'

export default {
  name: 'GamepadStatusIndicator',
  computed: {
    info() {
      return gamepad.info.value
    },
  },
}
</script>

<style scoped>
.pad-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--status-success);
  text-decoration: none;
  user-select: none;
}

.pad-dot {
  font-size: 10px;
  line-height: 1;
}
</style>
