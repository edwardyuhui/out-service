<template>
  <teleport to="body">
    <div
      v-if="isOpen"
      class="cmd-palette-backdrop"
      @click.self="close"
      @keydown.esc="close"
    >
      <div class="cmd-palette-modal" role="dialog" aria-modal="true" aria-label="快捷指令面板">
        <!-- Search Input Bar -->
        <div class="cmd-search-wrapper">
          <el-icon class="cmd-search-icon"><Search /></el-icon>
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            placeholder="搜索功能模块、算法步骤或执行指令... (例如: ARX, 寻优, 时滞)"
            class="cmd-input"
            @keydown.down.prevent="moveSelection(1)"
            @keydown.up.prevent="moveSelection(-1)"
            @keydown.enter.prevent="executeSelected"
          />
          <span class="cmd-esc-badge" @click="close">ESC</span>
        </div>

        <!-- Suggestions List -->
        <div class="cmd-list" ref="listRef">
          <template v-if="groupedItems.length > 0">
            <div v-for="group in groupedItems" :key="group.category" class="cmd-group">
              <div class="cmd-group-title">{{ group.category }}</div>
              <div
                v-for="item in group.items"
                :key="item.id"
                class="cmd-item"
                :class="{ active: selectedId === item.id }"
                @click="executeItem(item)"
                @mouseenter="selectedId = item.id"
              >
                <div class="cmd-item-left">
                  <div class="cmd-icon-box">
                    <component :is="item.icon" class="cmd-item-icon" />
                  </div>
                  <div class="cmd-item-text">
                    <span class="cmd-item-title">{{ item.title }}</span>
                    <span v-if="item.sub" class="cmd-item-sub">{{ item.sub }}</span>
                  </div>
                </div>
                <div class="cmd-item-right">
                  <span v-if="item.shortcut" class="cmd-item-shortcut">{{ item.shortcut }}</span>
                  <el-icon class="cmd-enter-icon"><Right /></el-icon>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="cmd-empty">
            <el-icon><Warning /></el-icon>
            <span>未找到匹配的指令或页面</span>
          </div>
        </div>

        <!-- Footer Help -->
        <div class="cmd-footer">
          <div class="footer-keys">
            <span><kbd>↑</kbd><kbd>↓</kbd> 移动选择</span>
            <span><kbd>Enter</kbd> 确认跳转</span>
            <span><kbd>Esc</kbd> 关闭面板</span>
          </div>
          <div class="footer-brand">IndusOpt Command Hub</div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  Search,
  Right,
  Warning,
  Odometer,
  Cpu,
  FolderOpened,
  Operation,
  TrendCharts,
  ChatDotSquare,
  Document,
  Setting,
  Lightning,
  Histogram,
  Compass,
} from "@element-plus/icons-vue";

interface CommandItem {
  id: string;
  category: "常用导航" | "预处理与优选" | "建模与寻优" | "分析与交付" | "系统环境设置";
  title: string;
  sub?: string;
  shortcut?: string;
  path?: string;
  action?: () => void;
  icon: any;
}

const router = useRouter();
const isOpen = ref(false);
const query = ref("");
const selectedId = ref("");
const inputRef = ref<HTMLInputElement | null>(null);
const listRef = ref<HTMLElement | null>(null);

const allCommands: CommandItem[] = [
  {
    id: "dashboard",
    category: "常用导航",
    title: "工作台总览 (Dashboard)",
    sub: "查看当前任务状态与模型排行榜",
    shortcut: "G D",
    path: "/dashboard",
    icon: Odometer,
  },
  {
    id: "copilot",
    category: "常用导航",
    title: "AI 智能工模 Copilot",
    sub: "自然语言驱动闭环建模与工作流编排",
    shortcut: "G C",
    path: "/copilot",
    icon: ChatDotSquare,
  },
  {
    id: "assets",
    category: "常用导航",
    title: "功能中心",
    sub: "集中访问数据、预处理、建模与分析交付能力",
    shortcut: "G A",
    path: "/assets",
    icon: FolderOpened,
  },
  {
    id: "datasets",
    category: "常用导航",
    title: "数据集与版本 (Datasets)",
    sub: "管理已上传工业 CSV 与版本血缘",
    path: "/datasets",
    icon: FolderOpened,
  },
  {
    id: "simulation",
    category: "常用导航",
    title: "仿真数据生成器 (Simulation)",
    sub: "生成 S1/S3/S6 带真值标准工况数据",
    shortcut: "G S",
    path: "/simulation",
    icon: Cpu,
  },
  {
    id: "cleaning",
    category: "预处理与优选",
    title: "时间规整与清洗 (Cleaning)",
    sub: "等间隔重采样、缺失填补与 3σ 异常过滤",
    path: "/preprocessing/cleaning",
    icon: Operation,
  },
  {
    id: "segmentation",
    category: "预处理与优选",
    title: "质量约束 D-最优优选 (Segmentation)",
    sub: "动态信噪比门控与信息矩阵行列式极大化",
    path: "/preprocessing/segmentation",
    icon: Histogram,
  },
  {
    id: "delay",
    category: "预处理与优选",
    title: "多变量时滞对齐 (Delay Compensation)",
    sub: "预白化互相关估计与通道纯时滞移位",
    path: "/preprocessing/delay",
    icon: Compass,
  },
  {
    id: "collinearity",
    category: "预处理与优选",
    title: "VIF 共线性与筛选 (Collinearity)",
    sub: "方差膨胀因子诊断与强相关输入特征剔除",
    path: "/preprocessing/collinearity",
    icon: Operation,
  },
  {
    id: "arx",
    category: "建模与寻优",
    title: "ARX 系统辨识 (ARX Modeling)",
    sub: "QR 最小二乘辨识与滚动自由仿真 FIT 评测",
    path: "/modeling/arx",
    icon: TrendCharts,
  },
  {
    id: "optimization",
    category: "建模与寻优",
    title: "Optuna 闭环寻优 (Hyperparameter Search)",
    sub: "贝叶斯 TPE 分级搜索与历史策略热启动",
    path: "/modeling/optimization",
    icon: Lightning,
  },
  {
    id: "benchmark",
    category: "分析与交付",
    title: "消融对账评测 (Benchmark)",
    sub: "执行 10 组随机种子消融实验与敏感性扫描",
    path: "/benchmark",
    icon: Odometer,
  },
  {
    id: "deliverables",
    category: "分析与交付",
    title: "工程报告与数据交付 (Deliverables)",
    sub: "导出全数值可溯源图文报告与优选特征集",
    path: "/deliverables",
    icon: Document,
  },
  {
    id: "settings",
    category: "系统环境设置",
    title: "系统环境设置 (Settings)",
    sub: "大模型 Provider 运行时配置与网络测试",
    path: "/settings",
    icon: Setting,
  },
];

const filteredCommands = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return allCommands;
  return allCommands.filter(
    (c) =>
      c.title.toLowerCase().includes(q) ||
      (c.sub && c.sub.toLowerCase().includes(q)) ||
      c.category.toLowerCase().includes(q) ||
      c.id.toLowerCase().includes(q)
  );
});

const groupedItems = computed(() => {
  const categories: CommandItem["category"][] = [
    "常用导航",
    "预处理与优选",
    "建模与寻优",
    "分析与交付",
    "系统环境设置",
  ];
  return categories
    .map((cat) => ({
      category: cat,
      items: filteredCommands.value.filter((item) => item.category === cat),
    }))
    .filter((g) => g.items.length > 0);
});

const flatFilteredItems = computed(() => {
  return groupedItems.value.flatMap((g) => g.items);
});

watch(
  () => flatFilteredItems.value,
  (items) => {
    if (items.length > 0 && (!selectedId.value || !items.some((i) => i.id === selectedId.value))) {
      selectedId.value = items[0]?.id || "";
    }
  },
  { immediate: true }
);

function open() {
  isOpen.value = true;
  query.value = "";
  if (flatFilteredItems.value.length > 0) {
    selectedId.value = flatFilteredItems.value[0]?.id || "";
  }
  void nextTick(() => {
    inputRef.value?.focus();
  });
}

function close() {
  isOpen.value = false;
  query.value = "";
}

function moveSelection(direction: 1 | -1) {
  const items = flatFilteredItems.value;
  if (items.length === 0) return;
  const currentIndex = items.findIndex((i) => i.id === selectedId.value);
  let nextIndex = currentIndex + direction;
  if (nextIndex < 0) nextIndex = items.length - 1;
  if (nextIndex >= items.length) nextIndex = 0;
  selectedId.value = items[nextIndex]?.id || "";
}

function executeSelected() {
  const current = flatFilteredItems.value.find((i) => i.id === selectedId.value);
  if (current) {
    executeItem(current);
  }
}

function executeItem(item: CommandItem) {
  close();
  if (item.action) {
    item.action();
  } else if (item.path) {
    void router.push(item.path);
  }
}

function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (isOpen.value) {
      close();
    } else {
      open();
    }
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleGlobalKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleGlobalKeydown);
});

defineExpose({
  open,
  close,
});
</script>

<style scoped>
.cmd-palette-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: clamp(60px, 14vh, 120px);
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.cmd-palette-modal {
  width: min(640px, 92vw);
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.18), 0 4px 12px rgba(15, 23, 42, 0.06);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: slideDown 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDown {
  from { transform: translateY(-12px) scale(0.98); opacity: 0; }
  to { transform: translateY(0) scale(1); opacity: 1; }
}

.cmd-search-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-light);
  background: #ffffff;
}

.cmd-search-icon {
  width: 18px;
  height: 18px;
  font-size: 18px;
  color: var(--color-primary);
  flex-shrink: 0;
}

.cmd-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 500;
  outline: none;
  line-height: 1.4;
}

.cmd-input::placeholder {
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 400;
}

.cmd-esc-badge {
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  background: var(--bg-subtle);
  color: var(--text-muted);
  border-radius: 4px;
  border: 1px solid var(--border-light);
  cursor: pointer;
  transition: all 0.15s ease;
}

.cmd-esc-badge:hover {
  background: #e2e8f0;
  color: var(--text-primary);
}

.cmd-list {
  max-height: 380px;
  overflow-y: auto;
  padding: 8px;
}

.cmd-group {
  margin-bottom: 6px;
}

.cmd-group-title {
  padding: 6px 12px 4px;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: normal;
  text-transform: none;
}

.cmd-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
  color: var(--text-primary);
  border: 1px solid transparent;
}

.cmd-item:hover, .cmd-item.active {
  background: var(--surface-3);
  border-color: var(--border-default);
}

.cmd-item-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.cmd-icon-box {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-xs);
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.cmd-item.active .cmd-icon-box {
  background: var(--surface-3);
  border-color: var(--border-strong);
}

.cmd-item-icon {
  width: 15px;
  height: 15px;
  max-width: 15px;
  max-height: 15px;
  color: var(--text-tertiary);
  transition: color var(--transition-fast);
}

.cmd-item.active .cmd-item-icon {
  color: var(--accent);
}

.cmd-item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cmd-item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cmd-item.active .cmd-item-title {
  color: var(--text-primary);
}

.cmd-item-sub {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cmd-item.active .cmd-item-sub {
  color: var(--text-secondary);
}

.cmd-item-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.cmd-item-shortcut {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  background: var(--surface-1);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-subtle);
}

.cmd-enter-icon {
  width: 14px;
  height: 14px;
  font-size: 12px;
  color: var(--accent);
  opacity: 0;
  transform: translateX(-4px);
  transition: all var(--transition-fast);
}

.cmd-item.active .cmd-enter-icon {
  opacity: 1;
  transform: translateX(0);
}

.cmd-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 36px 16px;
  color: var(--text-muted);
  font-size: 13px;
}

.cmd-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  background: var(--surface-1);
  border-top: 1px solid var(--border-subtle);
  font-size: 11px;
  color: var(--text-muted);
}

.footer-keys {
  display: flex;
  align-items: center;
  gap: 14px;
}

.footer-keys kbd {
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xs);
  color: var(--text-secondary);
  margin-right: 3px;
}

.footer-brand {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: normal;
  font-family: var(--font-sans);
  color: var(--text-muted);
}

</style>
