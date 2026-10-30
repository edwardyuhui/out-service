<template>
  <div class="workspace-view">
    <!-- Left Sidebar: Task Overview, New Task, Shortcuts & Recent Tasks -->
    <aside class="ws-sidebar" :class="{ 'is-collapsed': sidebarCollapsed }">
      <!-- 1. Header: 任务概览 -->
      <div class="ws-sidebar__header">
        <h2 class="ws-sidebar__title">任务概览</h2>
        <button
          type="button"
          class="ws-sidebar__toggle"
          title="收起任务概览"
          aria-label="收起任务概览"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14">
            <path d="m15 18-6-6 6-6"/>
          </svg>
        </button>
      </div>

      <div class="ws-sidebar__scroll-area">
        <!-- 2. Primary Action: 新建任务 -->
        <div class="ws-sidebar__action-box">
          <button
            type="button"
            class="ws-new-task-btn"
            title="新建并开始一个新 Agent 任务"
            @click="startNewTask"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" width="15" height="15">
              <line x1="12" y1="5" x2="12" y2="19"/>
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            <span>新建任务</span>
          </button>
        </div>

        <!-- 3. Current Execution Info & Steps (if execution is active) -->
        <div class="ws-sidebar__section ws-sidebar__section--current" v-if="execution">
          <div class="ws-section-header">
            <span class="ws-section-label">当前任务</span>
            <span class="status-badge status-badge--sm" :class="workflowClass(execution.workflow_status)">
              {{ workflowLabel(execution.workflow_status) }}
            </span>
          </div>
          <div class="ws-sidebar__goal" :title="execution.plan?.goal">
            {{ execution.plan?.goal || '工业时序建模与优化任务' }}
          </div>
          <div class="ws-sidebar__dataset-meta" v-if="execution?.dataset_id">
            <span
              class="ws-sidebar__dataset-name"
              :title="datasetStore.resolveDatasetName(execution.dataset_id)"
            >
              数据集：{{ datasetStore.resolveDatasetName(execution.dataset_id) }}
            </span>
          </div>

          <!-- Step Progress -->
          <div class="ws-sidebar__progress" v-if="execution?.plan?.steps?.length">
            <div
              v-for="step in execution.plan.steps"
              :key="step.step_id"
              class="ws-progress-step"
              :class="agentStepStatus(execution.step_runs.find(r => r.step_id === step.step_id)?.status ?? step.status)"
              @click="handleArtifactSelect(step.step_id)"
            >
              <span class="ws-progress-step__dot" />
              <span class="ws-progress-step__name">{{ localizedStepName(step.tool) }}</span>
            </div>
          </div>
        </div>

        <!-- 4. Shortcut Entry List (快捷入口 - List Style) -->
        <div class="ws-sidebar__section">
          <div class="ws-section-header">
            <span class="ws-section-label">快捷入口</span>
          </div>
          <div class="ws-shortcut-list">
            <!-- 历史任务记录 -->
            <router-link to="/runs" class="ws-shortcut-item">
              <div class="ws-shortcut-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                  <path d="M3 3v5h5"/>
                  <path d="M12 7v5l4 2"/>
                </svg>
              </div>
              <div class="ws-shortcut-text">
                <div class="ws-shortcut-title">历史任务记录</div>
                <div class="ws-shortcut-desc">查看此前执行的 Agent 任务</div>
              </div>
            </router-link>

            <!-- 数据与模型资产 -->
            <router-link to="/assets" class="ws-shortcut-item">
              <div class="ws-shortcut-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <rect width="20" height="5" x="2" y="3" rx="1"/>
                  <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>
                  <path d="M10 12h4"/>
                </svg>
              </div>
              <div class="ws-shortcut-text">
                <div class="ws-shortcut-title">数据与模型资产</div>
                <div class="ws-shortcut-desc">管理任务产生的数据与模型</div>
              </div>
            </router-link>

            <!-- 消融评测基准 -->
            <router-link to="/benchmark" class="ws-shortcut-item">
              <div class="ws-shortcut-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 20V10"/>
                  <path d="M12 20V4"/>
                  <path d="M6 20v-6"/>
                </svg>
              </div>
              <div class="ws-shortcut-text">
                <div class="ws-shortcut-title">消融评测基准</div>
                <div class="ws-shortcut-desc">4 策略对照真实值自评测</div>
              </div>
            </router-link>
          </div>
        </div>

        <!-- 5. Recent Tasks (最近任务 - Top 3~5) -->
        <div class="ws-sidebar__section">
          <div class="ws-section-header">
            <span class="ws-section-label">最近任务</span>
            <router-link to="/runs" class="ws-section-link">全部 →</router-link>
          </div>

          <div class="ws-recent-list" v-if="recentExecutions.length > 0">
            <router-link
              v-for="rec in recentExecutions.slice(0, 5)"
              :key="rec.execution_id"
              :to="`/workspace/${rec.execution_id}`"
              class="ws-recent-item"
              :class="{ 'is-active': rec.execution_id === execution?.execution_id }"
            >
              <div class="ws-recent-item__top">
                <span class="status-dot" :class="workflowClass(rec.workflow_status)" />
                <span class="ws-recent-item__goal">{{ rec.plan?.goal || 'Agent Task' }}</span>
              </div>
              <div class="ws-recent-item__bottom">
                <span class="ws-recent-item__status-text">{{ workflowLabel(rec.workflow_status) }}</span>
                <span class="ws-recent-item__time">{{ formatRelativeTime(rec.created_at) }}</span>
              </div>
            </router-link>
          </div>

          <div class="ws-recent-empty" v-else>
            <span class="ws-recent-empty__title">暂无最近任务</span>
            <span class="ws-recent-empty__desc">创建一个任务开始使用 Agent</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- Center: Conversation & Stream -->
    <main class="ws-main">
      <!-- Top Sub-Header (When sidebar is collapsed or task bar active) -->
      <header class="ws-top-bar" v-if="execution">
        <div class="ws-top-bar__left">
          <button
            v-if="sidebarCollapsed"
            type="button"
            class="ws-top-btn"
            title="展开任务概览"
            aria-label="展开任务概览"
            @click="sidebarCollapsed = false"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
              <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/>
            </svg>
            <span>任务概览</span>
          </button>
          <span class="ws-top-goal">{{ execution.plan?.goal || 'Agent Task' }}</span>
          <span class="status-badge" :class="workflowClass(execution.workflow_status)">
            {{ workflowLabel(execution.workflow_status) }}
          </span>
        </div>
        <div class="ws-top-bar__right">
          <button
            type="button"
            class="ws-top-btn"
            :class="{ 'is-active': showArtifact }"
            :title="showArtifact ? '收起成果展示区' : '展开成果展示区'"
            :aria-label="showArtifact ? '收起成果展示区' : '展开成果展示区'"
            @click="showArtifact = !showArtifact"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
              <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="15" y1="3" x2="15" y2="21"/>
            </svg>
            <span>成果展示区</span>
          </button>
        </div>
      </header>

      <!-- Immediate acknowledgement while the first task is being created and planned -->
      <div
        v-if="isSending && !execution"
        class="ws-thinking"
        data-test="agent-submit-thinking"
        aria-live="polite"
      >
        <div class="agent-working-dot" />
        <div class="ws-thinking__copy">
          <h3 class="ws-thinking__title">Agent 正在思考…</h3>
          <p class="ws-thinking__desc">正在理解任务并生成执行计划</p>
        </div>
      </div>

      <!-- No execution state: show composer in center -->
      <div v-else-if="!execution && !loading" class="ws-empty">
        <div class="ws-empty__icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect width="18" height="10" x="3" y="11" rx="2"/>
            <circle cx="12" cy="5" r="2"/>
            <path d="M12 7v4"/>
          </svg>
        </div>
        <h3 class="ws-empty__title">新建 Agent 任务</h3>
        <p class="ws-empty__desc">描述你的分析目标，Agent 将自动规划执行数据清洗、时滞补偿、特征筛选、ARX 建模与 Optuna 参数寻优</p>
        <AgentComposer class="ws-empty__composer" :submitting="isSending" @submit="handleNewTask" />
      </div>

      <!-- Loading state -->
      <div v-else-if="loading" class="ws-loading">
        <div class="agent-working-dot" />
        <span>正在加载任务…</span>
      </div>

      <!-- Agent Stream -->
      <AgentStream
        v-else-if="execution"
        :execution="execution"
        :is-sending="isSending"
        :is-confirming="isConfirming"
        @confirm="handleConfirm"
        @execute-evaluation="handleExecuteEvaluation"
        @execute-optimization="handleExecuteOptimization"
        @artifact-select="handleArtifactSelect"
      />

      <!-- New task composer at bottom (when execution is completed or for follow-up) -->
      <div v-if="execution && isCompleted" class="ws-followup">
        <div class="ws-followup-inner">
          <AgentComposer
            placeholder="继续对话或发起新分析目标…"
            :rows="2"
            :submitting="isSending"
            @submit="handleNewTask"
          />
        </div>
      </div>
    </main>

    <!-- Right: Artifact Workbench -->
    <ArtifactWorkbench
      v-if="execution"
      :execution="execution"
      :active-step-id="activeArtifactStepId"
      class="ws-artifact"
      :class="{ 'is-hidden': !showArtifact }"
      @toggle="showArtifact = !showArtifact"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { agentStepStatus } from '../utils/agentStepStatus';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import AgentComposer from '../components/composer/AgentComposer.vue';
import AgentStream from '../components/workspace/AgentStream.vue';
import ArtifactWorkbench from '../components/artifact/ArtifactWorkbench.vue';
import { chatWithCopilot, getCopilotExecution, confirmCopilotStep, executeModelEvaluation, executePipelineOptimization } from '../api/copilot';
import { useCopilotExecutionStore } from '../stores/copilotExecution';
import { useDatasetStore } from '../stores/datasetStore';
import type { CopilotExecutionSnapshot, CopilotConfirmRequest } from '../types/api';

const route = useRoute();
const router = useRouter();
const executionStore = useCopilotExecutionStore();
const datasetStore = useDatasetStore();

const execution = ref<CopilotExecutionSnapshot | null>(null);
const recentExecutions = ref<CopilotExecutionSnapshot[]>([]);
const loading = ref(false);
const isSending = ref(false);
const isConfirming = ref(false);
const showArtifact = ref(true);
const sidebarCollapsed = ref(false);
const activeArtifactStepId = ref<string | null>(null);
let loadingExecutionId: string | null = null;

// Polling
let pollTimer: ReturnType<typeof setInterval> | null = null;
let pollFailureCount = 0;
const POLL_FAILURE_WARNING_THRESHOLD = 3;

const isCompleted = computed(() => {
  const s = execution.value?.workflow_status;
  return s === 'SUCCEEDED' || s === 'FAILED' || s === 'CANCELLED';
});

const STEP_LOCALIZED_NAMES: Record<string, string> = {
  profile_dataset: '数据画像',
  detect_anomalies: '异常检测',
  clean_data: '数据清洗',
  detect_dynamic_segments: '动态区间优选',
  estimate_delays: '时滞估计',
  apply_lag_compensation: '时滞补偿',
  analyze_collinearity: '共线性分析',
  select_variables: '变量筛选',
  fit_arx: '系统辨识',
  export_dataset: '数据导出',

  clean: '数据清洗',
  segment: '工况优选',
  delay_analyze: '时滞估计',
  collinearity: '共线性分析',
  feature_apply: '特征筛选',
  feature_selection_apply: '特征筛选',
  arx_fit: 'ARX 辨识',
  evaluate_model: '模型评价',
  optimize_pipeline: '参数寻优',
  generate_report: '报告交付',
};

function localizedStepName(t: string): string {
  return STEP_LOCALIZED_NAMES[t] ?? t;
}

function workflowClass(status: string): string {
  const map: Record<string, string> = {
    RUNNING: 'running', WAITING_CONFIRMATION: 'waiting',
    WAITING_ASYNC_TASK: 'running', SUCCEEDED: 'completed',
    FAILED: 'failed', CANCELLED: 'cancelled', PLANNED: 'pending',
  };
  return map[status] ?? 'pending';
}

function workflowLabel(status: string): string {
  const map: Record<string, string> = {
    RUNNING: '执行中', WAITING_CONFIRMATION: '待确认',
    WAITING_ASYNC_TASK: '处理中', SUCCEEDED: '已完成',
    FAILED: '失败', CANCELLED: '已取消', PLANNED: '已规划',
  };
  return map[status] ?? status;
}

function formatRelativeTime(iso?: string): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function startNewTask() {
  execution.value = null;
  executionStore.clearActiveExecutionId();
  router.push('/workspace');
}

async function loadExecution(executionId: string) {
  if (loadingExecutionId === executionId) return;
  loadingExecutionId = executionId;
  loading.value = true;
  try {
    execution.value = await getCopilotExecution(executionId);
    void datasetStore.ensureDatasetNamesLoaded();
    startPollingIfNeeded();
    cacheRecentExecution(execution.value);
  } catch (err: any) {
    console.error('Failed to load execution', err);
  } finally {
    if (loadingExecutionId === executionId) loadingExecutionId = null;
    loading.value = false;
  }
}

function startPollingIfNeeded() {
  stopPolling();
  const status = execution.value?.workflow_status;
  if (status === 'RUNNING' || status === 'WAITING_ASYNC_TASK' || status === 'WAITING_CONFIRMATION') {
    pollFailureCount = 0;
    pollTimer = setInterval(async () => {
      if (!execution.value) return;
      try {
        const updated = await getCopilotExecution(execution.value.execution_id);
        pollFailureCount = 0;
        execution.value = updated;
        if (updated.workflow_status === 'SUCCEEDED' || updated.workflow_status === 'FAILED' || updated.workflow_status === 'CANCELLED') {
          stopPolling();
          cacheRecentExecution(updated);
        }
      } catch {
        // Poll errors are expected to be transient, so don't interrupt the
        // user on every tick — but if it keeps failing, let them know
        // instead of leaving the UI silently stuck.
        pollFailureCount += 1;
        if (pollFailureCount === POLL_FAILURE_WARNING_THRESHOLD) {
          ElMessage.warning('执行状态刷新持续失败，请检查网络连接');
        }
      }
    }, 2000);
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function handleNewTask(payload: { message: string; datasetId?: string | null; versionId?: string | null }) {
  if (isSending.value) return;
  if (!payload.datasetId || !payload.versionId) {
    ElMessage.warning('请先挂载数据集后再发起 Agent 任务。');
    return;
  }
  isSending.value = true;
  try {
    const res = await chatWithCopilot({
      message: payload.message,
      dataset_id: payload.datasetId || null,
      active_version_id: payload.versionId || null,
    });
    if (res.execution_id) {
      executionStore.setActiveExecutionId(res.execution_id);
      await router.push(`/workspace/${res.execution_id}`);
      if (execution.value?.execution_id !== res.execution_id) {
        await loadExecution(res.execution_id);
      }
    } else {
      ElMessage.warning(
        res.conclusion || '计划已生成！请点击输入框左下角的「📎 挂载数据」选择数据集，Agent 将自动执行全流程任务。'
      );
    }
  } catch (err: any) {
    console.error('Failed to start task', err);
    ElMessage.error(err.message || '任务发起失败，请检查服务状态');
  } finally {
    isSending.value = false;
  }
}

async function handleConfirm(req: CopilotConfirmRequest) {
  if (isConfirming.value) return;
  isConfirming.value = true;
  stopPolling();
  try {
    await confirmCopilotStep(req);
    if (execution.value?.execution_id === req.execution_id) {
      execution.value = await getCopilotExecution(req.execution_id!);
      cacheRecentExecution(execution.value);
      const step = execution.value.step_runs.find(s => s.step_id === req.step_id);
      if (step?.status === 'SUCCEEDED') handleArtifactSelect(step.step_id);
    }
  } catch (err: any) {
    console.error('Confirm failed', err);
    ElMessage.error(err?.message || '确认操作失败，请检查任务状态和服务日志');
  } finally {
    isConfirming.value = false;
    startPollingIfNeeded();
  }
}

async function handleExecuteEvaluation() {
  if (!execution.value) return;
  try {
    await executeModelEvaluation(execution.value.execution_id);
    execution.value = await getCopilotExecution(execution.value.execution_id);
    startPollingIfNeeded();
  } catch (err: any) {
    console.error('Evaluation failed', err);
  }
}

async function handleExecuteOptimization() {
  if (!execution.value) return;
  try {
    await executePipelineOptimization(execution.value.execution_id);
    execution.value = await getCopilotExecution(execution.value.execution_id);
    startPollingIfNeeded();
  } catch (err: any) {
    console.error('Optimization failed', err);
  }
}

function handleArtifactSelect(stepId: string) {
  activeArtifactStepId.value = stepId;
  showArtifact.value = true;
}

function refreshRecentExecutions() {
  try {
    const cached = JSON.parse(localStorage.getItem('indusopt.recent_executions') ?? '[]');
    recentExecutions.value = cached;
  } catch {
    recentExecutions.value = [];
  }
}

function cacheRecentExecution(exec: CopilotExecutionSnapshot) {
  try {
    const cached = JSON.parse(localStorage.getItem('indusopt.recent_executions') ?? '[]');
    const filtered = cached.filter((e: any) => e.execution_id !== exec.execution_id);
    const updated = [exec, ...filtered].slice(0, 10);
    localStorage.setItem('indusopt.recent_executions', JSON.stringify(updated));
    recentExecutions.value = updated;
  } catch {
    ElMessage.warning('最近执行记录缓存失败');
  }
}

// Route handling
onUnmounted(stopPolling);
onMounted(async () => {
  refreshRecentExecutions();
  const execId = route.params.executionId as string | undefined;
  if (execId) {
    await loadExecution(execId);
  } else {
    // Check if there's a prompt from HomeView
    const prompt = route.query.prompt as string | undefined;
    if (prompt) {
      await handleNewTask({
        message: prompt,
        datasetId: (route.query.dataset_id as string) || null,
        versionId: (route.query.version_id as string) || null,
      });
    } else if (executionStore.activeExecutionId) {
      await loadExecution(executionStore.activeExecutionId);
    }
  }
});

watch(() => route.params.executionId, async (newId) => {
  if (newId && newId !== execution.value?.execution_id) {
    await loadExecution(newId as string);
  }
});
</script>

<style scoped>
.workspace-view {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--bg-app);
}

/* Sidebar: 240px width, top-down clean layout */
.ws-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: #FFFFFF;
  border-right: 1px solid #E5E5E8;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.18s ease;
}

.ws-sidebar.is-collapsed {
  width: 0;
  border-right: none;
}

/* Header */
.ws-sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  height: 52px;
  border-bottom: 1px solid #ECECED;
  flex-shrink: 0;
  background: #FAFAFA;
}

.ws-sidebar__title {
  font-size: 16px;
  font-weight: 600;
  color: #171717;
  letter-spacing: normal;
  margin: 0;
}

.ws-sidebar__toggle {
  background: none;
  border: none;
  color: #8E8E93;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
}

.ws-sidebar__toggle:hover {
  background: #EFEFF1;
  color: #171717;
}

/* Scroll Area */
.ws-sidebar__scroll-area {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding-bottom: 16px;
}

/* 2. New Task Button */
.ws-sidebar__action-box {
  padding: 12px 14px 8px;
}

.ws-new-task-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 36px;
  background: #426340;
  border: 1px solid #426340;
  border-radius: 8px;
  color: #FFFFFF;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(66, 99, 64, 0.15);
  transition: all 0.15s ease;
}

.ws-new-task-btn:hover {
  background: #355033;
  border-color: #355033;
}

/* Common Section */
.ws-sidebar__section {
  padding: 12px 14px;
  border-bottom: 1px solid #ECECED;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ws-sidebar__section--current {
  background: #FAFAFA;
}

.ws-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ws-section-label {
  font-size: 11px;
  color: #8E8E93;
  letter-spacing: 0.04em;
  font-weight: 600;
}

.ws-section-link {
  font-size: 11px;
  color: #666666;
  text-decoration: none;
  transition: color 0.15s ease;
}

.ws-section-link:hover {
  color: #426340;
}

.status-badge--sm {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
}

.ws-sidebar__goal {
  font-size: 13px;
  font-weight: 500;
  color: #171717;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ws-sidebar__dataset-meta {
  font-size: 11px;
  color: #8E8E93;
  display: flex;
  gap: 8px;
  min-width: 0;
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.ws-sidebar__dataset-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Progress steps */
.ws-sidebar__progress {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 4px;
}

.ws-progress-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #8E8E93;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.ws-progress-step:hover {
  background: #EFEFF1;
  color: #171717;
}

.ws-progress-step.completed { color: #4A7C59; }
.ws-progress-step.running   { color: #426340; font-weight: 600; }
.ws-progress-step.waiting_confirmation { color: #A87B32; font-weight: 600; }
.ws-progress-step.failed    { color: #B34E48; }

.ws-progress-step__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.ws-progress-step.running .ws-progress-step__dot {
  animation: agent-breathe 2s ease-in-out infinite;
}

.ws-progress-step__name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
}

/* 4. Shortcut List (List Style) */
.ws-shortcut-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ws-shortcut-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 6px 8px;
  border-radius: 6px;
  text-decoration: none;
  transition: background 0.15s ease;
}

.ws-shortcut-item:hover {
  background: #F5F5F7;
}

.ws-shortcut-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #F0F4EE;
  color: #426340;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ws-shortcut-icon svg {
  width: 15px;
  height: 15px;
}

.ws-shortcut-text {
  flex: 1;
  min-width: 0;
}

.ws-shortcut-title {
  font-size: 13px;
  font-weight: 500;
  color: #171717;
  line-height: 1.25;
}

.ws-shortcut-desc {
  font-size: 11px;
  color: #8E8E93;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 5. Recent Tasks List */
.ws-recent-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ws-recent-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 10px;
  border-radius: 6px;
  text-decoration: none;
  background: #FAFAFA;
  border: 1px solid #E5E5E8;
  transition: all 0.15s ease;
}

.ws-recent-item:hover {
  background: #F0F4EE;
  border-color: #D6E5D1;
  transform: translateY(-1px);
}

.ws-recent-item.is-active {
  background: #EDF4E9;
  border-color: #AFC8A8;
  border-left: 3px solid #426340;
}

.ws-recent-item__top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ws-recent-item__goal {
  font-size: 13px;
  font-weight: 500;
  color: #171717;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ws-recent-item__bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: #8E8E93;
  padding-left: 13px;
}

.ws-recent-item__status-text {
  color: #666666;
}

.ws-recent-empty {
  padding: 16px 8px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: #FAFAFA;
  border: 1px dashed #E5E5E8;
  border-radius: 6px;
}

.ws-recent-empty__title {
  font-size: 12px;
  font-weight: 500;
  color: #666666;
}

.ws-recent-empty__desc {
  font-size: 11px;
  color: #8E8E93;
}

/* Main */
.ws-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-app);
}

/* Top Sub-Header */
.ws-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: #FFFFFF;
  border-bottom: 1px solid #E5E5E8;
  flex-shrink: 0;
  min-width: 0;
  gap: 12px;
}

.ws-top-bar__left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1 1 auto;
  min-width: 0;
}

.ws-top-goal {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: #171717;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 420px;
}

.ws-top-bar__left > .status-badge {
  flex-shrink: 0;
  white-space: nowrap;
}

.ws-top-bar__right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.ws-top-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  height: 28px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  font-size: 12px;
  color: #666666;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
  white-space: nowrap;
}

.ws-top-btn:hover {
  background: #F5F5F7;
  color: #171717;
}

.ws-top-btn.is-active {
  background: #EDF4E9;
  border-color: #D6E5D1;
  color: #426340;
  font-weight: 500;
}

/* Empty state */
.ws-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 32px;
  text-align: center;
  max-width: 680px;
  width: 100%;
  margin: 0 auto;
}

.ws-empty__icon {
  color: #8E8E93;
}

.ws-empty__title {
  font-size: 20px;
  font-weight: 600;
  color: #171717;
}

.ws-empty__desc {
  font-size: 13px;
  color: #666666;
  line-height: 1.6;
}

.ws-empty__composer {
  width: 100%;
}

.ws-thinking {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 32px;
  color: #171717;
}

.ws-thinking__copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ws-thinking__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.ws-thinking__desc {
  margin: 0;
  color: #666666;
  font-size: 13px;
}

.ws-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  font-size: 13px;
  color: #8E8E93;
}

/* Follow-up composer */
.ws-followup {
  padding: 12px 20px 16px;
  border-top: 1px solid #E5E5E8;
  flex-shrink: 0;
  background: #FFFFFF;
}

.ws-followup-inner {
  max-width: 760px;
  margin: 0 auto;
}

/* Artifact panel */
.ws-artifact {
  width: clamp(440px, 36vw, 600px);
  flex-shrink: 0;
  transition: width 0.18s ease;
  background: #FFFFFF;
}

.ws-artifact.is-hidden {
  width: 0;
  overflow: hidden;
}
</style>
