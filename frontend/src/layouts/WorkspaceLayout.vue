<template>
  <div class="workspace-layout">
    <AppShell />
  </div>
</template>

<script setup lang="ts">
import AppShell from '../components/shell/AppShell.vue';
</script>

<style scoped>
.workspace-layout {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}
</style>
