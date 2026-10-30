<template>
  <header class="app-header">
    <div class="header-left">
      <router-link to="/" class="logo" title="返回产品概览首页">
        <div class="logo-icon-box">
          <el-icon class="logo-icon"><DataAnalysis /></el-icon>
        </div>
        <span class="logo-text">IndusOpt 工模智优</span>
        <span class="logo-tag">A14</span>
      </router-link>

      <div class="dataset-selector" v-if="datasetStore.activeDataset">
        <span class="label">当前数据：</span>
        <el-tooltip
          :content="`版本 ID：${datasetStore.activeDataset.version_id}`"
          placement="bottom"
        >
          <el-tag type="primary" effect="light" class="ds-tag">
            {{ datasetStore.activeDataset.name }}
          </el-tag>
        </el-tooltip>
      </div>
    </div>

    <!-- Center / Right Command & Status Bar -->
    <div class="header-right">
      <!-- Quick Command Hub Trigger Button -->
      <button class="cmd-trigger-btn" type="button" @click="emit('openCommand')">
        <el-icon><Search /></el-icon>
        <span class="cmd-trigger-text">快速指令 / 页面跳转</span>
        <span class="cmd-kbd">{{ isMac ? '⌘K' : 'Ctrl+K' }}</span>
      </button>

      <!-- Return to Landing Overview -->
      <router-link to="/" class="landing-link" title="返回首页系统介绍">
        <span>产品首页</span>
        <span class="link-arrow">↗</span>
      </router-link>

      <!-- System Health Indicator -->
      <el-tooltip content="后端、PostgreSQL 与 Redis 的健康状态，每 5 秒自动检测" placement="bottom">
        <div class="status-indicator">
          <span class="dot-wrapper">
            <span class="dot" :class="systemStore.status"></span>
            <span class="dot-ping" v-if="systemStore.status === 'ready'"></span>
          </span>
          <span class="status-text">{{ statusLabel }}</span>
        </div>
      </el-tooltip>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { DataAnalysis, Search } from "@element-plus/icons-vue";
import { useDatasetStore } from "../stores/datasetStore";
import { useSystemStore } from "../stores/systemStore";

const emit = defineEmits<{
  openCommand: [];
}>();

const datasetStore = useDatasetStore();
const systemStore = useSystemStore();

const isMac = typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

const statusLabel = computed(() => ({
  connecting: "正在检测",
  ready: "系统就绪",
  offline: "服务离线",
}[systemStore.status]));
</script>

<style scoped>
.app-header {
  height: 54px;
  background: var(--bg-header);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  position: relative;
  z-index: 10;
}

.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 800;
  font-size: 15px;
  color: var(--text-primary);
  text-decoration: none;
  letter-spacing: -0.02em;
  transition: opacity 0.2s ease;
}

.logo:hover {
  opacity: 0.85;
}

.logo-icon-box {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

.logo-icon {
  font-size: 16px;
}

.logo-text {
  white-space: nowrap;
}

.logo-tag {
  font-size: 10px;
  font-weight: 700;
  background: var(--color-primary-light);
  color: var(--color-primary);
  border: 1px solid var(--color-primary-border);
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.dataset-selector {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding-left: 14px;
  border-left: 1px solid var(--border-light);
}

.ds-tag {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
  font-weight: 600;
}

.label {
  color: var(--text-muted);
  font-size: 12px;
}

/* Command Palette Trigger */
.cmd-trigger-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 6px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.cmd-trigger-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.cmd-kbd {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  background: #ffffff;
  border-radius: 3px;
  border: 1px solid var(--border-light);
  color: var(--text-muted);
}

.landing-link {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  transition: all 0.2s ease;
}

.landing-link:hover {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.link-arrow {
  font-size: 11px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  letter-spacing: normal;
  background: var(--bg-subtle);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-light);
}

.dot-wrapper {
  position: relative;
  width: 8px;
  height: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-warning);
  position: relative;
  z-index: 2;
}

.dot.ready {
  background: var(--color-success);
}

.dot.offline {
  background: var(--color-danger);
}

.dot-ping {
  position: absolute;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: rgba(5, 150, 105, 0.35);
  animation: pulsePing 2s cubic-bezier(0, 0, 0.2, 1) infinite;
  z-index: 1;
}

@keyframes pulsePing {
  0% {
    transform: scale(0.6);
    opacity: 1;
  }
  100% {
    transform: scale(1.8);
    opacity: 0;
  }
}

@media (max-width: 980px) {
  .dataset-selector,
  .logo-tag,
  .landing-link {
    display: none;
  }
}

@media (max-width: 640px) {
  .cmd-trigger-text {
    display: none;
  }
}
</style>
