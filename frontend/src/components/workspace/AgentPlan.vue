<template>
  <div class="agent-plan">
    <div class="plan-header">
      <button type="button" class="plan-toggle" @click="collapsed = !collapsed">
        <svg class="plan-toggle__icon" :class="{ 'is-open': !collapsed }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="12" height="12">
          <path d="m9 18 6-6-6-6"/>
        </svg>
        <span class="plan-header__label">执行计划</span>
      </button>
      <div class="plan-header__right">
        <span class="plan-count">{{ completedCount }}/{{ steps.length }}</span>
      </div>
    </div>

    <div class="plan-steps" v-if="!collapsed">
      <div
        v-for="step in displaySteps"
        :key="step.step_id"
        class="plan-step"
        :class="[stepClass(step), { 'is-clickable': hasResult(step.step_id) }]"
        @click="hasResult(step.step_id) && $emit('step-click', step.step_id)"
      >
        <!-- Step Icon -->
        <div class="plan-step__icon">
          <svg v-if="step.status === 'completed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <svg v-else-if="step.status === 'running'" class="spin-slow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
          </svg>
          <svg v-else-if="step.status === 'waiting_confirmation'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" x2="12" y1="8" y2="12"/>
            <line x1="12" x2="12.01" y1="16" y2="16"/>
          </svg>
          <svg v-else-if="step.status === 'failed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" x2="9" y1="9" y2="15"/>
            <line x1="9" x2="15" y1="9" y2="15"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
          </svg>
        </div>

        <!-- Step Content -->
        <div class="plan-step__content">
          <div class="plan-step__top">
            <span
              class="plan-step__tool"
              :class="{ 'plan-step__tool--report': step.tool === 'generate_report' }"
            >{{ localizedToolName(step.tool) }}</span>
            <span v-if="step.requires_confirmation" class="plan-step__confirm-badge">需确认</span>
            <span v-if="step.status === 'running'" class="agent-working-dot" style="margin-left: auto" />
          </div>
          <div v-if="stepRun(step.step_id)" class="plan-step__meta">
            <span v-if="stepRun(step.step_id)?.summary" class="plan-step__summary">
              {{ stepRun(step.step_id)?.summary }}
            </span>
            <span v-if="stepRun(step.step_id)?.duration_ms" class="plan-step__duration">
              {{ formatDuration(stepRun(step.step_id)!.duration_ms!) }}
            </span>
          </div>
          <!-- Error -->
          <div v-if="step.status === 'failed' && stepRun(step.step_id)?.error_message" class="plan-step__error">
            {{ stepRun(step.step_id)?.error_message }}
          </div>
        </div>

        <!-- Connector line -->
        <div class="plan-step__line" v-if="!isLast(step.step_id)" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { ExecutionPlanStep, CopilotExecutionStepSnapshot } from '../../types/api';
import { agentStepStatus } from '../../utils/agentStepStatus';

const props = defineProps<{
  steps: ExecutionPlanStep[];
  stepRuns: CopilotExecutionStepSnapshot[];
  currentStepId: string | null;
}>();

defineEmits<{
  'step-click': [stepId: string];
}>();

const collapsed = ref(false);

const displaySteps = computed(() => props.steps.map(step => ({
  ...step,
  status: agentStepStatus(stepRun(step.step_id)?.status ?? step.status),
})));
const completedCount = computed(() => displaySteps.value.filter(s => s.status === 'completed').length);

const TOOL_NAMES: Record<string, string> = {
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

  clean: '数据清洗 (Clean)',
  segment: '工况区间优选 (Segment)',
  delay_analyze: '纯时滞估计 (Delay)',
  collinearity: '共线性分析 (Collinearity)',
  feature_apply: '特征筛选执行 (Feature Apply)',
  feature_selection_apply: '特征筛选执行',
  arx_fit: 'ARX 系统辨识 (ARX Fit)',
  evaluate_model: '模型测试集评价 (Evaluate)',
  optimize_pipeline: 'Optuna 闭环寻优 (Optimize)',
  generate_report: '报告交付',
};

function localizedToolName(tool: string): string {
  return TOOL_NAMES[tool] ?? tool;
}

function stepRun(stepId: string) {
  const run = props.stepRuns.find(r => r.step_id === stepId);
  if (!run) return undefined;
  return {
    ...run,
    summary: typeof run.result_payload?.summary === 'string' ? run.result_payload.summary : '',
    duration_ms: run.started_at && run.finished_at
      ? Date.parse(run.finished_at) - Date.parse(run.started_at) : null,
  };
}

function hasResult(stepId: string): boolean {
  const run = stepRun(stepId);
  return !!run && Object.keys(run.result_payload ?? {}).length > 0;
}

function stepClass(step: { status: string }): string {
  return step.status;
}

function isLast(stepId: string): boolean {
  return props.steps[props.steps.length - 1]?.step_id === stepId;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
</script>

<style scoped>
.agent-plan {
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #ECECED;
  background: #FAFAFA;
}

.plan-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: none;
  cursor: pointer;
  color: #666666;
  transition: color 0.15s ease;
}

.plan-toggle:hover {
  color: #171717;
}

.plan-toggle__icon {
  transition: transform 0.15s ease;
}

.plan-toggle__icon.is-open {
  transform: rotate(90deg);
}

.plan-header__label {
  font-family: var(--font-sans);
  font-size: 12px;
  letter-spacing: normal;
  font-weight: 600;
  color: #426340;
}

.plan-count {
  font-size: 11px;
  color: #8E8E93;
}

/* Steps */
.plan-steps {
  padding: 8px 14px 12px;
  display: flex;
  flex-direction: column;
}

.plan-step {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 8px 0;
  cursor: default;
  transition: all 0.15s ease;
}

.plan-step.is-clickable {
  cursor: pointer;
}

.plan-step.is-clickable:hover .plan-step__tool {
  color: #426340;
}

/* Step status coloring */
.plan-step.completed .plan-step__icon { color: #4A7C59; }
.plan-step.running   .plan-step__icon { color: #426340; }
.plan-step.waiting_confirmation .plan-step__icon { color: #A87B32; }
.plan-step.failed    .plan-step__icon { color: #B34E48; }
.plan-step.pending   .plan-step__icon { color: #C7C7CC; }
.plan-step.cancelled .plan-step__icon { color: #8E8E93; }

/* Dim completed steps */
.plan-step.completed .plan-step__tool { color: #666666; }
.plan-step.pending   .plan-step__tool { color: #8E8E93; }

.plan-step__icon {
  width: 18px;
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  padding-top: 2px;
}

.plan-step__icon svg {
  width: 14px;
  height: 14px;
}

.plan-step__content {
  flex: 1;
  min-width: 0;
}

.plan-step__top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plan-step__tool {
  font-size: 13px;
  font-weight: 500;
  color: #171717;
  transition: color 0.15s ease;
}

.plan-step__tool--report {
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.plan-count,
.plan-step__tool,
.plan-step__duration {
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.plan-step__confirm-badge {
  font-size: 10px;
  font-weight: 600;
  color: #A87B32;
  background: #FAF4E8;
  border: 1px solid #EFE0C2;
  border-radius: 9999px;
  padding: 1px 6px;
}

.plan-step__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 2px;
}

.plan-step__summary {
  font-size: 12px;
  color: #8E8E93;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}

.plan-step__duration {
  font-size: 12px;
  color: #A1A1A6;
  flex-shrink: 0;
}

.plan-step__error {
  margin-top: 2px;
  font-size: 12px;
  color: #B34E48;
}

/* Vertical connector line */
.plan-step__line {
  position: absolute;
  left: 6px;
  top: 26px;
  bottom: 0;
  width: 1px;
  background: #ECECED;
}

/* Animations */
.spin-slow {
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
