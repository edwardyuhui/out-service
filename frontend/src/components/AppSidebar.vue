<template>
  <aside class="app-sidebar" :class="{ collapsed: isCollapsed }">
    <div class="toggle-btn" @click="isCollapsed = !isCollapsed">
      <el-icon><Fold v-if="!isCollapsed" /><Expand v-else /></el-icon>
    </div>

    <el-menu
      :default-active="activePath"
      class="sidebar-menu"
      :collapse="isCollapsed"
      router
    >
      <el-menu-item index="/dashboard">
        <el-icon><Odometer /></el-icon>
        <template #title>工作台总览</template>
      </el-menu-item>

      <el-menu-item-group title="数据准备">
        <el-menu-item index="/simulation">
          <el-icon><Cpu /></el-icon>
          <template #title>生成仿真数据</template>
        </el-menu-item>
        <el-menu-item index="/datasets">
          <el-icon><FolderOpened /></el-icon>
          <template #title>数据资产管理</template>
        </el-menu-item>
      </el-menu-item-group>

      <el-menu-item-group title="分析与建模">
        <el-sub-menu index="/preprocessing">
          <template #title>
            <el-icon><Operation /></el-icon>
            <span>预处理与优选</span>
          </template>
          <el-menu-item index="/preprocessing/cleaning">时间规整与清洗</el-menu-item>
          <el-menu-item index="/preprocessing/segmentation">D-最优动态区间优选</el-menu-item>
          <el-menu-item index="/preprocessing/delay">多变量时滞对齐</el-menu-item>
          <el-menu-item index="/preprocessing/collinearity">VIF 共线性与筛选</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="/modeling">
          <template #title>
            <el-icon><TrendCharts /></el-icon>
            <span>辨识与寻优</span>
          </template>
          <el-menu-item index="/modeling/arx">ARX 系统辨识</el-menu-item>
          <el-menu-item index="/modeling/optimization">Optuna 闭环寻优</el-menu-item>
        </el-sub-menu>
      </el-menu-item-group>

      <el-menu-item-group title="协作与交付">
        <el-menu-item index="/copilot">
          <el-icon><ChatDotSquare /></el-icon>
          <template #title>AI 智能工模 Copilot</template>
        </el-menu-item>
        <el-menu-item index="/benchmark">
          <el-icon><Odometer /></el-icon>
          <template #title>消融对账评测</template>
        </el-menu-item>
        <el-menu-item index="/deliverables">
          <el-icon><Document /></el-icon>
          <template #title>工程报告与交付</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>系统环境设置</template>
        </el-menu-item>
      </el-menu-item-group>
    </el-menu>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { useRoute } from "vue-router";
import {
  Odometer,
  Cpu,
  FolderOpened,
  Operation,
  TrendCharts,
  ChatDotSquare,
  Document,
  Setting,
  Fold,
  Expand,
} from "@element-plus/icons-vue";

const route = useRoute();
const isCollapsed = ref(false);

const activePath = computed(() => route.path);
</script>

<style scoped>
.app-sidebar {
  width: 232px;
  background: var(--bg-sidebar);
  border-right: 1px solid #1e293b;
  transition: width 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  z-index: 5;
}

.app-sidebar.collapsed {
  width: 64px;
}

.toggle-btn {
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 16px;
  color: #64748b;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  transition: color 0.18s ease;
}

.toggle-btn:hover {
  color: #f8fafc;
}

.app-sidebar.collapsed .toggle-btn {
  justify-content: center;
  padding: 0;
}

.sidebar-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  min-height: 0;
  padding: 8px 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-color: rgba(148, 163, 184, 0.3) transparent;
  scrollbar-width: thin;
}

.sidebar-menu::-webkit-scrollbar {
  width: 5px;
}

.sidebar-menu::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.25);
  border-radius: 999px;
}

:deep(.el-menu) {
  background: transparent;
}

:deep(.el-menu-item), :deep(.el-sub-menu__title) {
  height: 42px;
  line-height: 42px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 500;
  margin: 2px 8px;
  border-radius: 6px;
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

:deep(.el-menu-item .el-icon), :deep(.el-sub-menu__title .el-icon) {
  font-size: 16px;
  color: #64748b;
  transition: color 0.18s ease;
}

:deep(.el-menu-item:hover), :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #f8fafc;
}

:deep(.el-menu-item:hover .el-icon), :deep(.el-sub-menu__title:hover .el-icon) {
  color: #93c5fd;
}

:deep(.el-menu-item.is-active) {
  color: #ffffff !important;
  background: linear-gradient(90deg, rgba(37, 99, 235, 0.25) 0%, rgba(37, 99, 235, 0.1) 100%) !important;
  font-weight: 700;
  border-left: 3px solid #3b82f6;
  border-radius: 0 6px 6px 0;
}

:deep(.el-menu-item.is-active .el-icon) {
  color: #60a5fa !important;
}

:deep(.el-menu-item-group__title) {
  padding: 14px 18px 4px !important;
  color: #475569;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: normal;
  text-transform: none;
  font-family: var(--font-sans);
}

.collapsed :deep(.el-menu-item-group__title) {
  display: none;
}
</style>
