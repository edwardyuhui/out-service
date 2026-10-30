<template>
  <div class="app-shell">
    <!-- Primary Navigation (left icon strip) -->
    <PrimaryNav />

    <!-- Page content with full vertical scroll capability -->
    <main class="app-shell__content">
      <router-view />
    </main>

    <!-- Global Command Palette -->
    <CommandPalette ref="cmdPaletteRef" />
  </div>
</template>

<script setup lang="ts">
import { ref, provide } from 'vue';
import PrimaryNav from './PrimaryNav.vue';
import CommandPalette from '../CommandPalette.vue';

const cmdPaletteRef = ref<{ open: () => void; close: () => void } | null>(null);

// Provide global command palette opener to descendants
provide('openCommandPalette', () => cmdPaletteRef.value?.open());
</script>

<style scoped>
.app-shell {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-app);
}

.app-shell__content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  scroll-behavior: smooth;
  position: relative;
}
</style>
