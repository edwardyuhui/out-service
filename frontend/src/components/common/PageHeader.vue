<template>
  <header class="page-header-unified">
    <div class="page-header-unified__main">
      <div v-if="eyebrow" class="page-header-unified__eyebrow">{{ eyebrow }}</div>
      <h1 class="page-header-unified__title">{{ title }}</h1>
      <p v-if="description || $slots.description" class="page-header-unified__desc">
        <slot name="description">{{ description }}</slot>
      </p>
    </div>
    <div v-if="$slots.actions" class="page-header-unified__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  eyebrow?: string;
  title: string;
  description?: string;
}>();
</script>

<style scoped>
.page-header-unified {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: start;
  column-gap: 32px;
  row-gap: 16px;
  margin-bottom: var(--section-gap-md, 32px);
  padding-bottom: var(--space-4, 16px);
  border-bottom: 1px solid var(--border-subtle, #e8eae5);
}

.page-header-unified__main {
  min-width: 0;
}

.page-header-unified__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: normal;
  font-family: var(--font-sans);
  text-transform: uppercase;
  color: #63805E;
  margin-bottom: 8px;
}

.page-header-unified__title {
  margin: 0;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.2;
  color: #2C332B;
  letter-spacing: -0.02em;
}

.page-header-unified__desc {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.5;
  color: #666E63;
  max-width: 760px;
}

.page-header-unified__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  padding-top: 4px;
}

:deep(.page-primary-btn) {
  height: 38px;
  padding: 0 16px;
  background: #82A978;
  border-color: #82A978;
  color: #FFFFFF;
  font-weight: 600;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  transition: all 0.15s ease;
  text-decoration: none;
  cursor: pointer;
}

:deep(.page-primary-btn:hover) {
  background: #719967;
  border-color: #719967;
}

@media (max-width: 768px) {
  .page-header-unified {
    grid-template-columns: 1fr;
  }
}
</style>
