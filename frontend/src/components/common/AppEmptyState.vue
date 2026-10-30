<template>
  <div class="app-empty-state" :class="{ 'app-empty-state--inline': inline }">
    <div class="app-empty-state__icon-wrap">
      <!-- History Icon -->
      <svg v-if="icon === 'history' || !icon" class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
        <path d="M3 3v5h5"/>
        <path d="M12 7v5l4 2"/>
      </svg>
      <!-- Dataset / Database Icon -->
      <svg v-else-if="icon === 'dataset'" class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3"/>
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
        <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
      </svg>
      <!-- Model / CPU Icon -->
      <svg v-else-if="icon === 'model'" class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
      </svg>
      <!-- Report / FileText Icon -->
      <svg v-else-if="icon === 'report'" class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
      <!-- Optimization / Sliders Icon -->
      <svg v-else-if="icon === 'optimization'" class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="m13 2-2 2.5h3L12 7"/><path d="M10 14v-3"/><path d="M14 14v-3"/><path d="M16 14v-3"/><path d="M8 14v-3"/><path d="M4 14h16a2 2 0 0 1 0 4H4a2 2 0 0 1 0-4z"/>
      </svg>
      <!-- Search Icon -->
      <svg v-else-if="icon === 'search'" class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.35-4.35"/>
      </svg>
    </div>

    <h3 class="app-empty-state__title">{{ title }}</h3>
    <p v-if="description" class="app-empty-state__desc">{{ description }}</p>

    <div v-if="primaryAction || secondaryAction" class="app-empty-state__actions">
      <router-link
        v-if="primaryAction?.to"
        :to="primaryAction.to"
        class="empty-cta-btn empty-cta-btn--primary"
      >
        <svg v-if="primaryAction.icon === 'plus' || !primaryAction.icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        <span>{{ primaryAction.label }}</span>
      </router-link>
      <button
        v-else-if="primaryAction"
        type="button"
        class="empty-cta-btn empty-cta-btn--primary"
        @click="primaryAction.onClick?.()"
      >
        <span>{{ primaryAction.label }}</span>
      </button>

      <router-link
        v-if="secondaryAction?.to"
        :to="secondaryAction.to"
        class="empty-cta-btn empty-cta-btn--secondary"
      >
        <span>{{ secondaryAction.label }}</span>
      </router-link>
      <button
        v-else-if="secondaryAction"
        type="button"
        class="empty-cta-btn empty-cta-btn--secondary"
        @click="secondaryAction.onClick?.()"
      >
        <span>{{ secondaryAction.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
interface ActionDef {
  label: string;
  to?: string;
  onClick?: () => void;
  icon?: string;
}

withDefaults(
  defineProps<{
    icon?: 'history' | 'dataset' | 'model' | 'report' | 'optimization' | 'search';
    title: string;
    description?: string;
    primaryAction?: ActionDef;
    secondaryAction?: ActionDef;
    inline?: boolean;
  }>(),
  {
    icon: 'history',
    inline: false,
  }
);
</script>

<style scoped>
.app-empty-state {
  max-width: 480px;
  margin: 100px auto 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 32px 24px;
}

.app-empty-state--inline {
  max-width: 100%;
  margin: 0;
  min-height: 200px;
  padding: 32px 16px;
  justify-content: center;
}

.app-empty-state__icon-wrap {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: #F0F2ED;
  border: 1px solid #E5E8E2;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #838A81;
  margin-bottom: 18px;
  transition: all 0.2s ease;
}

.app-empty-state--inline .app-empty-state__icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  margin-bottom: 12px;
}

.empty-icon {
  width: 28px;
  height: 28px;
}

.app-empty-state--inline .empty-icon {
  width: 22px;
  height: 22px;
}

.app-empty-state__title {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 600;
  color: #2C332B;
  letter-spacing: -0.01em;
}

.app-empty-state--inline .app-empty-state__title {
  font-size: 15px;
  margin-bottom: 6px;
}

.app-empty-state__desc {
  margin: 0 0 22px;
  font-size: 14px;
  line-height: 1.6;
  color: #666E63;
  max-width: 380px;
}

.app-empty-state--inline .app-empty-state__desc {
  font-size: 13px;
  margin-bottom: 16px;
}

.app-empty-state__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
}

.empty-cta-btn {
  height: 38px;
  padding: 0 18px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.empty-cta-btn--primary {
  background: #82A978;
  color: #FFFFFF;
  border-color: #82A978;
}

.empty-cta-btn--primary:hover {
  background: #719967;
  border-color: #719967;
}

.empty-cta-btn--secondary {
  background: #FFFFFF;
  color: #426340;
  border-color: #DFE4DB;
}

.empty-cta-btn--secondary:hover {
  background: #F0F2ED;
  border-color: #82A978;
}
</style>
