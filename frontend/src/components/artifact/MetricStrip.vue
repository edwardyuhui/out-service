<template>
  <div class="metric-strip">
    <div
      v-for="m in metrics"
      :key="m.label"
      class="metric-item"
      :class="{ 'is-primary': m.primary }"
    >
      <div class="metric-label">{{ m.label }}</div>
      <div class="metric-value tabular-nums">{{ m.value }}</div>
      <div v-if="m.sub" class="metric-sub">{{ m.sub }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  metrics: {
    label: string;
    value: string;
    sub?: string;
    primary?: boolean;
  }[];
}>();
</script>

<style scoped>
.metric-strip {
  display: flex;
  gap: 1px;
  background: var(--border-subtle);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.metric-item {
  flex: 1;
  padding: var(--space-3) var(--space-3);
  background: var(--surface-1);
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  transition: background var(--transition-fast);
}

.metric-item.is-primary {
  background: var(--surface-2);
}

.metric-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: normal;
  font-family: var(--font-sans);
  white-space: nowrap;
}

.metric-item.is-primary .metric-label {
  color: var(--accent-dark);
}

.metric-value {
  font-size: var(--font-size-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.metric-item.is-primary .metric-value {
  color: var(--accent-dark);
}

.metric-sub {
  font-family: var(--font-sans);
  letter-spacing: normal;
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
</style>
