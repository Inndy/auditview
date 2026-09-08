<script setup lang="ts">
import { ref, computed } from 'vue'

const count = ref(0)
const doubled = computed(() => count.value * 2)

function increment() {
  count.value += 1
}
</script>

<template>
  <div>
    <span>{{ count }}</span>
    <span>{{ doubled }}</span>
    <button @click="increment">+1</button>
  </div>
</template>
