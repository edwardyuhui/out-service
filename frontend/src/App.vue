<template>
  <router-view />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { useSystemStore } from "./stores/systemStore";

const systemStore = useSystemStore();

onMounted(() => {
  const savedTheme = localStorage.getItem("indusopt_theme");
  if (savedTheme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  systemStore.startHealthPolling();
});

onBeforeUnmount(() => {
  systemStore.stopHealthPolling();
});
</script>
