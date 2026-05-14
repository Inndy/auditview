<template>
  <label class="skip-comments-toggle">
    <input type="checkbox" :checked="modelValue" @change="$emit('change', $event.target.checked)" />
    Skip comments
  </label>
</template>

<script>
export default {
  name: 'SkipCommentsToggle',
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['change'],
}
</script>

<style scoped>
.skip-comments-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}
</style>
