<template>
  <div
    class="tool-execution"
    :class="[stepRun.status, { 'has-result': hasResult }]"
    @click="hasResult && $emit('click')"
  >
    <!-- Header Row -->
    <div class="te-header">
      <div class="te-header__left">
        <span class="te-status-icon">
          <svg v-if="stepRun.status === 'completed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="11" height="11"><polyline points="20 6 9 17 4 12"/></svg>
          <svg v-else-if="stepRun.status === 'running'" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="11" height="11"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
          <svg v-else-if="stepRun.status === 'failed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="11" height="11"><circle cx="12" cy="12" r="10"/><line x1="15" x2="9" y1="9" y2="15"/><line x1="9" x2="15" y1="9" y2="15"/></svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="11" height="11"><circle cx="12" cy="12" r="10"/></svg>
        </span>
        <span
          class="te-tool"
          :class="{ 'te-tool--report': toolKey === 'generate_report' }"
        >{{ localizedTool(toolKey) }}</span>
        <span v-if="stepRun.status === 'waiting_confirmation'" class="te-awaiting">等待确认</span>
      </div>
      <div class="te-header__right">
        <span v-if="stepRun.duration_ms" class="te-duration">{{ formatDuration(stepRun.duration_ms) }}</span>
        <span v-if="hasResult" class="te-view-link">查看成果 →</span>
      </div>
    </div>

    <!-- Summary -->
    <div v-if="stepRun.summary" class="te-summary">
      {{ stepRun.summary }}
    </div>

    <!-- Key result metrics (inline, compact) -->
    <div v-if="keyMetrics.length > 0" class="te-metrics">
      <div v-for="m in keyMetrics" :key="m.label" class="te-metric">
        <span class="te-metric__label">{{ m.label }}</span>
        <span class="te-metric__value">{{ m.value }}</span>
      </div>
    </div>

    <!-- Error -->
    <div v-if="stepRun.status === 'failed' && stepRun.error_message" class="te-error">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>
      {{ stepRun.error_message }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { agentStepStatus } from '../../utils/agentStepStatus';
import type { CopilotExecutionStepSnapshot, ExecutionPlanStep } from '../../types/api';

const props = defineProps<{
  stepRun: CopilotExecutionStepSnapshot;
  planStep?: ExecutionPlanStep;
}>();

// Render the persistent snapshot through the same status vocabulary as the plan.
const stepRun = computed(() => ({
  ...props.stepRun,
  status: agentStepStatus(props.stepRun.status),
  summary: typeof props.stepRun.result_payload?.summary === 'string'
    ? props.stepRun.result_payload.summary : '',
  duration_ms: props.stepRun.started_at && props.stepRun.finished_at
    ? Date.parse(props.stepRun.finished_at) - Date.parse(props.stepRun.started_at) : null,
}));

const toolKey = computed(() => props.planStep?.tool ?? props.stepRun.tool ?? props.stepRun.step_id);

defineEmits<{ click: [] }>();

const TOOL_MAP: Record<string, string> = {
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
  segment: '工况优选 (Segment)',
  delay_analyze: '时滞估计 (Delay)',
  collinearity: '共线性分析 (Collinearity)',
  feature_apply: '特征筛选 (Feature Apply)',
  feature_selection_apply: '特征筛选 (Feature Selection)',
  arx_fit: 'ARX 系统辨识 (ARX Fit)',
  evaluate_model: '模型评价 (Evaluate)',
  optimize_pipeline: 'Optuna 寻优 (Optimize)',
  generate_report: '报告交付',
};

function localizedTool(t: string): string {
  return TOOL_MAP[t] ?? t;
}

const hasResult = computed(() =>
  !!props.stepRun.result_payload && Object.keys(props.stepRun.result_payload).length > 0
);

function isCompositeObjective(payload: Record<string, any>): boolean {
  return payload.objective_semantics?.name === 'composite_identification_score';
}

function formatObjectiveValue(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '—';
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Extract 2-3 key metrics from result payload for inline display */
const keyMetrics = computed<{ label: string; value: string }[]>(() => {
  const p = props.stepRun.result_payload;
  if (!p) return [];
  const results: { label: string; value: string }[] = [];
  const tool = toolKey.value;

  if (tool === 'arx_fit' || tool === 'evaluate_model') {
    if (p.fit_pct !== undefined) results.push({ label: 'FIT', value: `${p.fit_pct.toFixed(1)}%` });
    if (p.r2 !== undefined) results.push({ label: 'R²', value: p.r2.toFixed(3) });
    if (p.rmse !== undefined) results.push({ label: 'RMSE', value: p.rmse.toFixed(4) });
  } else if (tool === 'delay_analyze') {
    const delays: string[] = [];
    if (p.estimated_delays) {
      Object.entries(p.estimated_delays).slice(0, 3).forEach(([k, v]: [string, any]) => {
        delays.push(`${k}: ${v}`);
      });
    }
    if (delays.length) results.push({ label: '时滞估计', value: delays.join(', ') });
  } else if (tool === 'collinearity' || tool === 'feature_apply') {
    if (p.removed_columns?.length !== undefined) {
      results.push({ label: '剔除冗余列', value: `${p.removed_columns.length} 列` });
    }
    if (p.kept_columns?.length !== undefined) {
      results.push({ label: '保留特征', value: `${p.kept_columns.length} 列` });
    }
  } else if (tool === 'optimize_pipeline') {
    if ('best_value' in p) {
      results.push({
        label: isCompositeObjective(p) ? '综合辨识得分' : '优化目标值',
        value: formatObjectiveValue(p.best_value),
      });
    }
  } else if (tool === 'clean') {
    if (p.replaced_count !== undefined) results.push({ label: '修正异常点', value: String(p.replaced_count) });
  } else if (tool === 'segment') {
    if (p.coverage !== undefined) results.push({ label: '工况覆盖率', value: `${(p.coverage * 100).toFixed(1)}%` });
  }

  return results;
});
</script>

<style scoped>
.tool-execution {
  padding: 12px 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.15s ease;
}

.tool-execution.has-result {
  cursor: pointer;
}

.tool-execution.has-result:hover {
  background: #FAFBF8;
  border-color: #D1D1D6;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

/* Status borders */
.tool-execution.completed { border-left: 2.5px solid var(--success); }
.tool-execution.running   { border-left: 2.5px solid var(--accent); }
.tool-execution.failed    { border-left: 2.5px solid var(--danger); }
.tool-execution.waiting_confirmation { border-left: 2.5px solid var(--warning); }

/* Header */
.te-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.te-header__left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.te-header__right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.te-status-icon {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  flex-shrink: 0;
}

.completed .te-status-icon { color: var(--success); }
.running   .te-status-icon { color: var(--accent); }
.failed    .te-status-icon { color: var(--danger); }
.waiting_confirmation .te-status-icon { color: var(--warning); }
.pending   .te-status-icon { color: var(--text-disabled); }

.te-tool {
  font-size: 13px;
  font-weight: 500;
  color: #171717;
}

.te-tool--report {
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.te-tool,
.te-duration,
.te-metric__value {
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.te-awaiting {
  font-size: 11px;
  color: var(--warning);
  background: var(--warning-soft);
  border: 1px solid var(--color-warning-border);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.te-duration {
  font-size: 12px;
  color: #8E8E93;
}

.te-view-link {
  font-size: 12px;
  color: #426340;
  font-weight: 500;
}

/* Summary */
.te-summary {
  margin-top: 4px;
  font-size: 12px;
  color: #666666;
  line-height: 1.5;
}

/* Metrics */
.te-metrics {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #ECECED;
}

.te-metric {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.te-metric__label {
  font-size: 10px;
  color: #8E8E93;
  text-transform: uppercase;
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.te-metric__value {
  font-size: 12px;
  font-weight: 600;
  color: #171717;
}

/* Error */
.te-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--danger);
  line-height: 1.5;
}

/* Spin */
.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
