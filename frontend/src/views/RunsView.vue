<template>
  <div class="page-container runs-view">
    <!-- Unified Page Header -->
    <PageHeader
      title="任务历史"
      description="查看 Agent 的执行阶段、审批和产物记录"
    >
      <template #actions>
        <router-link to="/workspace" class="page-primary-btn" aria-label="新建任务">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          <span>新建任务</span>
        </router-link>
      </template>
    </PageHeader>

    <!-- Loading Skeleton State -->
    <div v-if="loading" class="runs-skeleton-list">
      <div v-for="i in 3" :key="i" class="runs-skeleton-row">
        <div class="skeleton-dot" />
        <div class="skeleton-body">
          <div class="skeleton-line skeleton-line--title" />
          <div class="skeleton-line skeleton-line--sub" />
        </div>
        <div class="skeleton-line skeleton-line--badge" />
      </div>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="runs-error-box">
      <div class="runs-error-content">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#C04B4B" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span>{{ error }}</span>
      </div>
      <button class="empty-cta-btn empty-cta-btn--secondary" type="button" @click="loadExecutions">
        重新加载
      </button>
    </div>

    <!-- Empty State (No Executions) -->
    <AppEmptyState
      v-else-if="executions.length === 0"
      icon="history"
      title="任务历史"
      description="还没有执行过 Agent 任务。创建任务后，这里会保存完整的执行阶段、人工审批、模型、优化结果与报告记录。"
      :primary-action="{ label: '创建第一个任务', to: '/workspace' }"
    />

    <!-- Populated State: Search/Filter Toolbar + Task Rows -->
    <div v-else class="runs-content">
      <!-- Toolbar -->
      <div class="runs-toolbar">
        <div class="runs-search-wrap">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="m21 21-4.35-4.35"/>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            class="runs-search-input"
            placeholder="搜索任务目标、数据集或 ID..."
            aria-label="搜索任务目标、数据集或 ID"
          />
          <button
            v-if="searchQuery"
            class="search-clear-btn"
            type="button"
            @click="searchQuery = ''"
            aria-label="清除搜索"
          >
            ×
          </button>
        </div>

        <div class="runs-filter-group">
          <!-- Status Select -->
          <el-select
            v-model="selectedStatus"
            placeholder="状态筛选"
            size="default"
            class="status-select"
            style="width: 140px;"
          >
            <el-option label="全部状态" value="" />
            <el-option label="执行中" value="RUNNING" />
            <el-option label="待确认" value="WAITING_CONFIRMATION" />
            <el-option label="已完成" value="SUCCEEDED" />
            <el-option label="失败" value="FAILED" />
            <el-option label="已取消" value="CANCELLED" />
          </el-select>

          <!-- Sort Select -->
          <el-select
            v-model="sortOrder"
            size="default"
            style="width: 130px;"
          >
            <el-option label="最新在前" value="desc" />
            <el-option label="最早在前" value="asc" />
          </el-select>
        </div>
      </div>

      <!-- No match for filter search -->
      <AppEmptyState
        v-if="filteredExecutions.length === 0"
        inline
        icon="search"
        title="无匹配的历史任务"
        description="没有找到符合筛选条件的任务，请尝试调整关键词或状态。"
        :secondary-action="{ label: '清空筛选条件', onClick: resetFilters }"
      />

      <!-- Populated History Rows -->
      <div v-else class="runs-list">
        <router-link
          v-for="exec in filteredExecutions"
          :key="exec.execution_id"
          :to="`/workspace/${exec.execution_id}`"
          class="run-row"
        >
          <!-- Status Indicator Dot -->
          <div class="run-row__status-indicator">
            <span class="status-dot" :class="statusClass(exec.workflow_status)" />
          </div>

          <!-- Main Info -->
          <div class="run-row__main">
            <div class="run-row__goal">
              {{ exec.plan?.goal || '工业时序建模与寻优任务' }}
            </div>
            <div class="run-row__meta">
              <span
                class="run-dataset"
                :title="datasetStore.resolveDatasetName(exec.dataset_id)"
              >
                数据集：{{ datasetStore.resolveDatasetName(exec.dataset_id) }}
              </span>
              <span class="meta-sep">·</span>
              <span v-if="exec.plan?.steps?.length" class="meta-steps">
                {{ exec.plan.steps.length }} 个阶段
              </span>
              <span class="meta-sep">·</span>
              <span class="meta-time">{{ formatTime(exec.created_at) }}</span>
            </div>
          </div>

          <!-- Artifacts Summary Chips -->
          <div class="run-row__artifacts">
            <span v-if="exec.artifacts?.arx_model" class="artifact-chip">ARX Model</span>
            <span v-if="exec.artifacts?.optimization_study" class="artifact-chip">Optuna Study</span>
            <span v-if="exec.artifacts?.report" class="artifact-chip">Report</span>
          </div>

          <!-- Status Badge -->
          <div class="run-row__status-badge-wrap">
            <span class="status-badge" :class="statusClass(exec.workflow_status)">
              {{ statusLabel(exec.workflow_status) }}
            </span>
          </div>

          <!-- Action Arrow -->
          <div class="run-row__arrow">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m9 18 6-6-6-6"/>
            </svg>
          </div>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import PageHeader from '../components/common/PageHeader.vue';
import AppEmptyState from '../components/common/AppEmptyState.vue';
import { useDatasetStore } from '../stores/datasetStore';

const loading = ref(false);
const error = ref<string | null>(null);
const executions = ref<any[]>([]);
const datasetStore = useDatasetStore();

const searchQuery = ref('');
const selectedStatus = ref('');
const sortOrder = ref<'desc' | 'asc'>('desc');

function loadExecutions() {
  loading.value = true;
  error.value = null;
  try {
    const cached = JSON.parse(localStorage.getItem('indusopt.recent_executions') ?? '[]');
    executions.value = Array.isArray(cached) ? cached : [];
  } catch (err: any) {
    error.value = '无法解析历史任务记录：' + (err.message || String(err));
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  loadExecutions();
  if (executions.value.some((execution) => execution.dataset_id)) {
    await datasetStore.ensureDatasetNamesLoaded();
  }
});

const filteredExecutions = computed(() => {
  let list = [...executions.value];

  // Search filter
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase();
    list = list.filter(
      (e) =>
        (e.plan?.goal && e.plan.goal.toLowerCase().includes(q)) ||
        (e.execution_id && e.execution_id.toLowerCase().includes(q)) ||
        datasetStore.resolveDatasetName(e.dataset_id).toLowerCase().includes(q)
    );
  }

  // Status filter
  if (selectedStatus.value) {
    list = list.filter((e) => e.workflow_status === selectedStatus.value);
  }

  // Sort
  list.sort((a, b) => {
    const timeA = new Date(a.created_at || 0).getTime();
    const timeB = new Date(b.created_at || 0).getTime();
    return sortOrder.value === 'desc' ? timeB - timeA : timeA - timeB;
  });

  return list;
});

function resetFilters() {
  searchQuery.value = '';
  selectedStatus.value = '';
  sortOrder.value = 'desc';
}

function statusClass(s: string) {
  const m: Record<string, string> = {
    RUNNING: 'running',
    WAITING_CONFIRMATION: 'waiting',
    WAITING_ASYNC_TASK: 'running',
    SUCCEEDED: 'succeeded',
    FAILED: 'failed',
    CANCELLED: 'cancelled',
    PLANNED: 'pending',
  };
  return m[s] ?? 'pending';
}

function statusLabel(s: string) {
  const m: Record<string, string> = {
    RUNNING: '执行中',
    WAITING_CONFIRMATION: '待确认',
    WAITING_ASYNC_TASK: '处理中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    PLANNED: '已规划',
  };
  return m[s] ?? (s || '待处理');
}

function formatTime(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
</script>

<style scoped>
.runs-view {
  min-height: 100%;
}

/* Skeleton Loading */
.runs-skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}

.runs-skeleton-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: #FFFFFF;
  border: 1px solid #E8EAE5;
  border-radius: 8px;
}

.skeleton-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #E5E8E2;
  animation: pulse 1.5s infinite ease-in-out;
}

.skeleton-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-line {
  background: #EAECE7;
  border-radius: 4px;
  animation: pulse 1.5s infinite ease-in-out;
}

.skeleton-line--title {
  width: 40%;
  height: 14px;
}

.skeleton-line--sub {
  width: 20%;
  height: 10px;
}

.skeleton-line--badge {
  width: 70px;
  height: 24px;
}

@keyframes pulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}

/* Error State */
.runs-error-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: #FDF2F2;
  border: 1px solid #F5D0D0;
  border-radius: 8px;
  color: #C04B4B;
  margin-top: 24px;
}

.runs-error-content {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}

/* Toolbar */
.runs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.runs-search-wrap {
  position: relative;
  width: 280px;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 10px;
  width: 15px;
  height: 15px;
  color: #858B82;
  pointer-events: none;
}

.runs-search-input {
  width: 100%;
  height: 36px;
  padding: 0 28px 0 32px;
  background: #FFFFFF;
  border: 1px solid #DFE4DB;
  border-radius: 6px;
  font-size: 13px;
  color: #2C332B;
  outline: none;
  transition: all 0.15s ease;
}

.runs-search-input:focus {
  border-color: #82A978;
  box-shadow: 0 0 0 2px rgba(130, 169, 120, 0.15);
}

.search-clear-btn {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  color: #858B82;
  font-size: 16px;
  cursor: pointer;
}

.runs-filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* History List Rows */
.runs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.run-row {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 76px;
  padding: 14px 20px;
  background: #FFFFFF;
  border: 1px solid #E8EAE5;
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  transition: all 0.15s ease;
  cursor: pointer;
}

.run-row:hover {
  background: #F7F9F5;
  border-color: #D6DDD2;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
}

.run-row__status-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #A0A69D;
}

.status-dot.running {
  background: #5E8358;
  box-shadow: 0 0 0 2px rgba(94, 131, 88, 0.2);
}

.status-dot.waiting {
  background: #E6A23C;
  box-shadow: 0 0 0 2px rgba(230, 162, 60, 0.2);
}

.status-dot.succeeded {
  background: #5E8358;
}

.status-dot.failed {
  background: #D96A6A;
}

.status-dot.cancelled {
  background: #A0A69D;
}

.run-row__main {
  flex: 1;
  min-width: 0;
}

.run-row__goal {
  font-size: 15px;
  font-weight: 600;
  color: #2C332B;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.run-row:hover .run-row__goal {
  color: #426340;
}

.run-row__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #858B82;
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.run-dataset {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-steps,
.meta-time,
.meta-sep {
  flex-shrink: 0;
}

.meta-sep {
  color: #D0D4CD;
}

.run-row__artifacts {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.artifact-chip {
  font-size: 11px;
  font-weight: 600;
  color: #5E8358;
  background: #F0F4EE;
  border: 1px solid #DFE6DC;
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
}

.run-row__status-badge-wrap {
  flex-shrink: 0;
  min-width: 80px;
  text-align: right;
}

.status-badge {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
  white-space: nowrap;
  border: 1px solid transparent;
}

.status-badge.running {
  background: #E8F0E5;
  color: #426340;
  border-color: #DFE4DB;
}

.status-badge.waiting {
  background: #FEF3E6;
  color: #B26A00;
  border-color: #F7DCB7;
}

.status-badge.succeeded {
  background: #EAF5E9;
  color: #3B703A;
  border-color: #D4EAD2;
}

.status-badge.failed {
  background: #FDF0F0;
  color: #C04B4B;
  border-color: #F5D0D0;
}

.status-badge.cancelled,
.status-badge.pending {
  background: #F0F2ED;
  color: #747A72;
  border-color: #E5E8E2;
}

.run-row__arrow {
  color: #A0A69D;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.15s ease;
}

.run-row:hover .run-row__arrow {
  color: #426340;
  transform: translateX(2px);
}
</style>
