<template>
  <div
    class="approval-card"
    :data-test="`confirmation-status-${stepRun.step_id}`"
  >
    <!-- Header -->
    <div class="ac-header">
      <div class="ac-header__icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" x2="12" y1="9" y2="13"/>
          <line x1="12" x2="12.01" y1="17" y2="17"/>
        </svg>
      </div>
      <div class="ac-header__body">
        <div class="ac-header__title">需要你的确认</div>
        <div class="ac-header__sub">{{ toolLabel }}</div>
      </div>
      <div :data-test="`confirm-actions-${stepRun.step_id}`" style="display: none" />
    </div>

    <!-- ── Lag Override ─────────────────────────────────── -->
    <template v-if="confirmationType === 'lag'">
      <div class="ac-body">
        <p class="ac-desc">Agent 估计了以下变量的时滞补偿量，请审查并确认（或手动覆盖）：</p>
        <div class="ac-lag-table" :data-test="`lag-recommendation-${stepRun.step_id}`">
          <div class="ac-lag-row ac-lag-row--header">
            <span>变量</span>
            <span>推荐时滞</span>
            <span>手动覆盖</span>
          </div>
          <div
            v-for="(item, idx) in lagItems"
            :key="item.variable"
            class="ac-lag-row"
          >
            <span>{{ item.variable }}</span>
            <span>{{ item.recommended ?? '—' }}</span>
            <input
              v-model.number="lagOverrides[idx].value"
              type="number"
              class="ac-lag-input"
              :placeholder="String(item.recommended ?? '')"
            />
          </div>
        </div>
        <div
          v-if="lagValidation"
          class="ac-validation"
          :class="lagValidation.valid ? 'ok' : 'error'"
          :data-test="`lag-validation-${stepRun.step_id}`"
        >
          {{ lagValidation.message }}
        </div>
      </div>
    </template>

    <!-- ── ARX Structure ────────────────────────────────── -->
    <template v-else-if="confirmationType === 'arx'">
      <div class="ac-body" :data-test="`arx-recommendation-${stepRun.step_id}`">
        <p class="ac-desc">Agent 推荐了以下 ARX 模型阶次，可手动覆盖后确认：</p>
        <div class="ac-arx-grid">
          <div class="ac-arx-item">
            <label class="ac-arx-label"><span>na</span>（输出阶）</label>
            <span class="ac-arx-recommended">推荐: <span>{{ arxRec.na }}</span></span>
            <input v-model.number="arxOverride.na" type="number" min="1" max="20" class="ac-lag-input" />
          </div>
          <div v-for="variable in arxVariables" :key="variable" class="ac-arx-item">
            <label class="ac-arx-label"><span>nb[{{ variable }}]</span>（输入阶）</label>
            <span class="ac-arx-recommended">推荐: <span>{{ arxRec.nb[variable] }}</span></span>
            <input v-model.number="arxOverride.nb[variable]" type="number" min="1" max="100" class="ac-lag-input" />
          </div>
        </div>
        <div
          v-if="arxModelId"
          class="ac-arx-model-id font-mono"
          :data-test="`arx-model-id-${stepRun.step_id}`"
        >
          Model: {{ arxModelId }}
        </div>
      </div>
    </template>

    <!-- ── Feature Selection ────────────────────────────── -->
    <template v-else-if="confirmationType === 'feature'">
      <div class="ac-body">
        <p v-if="featureItems.length === 0" class="ac-desc">分析未建议剔除输入变量，本次将保留全部输入。</p>
        <p v-else class="ac-desc">Agent 建议移除以下列（VIF / 相关性超标），可取消勾选保留：</p>
        <div v-if="featureItems.length > 0" class="ac-feature-list" :data-test="`feature-recommendation-${stepRun.step_id}`">
          <label
            v-for="col in featureItems"
            :key="col.name"
            class="ac-feature-item"
            :data-test="`feature-variable-${col.name}`"
          >
            <input type="checkbox" v-model="col.shouldRemove" class="ac-feature-checkbox" />
            <span class="ac-feature-name">{{ col.name }}</span>
            <span v-if="col.reason" class="ac-feature-reason">{{ col.reason }}</span>
          </label>
        </div>
      </div>
    </template>

    <!-- Actions -->
    <p v-if="!copilotRunId" class="ac-desc" role="alert">该任务缺少运行标识，请从任务历史重新打开或新建任务。</p>
    <div class="ac-actions">
      <button
        type="button"
        class="ac-btn ac-btn--reject"
        :disabled="isSubmitting || !copilotRunId"
        :data-test="`reject-${stepRun.step_id}`"
        @click="handleReject"
      >
        拒绝
      </button>
      <button
        type="button"
        class="ac-btn ac-btn--approve"
        :disabled="isSubmitting || !copilotRunId"
        :data-test="`approve-${stepRun.step_id}`"
        @click="handleApprove"
      >
        <svg v-if="!isSubmitting" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="13" height="13"><polyline points="20 6 9 17 4 12"/></svg>
        <span>{{ isSubmitting ? '确认中…' : '批准并继续' }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { CopilotExecutionStepSnapshot, ExecutionPlanStep, CopilotConfirmRequest } from '../../types/api';

const props = defineProps<{
  stepRun: CopilotExecutionStepSnapshot;
  planStep?: ExecutionPlanStep;
  executionId: string;
  copilotRunId: string | null;
  submitting?: boolean;
}>();

const emit = defineEmits<{
  confirm: [req: CopilotConfirmRequest];
}>();

const isSubmitting = computed(() => props.submitting ?? false);

// Determine confirmation type from tool name
const confirmationType = computed((): 'lag' | 'arx' | 'feature' | null => {
  const tool = props.stepRun.tool || props.planStep?.tool || '';
  if (tool === 'apply_lag_compensation' || tool === 'lag_apply' || tool === 'lag_compensation_apply' || tool === 'delay_analyze') return 'lag';
  if (tool === 'fit_arx' || tool === 'arx_fit') return 'arx';
  if (tool === 'select_variables' || tool === 'feature_apply' || tool === 'feature_selection_apply' || tool === 'collinearity') return 'feature';
  return null;
});

const toolLabel = computed((): string => {
  const labels: Record<string, string> = {
    lag: '时滞补偿确认',
    arx: 'ARX 模型阶次确认',
    feature: '特征筛选确认',
  };
  return labels[confirmationType.value ?? ''] ?? props.planStep?.tool ?? '人工确认';
});

// ── Lag ──────────────────────────────────────────────────
const lagRecommendations = computed<{ variable: string; recommended: number }[]>(() => {
  const recs = props.stepRun.input_payload?.recommended_lag_map
    ?? props.stepRun.input_payload?.recommendations
    ?? {};
  return Object.entries(recs).map(([variable, recommended]) => ({
    variable,
    recommended: recommended as number,
  }));
});

const lagItems = computed(() => lagRecommendations.value);
const lagOverrides = ref<{ variable: string; value: number | '' | null }[]>([]);

if (lagItems.value.length > 0) {
  lagOverrides.value = lagItems.value.map(i => ({ variable: i.variable, value: null }));
}

const lagValidation = ref<{ valid: boolean; message: string } | null>(null);

// ── ARX ──────────────────────────────────────────────────
const arxRec = computed(() => ({
  na: props.stepRun.input_payload?.arx_structure_recommendation?.recommended_na ?? 2,
  nb: props.stepRun.input_payload?.arx_structure_recommendation?.recommended_nb ?? {},
}));
const arxVariables = computed(() => Object.keys(arxRec.value.nb));
const arxOverride = ref({ na: arxRec.value.na, nb: { ...arxRec.value.nb } });
const arxModelId = computed(() => props.stepRun.result_payload?.model_id ?? null);

// ── Feature ───────────────────────────────────────────────
const featureItems = ref<{ name: string; reason: string; shouldRemove: boolean }[]>([]);
const rawFeatureRecs = computed<string[]>(() => props.stepRun.input_payload?.recommended_drop_columns ?? []);

if (rawFeatureRecs.value.length > 0) {
  featureItems.value = rawFeatureRecs.value.map(name => ({
    name,
    reason: props.stepRun.input_payload?.recommendation_evidence?.[name]?.reason ?? '',
    shouldRemove: true,
  }));
}

// ── Actions ───────────────────────────────────────────────
async function handleApprove() {
  if (isSubmitting.value) return;
  if (!props.copilotRunId) return;
    const base = {
      execution_id: props.executionId,
      copilot_run_id: props.copilotRunId,
      confirmation_id: props.stepRun.step_id,
      step_id: props.stepRun.step_id,
      approved: true,
    };

    if (confirmationType.value === 'lag') {
      const overrides = lagOverrides.value
        .filter(o => o.value !== null && o.value !== '')
        .map(o => ({ variable: o.variable, value: o.value as number }));
      emit('confirm', {
        ...base,
        manual_overrides: overrides,
      });
    } else if (confirmationType.value === 'arx') {
      emit('confirm', {
        ...base,
        arx_structure_overrides: arxOverride.value,
      });
    } else if (confirmationType.value === 'feature') {
      const columnsToRemove = featureItems.value.filter(f => f.shouldRemove).map(f => f.name);
      emit('confirm', {
        ...base,
        feature_drop_columns: columnsToRemove,
      });
    } else {
      emit('confirm', base);
    }
}

async function handleReject() {
  if (isSubmitting.value || !props.copilotRunId) return;
    emit('confirm', {
      execution_id: props.executionId,
      copilot_run_id: props.copilotRunId,
      confirmation_id: props.stepRun.step_id,
      step_id: props.stepRun.step_id,
      approved: false,
    });
}
</script>

<style scoped>
.approval-card {
  border: 1px solid #E5E5E8;
  border-left: 3px solid var(--warning);
  background: #FFFFFF;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

/* Header */
.ac-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #ECECED;
  background: #FAF9F5;
}

.ac-header__icon {
  width: 26px;
  height: 26px;
  background: #FAF4E8;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--warning);
  flex-shrink: 0;
}

.ac-header__icon svg {
  width: 14px;
  height: 14px;
}

.ac-header__title {
  font-size: 13px;
  font-weight: 600;
  color: #171717;
}

.ac-header__sub {
  font-size: 11px;
  color: #8E8E93;
  margin-top: 1px;
}

/* Body */
.ac-body {
  padding: 16px;
  background: #FFFFFF;
}

.ac-desc {
  font-size: 13px;
  color: #666666;
  margin-bottom: 12px;
  line-height: 1.5;
}

/* Lag Table */
.ac-lag-table {
  display: flex;
  flex-direction: column;
  gap: 1px;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  overflow: hidden;
  background: #F5F5F7;
}

.ac-lag-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  font-size: 13px;
  font-family: var(--font-sans);
  letter-spacing: normal;
  background: #FFFFFF;
  border-bottom: 1px solid #ECECED;
}

.ac-lag-row:last-child {
  border-bottom: none;
}

.ac-lag-row--header {
  font-size: 11px;
  color: #8E8E93;
  text-transform: uppercase;
  letter-spacing: normal;
  background: #FAFAFA;
}

.ac-lag-input {
  width: 80px;
  padding: 4px 8px;
  background: #F5F5F7;
  border: 1px solid #E5E5E8;
  border-radius: 4px;
  color: #171717;
  font-size: 13px;
  font-family: var(--font-sans);
  outline: none;
  transition: border-color 0.15s ease;
}

.ac-lag-input:focus {
  border-color: #426340;
}

/* Validation */
.ac-validation {
  margin-top: 8px;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
}

.ac-validation.ok {
  color: var(--success);
  background: var(--success-soft);
}

.ac-validation.error {
  color: var(--danger);
  background: var(--danger-soft);
}

/* ARX Grid */
.ac-arx-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.ac-arx-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ac-arx-label {
  font-size: 11px;
  color: #8E8E93;
  text-transform: uppercase;
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.ac-arx-recommended {
  font-size: 12px;
  color: #666666;
}

.ac-arx-model-id {
  font-size: 11px;
  color: #8E8E93;
}

/* Feature List */
.ac-feature-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ac-feature-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #FAFAFA;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.ac-feature-item:hover {
  background: #F5F5F7;
}

.ac-feature-checkbox {
  accent-color: var(--accent);
  width: 14px;
  height: 14px;
}

.ac-feature-name {
  font-size: 13px;
  color: #171717;
  font-weight: 500;
}

.ac-feature-reason {
  font-size: 12px;
  color: #8E8E93;
  margin-left: auto;
}

/* Actions */
.ac-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid #ECECED;
  background: #FAFAFA;
}

.ac-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.ac-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ac-btn--reject {
  background: #FFFFFF;
  border-color: #E5E5E8;
  color: #666666;
}

.ac-btn--reject:hover:not(:disabled) {
  background: #F5F5F7;
  border-color: #D1D1D6;
  color: #171717;
}

.ac-btn--approve {
  background: #426340;
  border-color: #426340;
  color: #FFFFFF;
}

.ac-btn--approve:hover:not(:disabled) {
  background: #345032;
  border-color: #345032;
}
</style>
