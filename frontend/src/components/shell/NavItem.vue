<template>
  <el-tooltip
    :content="item.label + (item.shortcut ? ` (${item.shortcut})` : '')"
    placement="right"
    :disabled="isExpanded"
    :show-after="300"
    :enterable="false"
  >
    <router-link
      :to="item.path"
      class="nav-item"
      :class="{ 'is-active': isActive }"
      :aria-label="item.label"
    >
      <div class="nav-item__icon-wrap">
        <!-- Home (⌂) -->
        <svg v-if="item.icon === 'home'" class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
          <polyline points="9 22 9 12 15 12 15 22"/>
        </svg>

        <!-- Bot / Agent Workspace (◈) -->
        <svg v-else-if="item.icon === 'bot'" class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect width="18" height="10" x="3" y="11" rx="2"/>
          <circle cx="12" cy="5" r="2"/>
          <path d="M12 7v4"/>
          <line x1="8" x2="8" y1="16" y2="16"/>
          <line x1="16" x2="16" y1="16" y2="16"/>
        </svg>

        <!-- History / Runs (↶) -->
        <svg v-else-if="item.icon === 'history'" class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
          <path d="M3 3v5h5"/>
          <path d="M12 7v5l4 2"/>
        </svg>

        <!-- Assets / Archive (▣) -->
        <svg v-else-if="item.icon === 'archive' || item.icon === 'assets'" class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect width="20" height="5" x="2" y="3" rx="1"/>
          <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>
          <path d="M10 12h4"/>
        </svg>

        <!-- Settings (⚙) -->
        <svg v-else-if="item.icon === 'settings'" class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>

        <!-- Search / Cmd (⌕) -->
        <svg v-else-if="item.icon === 'search'" class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"/>
          <path d="m21 21-4.35-4.35"/>
        </svg>
      </div>

      <span class="nav-item__label" :class="{ 'is-hidden': !isExpanded }">{{ item.label }}</span>
      <span v-if="item.shortcut && isExpanded" class="nav-item__shortcut">{{ item.shortcut }}</span>
    </router-link>
  </el-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

export interface NavItemDef {
  name: string;
  path: string;
  label: string;
  icon: string;
  shortcut?: string;
}

const props = defineProps<{
  item: NavItemDef;
  isExpanded: boolean;
}>();

const route = useRoute();
const isActive = computed(() => {
  if (props.item.path === '/home') {
    return route.path === '/home';
  }
  if (props.item.path === '/workspace') {
    return route.path.startsWith('/workspace') || route.path.startsWith('/copilot');
  }
  if (props.item.path === '/assets') {
    return (
      route.path === '/assets' ||
      route.path.startsWith('/datasets') ||
      route.path.startsWith('/modeling') ||
      route.path.startsWith('/preprocessing') ||
      route.path.startsWith('/benchmark') ||
      route.path.startsWith('/simulation') ||
      route.path.startsWith('/deliverables')
    );
  }
  return route.path === props.item.path || route.path.startsWith(props.item.path);
});
</script>

<style scoped>
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  padding: 0 10px;
  margin: 2px 6px;
  border-radius: 8px;
  color: #747A72;
  text-decoration: none;
  overflow: hidden;
  white-space: nowrap;
  transition: all 0.15s ease;
  position: relative;
  outline: none;
}

.nav-item:hover {
  background: #F0F2ED;
  color: #30352F;
}

.nav-item:hover .ni-icon {
  color: #555C53;
}

.nav-item.is-active {
  background: #E8F0E5;
  color: #426340;
  font-weight: 600;
}

.nav-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2.5px;
  background: #82A978;
  border-radius: 0 2px 2px 0;
}

.nav-item:focus-visible {
  outline: 2px solid #82A978;
  outline-offset: 1px;
}

.nav-item__icon-wrap {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ni-icon {
  width: 18px;
  height: 18px;
  color: #858B82;
  transition: color 0.15s ease;
}

.nav-item.is-active .ni-icon {
  color: #5E8358;
}

.nav-item__label {
  font-size: 14px;
  line-height: 1;
  flex: 1;
  opacity: 1;
  transition: opacity 0.15s ease;
}

.nav-item__label.is-hidden {
  opacity: 0;
  pointer-events: none;
}

.nav-item__shortcut {
  font-size: 11px;
  color: #9AA096;
  background: #E5E8E2;
  padding: 2px 5px;
  border-radius: 4px;
  margin-left: auto;
}
</style>
