<template>
  <div class="home-view">
    <div class="home-primary">
      <!-- Headline -->
      <div class="home-headline">
        <h1 class="home-headline__main">今天想完成什么？</h1>
      </div>

      <!-- Agent Composer (Visual Core) -->
      <AgentComposer
        class="home-composer"
        @submit="handleComposerSubmit"
      />

      <!-- Quick Action Suggestions -->
      <div class="home-suggestions">
        <button
          v-for="action in quickActions"
          :key="action.label"
          type="button"
          class="suggestion-chip"
          @click="handleQuickAction(action)"
        >
          <!-- ScanSearch -->
          <svg v-if="action.icon === 'scan'" class="chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>
            <circle cx="12" cy="12" r="3"/><path d="m16 16 2 2"/>
          </svg>
          <!-- ChartSpline -->
          <svg v-else-if="action.icon === 'chart'" class="chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
          </svg>
          <!-- Gauge -->
          <svg v-else-if="action.icon === 'gauge'" class="chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>
          </svg>
          <!-- FileText -->
          <svg v-else-if="action.icon === 'file'" class="chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>
            <path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>
          </svg>
          <span class="chip-label">{{ action.label }}</span>
        </button>
      </div>

      <!-- Lower Section: Recent Tasks OR Suggested Workflows -->
      <div class="home-bottom-section">
        <!-- 1. Recent Tasks Mode -->
        <div v-if="recentExecutions.length > 0" class="home-recent">
          <div class="home-section-header">
            <span class="home-section-label home-section-label--recent">最近任务</span>
            <router-link to="/runs" class="home-section-more">全部记录 →</router-link>
          </div>
          <div class="recent-list">
            <router-link
              v-for="exec in recentExecutions"
              :key="exec.execution_id"
              :to="`/workspace/${exec.execution_id}`"
              class="recent-item"
            >
              <div class="recent-item__status">
                <span class="status-dot" :class="workflowStatusClass(exec.workflow_status)" />
              </div>
              <div class="recent-item__body">
                <div class="recent-item__goal">{{ exec.plan?.goal || 'Agent Task' }}</div>
                <div class="recent-item__meta">
                  <span
                    v-if="exec.dataset_id"
                    class="recent-item__dataset"
                    :title="datasetStore.resolveDatasetName(exec.dataset_id)"
                  >
                    数据集：{{ datasetStore.resolveDatasetName(exec.dataset_id) }}
                  </span>
                  <span class="recent-item__time">{{ formatRelativeTime(exec.created_at) }}</span>
                </div>
              </div>
              <div class="recent-item__badge">
                <span class="status-badge" :class="workflowStatusClass(exec.workflow_status)">
                  {{ workflowStatusLabel(exec.workflow_status) }}
                </span>
              </div>
            </router-link>
          </div>
        </div>

        <!-- 2. Suggested Workflows Mode -->
        <div v-else class="home-workflows">
          <div class="home-section-header">
            <span class="home-section-label">
              <span class="home-section-label__technical">SUGGESTED WORKFLOWS</span>
              <span class="home-section-label__localized"> · 推荐场景</span>
            </span>
          </div>
          <div class="workflow-grid">
            <div
              v-for="wf in suggestedWorkflows"
              :key="wf.title"
              class="workflow-card"
              @click="handleQuickAction({ label: wf.title, prompt: wf.prompt })"
            >
              <div class="workflow-card__top">
                <span class="workflow-badge">{{ wf.tag }}</span>
                <svg class="workflow-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>
                </svg>
              </div>
              <div class="workflow-card__title">{{ wf.title }}</div>
              <div class="workflow-card__desc">{{ wf.desc }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import AgentComposer from '../components/composer/AgentComposer.vue';
import { useDatasetStore } from '../stores/datasetStore';
import type { CopilotExecutionSnapshot } from '../types/api';

const router = useRouter();
const datasetStore = useDatasetStore();

const recentExecutions = ref<CopilotExecutionSnapshot[]>([]);

const quickActions = [
  { label: '诊断数据质量', icon: 'scan', prompt: '对当前数据集进行完整的数据质量诊断，包括缺失值、异常检测和采样一致性分析。' },
  { label: '建立动态模型', icon: 'chart', prompt: '基于当前数据集进行时滞估计、特征筛选和 ARX 系统辨识，建立动态模型。' },
  { label: '运行参数优化', icon: 'gauge', prompt: '在已有 ARX 模型基础上，使用 Optuna 进行闭环参数寻优，最大化 Free-run FIT。' },
  { label: '生成分析报告', icon: 'file', prompt: '基于当前已完成的分析结果，生成完整的工程分析报告，包含模型指标和结论。' },
];

const suggestedWorkflows = [
  {
    tag: 'SYSTEM ID',
    title: 'S3 动态时序辨识',
    desc: '自动估计输入输出纯延迟、执行 VIF 共线性降维并拟合最佳 ARX 结构。',
    prompt: '对 S3 数据集执行时滞估计与 ARX 动态建模，自动完成特征筛选并输出验证指标。',
  },
  {
    tag: 'DIAGNOSTICS',
    title: '多变量数据质量诊断',
    desc: '自动对齐时间戳、填补传感器断续缺失并清洗孤立野点。',
    prompt: '进行多变量工业数据质量诊断，自动生成时间规整与稳态区间分割方案。',
  },
  {
    tag: 'OPTIMIZATION',
    title: '闭环建模参数寻优',
    desc: '以验证集辨识指标反馈数据优选与模型参数，保留最优可复核结果。',
    prompt: '配置 Optuna 闭环寻优任务，迭代数据优选和建模参数，使用验证集选择模型，最后评价冻结模型并生成报告。',
  },
];

async function handleComposerSubmit(payload: { message: string; datasetId?: string | null; versionId?: string | null }) {
  await router.push({
    path: '/workspace',
    query: {
      prompt: payload.message,
      dataset_id: payload.datasetId || undefined,
      version_id: payload.versionId || undefined,
    },
  });
}

function handleQuickAction(action: { label: string; prompt: string }) {
  router.push({
    path: '/workspace',
    query: { prompt: action.prompt },
  });
}

function workflowStatusClass(status: string): string {
  const map: Record<string, string> = {
    RUNNING: 'running',
    WAITING_CONFIRMATION: 'waiting',
    WAITING_ASYNC_TASK: 'running',
    SUCCEEDED: 'completed',
    FAILED: 'failed',
    CANCELLED: 'cancelled',
    PLANNED: 'pending',
  };
  return map[status] ?? 'pending';
}

function workflowStatusLabel(status: string): string {
  const map: Record<string, string> = {
    RUNNING: '执行中',
    WAITING_CONFIRMATION: '待确认',
    WAITING_ASYNC_TASK: '处理中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    PLANNED: '已规划',
  };
  return map[status] ?? status;
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

onMounted(async () => {
  try {
    const cached = localStorage.getItem('indusopt.recent_executions');
    if (cached) {
      const parsed = JSON.parse(cached);
      recentExecutions.value = Array.isArray(parsed) ? parsed.slice(0, 5) : [];
    }
  } catch {
    ElMessage.warning('最近执行记录读取失败');
  }
  if (recentExecutions.value.some((execution) => execution.dataset_id)) {
    await datasetStore.ensureDatasetNamesLoaded();
  }
});
</script>

<style scoped>
.home-view {
  width: 100%;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: calc(clamp(48px, 6vh, 88px) + var(--space-10));
  padding-bottom: 48px;
  padding-left: var(--page-gutter);
  padding-right: var(--page-gutter);
  box-sizing: border-box;
}

.home-primary {
  width: min(860px, 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* Headline */
.home-headline {
  text-align: center;
  margin-bottom: 24px;
}

.home-headline__main {
  font-size: clamp(28px, 3vw, 34px);
  font-weight: 600;
  color: #171717;
  letter-spacing: normal;
  line-height: 1.2;
}

/* Composer Container */
.home-composer {
  width: 100%;
  margin-bottom: 0;
}

/* Suggestion Row */
.home-suggestions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
  width: 100%;
  margin-top: 16px;
}

.suggestion-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  color: #666666;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.15s ease;
  white-space: nowrap;
}

.suggestion-chip:hover {
  background: #F5F5F7;
  border-color: #D1D1D6;
  color: #171717;
}

.chip-icon {
  width: 14px;
  height: 14px;
  color: #8E8E93;
  transition: color 0.15s ease;
}

.suggestion-chip:hover .chip-icon {
  color: #426340;
}

/* Bottom Section */
.home-bottom-section {
  width: 100%;
  margin-top: 40px;
}

.home-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding: 0 2px;
}

.home-section-label {
  font-size: 11px;
  color: #8E8E93;
  font-weight: 600;
}

.home-section-label--recent {
  font-family: var(--font-sans);
  font-size: var(--font-size-md);
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: normal;
  color: var(--text-primary);
}

.home-section-label__technical {
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.home-section-label__localized {
  font-weight: 500;
  letter-spacing: normal;
}

.home-section-more {
  font-size: 11px;
  color: #666666;
  text-decoration: none;
}

.home-section-more:hover {
  color: #171717;
  text-decoration: underline;
}

/* Recent list */
.recent-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  color: inherit;
  text-decoration: none;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.15s ease;
}

.recent-item:hover {
  background: #F7F9F5;
  border-color: #D1D1D6;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

.recent-item__status {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.recent-item__body {
  flex: 1;
  min-width: 0;
}

.recent-item__goal {
  font-size: 14px;
  font-weight: 500;
  color: #171717;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-item__meta {
  font-size: 12px;
  color: #8E8E93;
  display: flex;
  gap: 12px;
  margin-top: 2px;
  min-width: 0;
}

.recent-item__dataset {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.recent-item__time {
  color: #A1A1A6;
  flex-shrink: 0;
}

.recent-item__badge {
  flex-shrink: 0;
}

/* Suggested Workflow Grid */
.workflow-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 800px) {
  .home-view {
    padding-top: calc(clamp(48px, 6vh, 88px) + var(--space-4));
  }

  .workflow-grid {
    grid-template-columns: 1fr;
  }
}

.workflow-card {
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.15s ease;
  display: flex;
  flex-direction: column;
}

.workflow-card:hover {
  background: #FAFBF8;
  border-color: #B0CEAA;
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.04);
  transform: translateY(-1px);
}

.workflow-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.workflow-badge {
  font-size: 10px;
  font-weight: 600;
  color: #426340;
  background: #EDF4E9;
  padding: 2px 6px;
  border-radius: 4px;
}

.workflow-arrow {
  color: #8E8E93;
  transition: transform 0.15s ease, color 0.15s ease;
}

.workflow-card:hover .workflow-arrow {
  color: #426340;
  transform: translateX(2px);
}

.workflow-card__title {
  font-size: 13px;
  font-weight: 600;
  color: #171717;
  margin-bottom: 4px;
}

.workflow-card__desc {
  font-size: 12px;
  color: #666666;
  line-height: 1.45;
}
</style>
