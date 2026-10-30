<template>
  <div class="artifact-download-actions" data-test="export-download-actions">
    <ElButton
      tag="a"
      type="primary"
      class="artifact-download-button artifact-download-button--primary"
      data-test="download-optimised-csv"
      :href="csvUrl"
      aria-label="下载优选 CSV"
    >
      <Download aria-hidden="true" />
      <span>下载优选 CSV</span>
    </ElButton>
    <ElButton
      tag="a"
      class="artifact-download-button artifact-download-button--secondary"
      data-test="download-export-manifest"
      :href="manifestUrl"
      aria-label="下载 Manifest"
    >
      <Document aria-hidden="true" />
      <span>下载 Manifest</span>
    </ElButton>
  </div>
</template>

<script setup lang="ts">
import { ElButton } from "element-plus";
import { Document, Download } from "@element-plus/icons-vue";

defineProps<{
  csvUrl: string;
  manifestUrl: string;
}>();
</script>

<style scoped>
.artifact-download-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
  min-width: 0;
  font-family: var(--font-sans);
}

.artifact-download-button {
  width: 100%;
  min-width: 0;
  min-height: 34px;
  margin: 0;
  border-radius: var(--radius-sm);
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  text-decoration: none;
  transition:
    color var(--transition-fast),
    background-color var(--transition-fast),
    border-color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--transition-fast);
}

.artifact-download-button + .artifact-download-button {
  margin-left: 0;
}

.artifact-download-button :deep(svg) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.artifact-download-button--primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #FFFFFF;
  box-shadow: 0 1px 3px var(--accent-glow);
}

.artifact-download-button--primary:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  color: #FFFFFF;
  box-shadow: 0 3px 8px rgba(66, 99, 64, 0.14);
}

.artifact-download-button--secondary {
  background: var(--surface-1);
  border-color: var(--accent-border);
  color: var(--accent-dark);
}

.artifact-download-button--secondary:hover {
  background: var(--accent-soft) !important;
  border-color: var(--border-focus) !important;
  color: var(--accent-dark) !important;
}

.artifact-download-button:active {
  transform: translateY(1px) scale(0.99);
}

.artifact-download-button:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
  box-shadow: 0 0 0 3px var(--accent-glow);
}

@media (max-width: 360px) {
  .artifact-download-actions {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
