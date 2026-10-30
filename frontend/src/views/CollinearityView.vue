<template>
  <div class="page-container collinearity-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge">STAGE 05 · COLLINEARITY & FEATURE REDUCTION</div>
      <div class="stage-links">
        <span class="stage-link" @click="$router.push('/preprocessing/cleaning')">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/segmentation')">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/delay')">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link active">05 VIF 降维</span>
      </div>
    </div>

    <!-- Header with Quick Action -->
    <div class="page-header">
      <span class="page-eyebrow">PEARSON CORRELATION & VARIANCE INFLATION FACTOR</span>
      <h2>共线性检测与冗余特征剔除面板</h2>
      <p class="subtitle">计算 Pearson 相关系数矩阵、方差膨胀因子 VIF 与矩阵条件数；由工程师安全确认后派生新的特征选择版本</p>
    </div>

    <div class="industrial-card analysis-context-card">
      <div class="analysis-context-header">
        <div>
          <span class="context-eyebrow">ANALYSIS CONTEXT</span>
          <h3>分析上下文</h3>
        </div>
        <span class="context-note">先选择数据集，再选择后端确认的时滞补偿版本</span>
      </div>

      <div class="analysis-context-grid">
        <div class="context-field">
          <label>数据集</label>
          <el-select
            v-model="selectedDatasetId"
            data-test="dataset-select"
            filterable
            :loading="loadingDatasets"
            placeholder="按名称选择数据集"
            style="width: 100%"
            @change="handleDatasetChange"
          >
            <el-option
              v-for="dataset in datasetOptions"
              :key="dataset.id"
              :label="dataset.name"
              :value="dataset.id"
            >
              <div class="selector-option">
                <span class="selector-option-name">{{ dataset.name }}</span>
                <span class="selector-option-meta">
                  {{ dataset.row_count }} rows · {{ dataset.col_count ?? dataset.column_count ?? 0 }} cols ·
                  <span class="font-mono">{{ shortId(dataset.id) }}</span>
                </span>
              </div>
            </el-option>
          </el-select>
        </div>

        <div class="context-field">
          <label>时滞补偿版本</label>
          <VersionLineagePicker
            data-test="source-select"
            :dataset-name="selectedDataset?.name ?? ''"
            :versions="versionNodes"
            :selected-version-id="selectedSourceVersionId"
            :loading="loadingSources"
            context-label="时滞补偿版本可用于共线性诊断"
            eligible-label="可用于共线性诊断"
            empty-state-text="该数据集暂无可用于共线性分析的时滞补偿版本。"
            empty-state-hint="请先完成时滞补偿后再进行共线性分析。"
            placeholder="选择时滞补偿版本"
            :is-eligible="isCollinearityEligibleVersion"
            :disabled-reason="collinearityDisabledReason"
            @select="handleSourceChange"
          />
        </div>
      </div>

      <el-alert
        v-if="datasetError || sourceError"
        :title="datasetError || sourceError"
        type="error"
        :closable="false"
        show-icon
        class="context-alert"
      />
      <div v-else-if="selectedSource" class="selected-source-detail">
        <span class="source-status" :class="selectedSource.collinearity_status">
          {{ sourceStatusLabel(selectedSource.collinearity_status) }}
        </span>
        <span>{{ sourceStatusDescription(selectedSource.collinearity_status) }}</span>
        <span class="selected-source-id font-mono">UUID · {{ shortVersionId(selectedSource.version_id) }}</span>
      </div>
      <div v-else-if="!loadingDatasets && !selectedDatasetId" class="context-prompt">
        请选择数据集以读取可用于共线性分析的时滞补偿版本。
      </div>
    </div>

    <!-- FORMAT 4: Top Slider Controller Strip (顶部横向控制条) -->
    <div class="industrial-card collin-control-strip">
      <div class="cs-row">
        <div class="cs-item">
          <label>正式输入变量 (u)</label>
          <div class="input-column-chips" data-test="input-columns">
            <span v-for="column in form.input_columns" :key="column" class="input-column-chip">
              {{ column }}
            </span>
            <span v-if="!form.input_columns.length" class="input-column-placeholder">选择时滞补偿版本后自动读取</span>
          </div>
        </div>
        <div class="cs-item">
          <label>相关报警阈值</label>
          <el-input-number v-model="form.correlation_threshold" :min="0.5" :max="1" :step="0.01" :precision="2" size="small" />
        </div>
        <div class="cs-item">
          <label>VIF 膨胀阈值</label>
          <el-input-number v-model="form.vif_threshold" :min="1.5" :max="100" :step="0.5" size="small" />
        </div>
        <div class="cs-actions">
          <el-button
            data-test="analyze-button"
            type="primary"
            size="small"
            :loading="loading || restoringResult"
            :disabled="analyzeDisabled"
            icon="Search"
            @click="handleAnalyze"
          >
            执行诊断分析
          </el-button>
        </div>
      </div>
    </div>

    <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
      <template #title>诊断失败：{{ errorMessage }}</template>
    </el-alert>

    <div v-if="hasInputDiagnostics" class="industrial-card qualification-card" data-test="input-qualification">
      <div>
        <span class="context-eyebrow">INPUT QUALIFICATION</span>
        <h3>输入资格判定</h3>
      </div>
      <div class="qualification-list">
        <div v-for="diagnostic in inputDiagnostics" :key="diagnostic.column" class="qualification-item">
          <span class="qualification-column">{{ diagnostic.column }}</span>
          <span class="qualification-status" :class="diagnostic.status">{{ qualificationStatusLabel(diagnostic.status) }}</span>
          <span class="qualification-reason">{{ diagnostic.reason }}</span>
        </div>
      </div>
    </div>
    <el-alert
      v-else-if="legacyResult"
      data-test="legacy-qualification-warning"
      title="该历史分析结果缺少输入资格诊断信息，建议重新执行分析以获得完整诊断。"
      type="warning"
      :closable="false"
      show-icon
      class="legacy-qualification-warning"
    />

    <!-- FORMAT 4: 3-Panel Tri-View Studio Grid (三联视窗工作台) -->
    <div class="collin-tri-grid" v-if="result">
      <!-- Panel A: Correlation Heatmap Matrix -->
      <div class="industrial-card tri-panel">
        <div class="industrial-card-header correlation-card-header">
          <div class="industrial-card-title">
            <el-icon><Grid /></el-icon>
            <span data-test="correlation-title">{{ correlationMatrixTitle }}</span>
          </div>
          <div class="correlation-header-actions">
            <span class="card-tag">HEATMAP</span>
            <div class="correlation-mode-switch" role="group" aria-label="相关矩阵显示方式">
              <button
                type="button"
                class="correlation-mode-button"
                :class="{ 'is-active': correlationMode === 'pearson' }"
                :aria-pressed="correlationMode === 'pearson'"
                data-test="correlation-mode-pearson"
                title="Pearson：线性相关"
                @click="correlationMode = 'pearson'"
              >
                Pearson
              </button>
              <button
                type="button"
                class="correlation-mode-button"
                :class="{ 'is-active': correlationMode === 'spearman' }"
                :aria-pressed="correlationMode === 'spearman'"
                data-test="correlation-mode-spearman"
                title="Spearman：秩相关"
                @click="correlationMode = 'spearman'"
              >
                Spearman
              </button>
            </div>
          </div>
        </div>
        <div v-if="!displayedCorrelationMatrix" class="matrix-unavailable" data-test="matrix-unavailable">
          <strong>N/A</strong>
          <span>当前历史结果没有可用的 {{ correlationMatrixTitle }} 数据。</span>
        </div>
        <ChartContainer
          v-else
          data-test="correlation-chart"
          :options="heatmapOptions"
          height="340px"
        />
      </div>

      <!-- Panel B: VIF Bar Chart Radar -->
      <div class="industrial-card tri-panel">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Histogram /></el-icon>
            <span>各特征 VIF 膨胀因子</span>
          </div>
          <span class="card-tag localized-card-tag">
            阈值: <span>{{ form.vif_threshold || 10 }}</span>
          </span>
        </div>
        <ChartContainer data-test="vif-chart" :options="vifOptions" height="340px" />
      </div>

      <!-- Panel C: Feature Decision Inspector & Human Approval Board -->
      <div class="industrial-card tri-panel decision-panel">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><TrendCharts /></el-icon>
            <span>特征决策检查</span>
          </div>
          <el-tag :type="conditionSeverity" effect="light" size="small">
            Cond: {{ formatDecisionMetric(result.condition_number) }}
          </el-tag>
        </div>

        <div class="decision-content">
          <div class="stat-mini-box">
            <div>
              <span class="s-l">总特征数</span>
              <strong class="s-v">{{ resultVariables.length }}</strong>
            </div>
            <div class="s-div"></div>
            <div>
              <span class="s-l">有效特征</span>
              <strong class="s-v text-cyan">{{ analyzableInputCount }}</strong>
            </div>
            <div class="s-div"></div>
            <div>
              <span class="s-l">低方差 / 建议剔除</span>
              <strong class="s-v text-danger">{{ dropCount }}</strong>
            </div>
          </div>

          <div v-if="correlatedGroups.length" class="correlated-list">
            <div class="cl-title">强相关共线性通道组：</div>
            <div class="cl-chips">
              <el-tag
              v-for="(group, index) in correlatedGroups"
                :key="index"
                type="warning"
                effect="plain"
                size="small"
              >
                {{ group.join(" ↔ ") }}
              </el-tag>
            </div>
          </div>

          <div class="decision-table" data-test="feature-decision-table">
            <div class="decision-table-header" aria-hidden="true">
              <span>变量</span>
              <span>数据资格</span>
              <span>VIF</span>
              <span>系统建议</span>
              <span>决策依据</span>
              <span></span>
            </div>
            <div
              v-for="row in decisionRows"
              :key="row.variable"
              class="decision-row"
              :data-test="`decision-row-${row.variable}`"
            >
              <div class="decision-row-summary">
                <strong class="decision-variable">{{ row.variable }}</strong>
                <span>{{ decisionQualificationLabel(row.diagnostic?.status) }}</span>
                <span>{{ formatVifValue(row.vif) }}</span>
                <span
                  class="decision-action"
                  :class="recommendationActionClass(row.recommendation?.action)"
                  :data-test="`decision-action-${row.variable}`"
                >
                  {{ recommendationActionLabel(row.recommendation?.action) }}
                </span>
                <span class="decision-reason" :data-test="`decision-reason-${row.variable}`">
                  {{ recommendationReason(row.recommendation) }}
                </span>
                <button
                  type="button"
                  class="decision-expand-button"
                  :aria-expanded="isDecisionExpanded(row.variable)"
                  :data-test="`decision-toggle-${row.variable}`"
                  @click="toggleDecisionDetails(row.variable)"
                >
                  {{ isDecisionExpanded(row.variable) ? '收起依据' : '查看依据' }}
                </button>
              </div>

              <div
                v-if="isDecisionExpanded(row.variable)"
                class="decision-evidence"
                :data-test="`decision-details-${row.variable}`"
              >
                <dl class="decision-evidence-list">
                  <div><dt>数据资格</dt><dd>{{ decisionQualificationLabel(row.diagnostic?.status) }}</dd></div>
                  <div><dt>资格原因</dt><dd>{{ qualificationReason(row.diagnostic) }}</dd></div>
                  <div><dt>方差</dt><dd>{{ formatDecisionMetric(row.diagnostic?.variance) }}</dd></div>
                  <div><dt>VIF</dt><dd>{{ formatVifValue(row.vif) }}</dd></div>
                  <div><dt>全局诊断</dt><dd>Condition Number = {{ formatDecisionMetric(result.condition_number) }}</dd></div>
                  <div><dt>系统建议</dt><dd>{{ recommendationActionLabel(row.recommendation?.action) }}</dd></div>
                  <div><dt>决策原因</dt><dd>{{ recommendationReason(row.recommendation) }}</dd></div>
                  <div><dt>相关变量</dt><dd>{{ relatedVariablesLabel(row.recommendation) }}</dd></div>
                </dl>

                <div class="correlation-evidence-grid">
                  <section :data-test="`decision-pearson-${row.variable}`">
                    <h5>Pearson</h5>
                    <div v-for="entry in correlationEvidence(row.variable, result.matrix)" :key="entry.variable" class="correlation-evidence-row">
                      <span>{{ row.variable }} ↔ {{ entry.variable }}</span>
                      <strong>{{ formatCorrelationValue(entry.value) }}</strong>
                    </div>
                    <span v-if="!correlationEvidence(row.variable, result.matrix).length" class="evidence-empty">无其他正式输入</span>
                  </section>
                  <section :data-test="`decision-spearman-${row.variable}`">
                    <h5>Spearman</h5>
                    <div v-for="entry in correlationEvidence(row.variable, result.spearman_matrix)" :key="entry.variable" class="correlation-evidence-row">
                      <span>{{ row.variable }} ↔ {{ entry.variable }}</span>
                      <strong>{{ formatCorrelationValue(entry.value) }}</strong>
                    </div>
                    <span v-if="!correlationEvidence(row.variable, result.spearman_matrix).length" class="evidence-empty">无其他正式输入</span>
                  </section>
                </div>

                <p
                  v-if="isLowVarianceDrop(row)"
                  class="qualification-explanation"
                  :data-test="`decision-qualification-note-${row.variable}`"
                >
                  该变量因低方差 / 信息不足被建议剔除，并非由于检测到严重共线性。
                </p>
              </div>
            </div>
            <div v-if="!decisionRows.length" class="decision-empty">当前结果没有可展示的正式输入变量。</div>
          </div>

          <div v-if="!recommendations.length" class="decision-empty" data-test="decision-recommendations-empty">
            当前结果未提供特征决策建议。
          </div>
          <div v-else-if="!dropCandidates.length" class="no-drops">
            当前系统建议中没有需要剔除的变量。
          </div>

          <div class="decision-action-strip" v-if="dropCandidates.length">
            <div class="apply-decision-summary" data-test="feature-apply-summary">
              <strong>本次建议剔除</strong>
              <div v-for="item in dropCandidates" :key="item.variable" class="apply-decision-item">
                <span>{{ item.variable }}</span>
                <span>{{ recommendationReason(item) }}</span>
              </div>
            </div>
            <el-button data-test="feature-apply-button" type="danger" size="default" :loading="applying" @click="handleApply" style="width: 100%">
              确认剔除并生成特征选择版本
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty Placeholder -->
    <div class="industrial-card collin-empty-card" v-else>
      <div class="empty-icon">
        <el-icon><Share /></el-icon>
      </div>
      <h3>{{ emptyStateTitle }}</h3>
      <p>{{ emptyStateDescription }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Grid, Histogram, Share, TrendCharts } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import VersionLineagePicker from "../components/versioning/VersionLineagePicker.vue";
import {
  applyFeatureSelection,
  calculateCollinearity,
  getLatestCollinearity,
} from "../api/preprocessing";
import {
  getCollinearitySourceVersions,
  getDatasetDetail,
  getDatasetVersions,
  listDatasets,
} from "../api/datasets";
import type {
  CollinearityRequest,
  CollinearityResponse,
  CollinearitySourceStatus,
  CollinearitySourceVersionItem,
  DatasetItem,
  DatasetVersionNode,
  InputDiagnostic,
  VariableRecommendation,
} from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage, ElMessageBox } from "element-plus";
import { useDatasetStore } from "../stores/datasetStore";
import { shortVersionId } from "../utils/versionOperation";

const loading = ref(false);
const applying = ref(false);
const loadingDatasets = ref(false);
const loadingSources = ref(false);
const restoringResult = ref(false);
const result = ref<CollinearityResponse | null>(null);
const errorMessage = ref("");
const datasetError = ref("");
const sourceError = ref("");
type CorrelationMode = "pearson" | "spearman";
const correlationMode = ref<CorrelationMode>("pearson");
const datasetStore = useDatasetStore();
const datasetOptions = ref<DatasetItem[]>([]);
const selectedDatasetId = ref<string | null>(null);
const collinearitySources = ref<CollinearitySourceVersionItem[]>([]);
const versionNodes = ref<DatasetVersionNode[]>([]);
const selectedSourceVersionId = ref<string | null>(null);
const expandedDecisionVariables = ref<Set<string>>(new Set());
const clearDecisionExpansion = () => {
  expandedDecisionVariables.value = new Set();
};
const rememberedSourceByDataset = new Map<string, string>();
let datasetListRequest = 0;
let datasetContextRequest = 0;
let sourceListRequest = 0;
let rehydrationRequest = 0;
let analysisRequest = 0;

const form = reactive<CollinearityRequest>({
  version_id: "",
  input_columns: [],
  correlation_threshold: 0.85,
  vif_threshold: 10,
});

const selectedSource = computed(
  () =>
    collinearitySources.value.find(
      (source) => source.version_id === selectedSourceVersionId.value
    ) ?? null
);
const selectedDataset = computed(
  () => datasetOptions.value.find((dataset) => dataset.id === selectedDatasetId.value) ?? null
);

const isCollinearityEligibleVersion = (version: DatasetVersionNode) =>
  version.tool === "preprocessing.lag_compensation" &&
  collinearitySources.value.some((source) => source.version_id === version.id);

const collinearityDisabledReason = (version: DatasetVersionNode) => {
  if (version.tool === "simulation_generate" || version.tool === "raw_upload") {
    return "需先完成清洗与时滞补偿";
  }
  if (version.tool === "preprocessing.clean") return "需先完成时滞补偿";
  if (version.tool === "preprocessing.feature_selection") return "已进入后续特征版本";
  if (version.tool === "preprocessing.lag_compensation") {
    return "该版本尚未进入可用共线性源列表";
  }
  return "该处理阶段不符合共线性诊断源要求";
};

const sourceInputColumns = (source: CollinearitySourceVersionItem | null) =>
  Array.isArray(source?.input_columns) ? source.input_columns : [];

const resultVariables = computed(() =>
  Array.isArray(result.value?.variables) ? result.value.variables : []
);
const inputDiagnostics = computed(() =>
  Array.isArray(result.value?.input_diagnostics) ? result.value.input_diagnostics : []
);
const hasInputDiagnostics = computed(
  () =>
    resultVariables.value.length > 0 &&
    inputDiagnostics.value.length === resultVariables.value.length
);
const legacyResult = computed(() => result.value !== null && !hasInputDiagnostics.value);
const correlatedGroups = computed(() =>
  Array.isArray(result.value?.correlated_groups) ? result.value.correlated_groups : []
);
const recommendations = computed(() =>
  Array.isArray(result.value?.recommendations) ? result.value.recommendations : []
);
const vifScores = computed<Record<string, number | null>>(() =>
  result.value?.vif_scores && typeof result.value.vif_scores === "object"
    ? result.value.vif_scores
    : {}
);
type DecisionRow = {
  variable: string;
  diagnostic: InputDiagnostic | null;
  recommendation: VariableRecommendation | null;
  vif: number | null | undefined;
};
const decisionVariables = computed(() => {
  const formalInputs = form.input_columns.length ? form.input_columns : resultVariables.value;
  return [...new Set(formalInputs.filter((variable) => typeof variable === "string" && variable.length > 0))];
});
const decisionRows = computed<DecisionRow[]>(() =>
  decisionVariables.value.map((variable) => ({
    variable,
    diagnostic: inputDiagnostics.value.find((item) => item.column === variable) ?? null,
    recommendation: recommendations.value.find((item) => item.variable === variable) ?? null,
    vif: vifScores.value[variable],
  }))
);

const hasValidLagCompensationSource = computed(
  () =>
    collinearitySources.value.length > 0 &&
    selectedSource.value?.operation_name === "preprocessing.lag_compensation"
);

const analyzeDisabled = computed(
  () =>
    !selectedDatasetId.value ||
    collinearitySources.value.length === 0 ||
    !hasValidLagCompensationSource.value ||
    loadingDatasets.value ||
    loadingSources.value ||
    restoringResult.value ||
    loading.value
);

const sourceStatusLabel = (status: CollinearitySourceStatus) =>
  ({
    complete: "已完成，可恢复",
    not_analyzed: "尚未分析",
    unrehydratable: "历史结果不可恢复",
  })[status];

const sourceStatusDescription = (status: CollinearitySourceStatus) =>
  ({
    complete: "正在使用该版本已持久化的完整共线性分析结果。",
    not_analyzed: "该时滞补偿版本尚未进行共线性分析。",
    unrehydratable: "该版本存在历史分析记录，但结果无法按当前格式完整恢复，可重新执行分析。",
  })[status];

const shortId = (value: string) => `${value.slice(0, 8)}…`;

const emptyStateTitle = computed(() => {
  if (loadingDatasets.value) return "正在读取数据集…";
  if (!selectedDatasetId.value) return "请先选择数据集";
  if (loadingSources.value) return "正在读取时滞补偿版本…";
  if (!collinearitySources.value.length) return "暂无时滞补偿版本";
  if (restoringResult.value) return "正在恢复历史共线性结果…";
  if (selectedSource.value) return sourceStatusLabel(selectedSource.value.collinearity_status);
  return "请选择时滞补偿版本";
});

const emptyStateDescription = computed(() => {
  if (!selectedDatasetId.value) return "请在分析上下文中按名称选择数据集。";
  if (!collinearitySources.value.length && !loadingSources.value) {
    return "该数据集暂无可用于共线性分析的时滞补偿版本，请先完成时滞补偿。";
  }
  if (selectedSource.value) return sourceStatusDescription(selectedSource.value.collinearity_status);
  return "选择后端确认的 Lag Compensation Source 后，可恢复历史结果或手动执行诊断。";
});

const invalidateSourceRequests = () => {
  sourceListRequest += 1;
  rehydrationRequest += 1;
  analysisRequest += 1;
  loadingSources.value = false;
  restoringResult.value = false;
  loading.value = false;
};

const clearSourceContext = () => {
  invalidateSourceRequests();
  clearDecisionExpansion();
  correlationMode.value = "pearson";
  collinearitySources.value = [];
  versionNodes.value = [];
  selectedSourceVersionId.value = null;
  form.version_id = "";
  form.dataset_id = null;
  form.input_columns = [];
  result.value = null;
  errorMessage.value = "";
  sourceError.value = "";
};

const hydratePersistedResult = async (versionId: string, datasetId: string) => {
  const request = ++rehydrationRequest;
  clearDecisionExpansion();
  restoringResult.value = true;
  errorMessage.value = "";
  result.value = null;
  try {
    const persisted = await getLatestCollinearity({
      version_id: versionId,
      dataset_id: datasetId,
    });
    if (
      request !== rehydrationRequest ||
      selectedDatasetId.value !== datasetId ||
      selectedSourceVersionId.value !== versionId
    ) {
      return;
    }
    result.value = persisted;
    form.version_id = versionId;
    form.dataset_id = datasetId;
    const persistedVariables = Array.isArray(persisted.variables) ? persisted.variables : [];
    if (!form.input_columns.length && persistedVariables.length) {
      form.input_columns = [...persistedVariables];
    }
  } catch (error) {
    if (request !== rehydrationRequest) return;
    result.value = null;
    errorMessage.value =
      error instanceof ApiError &&
      (error.code === "COLLINEARITY_RESULT_NOT_FOUND" ||
        error.code === "COLLINEARITY_RESULT_UNAVAILABLE")
        ? "历史结果状态已变化，无法恢复该版本的完整共线性结果；请重新分析或刷新版本状态。"
        : error instanceof ApiError
          ? error.message
          : String(error);
  } finally {
    if (request === rehydrationRequest) restoringResult.value = false;
  }
};

const selectCollinearitySource = async (versionId: string | null, datasetId: string) => {
  const source =
    collinearitySources.value.find((item) => item.version_id === versionId) ?? null;
  rehydrationRequest += 1;
  analysisRequest += 1;
  restoringResult.value = false;
  loading.value = false;
  clearDecisionExpansion();
  correlationMode.value = "pearson";
  result.value = null;
  errorMessage.value = "";
  selectedSourceVersionId.value = source?.version_id ?? null;
  form.version_id = source?.version_id ?? "";
  form.dataset_id = datasetId;
  const sourceInputs = sourceInputColumns(source);
  if (sourceInputs.length) {
    form.input_columns = [...sourceInputs];
  }

  if (source?.collinearity_status === "complete") {
    await hydratePersistedResult(source.version_id, datasetId);
  }
};

const handleSourceChange = (versionId: string) => {
  const datasetId = selectedDatasetId.value;
  if (!datasetId) return;
  rememberedSourceByDataset.set(datasetId, versionId);
  void selectCollinearitySource(versionId, datasetId);
};

const chooseDefaultCollinearitySource = (
  datasetId: string,
  activeVersionId: string | undefined,
  nodes: DatasetVersionNode[]
) => {
  const eligible = nodes.filter(isCollinearityEligibleVersion);
  const rememberedId = rememberedSourceByDataset.get(datasetId);
  return eligible.find((version) => version.id === rememberedId)?.id
    ?? eligible.find((version) => version.id === activeVersionId)?.id
    ?? [...eligible].sort(
      (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
    )[0]?.id
    ?? null;
};

const loadDatasetContext = async (
  datasetId: string,
  options: {
    preferredSourceVersionId?: string;
    preserveExistingContext?: boolean;
    refreshFailureMessage?: string;
  } = {}
) => {
  const contextRequest = ++datasetContextRequest;
  if (options.preserveExistingContext) {
    sourceListRequest += 1;
    sourceError.value = "";
  } else {
    clearSourceContext();
  }
  form.dataset_id = datasetId;
  loadingSources.value = true;
  try {
    const detail = await getDatasetDetail(datasetId);
    if (
      contextRequest !== datasetContextRequest ||
      selectedDatasetId.value !== datasetId
    ) {
      return;
    }
    datasetStore.setActiveDataset(detail);
    form.input_columns = [...detail.input_columns];

    const sourceRequest = ++sourceListRequest;
    const [data, versions] = await Promise.all([
      getCollinearitySourceVersions(datasetId),
      getDatasetVersions(datasetId),
    ]);
    if (
      contextRequest !== datasetContextRequest ||
      sourceRequest !== sourceListRequest ||
      selectedDatasetId.value !== datasetId
    ) {
      return;
    }
    collinearitySources.value = data.sources;
    versionNodes.value = versions.nodes;
    loadingSources.value = false;
    const preferredSourceVersionId = options.preferredSourceVersionId;
    const preferredSource = preferredSourceVersionId &&
      versions.nodes.some(
        (version) =>
          version.id === preferredSourceVersionId && isCollinearityEligibleVersion(version)
      )
      ? data.sources.find((source) => source.version_id === preferredSourceVersionId) ?? null
      : null;
    if (options.preserveExistingContext && preferredSource) {
      selectedSourceVersionId.value = preferredSource.version_id;
      form.version_id = preferredSource.version_id;
      form.dataset_id = datasetId;
      const sourceInputs = sourceInputColumns(preferredSource);
      if (sourceInputs.length) form.input_columns = [...sourceInputs];
    } else {
      const defaultVersionId = preferredSource?.version_id
        ?? chooseDefaultCollinearitySource(
          datasetId,
          detail.version_id || detail.latest_version_id,
          versions.nodes
        );
      await selectCollinearitySource(defaultVersionId, datasetId);
    }
  } catch (error) {
    if (contextRequest !== datasetContextRequest) return;
    const message = error instanceof ApiError ? error.message : String(error);
    sourceError.value = options.refreshFailureMessage
      ? `${options.refreshFailureMessage}：${message}`
      : message;
  } finally {
    if (contextRequest === datasetContextRequest) loadingSources.value = false;
  }
};

const handleDatasetChange = (datasetId: string) => {
  datasetError.value = "";
  if (!datasetId) {
    datasetContextRequest += 1;
    clearSourceContext();
    return;
  }
  void loadDatasetContext(datasetId);
};

const initializeDatasets = async () => {
  const request = ++datasetListRequest;
  loadingDatasets.value = true;
  datasetError.value = "";
  try {
    const data = await listDatasets({ page: 1, page_size: 100 });
    if (request !== datasetListRequest) return;
    datasetOptions.value = data.items;
    datasetStore.setDatasetsList(data.items);
    const activeDatasetId = datasetStore.activeDataset?.id ?? null;
    if (activeDatasetId && data.items.some((dataset) => dataset.id === activeDatasetId)) {
      selectedDatasetId.value = activeDatasetId;
      await loadDatasetContext(activeDatasetId);
    }
  } catch (error) {
    if (request !== datasetListRequest) return;
    datasetOptions.value = [];
    selectedDatasetId.value = null;
    datasetError.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (request === datasetListRequest) loadingDatasets.value = false;
  }
};

const refreshSourcesAfterAnalyze = async (
  datasetId: string,
  sourceVersionId: string,
  analyzeRequest: number,
  contextRequest: number
) => {
  const request = ++sourceListRequest;
  loadingSources.value = true;
  try {
    const data = await getCollinearitySourceVersions(datasetId);
    if (
      request !== sourceListRequest ||
      analyzeRequest !== analysisRequest ||
      contextRequest !== datasetContextRequest ||
      selectedDatasetId.value !== datasetId ||
      selectedSourceVersionId.value !== sourceVersionId
    ) {
      return;
    }
    collinearitySources.value = data.sources;
    const refreshedSource = data.sources.find(
      (source) => source.version_id === sourceVersionId
    );
    if (refreshedSource) {
      selectedSourceVersionId.value = refreshedSource.version_id;
      form.version_id = refreshedSource.version_id;
    }
  } catch (error) {
    if (request !== sourceListRequest || analyzeRequest !== analysisRequest) return;
    sourceError.value = `分析已完成，但版本状态刷新失败：${
      error instanceof ApiError ? error.message : String(error)
    }`;
  } finally {
    if (request === sourceListRequest) loadingSources.value = false;
  }
};

const handleAnalyze = async () => {
  rehydrationRequest += 1;
  clearDecisionExpansion();
  restoringResult.value = false;
  errorMessage.value = "";
  sourceError.value = "";
  const source = selectedSource.value;
  const datasetId = selectedDatasetId.value;
  if (!source || !datasetId) {
    errorMessage.value = "请先选择数据集和时滞补偿版本。";
    return;
  }
  const inputColumns = [...form.input_columns];
  if (inputColumns.length < 2) {
    errorMessage.value = "共线性诊断需要至少两个输入变量。";
    return;
  }

  const request = ++analysisRequest;
  const contextRequest = datasetContextRequest;
  form.version_id = source.version_id;
  form.dataset_id = datasetId;
  form.input_columns = inputColumns;
  loading.value = true;
  try {
    const analyzed = await calculateCollinearity({
      ...form,
      version_id: source.version_id,
      dataset_id: datasetId,
      input_columns: inputColumns,
    });
    if (
      request !== analysisRequest ||
      contextRequest !== datasetContextRequest ||
      selectedDatasetId.value !== datasetId ||
      selectedSourceVersionId.value !== source.version_id
    ) {
      return;
    }
    result.value = analyzed;
    source.collinearity_status = "complete";
    source.latest_complete_collinearity_run_id = analyzed.processing_run_id;
    ElMessage.success("共线性诊断完成");
    await refreshSourcesAfterAnalyze(datasetId, source.version_id, request, contextRequest);
  } catch (err) {
    if (request !== analysisRequest) return;
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    if (request === analysisRequest) loading.value = false;
  }
};

onMounted(() => {
  void initializeDatasets();
});

const dropCount = computed(
  () => recommendations.value.filter((item) => item.action === "drop").length
);
const dropCandidates = computed(
  () => recommendations.value.filter((item) => item.action === "drop")
);
const analyzableInputCount = computed(
  () =>
    hasInputDiagnostics.value
      ? inputDiagnostics.value.filter((item) => item.status === "analyzable").length
      : resultVariables.value.length
);

const conditionSeverity = computed(() => {
  const value = result.value?.condition_number;
  if (value === null || value === undefined) return "info";
  if (value >= 100) return "danger";
  if (value >= 30) return "warning";
  return "success";
});

const correlationMatrixTitle = computed(() =>
  correlationMode.value === "pearson"
    ? "Pearson 相关系数矩阵"
    : "Spearman 秩相关系数矩阵"
);

const qualificationStatusLabel = (status: string) =>
  ({
    analyzable: "可分析",
    constant_or_near_constant: "常量 / 近常量 · N/A",
    non_numeric: "非数值",
    missing: "缺失",
  })[status] ?? status;

const isUsableCorrelationMatrix = (
  matrix: Array<Array<number | null>> | null | undefined,
  variables: string[]
): matrix is Array<Array<number | null>> =>
  Array.isArray(matrix) &&
  variables.length > 0 &&
  matrix.length === variables.length &&
  matrix.every(
    (row) =>
      Array.isArray(row) &&
      row.length === variables.length &&
      row.every((value) => value === null || (typeof value === "number" && Number.isFinite(value)))
  );

const displayedCorrelationMatrix = computed<Array<Array<number | null>> | null>(() => {
  if (!result.value) return null;
  const matrix =
    correlationMode.value === "pearson"
      ? result.value.matrix
      : result.value.spearman_matrix;
  return isUsableCorrelationMatrix(matrix, resultVariables.value) ? matrix : null;
});

interface HeatmapTooltipParams {
  value: [number, number] | [number, number, number];
  data?: { unavailable?: boolean; reason?: string };
}

interface VifTooltipParams {
  axisValue?: string | number;
  name?: string;
}

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10000) return value.toExponential(2);
  return value.toFixed(2);
};

const isFiniteVif = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value);

const formatVifValue = (value: number | null | undefined) =>
  isFiniteVif(value) ? formatNumber(value) : "N/A";

const formatDecisionMetric = (value: number | null | undefined) =>
  typeof value === "number" && Number.isFinite(value) ? formatNumber(value) : "N/A";

const formatCorrelationValue = (value: number | null) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "N/A";

const decisionQualificationLabel = (status: InputDiagnostic["status"] | undefined) => {
  if (!status) return "未提供";
  return ({
    analyzable: "可分析",
    constant_or_near_constant: "常量 / 近常量",
    non_numeric: "非数值",
    missing: "缺失",
  } satisfies Record<InputDiagnostic["status"], string>)[status];
};

const recommendationActionLabel = (action: VariableRecommendation["action"] | undefined) => {
  if (!action) return "未提供";
  return ({
    keep: "保留",
    drop: "建议剔除",
    merge: "建议合并",
    review: "建议复核",
  } satisfies Record<VariableRecommendation["action"], string>)[action];
};

const recommendationActionClass = (action: VariableRecommendation["action"] | undefined) =>
  action ?? "missing";

const recommendationReason = (recommendation: VariableRecommendation | null | undefined) => {
  if (!recommendation) return "当前结果未提供该变量的决策建议。";
  const reason = typeof recommendation.reason === "string" ? recommendation.reason.trim() : "";
  return reason || "当前结果未提供详细决策原因";
};

const qualificationReason = (diagnostic: InputDiagnostic | null) => {
  const reason = typeof diagnostic?.reason === "string" ? diagnostic.reason.trim() : "";
  return reason || "当前结果未提供数据资格原因。";
};

const relatedVariablesLabel = (recommendation: VariableRecommendation | null) =>
  recommendation?.related_variables?.length ? recommendation.related_variables.join("、") : "无";

const correlationEvidence = (
  variable: string,
  matrix: Array<Array<number | null>> | null | undefined
) => {
  const variableIndex = resultVariables.value.indexOf(variable);
  return decisionVariables.value
    .filter((otherVariable) => otherVariable !== variable)
    .map((otherVariable) => {
      const otherIndex = resultVariables.value.indexOf(otherVariable);
      const value = variableIndex >= 0 && otherIndex >= 0
        ? matrix?.[variableIndex]?.[otherIndex]
        : null;
      return {
        variable: otherVariable,
        value: typeof value === "number" && Number.isFinite(value) ? value : null,
      };
    });
};

const isLowVarianceDrop = (row: DecisionRow) =>
  row.diagnostic?.status === "constant_or_near_constant" && row.recommendation?.action === "drop";

const isDecisionExpanded = (variable: string) => expandedDecisionVariables.value.has(variable);

const toggleDecisionDetails = (variable: string) => {
  const next = new Set(expandedDecisionVariables.value);
  if (next.has(variable)) next.delete(variable);
  else next.add(variable);
  expandedDecisionVariables.value = next;
};

const heatmapOptions = computed(() => {
  if (!result.value || !displayedCorrelationMatrix.value) return {};
  const names = resultVariables.value;
  const data: Array<[number, number, number]> = [];
  const unavailableData: Array<{ value: [number, number]; unavailable: true; reason: string }> = [];
  displayedCorrelationMatrix.value.forEach((row, i) => {
    row.forEach((value, j) => {
      if (typeof value === "number" && Number.isFinite(value)) {
        data.push([j, i, Number(value.toFixed(3))]);
        return;
      }
      const rowDiagnostic = inputDiagnostics.value.find((item) => item.column === names[i]);
      const columnDiagnostic = inputDiagnostics.value.find((item) => item.column === names[j]);
      unavailableData.push({
        value: [j, i],
        unavailable: true,
        reason: rowDiagnostic?.reason ?? columnDiagnostic?.reason ?? "当前数据条件下无法可靠计算相关系数。",
      });
    });
  });
  const coefficientLabel =
    correlationMode.value === "pearson" ? "Pearson r" : "Spearman correlation";
  return {
    tooltip: {
      formatter: (params: HeatmapTooltipParams) => {
        const [columnIndex, rowIndex] = params.value;
        const prefix = `${names[rowIndex]} × ${names[columnIndex]}<br/>${coefficientLabel}: `;
        return params.data?.unavailable
          ? `${prefix}N/A<br/>${params.data.reason}`
          : `${prefix}${params.value[2]}`;
      },
    },
    grid: { left: "12%", right: "12%", bottom: "12%", top: "6%", containLabel: true },
    xAxis: { type: "category", data: names, splitArea: { show: true } },
    yAxis: { type: "category", data: names, splitArea: { show: true } },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: "vertical",
      right: "2%",
      top: "middle",
      inRange: { color: ["#7995A8", "#FFFFFF", "#B8746E"] },
    },
    series: [
      {
        type: "heatmap",
        data,
        label: { show: names.length <= 8 },
        emphasis: { itemStyle: { shadowBlur: 10 } },
      },
      {
        type: "custom",
        data: unavailableData,
        silent: false,
        renderItem: (params: unknown, api: { value: (index: number) => number; coord: (value: number[]) => number[]; size: (value: number[]) => number[] }) => {
          const point = api.coord([api.value(0), api.value(1)]);
          const size = api.size([1, 1]);
          return {
            type: "group",
            children: [
              {
                type: "rect",
                shape: { x: point[0] - size[0] * 0.46, y: point[1] - size[1] * 0.46, width: size[0] * 0.92, height: size[1] * 0.92 },
                style: { fill: "#EEF1ED" },
              },
              {
                type: "text",
                style: { x: point[0], y: point[1], text: "N/A", textAlign: "center", textVerticalAlign: "middle", fill: "#66716A", fontSize: 11 },
              },
            ],
          };
        },
      },
    ],
  };
});

const vifOptions = computed(() => {
  if (!result.value) return {};
  const names = resultVariables.value;
  const scores = vifScores.value;
  const threshold = form.vif_threshold ?? 10;
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params: VifTooltipParams | VifTooltipParams[]) => {
        const first = Array.isArray(params) ? params[0] : params;
        const name = String(first?.axisValue ?? first?.name ?? "");
        const value = scores[name];
        const detail = isFiniteVif(value)
          ? ""
          : "<br/>当前数据条件下无法可靠计算 VIF";
        return `${name}<br/>VIF: ${formatVifValue(value)}${detail}`;
      },
    },
    grid: { left: "3%", right: "4%", bottom: "10%", top: "8%", containLabel: true },
    xAxis: {
      type: "category",
      data: names,
      axisLabel: {
        formatter: (name: string) =>
          isFiniteVif(scores[name]) ? name : `${name}\nN/A`,
      },
    },
    yAxis: { type: "value", name: "VIF" },
    series: [
      {
        type: "bar",
        data: names.map((name) => {
          const value = scores[name];
          if (!isFiniteVif(value)) {
            return {
              value: null,
              itemStyle: { color: "#A7ADA8" },
              label: {
                show: true,
                position: "top",
                formatter: "N/A",
                color: "#7C847E",
                fontSize: 11,
              },
            };
          }
          return {
            value,
            itemStyle: { color: value >= threshold ? "#B96560" : "#6E9B69" },
            label: { show: false },
          };
        }),
        markLine: {
          symbol: "none",
          data: [{ yAxis: threshold, name: "VIF阈值" }],
          lineStyle: { type: "dashed", color: "#B48A47", width: 1.5 },
        },
      },
    ],
  };
});

const handleApply = async () => {
  const source = selectedSource.value;
  const datasetId = selectedDatasetId.value;
  if (!result.value || !source || !datasetId || !dropCandidates.value.length) return;
  if (result.value.source_version_id !== source.version_id) {
    ElMessage.error("当前共线性结果与所选时滞补偿版本不一致，请重新选择或恢复分析结果。");
    return;
  }
  const names = dropCandidates.value.map((item) => item.variable);
  const confirmationDetails = dropCandidates.value
    .map((item) => `${item.variable}：${recommendationReason(item)}`)
    .join("\n");
  try {
    await ElMessageBox.confirm(
      `将在新的特征选择版本中剔除：\n${confirmationDetails}\n\n源版本不会被覆盖。\n\n确认继续生成新的特征选择版本吗？`,
      "确认变量筛选",
      { type: "warning", confirmButtonText: "确认生成", cancelButtonText: "取消" }
    );
    applying.value = true;
    const applied = await applyFeatureSelection({
      version_id: source.version_id,
      dataset_id: datasetId,
      drop_columns: names,
      user_confirmed: true,
      recommendation_source: "collinearity_analysis",
      evidence: Object.fromEntries(
        dropCandidates.value.map((item) => [
          item.variable,
          {
            reason: item.reason,
            related_variables: item.related_variables,
            vif: vifScores.value[item.variable] ?? null,
            threshold: form.vif_threshold ?? 10,
          },
        ])
      ),
    });
    ElMessage.success(`已创建变量筛选版本：${applied.result_version_id}`);
    rememberedSourceByDataset.set(datasetId, source.version_id);
    await loadDatasetContext(datasetId, {
      preferredSourceVersionId: source.version_id,
      preserveExistingContext: true,
      refreshFailureMessage: "变量筛选版本已创建，但版本血缘刷新失败",
    });
    if (
      selectedDatasetId.value === datasetId &&
      !sourceError.value &&
      !versionNodes.value.some((version) => version.id === applied.result_version_id)
    ) {
      sourceError.value = "变量筛选版本已创建，但新版本尚未出现在版本血缘中，请稍后刷新。";
    }
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err instanceof ApiError ? err.message : String(err));
  } finally {
    applying.value = false;
  }
};
</script>

<style scoped>
.collinearity-view {
  display: flex;
  flex-direction: column;
  gap: var(--section-gap-md);
  min-height: 100%;
}

/* Stage Nav */
.pipeline-stage-nav {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 14px;
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  font-size: 11px;
}

.stage-badge {
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.stage-links {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.stage-link {
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.16s ease;
}

.stage-link:hover {
  color: var(--color-primary);
}

.stage-link.active {
  color: var(--text-primary);
  font-weight: 700;
  cursor: default;
}

.stage-sep {
  color: var(--text-faint);
}

/* Analysis Context */
.analysis-context-card {
  padding: 16px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.analysis-context-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.analysis-context-header h3 {
  margin: 2px 0 0;
  font-size: 15px;
  color: var(--text-primary);
}

.context-eyebrow {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: normal;
  font-family: var(--font-sans);
  color: var(--color-primary);
}

.context-note {
  font-size: 12px;
  color: var(--text-muted);
}

.analysis-context-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.9fr) minmax(320px, 1.4fr);
  gap: 14px;
}

.context-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.context-field label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.selector-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 3px 0;
}

.selector-option-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.selector-option-name {
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selector-option-meta,
.selected-source-id {
  color: var(--text-faint);
  font-size: 10px;
}

.source-status {
  flex: none;
  padding: 2px 7px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.35;
  color: var(--text-muted);
  background: var(--surface-2);
}

.source-status.complete {
  color: var(--success);
  background: var(--success-soft);
  border-color: var(--color-success-border);
}

.source-status.unrehydratable {
  color: #9a6700;
  background: #fff8e6;
  border-color: #ecd7a4;
}

.selected-source-detail,
.context-prompt {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: 12px;
}

.selected-source-id {
  margin-left: auto;
}

.context-alert {
  margin-top: 12px;
}

/* FORMAT 4: Controller Strip */
.collin-control-strip {
  padding: 14px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.cs-row {
  display: grid;
  grid-template-columns: minmax(220px, 1.5fr) minmax(140px, 1fr) minmax(140px, 1fr) auto;
  gap: 14px;
  align-items: flex-end;
}

.cs-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cs-item label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.cs-actions {
  display: flex;
  align-items: flex-end;
}

.input-column-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding: 4px 7px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
}

.input-column-chip {
  padding: 2px 5px;
  border-radius: 4px;
  background: #edf4eb;
  color: var(--text-primary);
  font-size: 11px;
}

.input-column-placeholder {
  color: var(--text-disabled);
  font-family: var(--font-sans);
  font-size: 11px;
}

.cs-actions :deep(.el-button--primary.is-disabled),
.cs-actions :deep(.el-button--primary.is-disabled:hover),
.cs-actions :deep(.el-button--primary.is-disabled:active),
.cs-actions :deep(.el-button--primary:disabled) {
  background: var(--surface-3) !important;
  border-color: var(--border-default) !important;
  color: var(--text-disabled) !important;
  box-shadow: none !important;
  cursor: not-allowed;
  opacity: 0.78;
}

.alert-gap {
  margin-top: 4px;
}

.qualification-card {
  display: grid;
  grid-template-columns: minmax(145px, 0.45fr) minmax(0, 1.55fr);
  gap: 16px;
  margin-top: 16px;
  margin-bottom: 16px;
  padding: 14px 18px;
  background: #ffffff;
}

.qualification-card h3 {
  margin: 4px 0 0;
  font-family: var(--font-sans);
  font-size: 15px;
  color: var(--text-primary);
}

.qualification-list {
  display: grid;
  gap: 6px;
}

.qualification-item {
  display: grid;
  grid-template-columns: 58px minmax(122px, auto) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--surface-1);
}

.qualification-column {
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 700;
}

.qualification-status {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary);
}

.qualification-status.constant_or_near_constant {
  color: #9a6b2f;
}

.qualification-status.non_numeric,
.qualification-status.missing {
  color: var(--color-danger);
}

.qualification-reason {
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 11px;
  line-height: 1.45;
}

/* FORMAT 4: Tri-Grid */
.collin-tri-grid {
  display: grid;
  grid-template-columns: 1.2fr 1.1fr;
  gap: 16px;
}

.tri-panel {
  padding: 18px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
  display: flex;
  flex-direction: column;
}

.card-tag {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.correlation-card-header {
  gap: 12px;
}

.correlation-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.correlation-mode-switch {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--border-default);
  border-radius: 7px;
  background: var(--surface-2);
}

.correlation-mode-button {
  padding: 4px 8px;
  border: 0;
  border-radius: 5px;
  color: var(--text-muted);
  background: transparent;
  cursor: pointer;
  font-size: 10px;
  font-weight: 650;
  line-height: 1.3;
  transition: color 0.16s ease, background-color 0.16s ease, box-shadow 0.16s ease;
}

.correlation-mode-button:hover {
  color: var(--text-primary);
}

.correlation-mode-button.is-active {
  color: var(--color-primary);
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(46, 63, 50, 0.1);
}

.correlation-mode-button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.matrix-unavailable {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  min-height: 340px;
  color: var(--text-muted);
  text-align: center;
}

.matrix-unavailable strong {
  color: var(--text-secondary);
  font-size: 18px;
}

.matrix-unavailable span {
  max-width: 260px;
  font-family: var(--font-sans);
  font-size: 12px;
}

.localized-card-tag {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: normal;
}

/* Decision Panel */
.decision-panel {
  grid-column: 1 / -1;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.decision-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 4px;
}

.stat-mini-box {
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 10px;
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.s-l {
  font-size: 9px;
  color: var(--text-muted);
  display: block;
}

.s-v {
  font-family: var(--font-sans);
  letter-spacing: normal;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.s-div {
  width: 1px;
  height: 24px;
  background: var(--border-light);
}

.text-cyan { color: #0284c7; }
.text-danger { color: #dc2626; }

.correlated-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cl-title {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

.cl-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.decision-table {
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: #ffffff;
}

.decision-table-header,
.decision-row-summary {
  display: grid;
  grid-template-columns: minmax(64px, .7fr) minmax(110px, 1fr) 70px minmax(90px, .9fr) minmax(220px, 2.2fr) 76px;
  align-items: center;
  gap: 12px;
}

.decision-table-header {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  background: var(--surface-2);
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 650;
}

.decision-row + .decision-row {
  border-top: 1px solid var(--border-light);
}

.decision-row-summary {
  min-height: 48px;
  padding: 9px 12px;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 11px;
}

.decision-variable {
  color: var(--text-primary);
  font-size: 12px;
}

.decision-action {
  justify-self: start;
  padding: 2px 7px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
}

.decision-action.keep {
  border-color: #c7d8c8;
  background: #edf4eb;
  color: #557562;
}

.decision-action.drop {
  border-color: #dec6bd;
  background: #f7eeea;
  color: #8b594c;
}

.decision-action.merge,
.decision-action.review {
  border-color: #dfd2b6;
  background: #f7f3e8;
  color: #846f42;
}

.decision-reason {
  min-width: 0;
  color: var(--text-secondary);
  line-height: 1.45;
}

.decision-expand-button {
  appearance: none;
  padding: 4px 8px;
  border: 1px solid var(--border-light);
  border-radius: 5px;
  color: var(--color-primary);
  background: var(--surface-1);
  box-shadow: none;
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 650;
  transition: border-color 0.15s ease, background-color 0.15s ease, color 0.15s ease;
}

.decision-expand-button:hover {
  border-color: var(--border-default);
  color: var(--text-primary);
  background: var(--surface-2);
}

.decision-expand-button:focus-visible {
  outline: 2px solid var(--color-primary-light);
  outline-offset: 1px;
}

.decision-evidence {
  padding: 14px;
  border-top: 1px solid var(--border-light);
  background: #f8faf8;
}

.decision-evidence-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.decision-evidence-list > div {
  padding: 8px 10px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: #ffffff;
}

.decision-evidence-list dt {
  margin-bottom: 3px;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 9px;
}

.decision-evidence-list dd {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 11px;
  line-height: 1.45;
}

.correlation-evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.correlation-evidence-grid section {
  padding: 9px 10px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: #ffffff;
}

.correlation-evidence-grid h5 {
  margin: 0 0 6px;
  color: var(--text-secondary);
  font-size: 10px;
}

.correlation-evidence-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 3px 0;
  color: var(--text-muted);
  font-size: 10px;
}

.correlation-evidence-row strong {
  color: var(--text-primary);
}

.evidence-empty,
.decision-empty {
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 11px;
}

.decision-empty {
  padding: 10px 12px;
  border: 1px dashed var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
}

.qualification-explanation {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-left: 3px solid #b5965d;
  background: #f7f3e8;
  color: #6f6246;
  font-family: var(--font-sans);
  font-size: 11px;
  line-height: 1.5;
}

.no-drops {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
  color: var(--success);
  padding: 10px;
  background: var(--success-soft);
  border: 1px solid var(--color-success-border);
  border-radius: var(--radius-xs);
}

.tri-panel .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.decision-action-strip {
  margin-top: auto;
  padding-top: 10px;
}

.apply-decision-summary {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid #decfc0;
  border-radius: 7px;
  background: #f8f3ed;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 11px;
}

.apply-decision-summary > strong {
  color: #795a4e;
  font-size: 11px;
}

.apply-decision-item {
  display: grid;
  grid-template-columns: minmax(60px, auto) 1fr;
  gap: 10px;
  line-height: 1.45;
}

.collin-empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.empty-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  margin-bottom: 12px;
}

.collin-empty-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.collin-empty-card p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 440px;
}

@media (max-width: 1180px) {
  .analysis-context-grid {
    grid-template-columns: 1fr;
  }
  .cs-row {
    grid-template-columns: 1fr 1fr;
  }
  .collin-tri-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .analysis-context-header,
  .selected-source-detail {
    align-items: flex-start;
    flex-direction: column;
  }

  .selected-source-id {
    margin-left: 0;
  }

  .decision-table-header {
    display: none;
  }

  .decision-row-summary {
    grid-template-columns: minmax(64px, .7fr) minmax(0, 1.3fr);
  }

  .decision-reason,
  .decision-expand-button {
    grid-column: 1 / -1;
  }

  .decision-expand-button {
    justify-self: start;
  }

  .decision-evidence-list,
  .correlation-evidence-grid {
    grid-template-columns: 1fr;
  }
}
</style>
