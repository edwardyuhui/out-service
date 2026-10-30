<template>
  <div class="artifact-workbench">
    <!-- Header -->
    <div class="aw-header">
      <div class="aw-header__left">
        <span class="aw-header__title">成果展示区</span>
      </div>
      <div class="aw-header__right">
        <button
          type="button"
          class="aw-icon-btn"
          :title="isPinned ? '取消固定' : '固定面板'"
          :aria-label="isPinned ? '取消固定' : '固定面板'"
          @click="isPinned = !isPinned"
        >
          <svg viewBox="0 0 24 24" fill="none" :stroke="isPinned ? 'var(--accent)' : 'currentColor'" stroke-width="2" width="14" height="14" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/>
          </svg>
        </button>
        <button
          type="button"
          class="aw-icon-btn"
          title="关闭面板"
          aria-label="关闭面板"
          @click="$emit('toggle')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" stroke-linecap="round" stroke-linejoin="round">
            <path d="m9 18 6-6-6-6"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="aw-data-actions" data-test="artifact-data-actions">
      <a
        class="aw-action-btn"
        data-test="download-current-dataset"
        :href="currentDatasetDownloadUrl"
      >下载当前数据集</a>
      <button
        type="button"
        class="aw-action-btn"
        data-test="export-optimised-dataset"
        :disabled="isExporting"
        @click="handleOptimisedExport"
      >{{ isExporting ? '导出中…' : '导出优选数据集' }}</button>
    </div>

    <div
      v-if="exportNotice"
      class="aw-export-notice"
      :class="{ 'is-error': exportNotice.kind === 'error' }"
      data-test="export-notice"
    >
      <span>{{ exportNotice.message }}</span>
      <template v-if="exportNotice.result">
        <span>导出 {{ exportNotice.result.exported_rows }} / {{ exportNotice.result.source_rows }} 行，覆盖率 {{ formatCoverage(exportNotice.result.coverage_ratio) }}</span>
        <ExportDownloadActions
          class="aw-notice-downloads"
          :csv-url="exportCsvUrl(exportNotice.result.export_id)"
          :manifest-url="exportManifestUrl(exportNotice.result.export_id)"
        />
      </template>
    </div>

    <!-- Artifact Tabs -->
    <div class="aw-tabs" v-if="availableArtifacts.length > 0">
      <button
        v-for="art in availableArtifacts"
        :key="art.stepId"
        type="button"
        class="aw-tab"
        :class="{ 'is-active': activeTab === art.stepId }"
        @click="activeTab = art.stepId"
      >
        <span class="aw-tab__label">{{ art.label }}</span>
      </button>
    </div>

    <!-- Artifact Content -->
    <div class="aw-content" v-if="activeArtifact">
      <!-- Dataset Profile Artifact -->
      <template v-if="activeArtifact.type === 'profile'">
        <ProfileArtifactRenderer :payload="activeArtifact.payload" />
      </template>

      <!-- Anomaly Detection Artifact -->
      <template v-else-if="activeArtifact.type === 'anomaly'">
        <AnomalyArtifactRenderer :payload="activeArtifact.payload" />
      </template>

      <!-- Cleaning Artifact -->
      <template v-else-if="activeArtifact.type === 'cleaning'">
        <CleaningArtifactRenderer :payload="activeArtifact.payload" />
      </template>

      <template v-else-if="activeArtifact.type === 'segmentation'">
        <SegmentationArtifactRenderer :payload="activeArtifact.payload" />
      </template>

      <template v-else-if="activeArtifact.type === 'collinearity'">
        <CollinearityArtifactRenderer :key="activeArtifact.stepId" :payload="activeArtifact.payload" />
      </template>

      <template v-else-if="activeArtifact.type === 'feature_selection'">
        <FeatureSelectionArtifactRenderer
          :payload="activeArtifact.payload"
          :source-version-id="activeArtifact.sourceVersionId"
          :result-version-id="activeArtifact.resultVersionId"
        />
      </template>

      <template v-else-if="activeArtifact.type === 'model'">
        <ArxModelArtifactRenderer :payload="activeArtifact.payload" />
      </template>

      <template v-else-if="activeArtifact.type === 'evaluation'">
        <ModelEvaluationArtifactRenderer :payload="activeArtifact.payload" />
      </template>

      <template v-else-if="activeArtifact.type === 'report'">
        <ReportArtifactRenderer :payload="activeArtifact.payload" :execution="execution" />
      </template>

      <template v-else-if="activeArtifact.type === 'export'">
        <section class="aw-export-artifact" data-test="export-artifact-renderer">
          <h3>优选数据集已导出</h3>
          <div class="aw-export-metrics">
            <span>导出样本数<strong>{{ activeArtifact.payload.exported_rows }}</strong></span>
            <span>源样本数<strong>{{ activeArtifact.payload.source_rows }}</strong></span>
            <span>覆盖率<strong>{{ formatCoverage(activeArtifact.payload.coverage_ratio) }}</strong></span>
          </div>
          <ExportDownloadActions
            v-if="typeof activeArtifact.payload.export_id === 'string'"
            class="aw-export-downloads"
            :csv-url="exportCsvUrl(activeArtifact.payload.export_id)"
            :manifest-url="exportManifestUrl(activeArtifact.payload.export_id)"
          />
        </section>
      </template>

      <!-- Optimization Artifact -->
      <template v-else-if="activeArtifact.type === 'optimization'">
        <MetricStrip :metrics="optimizationMetrics(activeArtifact)" />
        <p
          v-if="isCompositeObjective(activeArtifact.payload)"
          class="aw-optimization-objective-note"
          data-test="optimization-objective-note"
        >综合考虑验证集自由运行拟合能力、预测误差、残差白度、模型复杂度与稳定性。</p>
        <div class="aw-section" data-test="optimization-parameters">
          <div class="aw-section__label">最优策略参数</div>
          <p class="aw-optimization-intro">由闭环寻优综合比较数据优选策略与 ARX 模型结构后得到的最佳参数组合。</p>
          <div
            v-for="group in optimizationParameterGroups(activeArtifact)"
            :key="group.key"
            class="aw-optimization-group"
            :data-test="`optimization-group-${group.key}`"
          >
            <div class="aw-optimization-group__title">{{ group.label }}</div>
            <div class="aw-kv-list">
              <div
                v-for="parameter in group.parameters"
                :key="parameter.key"
                class="aw-kv aw-optimization-param"
                :data-test="`optimization-param-${parameter.key}`"
              >
                <div class="aw-optimization-param__main">
                  <span class="aw-kv__key">{{ parameter.label }}</span>
                  <span class="aw-kv__val">{{ parameter.value }}</span>
                </div>
                <p v-if="parameter.description" class="aw-optimization-param__description">{{ parameter.description }}</p>
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="activeArtifact.type === 'lag'">
        <template v-if="activeArtifact.payload.disposition === 'CONFIRMED_NO_OP'">
          <div class="aw-section" data-test="lag-no-op-result">
            <div class="aw-section__label">处理结论</div>
            <div class="aw-kv">
              <span class="aw-kv__key">确认结果</span>
              <span class="aw-kv__val">已确认无需额外时滞补偿</span>
            </div>
            <div data-test="lag-no-op-description">时滞分析结果显示当前各输入通道无需进一步时间平移，并已通过人工确认。本次处理未改变数据，未执行数据平移或边界裁剪，因此未生成新的数据版本。</div>
          </div>
          <div class="aw-section" data-test="lag-no-op-lags">
            <div class="aw-section__label">已确认时滞</div>
            <div class="aw-kv-list">
              <div v-for="(val, key) in activeArtifact.payload.final_lag_map" :key="key" class="aw-kv">
                <span class="aw-kv__key">{{ key }}</span>
                <span class="aw-kv__val">{{ val }} 个采样点</span>
              </div>
            </div>
          </div>
          <div class="aw-section" data-test="lag-no-op-version-status">
            <div class="aw-section__label">版本状态</div>
            <div class="aw-kv">
              <span class="aw-kv__key">当前状态</span>
              <span class="aw-kv__val">数据版本保持不变</span>
            </div>
            <div>本次处理为确认型操作，源数据版本继续作为后续建模输入。</div>
            <div>数据未发生变化，如需下载可使用顶部“下载当前数据集”。</div>
          </div>
        </template>
        <template v-else>
          <MetricStrip :metrics="[
            { label: '补偿前样本数', value: String(activeArtifact.payload.summary?.rows_before ?? '—') },
            { label: '补偿后样本数', value: String(activeArtifact.payload.summary?.rows_after ?? '—'), primary: true },
            { label: '裁剪边界行数', value: String(activeArtifact.payload.summary?.removed_boundary_rows ?? '—') },
          ]" />
          <div class="aw-section">
            <div class="aw-section__label">各输入已应用补偿量</div>
            <p class="aw-lag-note">单位：采样点。展示本次实际应用的时间平移量，0 表示未平移。</p>
            <ChartContainer
              v-if="lagEntries.length"
              data-test="lag-compensation-chart"
              :options="lagChartOptions"
              :height="`${Math.max(180, lagEntries.length * 42 + 64)}px`"
            />
            <p v-else class="aw-lag-note" data-test="lag-chart-empty">该记录未保存有效的补偿量，暂无法展示图表。</p>
            <details v-if="lagEntries.length" class="aw-lag-details">
              <summary>查看补偿数值明细</summary>
              <div class="aw-kv-list">
                <div v-for="[key, val] in lagEntries" :key="key" class="aw-kv">
                  <span>{{ key }}</span><span>{{ val }} 采样点{{ val === 0 ? ' · 未平移' : '' }}</span>
                </div>
              </div>
            </details>
          </div>
          <div class="aw-lag-delivery">
            <div class="aw-section__label">补偿结果数据</div>
            <template v-if="lagDownloadUrl">
              <p class="aw-lag-note">已生成补偿后数据版本</p>
              <code data-test="lag-result-version">{{ activeArtifact.payload.result_version_id }}</code>
              <ElButton tag="a" type="primary" class="aw-lag-download" :href="lagDownloadUrl" data-test="download-lag-csv" aria-label="下载补偿后 CSV">
                <Download aria-hidden="true" />
                <span>下载补偿后 CSV</span>
              </ElButton>
            </template>
            <p v-else class="aw-lag-note">该记录缺少结果版本信息，暂无法下载补偿后 CSV。</p>
          </div>
        </template>
      </template>

      <!-- Delay Artifact -->
      <template v-else-if="activeArtifact.type === 'delay'">
        <div class="aw-section">
          <div class="aw-section__label">估计纯时滞 (Estimated Delays)</div>
          <div class="aw-kv-list">
            <div v-for="(val, key) in (activeArtifact.payload.best_delays ?? activeArtifact.payload.estimated_delays)" :key="key" class="aw-kv">
              <span class="aw-kv__key">{{ key }}</span>
              <span class="aw-kv__val">{{ val }} 采样点</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Feature / Collinearity Artifact -->
      <template v-else-if="activeArtifact.type === 'feature'">
        <div class="aw-section">
          <div class="aw-section__label">保留特征列 (Kept Features)</div>
          <div class="aw-tag-list">
            <span v-for="col in activeArtifact.payload.kept_columns" :key="col" class="aw-tag kept">{{ col }}</span>
          </div>
        </div>
        <div class="aw-section" v-if="activeArtifact.payload.removed_columns?.length">
          <div class="aw-section__label">剔除冗余列 (Removed Features)</div>
          <div class="aw-tag-list">
            <span v-for="col in activeArtifact.payload.removed_columns" :key="col" class="aw-tag removed">{{ col }}</span>
          </div>
        </div>
      </template>

      <!-- Generic fallback -->
      <template v-else>
        <div class="aw-section">
          <div class="aw-section__label">工件详细数据 (Payload Details)</div>
          <pre class="aw-json font-mono">{{ JSON.stringify(activeArtifact.payload, null, 2) }}</pre>
        </div>
      </template>
    </div>

    <!-- Empty state -->
    <div class="aw-empty" v-else-if="availableArtifacts.length === 0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28" stroke-linecap="round" stroke-linejoin="round">
        <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="3" x2="21" y1="9" y2="9"/><line x1="3" x2="21" y1="15" y2="15"/><line x1="9" x2="9" y1="9" y2="21"/><line x1="15" x2="15" y1="9" y2="21"/>
      </svg>
      <p>Agent 任务执行完成后，辨识模型、寻优参数与工件将实时在此呈现</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { ElButton, ElMessage } from 'element-plus';
import { Download } from '@element-plus/icons-vue';
import ChartContainer, { type ChartOption } from '../ChartContainer.vue';
import MetricStrip from './MetricStrip.vue';
import AnomalyArtifactRenderer from './AnomalyArtifactRenderer.vue';
import ArxModelArtifactRenderer from './ArxModelArtifactRenderer.vue';
import CleaningArtifactRenderer from './CleaningArtifactRenderer.vue';
import CollinearityArtifactRenderer from './CollinearityArtifactRenderer.vue';
import ExportDownloadActions from './ExportDownloadActions.vue';
import FeatureSelectionArtifactRenderer from './FeatureSelectionArtifactRenderer.vue';
import ProfileArtifactRenderer from './ProfileArtifactRenderer.vue';
import ReportArtifactRenderer from './ReportArtifactRenderer.vue';
import SegmentationArtifactRenderer from './SegmentationArtifactRenderer.vue';
import ModelEvaluationArtifactRenderer from './ModelEvaluationArtifactRenderer.vue';
import type { CopilotExecutionSnapshot } from '../../types/api';
import type { ExportDatasetResponse } from '../../types/api';
import { exportDataset } from '../../api/delivery';
import { ApiError } from '../../api/client';
import { agentStepStatus } from '../../utils/agentStepStatus';

const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const props = defineProps<{
  execution: CopilotExecutionSnapshot;
  activeStepId?: string | null;
}>();

defineEmits<{ toggle: [] }>();

const isPinned = ref(false);
const activeTab = ref<string | null>(null);

interface ArtifactDef {
  stepId: string;
  type: 'profile' | 'anomaly' | 'model' | 'evaluation' | 'optimization' | 'delay' | 'lag' | 'feature' | 'feature_selection' | 'collinearity' | 'cleaning' | 'segmentation' | 'report' | 'export' | 'generic';
  label: string;
  payload: Record<string, any>;
  sourceVersionId?: string | null;
  resultVersionId?: string | null;
}

const TOOL_META: Record<string, { type: ArtifactDef['type']; label: string }> = {
  profile_dataset:         { type: 'profile',      label: '数据画像' },
  detect_anomalies:        { type: 'anomaly',      label: '异常检测' },
  clean_data:              { type: 'cleaning',     label: '数据清洗' },
  detect_dynamic_segments: { type: 'segmentation', label: '区间优选' },
  estimate_delays:         { type: 'delay',        label: '时滞分析' },
  apply_lag_compensation:  { type: 'lag',          label: '时滞补偿结果' },
  analyze_collinearity:    { type: 'collinearity', label: '共线性分析' },
  fit_arx:                 { type: 'model',        label: 'ARX 模型' },
  select_variables:        { type: 'feature_selection', label: '特征筛选' },
  arx_fit:                 { type: 'model',        label: 'ARX 模型' },
  evaluate_model:          { type: 'evaluation',   label: '模型评价' },
  optimize_pipeline:       { type: 'optimization', label: '寻优结果' },
  delay_analyze:           { type: 'delay',        label: '时滞分析' },
  collinearity:            { type: 'feature',      label: '特征筛选' },
  feature_apply:           { type: 'feature',      label: '特征筛选' },
  feature_selection_apply: { type: 'feature',      label: '特征筛选' },
  clean:                   { type: 'cleaning',     label: '数据清洗' },
  segment:                 { type: 'segmentation', label: '区间优选' },
  generate_report:         { type: 'report',       label: '分析报告' },
  export_dataset:          { type: 'export',       label: '导出结果' },
};

const isExporting = ref(false);
const exportNotice = ref<{
  kind: 'success' | 'error';
  message: string;
  result?: ExportDatasetResponse;
} | null>(null);

const currentDatasetDownloadUrl = computed(() =>
  `${apiBase}/datasets/${encodeURIComponent(props.execution.dataset_id)}/download?version_id=${encodeURIComponent(props.execution.current_version_id)}`
);

const exportCsvUrl = (exportId: string) =>
  `${apiBase}/delivery/exports/${encodeURIComponent(exportId)}/csv`;
const exportManifestUrl = (exportId: string) =>
  `${apiBase}/delivery/exports/${encodeURIComponent(exportId)}/manifest`;
const formatCoverage = (value: unknown): string =>
  typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '';

async function handleOptimisedExport() {
  if (isExporting.value) return;
  isExporting.value = true;
  exportNotice.value = null;
  try {
    const result = await exportDataset({
      dataset_id: props.execution.dataset_id,
      version_id: props.execution.current_version_id,
    });
    exportNotice.value = { kind: 'success', message: '优选数据集导出完成。', result };
    ElMessage.success('优选数据集导出完成');
  } catch (error) {
    const message = error instanceof ApiError && error.code === 'EXPORT_NO_SELECTION'
      ? '尚未完成样本优选，无法导出优选数据集。'
      : error instanceof Error
        ? error.message
        : '优选数据集导出失败。';
    exportNotice.value = { kind: 'error', message };
    ElMessage.error(message);
  } finally {
    isExporting.value = false;
  }
}

const availableArtifacts = computed<ArtifactDef[]>(() => {
  return props.execution.step_runs
    .filter(r => {
      if (agentStepStatus(r.status) !== 'completed') return false;
      if (r.result_payload && Object.keys(r.result_payload).length > 0) return true;
      const tool = r.tool || props.execution.plan?.steps?.find(s => s.step_id === r.step_id)?.tool;
      return tool === 'analyze_collinearity' || tool === 'select_variables';
    })
    .map(r => {
      const plan = props.execution.plan?.steps?.find(s => s.step_id === r.step_id);
      const tool = r.tool || plan?.tool || r.step_id;
      const meta = TOOL_META[tool] ?? { type: 'generic', label: tool };
      return {
        stepId: r.step_id,
        type: meta.type,
        label: meta.label,
        payload: r.result_payload ?? {},
        sourceVersionId: r.source_version_id,
        resultVersionId: r.result_version_id,
      };
    });
});

const activeArtifact = computed(() =>
  availableArtifacts.value.find(a => a.stepId === activeTab.value) ?? null
);

const lagEntries = computed<[string, number][]>(() => {
  if (activeArtifact.value?.type !== 'lag') return [];
  const map: unknown = activeArtifact.value.payload.summary?.lag_map;
  if (!map || typeof map !== 'object' || Array.isArray(map)) return [];
  return Object.entries(map).filter((entry): entry is [string, number] =>
    typeof entry[1] === 'number' && Number.isSafeInteger(entry[1]) && entry[1] >= 0
  );
});

const lagChartOptions = computed<ChartOption>(() => ({
  tooltip: { trigger: 'axis', renderMode: 'richText', axisPointer: { type: 'shadow' } },
  grid: { left: 12, right: 90, top: 12, bottom: 32, containLabel: true },
  xAxis: { type: 'value', min: 0, minInterval: 1, name: '采样点', nameLocation: 'middle', nameGap: 24 },
  yAxis: { type: 'category', inverse: true, data: lagEntries.value.map(([name]) => name), axisLabel: { width: 96, overflow: 'truncate' } },
  series: [{
    name: '已应用补偿量（采样点）',
    type: 'bar',
    data: lagEntries.value.map(([, value]) => value),
    barMaxWidth: 20,
    itemStyle: { color: '#52735A', borderRadius: [0, 4, 4, 0] },
    emphasis: { itemStyle: { color: '#426340' } },
    label: { show: true, position: 'right', formatter: params => params.value === 0 ? '0 · 未平移' : String(params.value) },
  }],
}));

const lagDownloadUrl = computed(() => {
  const artifact = activeArtifact.value;
  const datasetId = props.execution.dataset_id;
  const versionId = artifact?.payload.result_version_id;
  if (artifact?.type !== 'lag' || artifact.payload.disposition === 'CONFIRMED_NO_OP'
    || !datasetId || typeof versionId !== 'string' || !versionId.trim()) return null;
  return `${apiBase}/datasets/${encodeURIComponent(datasetId)}/download?version_id=${encodeURIComponent(versionId)}`;
});

watch(availableArtifacts, (arts, previous = []) => {
  if (!arts.some(a => a.stepId === activeTab.value) || (!isPinned.value && arts.length > previous.length)) {
    activeTab.value = arts.at(-1)?.stepId ?? null;
  }
}, { immediate: true });

watch(() => props.activeStepId, (id) => {
  if (id && availableArtifacts.value.some(a => a.stepId === id)) activeTab.value = id;
});

function optimizationMetrics(art: ArtifactDef) {
  const p = art.payload;
  const metrics: { label: string; value: string; primary?: boolean }[] = [];
  if ('best_value' in p) {
    metrics.push({
      label: isCompositeObjective(p)
        ? '综合辨识得分（Composite Identification Score）'
        : '优化目标值',
      value: formatObjectiveValue(p.best_value),
      primary: true,
    });
  }
  if (p.n_trials !== undefined)   metrics.push({ label: '试验次数', value: `${p.n_trials} 次` });
  return metrics;
}

type OptimizationParameterGroupKey = 'data-selection' | 'arx-model' | 'other';
type OptimizationParameterFormatter = (value: unknown) => string;

interface OptimizationParameterDefinition {
  label: string;
  description: string;
  group: OptimizationParameterGroupKey;
  format: OptimizationParameterFormatter;
}

interface OptimizationParameterDisplay {
  key: string;
  label: string;
  description: string;
  value: string;
}

interface OptimizationParameterGroup {
  key: OptimizationParameterGroupKey;
  label: string;
  parameters: OptimizationParameterDisplay[];
}

const EMPTY_VALUE = '—';
const compactNumber = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 8 });
const compactPercent = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function formatNumberWithUnit(value: unknown, unit: string): string {
  const number = finiteNumber(value);
  return number === null ? EMPTY_VALUE : `${compactNumber.format(number)} ${unit}`;
}

function formatRatio(value: unknown): string {
  const number = finiteNumber(value);
  return number === null ? EMPTY_VALUE : `${compactPercent.format(number * 100)}%`;
}

function formatCompactNumber(value: unknown): string {
  const number = finiteNumber(value);
  return number === null ? EMPTY_VALUE : compactNumber.format(number);
}

function formatEstimator(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) return EMPTY_VALUE;
  const estimator = value.toLowerCase();
  if (estimator === 'ridge') return '岭回归（Ridge）';
  if (estimator === 'ols') return '普通最小二乘（OLS）';
  return value;
}

function formatRawParameter(value: unknown): string {
  if (value === null || value === undefined) return EMPTY_VALUE;
  if (typeof value === 'number') return Number.isFinite(value) ? compactNumber.format(value) : EMPTY_VALUE;
  if (typeof value === 'string') return value || EMPTY_VALUE;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

const OPTIMIZATION_PARAMETER_DEFINITIONS: Record<string, OptimizationParameterDefinition> = {
  window_size: {
    label: '滑动窗口长度（window_size）',
    description: '控制动态区段分析时每个候选窗口包含的采样点数。',
    group: 'data-selection',
    format: value => formatNumberWithUnit(value, '个采样点'),
  },
  max_segments: {
    label: '最大优选区段数（max_segments）',
    description: '限制最多选取多少个高价值动态区段参与建模。',
    group: 'data-selection',
    format: value => formatNumberWithUnit(value, '个区段'),
  },
  max_anomaly_ratio: {
    label: '最大异常比例（max_anomaly_ratio）',
    description: '异常数据超过该比例的候选区段将被质量门控过滤。',
    group: 'data-selection',
    format: formatRatio,
  },
  max_missing_ratio: {
    label: '最大缺失比例（max_missing_ratio）',
    description: '缺失数据超过该比例的候选区段将被质量门控过滤。',
    group: 'data-selection',
    format: formatRatio,
  },
  min_input_activity_ratio: {
    label: '最小输入活跃比例（min_input_activity_ratio）',
    description: '保证入选区段具有足够输入变化，避免大量稳态数据进入建模。',
    group: 'data-selection',
    format: formatRatio,
  },
  nk: {
    label: '输入时滞阶数（nk）',
    description: '表示输入作用于输出前需要延迟的采样周期数。',
    group: 'arx-model',
    format: value => formatNumberWithUnit(value, '阶'),
  },
  na: {
    label: '输出阶数（na）',
    description: '决定模型参考多少阶历史输出描述系统自身动态。',
    group: 'arx-model',
    format: value => formatNumberWithUnit(value, '阶'),
  },
  nb: {
    label: '输入阶数（nb）',
    description: '决定模型使用多少阶历史输入描述输入对输出的动态影响。',
    group: 'arx-model',
    format: value => formatNumberWithUnit(value, '阶'),
  },
  estimator: {
    label: '参数估计方法（estimator）',
    description: '决定采用何种方法估计 ARX 模型参数。',
    group: 'arx-model',
    format: formatEstimator,
  },
  ridge_alpha: {
    label: '岭回归正则强度（ridge_alpha）',
    description: '控制 Ridge 对模型参数的正则化程度，降低参数估计过度波动。',
    group: 'arx-model',
    format: formatCompactNumber,
  },
};

const OPTIMIZATION_GROUP_LABELS: Record<OptimizationParameterGroupKey, string> = {
  'data-selection': '数据优选参数',
  'arx-model': 'ARX 模型参数',
  other: '其他参数',
};

function isCompositeObjective(payload: Record<string, any>): boolean {
  return payload.objective_semantics?.name === 'composite_identification_score';
}

function formatObjectiveValue(value: unknown): string {
  const number = finiteNumber(value);
  return number === null ? EMPTY_VALUE : number.toFixed(3);
}

function optimizationParameterGroups(art: ArtifactDef): OptimizationParameterGroup[] {
  const params = art.payload.best_params;
  if (!params || typeof params !== 'object' || Array.isArray(params)) return [];

  const grouped: Record<OptimizationParameterGroupKey, OptimizationParameterDisplay[]> = {
    'data-selection': [],
    'arx-model': [],
    other: [],
  };

  Object.entries(params).forEach(([key, value]) => {
    const definition = OPTIMIZATION_PARAMETER_DEFINITIONS[key];
    const group = definition?.group ?? 'other';
    grouped[group].push({
      key,
      label: definition?.label ?? key,
      description: definition?.description ?? '',
      value: definition ? definition.format(value) : formatRawParameter(value),
    });
  });

  return (Object.keys(OPTIMIZATION_GROUP_LABELS) as OptimizationParameterGroupKey[])
    .filter(key => grouped[key].length > 0)
    .map(key => ({ key, label: OPTIMIZATION_GROUP_LABELS[key], parameters: grouped[key] }));
}
</script>

<style scoped>
.aw-lag-note { margin: 0 0 10px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }
.aw-lag-details summary { margin: 8px 0; color: var(--accent-dark); font-size: 12px; cursor: pointer; }
.aw-lag-delivery { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; padding: 16px; border: 1px solid var(--accent-border); border-radius: 8px; background: var(--surface-1); }
.aw-lag-delivery .aw-lag-note { margin: 0; }
.aw-lag-delivery code { max-width: 100%; overflow-wrap: anywhere; font-size: 12px; color: var(--text-muted); }
.aw-lag-download { min-height: 38px; max-width: 100%; padding: 9px 16px; gap: 8px; border-radius: var(--radius-sm); background: var(--accent); border-color: var(--accent); color: #fff; font-family: var(--font-sans); font-weight: 600; text-decoration: none; transition: background-color 160ms, border-color 160ms, box-shadow 160ms, transform 160ms; }
.aw-lag-download :deep(svg) { width: 16px; height: 16px; margin-right: 6px; flex-shrink: 0; }
.aw-lag-download:hover { background: var(--accent-hover); border-color: var(--accent-hover); color: #fff; box-shadow: 0 3px 8px rgba(66, 99, 64, 0.18); }
.aw-lag-download:active { transform: translateY(1px); }
.aw-lag-download:focus-visible { outline: 2px solid var(--border-focus); outline-offset: 3px; }

.artifact-workbench {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #FFFFFF;
  border-left: 1px solid #E5E5E8;
  overflow: hidden;
}

/* Header */
.aw-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  height: 48px;
  border-bottom: 1px solid #ECECED;
  background: #FAFAFA;
  flex-shrink: 0;
}

.aw-header__title {
  font-family: var(--font-sans);
  font-size: 12px;
  color: #426340;
  letter-spacing: normal;
  font-weight: 600;
}

.aw-data-actions { display: flex; gap: 8px; padding: 9px 12px; border-bottom: 1px solid #ECECED; background: #FFFFFF; }
.aw-action-btn { flex-shrink: 0; padding: 6px 10px; border: 1px solid var(--border-default); border-radius: 6px; background: #FFFFFF; color: var(--accent-dark); font-family: var(--font-sans); font-size: 11px; line-height: 1.3; text-decoration: none; white-space: nowrap; cursor: pointer; }
.aw-action-btn:disabled { cursor: wait; opacity: .55; }
.aw-export-notice { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 8px 12px; border-bottom: 1px solid #DDE8D9; background: #F3F8F1; color: #426340; font-size: 11px; }
.aw-export-notice.is-error { border-color: #F0D7D4; background: #FFF5F4; color: #9B3F36; }
.aw-export-artifact h3 { margin: 0 0 14px; font-size: 16px; }
.aw-export-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.aw-export-metrics span { padding: 10px; border: 1px solid var(--border-default); border-radius: 7px; color: var(--text-tertiary); font-size: 10px; }
.aw-export-metrics strong { display: block; margin-top: 4px; color: var(--text-primary); font-size: 17px; }
.aw-notice-downloads { flex-basis: 100%; }
.aw-export-downloads { margin-top: 14px; }

.aw-header__right {
  display: flex;
  gap: 4px;
}

.aw-icon-btn {
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  color: #8E8E93;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
}

.aw-icon-btn:hover {
  background: #EFEFF1;
  color: #171717;
}

/* Tabs */
.aw-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px;
  overflow-x: auto;
  flex-shrink: 0;
  border-bottom: 1px solid #ECECED;
  background: #F5F5F7;
}

.aw-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: none;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #666666;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.aw-tab:hover {
  background: #EFEFF1;
  color: #171717;
}

.aw-tab.is-active {
  background: #FFFFFF;
  border-color: #E5E5E8;
  color: #426340;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

/* Content */
.aw-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.aw-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.aw-section__label {
  font-family: var(--font-sans);
  font-size: 11px;
  color: #8E8E93;
  letter-spacing: normal;
  text-transform: none;
  font-weight: 600;
}

/* KV List */
.aw-kv-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.aw-kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #F8F9F7;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  font-size: 13px;
}

.aw-kv__key {
  color: #666666;
}

.aw-kv__val {
  color: #171717;
  font-weight: 600;
}

.aw-optimization-objective-note,
.aw-optimization-intro,
.aw-optimization-param__description {
  margin: 0;
  font-family: var(--font-sans);
  font-size: 11px;
  line-height: 1.5;
}

.aw-optimization-objective-note {
  margin-top: -8px;
  color: #8E8E93;
}

.aw-optimization-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.aw-optimization-group + .aw-optimization-group {
  margin-top: 4px;
}

.aw-optimization-group__title {
  padding-bottom: 5px;
  border-bottom: 1px solid #ECECED;
  color: #666666;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
}

.aw-optimization-param {
  align-items: stretch;
  flex-direction: column;
  gap: 3px;
}

.aw-optimization-param__main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.aw-optimization-param__description {
  padding-right: 12px;
}

.aw-optimization-intro,
.aw-optimization-param__description {
  font-weight: 500;
}

.aw-optimization-param .aw-kv__key {
  font-weight: 600;
}

.aw-section[data-test="optimization-parameters"] > .aw-section__label,
.aw-optimization-intro,
.aw-optimization-group__title,
.aw-optimization-param .aw-kv__key,
.aw-optimization-param .aw-kv__val,
.aw-optimization-param__description {
  color: var(--text-primary);
}

/* Tag list */
.aw-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.aw-tag {
  font-family: var(--font-sans);
  letter-spacing: normal;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 4px;
  font-weight: 500;
}

.aw-tag.kept {
  color: var(--success);
  background: var(--success-soft);
  border: 1px solid var(--color-success-border);
}

.aw-tag.removed {
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid var(--color-error-border);
}

/* JSON fallback */
.aw-json {
  font-size: 11px;
  color: #171717;
  background: #F8F9F7;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}

/* Empty */
.aw-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #8E8E93;
  padding: 32px;
  text-align: center;
}

.aw-empty p {
  font-size: 13px;
  color: #8E8E93;
  line-height: 1.5;
  max-width: 240px;
}
</style>
