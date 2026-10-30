<template>
  <aside
    class="primary-nav"
    :class="{ 'is-expanded': isExpanded, 'is-collapsed': !isExpanded }"
  >
    <!-- Top Header / Brand Bar -->
    <div class="nav-header">
      <router-link to="/home" class="nav-brand" :title="!isExpanded ? 'IndusOpt 首页' : undefined">
        <div class="brand-logo">
          <img
            class="brand-logo__image"
            :src="indusOptMark"
            alt=""
            width="24"
            height="24"
          />
        </div>
        <div v-show="isExpanded" class="brand-info">
          <span class="brand-name">IndusOpt</span>
        </div>
      </router-link>

      <!-- Toggle Button (Expanded mode) -->
      <button
        v-if="isExpanded"
        class="nav-toggle-btn"
        type="button"
        title="折叠侧边栏"
        aria-label="折叠侧边栏"
        @click="toggleSidebar"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>
          <line x1="9" y1="3" x2="9" y2="21"/>
          <path d="m15 9-3 3 3 3"/>
        </svg>
      </button>

      <!-- Toggle Button (Collapsed mode) -->
      <el-tooltip
        v-else
        content="展开侧边栏"
        placement="right"
        :show-after="300"
        :enterable="false"
      >
        <button
          class="nav-toggle-btn nav-toggle-btn--collapsed"
          type="button"
          aria-label="展开侧边栏"
          @click="toggleSidebar"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>
            <line x1="9" y1="3" x2="9" y2="21"/>
            <path d="m13 9 3 3-3 3"/>
          </svg>
        </button>
      </el-tooltip>
    </div>

    <!-- Navigation Items List -->
    <nav class="nav-items" aria-label="主导航">
      <NavItem
        v-for="item in primaryNavItems"
        :key="item.name"
        :item="item"
        :is-expanded="isExpanded"
      />
    </nav>

    <!-- Bottom Actions / System Status -->
    <div class="nav-bottom">
      <div class="nav-divider" />

      <!-- Command Palette Search Button -->
      <el-tooltip
        :content="'搜索 · ' + (isMac ? '⌘K' : 'Ctrl+K')"
        placement="right"
        :disabled="isExpanded"
        :show-after="300"
        :enterable="false"
      >
        <button
          class="nav-action-btn"
          type="button"
          :aria-label="'搜索 ' + (isMac ? '⌘K' : 'Ctrl+K')"
          @click="openCommandPalette()"
        >
          <div class="nav-action-btn__icon">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
          </div>
          <span v-show="isExpanded" class="nav-action-btn__label">搜索</span>
          <span v-show="isExpanded" class="nav-action-btn__shortcut">{{ isMac ? '⌘K' : 'Ctrl+K' }}</span>
        </button>
      </el-tooltip>

      <!-- Settings -->
      <NavItem
        :item="settingsItem"
        :is-expanded="isExpanded"
      />

      <!-- Health Indicator -->
      <el-tooltip
        :content="healthTooltip"
        placement="right"
        :show-after="300"
        :enterable="false"
      >
        <div class="nav-health" :class="{ 'is-collapsed': !isExpanded }">
          <span class="health-dot" :class="systemStore.status" />
          <span v-show="isExpanded" class="health-text">{{ healthLabel }}</span>
        </div>
      </el-tooltip>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, inject, onMounted } from 'vue';
import indusOptMark from '../../assets/brand/indusopt-mark.png';
import { useSystemStore } from '../../stores/systemStore';
import NavItem, { type NavItemDef } from './NavItem.vue';

const systemStore = useSystemStore();
const isExpanded = ref(true);
const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

const openCommandPalette = inject<() => void>('openCommandPalette', () => {});

onMounted(() => {
  const savedState = localStorage.getItem('indusopt.sidebar_collapsed');
  if (savedState === 'true') {
    isExpanded.value = false;
  } else {
    isExpanded.value = true;
  }
});

function toggleSidebar() {
  isExpanded.value = !isExpanded.value;
  localStorage.setItem('indusopt.sidebar_collapsed', isExpanded.value ? 'false' : 'true');
}

const primaryNavItems: NavItemDef[] = [
  {
    name: 'home',
    path: '/home',
    label: '首页',
    icon: 'home',
  },
  {
    name: 'workspace',
    path: '/workspace',
    label: 'Agent 工作台',
    icon: 'bot',
  },
  {
    name: 'runs',
    path: '/runs',
    label: '任务历史',
    icon: 'history',
  },
  {
    name: 'assets',
    path: '/assets',
    label: '功能中心',
    icon: 'assets',
  },
];

const settingsItem: NavItemDef = {
  name: 'settings',
  path: '/settings',
  label: '设置',
  icon: 'settings',
};

const healthLabel = computed(() => {
  switch (systemStore.status) {
    case 'ready':
      return '系统正常';
    case 'connecting':
      return '正在连接';
    case 'offline':
    default:
      return '服务未连接';
  }
});

const healthTooltip = computed(() => {
  switch (systemStore.status) {
    case 'ready':
      return '系统状态：正常 (后端服务、数据库就绪)';
    case 'connecting':
      return '系统状态：正在连接后端服务…';
    case 'offline':
    default:
      return '系统状态：服务未连接，请检查后端运行状态';
  }
});
</script>

<style scoped>
.primary-nav {
  width: 224px;
  height: 100vh;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #FDFCFA;
  border-right: 1px solid #E8EAE5;
  overflow: hidden;
  transition: width 0.2s cubic-bezier(0.2, 0.9, 0.3, 1);
  z-index: 50;
  user-select: none;
}

.primary-nav.is-collapsed {
  width: 56px;
}

/* Header */
.nav-header {
  height: 64px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  border-bottom: 1px solid #F0F2ED;
}

.primary-nav.is-collapsed .nav-header {
  justify-content: center;
  padding: 0;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  min-width: 0;
}

.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #FFFFFF;
  border: 1px solid #DFE4DB;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #5E8358;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.brand-logo__image {
  display: block;
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.nav-brand:hover .brand-logo {
  border-color: #82A978;
  color: #426340;
}

.brand-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
  color: #2C332B;
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.nav-toggle-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #858B82;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.nav-toggle-btn:hover {
  background: #F0F2ED;
  color: #30352F;
}

.nav-toggle-btn--collapsed {
  display: none;
}

.primary-nav.is-collapsed .nav-toggle-btn--collapsed {
  display: flex;
  margin-top: 6px;
}

/* Nav Items */
.nav-items {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 0;
  overflow-y: auto;
  overflow-x: hidden;
}

/* Bottom Actions */
.nav-bottom {
  padding: 8px 0 12px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-divider {
  height: 1px;
  background: #E8EAE5;
  margin: 4px 10px 8px;
}

.nav-action-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  padding: 0 10px;
  margin: 2px 6px;
  border-radius: 8px;
  color: #747A72;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s ease;
  outline: none;
  text-align: left;
}

.nav-action-btn:hover {
  background: #F0F2ED;
  color: #30352F;
}

.nav-action-btn:focus-visible {
  outline: 2px solid #82A978;
  outline-offset: 1px;
}

.nav-action-btn__icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nav-action-btn__label {
  font-size: 14px;
  font-weight: 500;
  color: #747A72;
  white-space: nowrap;
}

.nav-action-btn__shortcut {
  font-size: 11px;
  color: #9AA096;
  background: #E5E8E2;
  padding: 2px 5px;
  border-radius: 4px;
  margin-left: auto;
}

/* Health Bar */
.nav-health {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 34px;
  padding: 0 14px;
  margin: 2px 6px;
  border-radius: 6px;
  cursor: default;
}

.nav-health.is-collapsed {
  padding: 0 10px;
  justify-content: center;
}

.health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #E6A23C; /* connecting/warning */
  transition: background-color 0.2s ease;
}

.health-dot.ready {
  background: #5E8358; /* sage ready */
  box-shadow: 0 0 0 2px rgba(94, 131, 88, 0.2);
}

.health-dot.offline {
  background: #D96A6A; /* danger */
}

.health-text {
  font-size: 12px;
  font-weight: 400;
  color: #858B82;
  font-family: var(--font-sans);
  letter-spacing: normal;
  white-space: nowrap;
}
</style>
