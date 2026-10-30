<template>
  <div class="page-container asset-category-view">
    <nav class="category-breadcrumb" aria-label="面包屑">
      <router-link to="/assets">功能中心</router-link>
      <span class="category-breadcrumb__separator" aria-hidden="true">/</span>
      <span aria-current="page">{{ content.title }}</span>
    </nav>

    <PageHeader
      :title="content.title"
      :description="content.description"
    />

    <div class="module-grid" :data-category="category">
      <router-link
        v-for="item in content.items"
        :key="item.path"
        :to="item.path"
        class="module-card"
      >
        <div class="module-card__icon">
          <component :is="item.icon" />
        </div>
        <div class="module-card__body">
          <h2>{{ item.title }}</h2>
          <p>{{ item.description }}</p>
        </div>
        <svg
          class="module-card__arrow"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m9 18 6-6-6-6" />
        </svg>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  Brush,
  DataAnalysis,
  Document,
  Grid,
  Lightning,
  Odometer,
  Timer,
  TrendCharts,
} from "@element-plus/icons-vue";
import { computed } from "vue";
import PageHeader from "../components/common/PageHeader.vue";

type AssetCategory = "preprocessing" | "modeling" | "delivery";

const props = defineProps<{
  category: AssetCategory;
}>();

const categoryContent = {
  preprocessing: {
    title: "预处理与优选",
    description: "从原始工业时序到可用于系统辨识的高质量输入版本",
    items: [
      {
        title: "时间规整与清洗",
        description: "等间隔重采样、缺失填补与异常数据治理",
        path: "/preprocessing/cleaning",
        icon: Brush,
      },
      {
        title: "质量约束 D-最优优选",
        description: "在质量门控下选择信息量充分的动态响应区段",
        path: "/preprocessing/segmentation",
        icon: DataAnalysis,
      },
      {
        title: "多变量时滞对齐",
        description: "估计输入通道纯时滞并生成对齐后的数据版本",
        path: "/preprocessing/delay",
        icon: Timer,
      },
      {
        title: "VIF 共线性与筛选",
        description: "诊断相关结构、VIF 与变量筛选建议",
        path: "/preprocessing/collinearity",
        icon: Grid,
      },
    ],
  },
  modeling: {
    title: "建模与寻优",
    description: "完成 ARX 系统辨识、模型评价与闭环超参数搜索",
    items: [
      {
        title: "ARX 系统辨识",
        description: "配置模型结构并验证一步预测与自由仿真性能",
        path: "/modeling/arx",
        icon: TrendCharts,
      },
      {
        title: "Optuna 闭环寻优",
        description: "以正式验证指标驱动超参数搜索与最优模型选择",
        path: "/modeling/optimization",
        icon: Lightning,
      },
    ],
  },
  delivery: {
    title: "分析与交付",
    description: "核验算法主张，并交付可追溯的工程报告与数据工件",
    items: [
      {
        title: "消融对账评测",
        description: "运行带真值的对照实验并检查核心算法收益",
        path: "/benchmark",
        icon: Odometer,
      },
      {
        title: "工程报告与数据交付",
        description: "生成可追溯工程报告并导出高质量数据集",
        path: "/deliverables",
        icon: Document,
      },
    ],
  },
} as const;

const content = computed(() => categoryContent[props.category]);
</script>

<style scoped>
.asset-category-view {
  min-height: 100%;
}

.category-breadcrumb {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-family: var(--font-sans);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 400;
  letter-spacing: normal;
}

.category-breadcrumb a {
  color: var(--text-secondary);
  text-decoration: none;
  transition: color var(--transition-fast);
}

.category-breadcrumb a:hover {
  color: var(--text-primary);
}

.category-breadcrumb a:focus-visible {
  outline: 2px solid var(--border-focus, var(--accent));
  outline-offset: 2px;
}

.category-breadcrumb__separator {
  color: var(--text-tertiary);
}

.asset-category-view :deep(.page-header-unified__desc) {
  max-width: 760px;
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 400;
  line-height: 1.6;
  color: var(--text-secondary);
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.module-card {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  box-shadow: var(--shadow-sm);
  transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.module-card:hover {
  background: #F7F9F5;
  border-color: #D6DDD2;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.module-card:focus-visible {
  outline: 2px solid var(--border-focus, #82A978);
  outline-offset: 2px;
}

.module-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  color: var(--accent-dark);
  transition: background-color 180ms ease, color 180ms ease;
}

.module-card:hover .module-card__icon {
  background: #E8F0E5;
  color: #426340;
}

.module-card__icon :deep(svg) {
  width: 20px;
  height: 20px;
}

.module-card__body {
  flex: 1;
  min-width: 0;
}

.module-card__body h2 {
  margin: 0 0 5px;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: normal;
}

.module-card:hover .module-card__body h2 {
  color: #426340;
}

.module-card__body p {
  margin: 0;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.5;
}

.module-card__arrow {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--text-tertiary);
  transition: transform 180ms ease, color 180ms ease;
}

.module-card:hover .module-card__arrow {
  color: #426340;
  transform: translateX(2px);
}

@media (max-width: 760px) {
  .module-grid {
    grid-template-columns: 1fr;
  }
}
</style>
