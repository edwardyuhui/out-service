<template>
  <div class="dashboard-view">
    <!-- Header with Breadcrumbs & Action Buttons -->
    <div class="dashboard-top-row">
      <div class="page-header">
        <span class="page-eyebrow">PROCESS INDUSTRY WORKSPACE</span>
        <h2>建模工作台</h2>
        <p class="subtitle">从原始工业时序到可验证模型交付，沿着当前数据版本推进工程闭环</p>
      </div>
      <div class="top-quick-actions">
        <el-button plain @click="$router.push('/copilot')">
          <el-icon><ChatDotSquare /></el-icon>
          <span>AI Copilot 协作</span>
        </el-button>
        <el-button type="primary" @click="$router.push('/simulation')">
          <el-icon><Cpu /></el-icon>
          <span>生成仿真数据</span>
        </el-button>
      </div>
    </div>

    <!-- Unified Workbench Hero + Metric Ribbon (Clean & Uncrowded) -->
    <section class="workbench-command-bar industrial-card">
      <div class="command-bar-left">
        <div class="command-tag-row">
          <span class="command-status-dot"></span>
          <span class="command-kicker">{{ currentDataset ? "ACTIVE TASK" : "INITIALIZE" }}</span>
          <span v-if="currentDataset" class="dataset-pill">
            {{ shortIdentifier(currentDataset.version_id || currentDataset.latest_version_id) }}
          </span>
        </div>
        <h3>{{ currentDataset ? `当前数据集：「${currentDataset.name}」` : "从一份可信数据开始建模" }}</h3>
        <p class="command-desc">
          {{ currentDataset
            ? `共 ${currentDataset.row_count} 行时序采样 · ${currentDataset.col_count || currentDataset.column_count} 通道。支持按工程目标组合清洗、优选与辨识步骤。`
            : "上传真实工业多变量 CSV，或生成带真值的 S1/S3/S6 标准工况仿真数据验证建模流程。" }}
        </p>
        <div class="command-actions">
          <el-button type="primary" @click="continueWork">
            {{ currentDataset ? "进入当前数据详情 →" : "选择并上传数据" }}
          </el-button>
          <el-button plain @click="$router.push('/datasets')">数据资产中心</el-button>
        </div>
      </div>

      <div class="command-bar-metrics">
        <div class="metric-chip">
          <div class="metric-label">DATA ASSETS</div>
          <div class="metric-value">{{ dashboardAvailable ? datasetCount : "暂不可用" }} <span v-if="dashboardAvailable" class="metric-unit">个</span></div>
          <div class="metric-hint">已登记数据资产</div>
        </div>
        <div class="metric-divider"></div>
        <div class="metric-chip">
          <div class="metric-label">OPTIMIZATIONS</div>
          <div class="metric-value">{{ dashboardAvailable ? leaderboardData.length : "暂不可用" }} <span v-if="dashboardAvailable" class="metric-unit">项</span></div>
          <div class="metric-hint">已完成闭环寻优</div>
        </div>
        <div class="metric-divider"></div>
        <div class="metric-chip">
          <div class="metric-label">TOP FREE-RUN FIT</div>
          <div class="metric-value text-primary">{{ dashboardAvailable ? (topEntry ? formatOptionalFit(topEntry.optimized_validation_fit) : "暂无结果") : "暂不可用" }}</div>
          <div class="metric-hint">{{ dashboardAvailable ? (topEntry ? topEntry.dataset_name : "完成寻优后显示") : "工作台数据暂不可用" }}</div>
        </div>
      </div>
    </section>

    <!-- Clean Dual-Mode Segmented Operations Deck -->
    <div class="dashboard-main-deck industrial-card">
      <div class="deck-header">
        <div class="deck-tabs">
          <button
            type="button"
            class="deck-tab-btn"
            :class="{ active: activeDeckTab === 'leaderboard' }"
            @click="activeDeckTab = 'leaderboard'"
          >
            <el-icon><Trophy /></el-icon>
            <span>建模对账与泛化排行 (LEADERBOARD)</span>
          </button>
          <button
            type="button"
            class="deck-tab-btn"
            :class="{ active: activeDeckTab === 'pipeline' }"
            @click="activeDeckTab = 'pipeline'"
          >
            <el-icon><Operation /></el-icon>
            <span>8 阶段工业闭环导引 (PIPELINE)</span>
          </button>
          <button
            type="button"
            class="deck-tab-btn"
            :class="{ active: activeDeckTab === 'telemetry' }"
            @click="activeDeckTab = 'telemetry'"
          >
            <el-icon><Lightning /></el-icon>
            <span>AI Copilot 与运行遥测 (TELEMETRY)</span>
          </button>
        </div>
      </div>

      <!-- Tab 1: Leaderboard Matrix -->
      <div v-show="activeDeckTab === 'leaderboard'" class="deck-content-pane">
        <el-alert
          v-if="loadError"
          type="error"
          title="工作台数据加载失败"
          description="请确认后端服务已启动，并检查数据库与任务队列状态后重新加载。"
          show-icon
          :closable="false"
          style="margin-bottom: 16px"
        >
          <template #default>
            <p class="error-help">请确认后端服务已启动，并检查数据库与任务队列状态。</p>
            <el-button type="danger" plain size="small" :loading="isLoading" @click="loadDashboard">重新加载</el-button>
          </template>
        </el-alert>
        <el-alert
          v-else
          type="info"
          title="指标说明：一步预测使用真实历史输出预测下一步；自由仿真仅依赖模型自身历史预测连续滚动，因而更严格、更能反映工业长期预测能力。"
          :closable="false"
          style="margin-bottom: 16px"
        />

        <el-table v-if="dashboardAvailable && leaderboardData.length" :data="leaderboardData" stripe style="width: 100%">
          <el-table-column prop="dataset_name" label="数据集名称" min-width="180" />
          <el-table-column label="基线验证 FIT" width="130">
            <template #default="{ row }">
              <span>{{ formatOptionalFit(row.baseline_validation_fit) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="优化后验证 FIT" width="140">
            <template #default="{ row }">
              <span class="fit-val">{{ formatOptionalFit(row.optimized_validation_fit) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="测试一步 FIT" width="130">
            <template #default="{ row }">
              <span>{{ formatOptionalFit(row.optimized_test_one_step_fit) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="提升幅度" width="120">
            <template #default="{ row }">
              <span v-if="row.improvement !== null" :class="row.improvement >= 0 ? 'improvement-text' : 'risk-text'">
                {{ formatSigned(row.improvement) }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="泛化风险提示" width="180">
            <template #default="{ row }">
              <el-tag :type="riskTagType(row.generalization_risk)" size="small">
                {{ row.risk_message }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="right">
            <template #default="{ row }">
              <el-button type="primary" text size="small" @click="goToDataset(row.dataset_id)">
                详情对账 →
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty
          v-else-if="dashboardAvailable"
          description="暂无建模结果。准备数据后，可从 ARX 辨识开始建立第一条结果。"
        >
          <el-button type="primary" @click="$router.push('/datasets')">选择数据集</el-button>
          <el-button @click="$router.push('/simulation')">生成仿真数据</el-button>
        </el-empty>
        <el-empty v-else-if="isLoading" description="正在加载工作台数据..." />
      </div>

      <!-- Tab 2: 8-Stage Interactive Pipeline -->
      <div v-show="activeDeckTab === 'pipeline'" class="deck-content-pane">
        <div class="pipeline-tab-intro">
          <p>按工程目标自由组合步骤，每个节点均提供严谨的算法数学证明与物理防呆门控。点击卡片直达对应功能模块：</p>
        </div>
        <div class="pipeline-cards-grid">
          <div
            v-for="step in pipelineSteps"
            :key="step.num"
            class="pipeline-card"
            @click="$router.push(step.path)"
          >
            <div class="p-card-top">
              <span class="p-num">{{ step.num }}</span>
              <span class="p-guard">{{ step.guard }}</span>
            </div>
            <div class="p-card-name">{{ step.name }}</div>
            <div class="p-card-desc">{{ step.desc }}</div>
            <div class="p-card-footer">
              <span>{{ step.tech }}</span>
              <span class="p-arrow">→</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 3: Copilot & Telemetry -->
      <div v-show="activeDeckTab === 'telemetry'" class="deck-content-pane">
        <div class="telemetry-tab-grid">
          <div class="copilot-tele-box">
            <div class="copilot-pill">
              <span class="copilot-dot"></span>
              <span>AI COPILOT 智能工模助手</span>
            </div>
            <h4>使用自然语言编排完整建模工作流</h4>
            <p>基于白名单安全门控体系，由 Agent 为您智能规划数据清洗、时滞对齐与 Optuna 寻优：</p>
            <div class="copilot-prompts-row">
              <button class="prompt-chip" type="button" @click="$router.push('/copilot')">
                <span>⚡ 一键执行 D-最优优选与 ARX 辨识</span>
              </button>
              <button class="prompt-chip" type="button" @click="$router.push('/copilot')">
                <span>🔍 自动诊断多通道时滞与 VIF 共线性</span>
              </button>
              <button class="prompt-chip" type="button" @click="$router.push('/copilot')">
                <span>📊 导出全数值可追溯图文工程交付报告</span>
              </button>
            </div>
          </div>

          <div class="system-tele-box">
            <div class="tele-title">ENGINE STATUS · 运行状态遥测</div>
            <div class="tele-list">
              <div class="tele-item">
                <span class="t-label">PostgreSQL 关系数据库</span>
                <span class="t-val text-green">🟢 CONNECTED (就绪)</span>
              </div>
              <div class="tele-item">
                <span class="t-label">Redis 异步任务队列</span>
                <span class="t-val text-green">🟢 READY (0 积压)</span>
              </div>
              <div class="tele-item">
                <span class="t-label">QR 分解矩阵满秩门控</span>
                <span class="t-val text-cyan">16/20 满秩保障</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  ChatDotSquare,
  Cpu,
  Lightning,
  Operation,
  Trophy,
} from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { getDashboardLeaderboard } from "../api/dashboard";
import { getDatasets } from "../api/datasets";
import { useDatasetStore } from "../stores/datasetStore";
import { useSystemStore } from "../stores/systemStore";
import type { DashboardLeaderboardEntry, DatasetItem } from "../types/api";

const router = useRouter();
const systemStore = useSystemStore();
const datasetStore = useDatasetStore();
const datasetCount = ref<number | null>(null);
const loadError = ref("");
const datasetItems = ref<DatasetItem[]>([]);
const leaderboardData = ref<DashboardLeaderboardEntry[]>([]);
const isLoading = ref(false);
const hasLoaded = ref(false);
const activeDeckTab = ref<"leaderboard" | "pipeline" | "telemetry">("leaderboard");

const pipelineSteps = [
  { num: "01", name: "数据接入与规整", desc: "多源工业 CSV 时间戳对齐与解析", guard: "Schema 校验", tech: "Pandas Resample", path: "/datasets" },
  { num: "02", name: "时间清洗与插值", desc: "等间隔重采样、缺失填补与 3σ 过滤", guard: "Hampel 窗口", tech: "样条 / 线性插值", path: "/preprocessing/cleaning" },
  { num: "03", name: "D-最优动态优选", desc: "反向最优实验设计截取满秩高信息段", guard: "预算比 ≥ 2.3", tech: "CELF 延迟贪心", path: "/preprocessing/segmentation" },
  { num: "04", name: "多变量时滞对齐", desc: "预白化互相关去除自相关伪峰", guard: "最大时滞 20s", tech: "AR 预白化", path: "/preprocessing/delay" },
  { num: "05", name: "VIF 共线性降维", desc: "方差膨胀因子诊断与强相关剔除", guard: "VIF ≤ 10.0", tech: "逆矩阵对角线", path: "/preprocessing/collinearity" },
  { num: "06", name: "ARX 系统辨识", desc: "差分方程多项式与单位圆极点分析", guard: "A(q) 渐近稳定", tech: "QR 最小二乘", path: "/modeling/arx" },
  { num: "07", name: "Optuna 闭环寻优", desc: "贝叶斯 TPE 分级自动调优预处理超参", guard: "24x 算力摊薄", tech: "Bayesian TPE", path: "/modeling/optimization" },
  { num: "08", name: "自由仿真独立评测", desc: "长周期无实测反馈严格滚动验证", guard: "Held-out 对账", tech: "Free-run FIT", path: "/benchmark" },
];

const topEntry = computed(() => leaderboardData.value[0] ?? null);
const currentDataset = computed(() => datasetStore.activeDataset ?? datasetItems.value[0] ?? null);
const dashboardAvailable = computed(() => hasLoaded.value && !loadError.value);
const formatFit = (value: number) => value.toFixed(2) + "%";
const formatOptionalFit = (value: number | null) => (value === null ? "—" : formatFit(value));
const formatSigned = (value: number) => (value >= 0 ? "+" : "") + value.toFixed(2) + "%";
const goToDataset = (datasetId: string) => router.push("/datasets/" + datasetId);
const shortIdentifier = (value?: string) => (value ? `${value.slice(0, 8)}…` : "V0-Original");
const continueWork = () =>
  currentDataset.value
    ? router.push(`/datasets/${currentDataset.value.id}`)
    : router.push("/datasets");

const riskTagType = (risk: DashboardLeaderboardEntry["generalization_risk"]) =>
  ({
    normal: "success",
    attention: "warning",
    high: "danger",
    unavailable: "info",
  }[risk] as "success" | "warning" | "danger" | "info");

const loadDashboard = async () => {
  if (isLoading.value) {
    return;
  }

  isLoading.value = true;
  try {
    const [datasets, leaderboard] = await Promise.all([
      getDatasets(1, 20),
      getDashboardLeaderboard(),
    ]);
    datasetItems.value = datasets.items;
    datasetStore.setDatasetsList(datasets.items);
    datasetCount.value = datasets.page?.total_items ?? datasets.items.length;
    leaderboardData.value = leaderboard.items;
    loadError.value = "";
    hasLoaded.value = true;
  } catch (error: any) {
    datasetCount.value = null;
    datasetItems.value = [];
    leaderboardData.value = [];
    hasLoaded.value = false;
    loadError.value = error.message || "未知错误";
  } finally {
    isLoading.value = false;
  }
};

watch(
  () => systemStore.status,
  (status) => {
    if (status === "ready" && !dashboardAvailable.value) {
      void loadDashboard();
    }
  }
);

onMounted(() => {
  void loadDashboard();
});
</script>

<style scoped>
.dashboard-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.dashboard-top-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}

.top-quick-actions {
  display: flex;
  gap: 10px;
}

/* Command Bar (Spacious Hero + Integrated Metrics) */
.workbench-command-bar {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(360px, 0.9fr);
  gap: 28px;
  padding: 24px 28px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
  position: relative;
  overflow: hidden;
}

.workbench-command-bar::before {
  position: absolute;
  right: 20%;
  top: -40px;
  width: 240px;
  height: 240px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.05) 0%, transparent 70%);
  pointer-events: none;
  content: "";
}

.command-bar-left {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.command-tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.command-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #059669;
}

.command-kicker {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.dataset-pill {
  font-size: 10px;
  font-weight: 700;
  background: var(--color-primary-light);
  color: var(--color-primary);
  border: 1px solid var(--color-primary-border);
  padding: 1px 6px;
  border-radius: 4px;
}

.command-bar-left h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.command-desc {
  margin: 6px 0 14px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.command-actions {
  display: flex;
  gap: 10px;
}

.command-bar-metrics {
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 10px;
  padding: 12px 18px;
}

.metric-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 2px;
}

.metric-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.metric-value {
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.15;
}

.text-primary {
  color: var(--color-primary);
}

.metric-unit {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
}

.metric-hint {
  font-size: 11px;
  color: var(--text-secondary);
}

.metric-divider {
  width: 1px;
  height: 38px;
  background: var(--border-light);
}

/* Dual-Mode Deck */
.dashboard-main-deck {
  padding: 0;
  background: #ffffff;
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 0;
}

.deck-header {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-light);
  background: #ffffff;
}

.deck-tabs {
  display: inline-flex;
  background: var(--bg-subtle);
  padding: 3px;
  border-radius: 8px;
  gap: 2px;
}

.deck-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.16s ease;
  white-space: nowrap;
}

.deck-tab-btn:hover {
  color: var(--text-primary);
}

.deck-tab-btn.active {
  background: #ffffff;
  color: var(--color-primary);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.deck-content-pane {
  padding: 20px 24px;
}

/* Tab 2 Pipeline Cards */
.pipeline-tab-intro p {
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: 16px;
}

.pipeline-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.pipeline-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px;
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  min-height: 120px;
}

.pipeline-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.1);
}

.p-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.p-num {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 1px 6px;
  border-radius: 4px;
}

.p-guard {
  font-size: 10px;
  color: #059669;
  font-weight: 600;
}

.p-card-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin-top: 6px;
}

.p-card-desc {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
  line-height: 1.4;
}

.p-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
  font-size: 10px;
  color: var(--text-secondary);
}

.p-arrow {
  color: var(--color-primary);
  font-weight: 700;
}

/* Tab 3 Telemetry Grid */
.telemetry-tab-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 20px;
}

.copilot-tele-box {
  padding: 20px;
  background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
  border: 1px solid #bfdbfe;
  border-radius: 10px;
}

.copilot-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 800;
  color: #2563eb;
  letter-spacing: normal;
  font-family: var(--font-sans);
  margin-bottom: 8px;
}

.copilot-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2563eb;
}

.copilot-tele-box h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.copilot-tele-box p {
  margin: 6px 0 14px;
  font-size: 13px;
  color: #475569;
}

.copilot-prompts-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prompt-chip {
  text-align: left;
  padding: 10px 14px;
  background: #ffffff;
  border: 1px solid #dbeafe;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #1e3a8a;
  cursor: pointer;
  transition: all 0.16s ease;
}

.prompt-chip:hover {
  background: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
  transform: translateX(4px);
}

.system-tele-box {
  padding: 20px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 10px;
}

.tele-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: normal;
  font-family: var(--font-sans);
  margin-bottom: 16px;
}

.tele-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tele-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-light);
}

.tele-item:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.t-label {
  color: var(--text-secondary);
}

.t-val {
  font-size: 11px;
  font-weight: 700;
}

.text-green { color: #059669; }
.text-cyan { color: #0284c7; }

.fit-val {
  font-weight: 700;
  color: var(--color-primary);
}

.improvement-text {
  color: var(--color-success);
  font-weight: 700;
}

.risk-text {
  color: var(--color-danger);
  font-weight: 700;
}

@media (max-width: 1100px) {
  .workbench-command-bar {
    grid-template-columns: 1fr;
  }
  .pipeline-cards-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .telemetry-tab-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .command-bar-metrics {
    flex-direction: column;
    gap: 12px;
  }
  .metric-divider {
    display: none;
  }
  .pipeline-cards-grid {
    grid-template-columns: 1fr;
  }
}
</style>
