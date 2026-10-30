<template>
  <div class="page-container delay-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge">STAGE 04 · DELAY ALIGNMENT STUDIO</div>
      <div class="stage-links">
        <span class="stage-link" @click="$router.push('/preprocessing/cleaning')">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/segmentation')">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link active">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/collinearity')">05 VIF 降维</span>
      </div>
    </div>

    <div class="page-header">
      <span class="page-eyebrow">PRE-WHITENING CROSS CORRELATION & PHASE ALIGNMENT</span>
      <h2>多变量时滞对齐工作室</h2>
      <p class="subtitle">预白化去除输入慢变自相关伪峰，并结合自由仿真 FIT 精修各通道物理纯滞后 \(n_k\)</p>
    </div>

    <div class="delay-primary-workspace" data-test="delay-primary-workspace">
      <aside class="delay-parameters-panel" data-test="delay-parameters-column">
        <div class="industrial-card rail-card" data-test="delay-parameters-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Timer /></el-icon>
              <span>时滞对齐参数</span>
            </div>
          </div>

          <el-form :model="form" label-position="top" class="rail-form">
            <el-form-item class="source-form-item">
              <template #label>
                <span data-test="delay-source-label">可用时滞源版本</span>
              </template>
              <VersionLineagePicker
                data-test="delay-source-picker"
                :dataset-name="datasetStore.activeDataset?.name ?? ''"
                :versions="versionNodes"
                :selected-version-id="selectedSourceVersionId"
                :loading="loadingSources"
                context-label="清洗规整版本可用于时滞分析"
                eligible-label="可用于时滞分析"
                empty-state-text="当前数据集尚无可用于时滞分析的清洗规整版本。"
                empty-state-hint="请先完成 Stage 02 时间清洗。"
                placeholder="选择清洗规整版本"
                :is-eligible="isDelayEligibleVersion"
                :disabled-reason="delayDisabledReason"
                @select="handleSourceChange"
              />
              <p class="source-helper" data-test="delay-source-helper">
                完整版本血缘可见；仅清洗规整版本可进入时滞分析。
              </p>
            </el-form-item>

            <div v-if="selectedSource" class="selected-source-detail" data-test="current-delay-source">
              <div class="selected-source-kicker">当前分析源</div>
              <div class="selected-source-name">{{ selectedSource.name }}</div>
              <dl class="selected-source-facts">
                <div>
                  <dt>Delay 状态</dt>
                  <dd>
                    <span class="selected-source-status" :class="selectedSource.delay_status">
                      {{ delayStatusLabel(selectedSource.delay_status) }}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>版本 ID</dt>
                  <dd class="font-mono">{{ shortVersionId(selectedSource.version_id) }}</dd>
                </div>
                <div>
                  <dt>创建时间</dt>
                  <dd>{{ formatSourceDate(selectedSource.created_at) }}</dd>
                </div>
              </dl>
              <div class="selected-source-description">
                {{ delayStatusDescription(selectedSource.delay_status) }}
              </div>
            </div>

            <el-form-item label="输入变量 (u)">
              <el-input v-model="inputColumnsText" placeholder="u1,u2" />
            </el-form-item>

            <el-form-item label="输出变量 (y)">
              <el-input v-model="form.output_column" placeholder="y" />
            </el-form-item>

            <el-form-item label="最大滞后搜索 (Max Lag)">
              <el-input-number v-model="form.max_lag" :min="1" :max="1000" :step="5" style="width: 100%" />
            </el-form-item>

            <el-form-item label="候选数 (Top-K)">
              <el-input-number v-model="form.top_k" :min="1" :max="10" style="width: 100%" />
            </el-form-item>

            <el-button type="primary" size="large" :loading="loading" :disabled="!selectedSource" icon="Search" @click="handleEstimate" style="width: 100%; margin-top: 6px">
              执行预白化时滞估计
            </el-button>
          </el-form>

          <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
            <template #title>时滞分析提示：{{ errorMessage }}</template>
          </el-alert>

          <div class="theory-box" data-test="prewhitening-note">
            <div class="t-title">为什么必须预白化？</div>
            <p class="t-p">工业慢信号自相关严重，直接互相关会导致峰值严重展宽和虚假偏移。系统先通过 AR 模型滤除自相关残差，再与输出互相关求得真实物理延迟。</p>
          </div>
        </div>
      </aside>

      <main class="delay-spectrum-panel" data-test="delay-analysis-column">
        <el-alert
          v-if="restoringResult && !result"
          title="正在读取最近一次已持久化的时滞分析结果…"
          type="info"
          :closable="false"
          show-icon
          class="restore-alert"
        />
        <template v-if="result">
          <div class="industrial-card studio-spectrum-card" data-test="delay-spectrum-card">
            <div class="industrial-card-header">
              <div class="industrial-card-title">
                <el-icon><DataLine /></el-icon>
                <span>预白化互相关函数响应图谱 (SPECTRUM)</span>
              </div>
              <div class="spectrum-metrics">
                <span class="text-cyan">VALIDATION FIT: {{ formatNumber(result.validation_fit) }}%</span>
                <span>REFINEMENT: {{ formatInteger(result.refinement_rounds) }} rounds</span>
              </div>
            </div>
            <div class="spectrum-explainer">
              <span><strong>Candidate Peaks</strong> 来自 correlation spectrum。</span>
              <span><strong>Validation-Refined Best Lag</strong> 由后续 validation refinement 选定，可能与候选峰不同。</span>
            </div>
            <ChartContainer :options="chartOptions" height="380px" />
          </div>

          <section class="delay-results-section" data-test="delay-results-section">
            <div class="channel-cards-grid">
              <div
                v-for="row in delayRows"
                :key="row.column"
                class="channel-tile industrial-card"
                :class="{ uncertain: row.uncertain }"
              >
                <div class="channel-top">
                  <span class="channel-name">{{ row.column }}</span>
                  <span class="channel-status-pill" :class="{ uncertain: row.uncertain }">
                    {{ row.uncertain ? "UNCERTAIN" : "CONFIRMED" }}
                  </span>
                </div>
                <div class="channel-main-lag">
                  <span class="lag-label">VALIDATION-REFINED BEST LAG \(n_k\)</span>
                  <span class="lag-num">{{ row.refined }} <span class="lag-unit">steps</span></span>
                </div>
                <div class="channel-candidates">
                  <span class="c-label">CORRELATION CANDIDATE PEAKS (TOP-K)</span>
                  <div v-if="row.candidates.length" class="c-chips">
                    <span
                      v-for="(peak, index) in row.candidates"
                      :key="peak.lag"
                      class="c-chip"
                      :class="{ 'matches-refined': peak.lag === row.refined }"
                    >
                      #{{ index + 1 }} · lag {{ peak.lag }} · r={{ formatNumber(peak.correlation) }}
                    </span>
                  </div>
                  <span v-else class="c-unavailable">N/A</span>
                </div>
                <div class="channel-evidence">
                  <span class="evidence-label">PREWHITENING ORDER</span>
                  <strong class="evidence-value">{{ formatInteger(row.prewhiteningOrder) }}</strong>
                </div>
              </div>
            </div>
          </section>
        </template>

        <div class="industrial-card studio-empty-card" v-else>
          <div class="empty-icon">
            <el-icon><Timer /></el-icon>
          </div>
          <h3>{{ emptyStateTitle }}</h3>
          <p>{{ emptyStateDescription }}</p>
        </div>
      </main>
    </div>

    <template v-if="result">
      <section class="industrial-card hitl-review-card" data-test="delay-hitl-review">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Timer /></el-icon>
            <span>时滞参数复核 / HITL</span>
          </div>
          <span class="hitl-review-note">UNCERTAIN 通道需由工程师确认最终采用值</span>
        </div>
        <div class="hitl-review-head" aria-hidden="true">
          <span>变量</span>
          <span>算法推荐</span>
          <span>分析状态</span>
          <span>最终采用值</span>
          <span>参数来源</span>
          <span>复核</span>
        </div>
        <div v-for="row in hitlRows" :key="row.column" class="hitl-review-row" :class="{ uncertain: row.requiresManualReview }">
          <strong>{{ row.column }}</strong>
          <span>{{ row.hasRecommendation ? row.refined : "N/A" }}</span>
          <span class="hitl-status" :class="{ uncertain: row.requiresManualReview }">
            {{ row.unavailable ? "UNAVAILABLE · 无可靠估计" : row.uncertain ? "UNCERTAIN · 需人工复核" : "CONFIRMED" }}
          </span>
          <el-input-number
            v-if="row.requiresManualReview"
            :model-value="finalLagByColumn[row.column]"
            :min="0"
            :step="1"
            :precision="0"
            controls-position="right"
            class="review-lag-input"
            :data-test="`final-lag-${row.column}`"
            @update:model-value="setFinalLag(row.column, $event)"
          />
          <span v-else>{{ finalLagByColumn[row.column] }}</span>
          <span :class="{ 'manual-source': row.requiresManualReview }" :data-test="`lag-source-${row.column}`">
            {{ lagSourceLabel(row) }}
          </span>
          <el-button
            v-if="row.requiresManualReview"
            size="small"
            :type="reviewedUncertain[row.column] ? 'success' : 'warning'"
            :disabled="!isValidLag(finalLagByColumn[row.column])"
            :data-test="`review-lag-${row.column}`"
            @click="confirmUncertainLag(row.column)"
          >
            {{ reviewedUncertain[row.column] ? "已复核" : "确认采用该值" }}
          </el-button>
          <span v-else class="reviewed-algorithm">算法确认</span>
        </div>
        <div v-if="hitlRows.some((row) => row.requiresManualReview)" class="hitl-review-hint">
          输入框中的推荐值不是自动确认；未获得可靠估计的通道默认采用 0 作为系统建议（暂不补偿），工程师可确认或基于工艺先验进行覆盖。
        </div>
      </section>

      <div class="industrial-card studio-apply-strip" data-test="delay-apply-strip">
        <div class="apply-left">
          <div class="apply-h">APPLY DELAY COMPENSATION · 创建移位版本</div>
          <div class="apply-d">
            {{ applySummary }}
          </div>
        </div>
        <el-button
          type="primary"
          size="large"
          :loading="applying || confirmingApply"
          :disabled="!applyReady || confirmingApply"
          data-test="apply-delay-button"
          @click="handleApply"
        >
          确认应用并生成时滞补偿版本 →
        </el-button>
      </div>
      <el-alert
        v-if="appliedVersionId"
        type="success"
        :closable="false"
        show-icon
        class="apply-success-alert"
        data-test="apply-success"
      >
        <template #title>已成功生成时滞补偿版本：{{ appliedVersionId }}</template>
      </el-alert>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { DataLine, Search, Timer } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import VersionLineagePicker from "../components/versioning/VersionLineagePicker.vue";
import { applyLagCompensation, calculateDelay, getLatestDelay } from "../api/preprocessing";
import { getDatasetVersions, getDelaySourceVersions } from "../api/datasets";
import type {
  DatasetVersionNode,
  DelayRequest,
  DelayResponse,
  DelaySourceStatus,
  DelaySourceVersion,
} from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage, ElMessageBox } from "element-plus";
import { useDatasetStore } from "../stores/datasetStore";
import { formatVersionDate, shortVersionId } from "../utils/versionOperation";

const PALETTE = ["#6E9B69", "#7995A8", "#B28B50", "#96799F", "#B8746E", "#52735A"];

const loading = ref(false);
const applying = ref(false);
const confirmingApply = ref(false);
const loadingSources = ref(false);
const restoringResult = ref(false);
const result = ref<DelayResponse | null>(null);
const errorMessage = ref("");
const inputColumnsText = ref("u1,u2");
const datasetStore = useDatasetStore();
const delaySources = ref<DelaySourceVersion[]>([]);
const versionNodes = ref<DatasetVersionNode[]>([]);
const selectedSourceVersionId = ref<string | null>(null);
const rememberedSourceByDataset = new Map<string, string>();
const sourceInputColumns = ref<string[]>([]);
const finalLagByColumn = ref<Record<string, number | null>>({});
const reviewedUncertain = ref<Record<string, boolean>>({});
const unavailableFallbackOverridden = ref<Record<string, boolean>>({});
const appliedVersionId = ref<string | null>(null);
let rehydrationRequest = 0;
let delaySourcesRequest = 0;

const form = reactive<DelayRequest>({
  version_id: "",
  input_columns: [],
  output_column: "y",
  max_lag: 30,
  top_k: 3,
});

const activeDatasetId = computed(() => datasetStore.activeDataset?.id ?? null);
const selectedSource = computed(
  () => delaySources.value.find((source) => source.version_id === selectedSourceVersionId.value) ?? null
);

const isDelayEligibleVersion = (version: DatasetVersionNode) =>
  version.tool === "preprocessing.clean" &&
  delaySources.value.some((source) => source.version_id === version.id);

const delayDisabledReason = (version: DatasetVersionNode) => {
  if (version.tool === "simulation_generate" || version.tool === "raw_upload") {
    return "需先完成清洗规整";
  }
  if (
    version.tool === "preprocessing.lag_compensation" ||
    version.tool === "preprocessing.feature_selection"
  ) {
    return "已完成时滞补偿，不作为新的时滞分析源";
  }
  if (version.tool === "preprocessing.clean") return "该版本尚未进入可用时滞源列表";
  return "该处理阶段不符合时滞分析源要求";
};

const isValidLag = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= 0;

const hasManualReview = computed(() => hitlRows.value.some((row) => row.requiresManualReview));
const allFinalLagsValid = computed(
  () => hitlRows.value.length > 0 && hitlRows.value.every((row) => isValidLag(finalLagByColumn.value[row.column]))
);
const allManualRowsReviewed = computed(() =>
  hitlRows.value
    .filter((row) => row.requiresManualReview)
    .every((row) => reviewedUncertain.value[row.column])
);
const applyReady = computed(
  () =>
    !!result.value &&
    !!activeDatasetId.value &&
    !!selectedSource.value &&
    form.version_id === selectedSource.value.version_id &&
    form.dataset_id === activeDatasetId.value &&
    !appliedVersionId.value &&
    !applying.value &&
    allFinalLagsValid.value &&
    allManualRowsReviewed.value
);

const lagSourceLabel = (row: {
  column: string;
  refined: number | null;
  uncertain: boolean;
  unavailable: boolean;
  requiresManualReview: boolean;
}) => {
  if (!row.requiresManualReview) return "算法确认";
  if (row.unavailable) {
    if (!reviewedUncertain.value[row.column]) {
      return unavailableFallbackOverridden.value[row.column]
        ? "待人工复核（将覆盖系统建议 0）"
        : "系统建议 · 暂不补偿";
    }
    return finalLagByColumn.value[row.column] === 0
      ? "人工确认系统建议（暂不补偿）"
      : "人工覆盖（原系统建议 0）";
  }
  if (!reviewedUncertain.value[row.column]) return "待人工复核";
  return finalLagByColumn.value[row.column] === row.refined ? "人工确认算法值" : "人工覆盖";
};

const applySummary = computed(() => {
  if (!result.value) return "";
  if (!allFinalLagsValid.value) return "请为全部输入变量提供合法的非负整数时滞。";
  if (!allManualRowsReviewed.value) return "存在需人工复核或指定的通道，请逐项确认最终采用值后再应用。";
  return hitlRows.value
    .map((row) => `${row.column} = ${finalLagByColumn.value[row.column]} · ${lagSourceLabel(row)}`)
    .join("；");
});

const resetHitlReview = (delayResult: DelayResponse | null) => {
  appliedVersionId.value = null;
  if (!delayResult) {
    finalLagByColumn.value = {};
    reviewedUncertain.value = {};
    unavailableFallbackOverridden.value = {};
    return;
  }
  finalLagByColumn.value = Object.fromEntries(
    hitlRows.value.map((row) => [row.column, row.hasRecommendation ? row.refined : 0])
  );
  reviewedUncertain.value = Object.fromEntries(
    hitlRows.value
      .filter((row) => row.requiresManualReview)
      .map((row) => [row.column, false])
  );
  unavailableFallbackOverridden.value = Object.fromEntries(
    hitlRows.value.filter((row) => row.unavailable).map((row) => [row.column, false])
  );
};

const setFinalLag = (column: string, value: number | null | undefined) => {
  finalLagByColumn.value[column] = typeof value === "number" ? value : null;
  if (hitlRows.value.find((row) => row.column === column)?.unavailable) {
    unavailableFallbackOverridden.value[column] = finalLagByColumn.value[column] !== 0;
  }
  reviewedUncertain.value[column] = false;
};

const confirmUncertainLag = (column: string) => {
  if (!isValidLag(finalLagByColumn.value[column])) {
    ElMessage.error("最终采用时滞必须是非负整数。");
    return;
  }
  reviewedUncertain.value[column] = true;
};

const delayStatusLabel = (status: DelaySourceStatus) =>
  ({
    complete: "已完成 · 可恢复",
    not_analyzed: "尚未分析",
    unrehydratable: "历史结果不可恢复",
  })[status];

const delayStatusDescription = (status: DelaySourceStatus) =>
  ({
    complete: "将读取该版本已持久化的完整 Delay 分析结果。",
    not_analyzed: "该 Cleaning 版本尚无成功可用 Delay 分析，可直接执行新的预白化时滞估计。",
    unrehydratable: "历史分析存在，但无法恢复完整频谱；可重新执行分析生成新的完整结果。",
  })[status];

const formatSourceDate = formatVersionDate;

const emptyStateTitle = computed(() => {
  if (loadingSources.value) return "正在读取 Delay Source 历史版本…";
  if (!activeDatasetId.value) return "请先选择数据集";
  if (!delaySources.value.length) return "暂无 Cleaning 版本";
  if (selectedSource.value?.delay_status === "not_analyzed") return "该版本尚无成功可用 Delay 分析";
  if (selectedSource.value?.delay_status === "unrehydratable") return "历史 Delay 结果无法恢复";
  return "时滞对齐工作室就绪";
});

const emptyStateDescription = computed(() => {
  if (loadingSources.value) return "正在读取后端已确认的 Cleaning 版本及其 Delay 分析状态。";
  if (!activeDatasetId.value) return "请从数据资产中心选择数据集后再进入时滞分析。";
  if (!delaySources.value.length) return "当前数据集尚无可用于时滞分析的 Cleaning 版本。";
  if (selectedSource.value) return delayStatusDescription(selectedSource.value.delay_status);
  return "请选择一个 Cleaning 历史版本后再执行时滞分析。";
});

const hydratePersistedResult = async (versionId: string, datasetId: string) => {
  const request = ++rehydrationRequest;
  restoringResult.value = true;
  errorMessage.value = "";
  result.value = null;
  try {
    const persisted = await getLatestDelay({ version_id: versionId, dataset_id: datasetId });
    if (request !== rehydrationRequest) return;
    result.value = persisted;
    form.version_id = persisted.source_version_id;
    form.dataset_id = persisted.dataset_id ?? datasetId;
    const persistedInputs = Object.keys(persisted.correlations);
    if (persistedInputs.length) {
      form.input_columns = persistedInputs;
      inputColumnsText.value = persistedInputs.join(",");
    }
  } catch (error) {
    if (request !== rehydrationRequest) return;
    result.value = null;
    errorMessage.value =
      error instanceof ApiError &&
      (error.code === "DELAY_RESULT_NOT_FOUND" || error.code === "DELAY_RESULT_UNAVAILABLE")
        ? "历史结果状态已变化，无法恢复该版本的完整频谱；请重新分析或刷新版本状态。"
        : error instanceof ApiError
          ? error.message
          : String(error);
  } finally {
    if (request === rehydrationRequest) restoringResult.value = false;
  }
};

const selectDelaySource = async (versionId: string | null, datasetId: string) => {
  const source = delaySources.value.find((item) => item.version_id === versionId) ?? null;
  rehydrationRequest += 1;
  restoringResult.value = false;
  result.value = null;
  errorMessage.value = "";
  selectedSourceVersionId.value = source?.version_id ?? null;
  sourceInputColumns.value = source?.input_columns ?? [];
  form.version_id = source?.version_id ?? "";
  form.dataset_id = source ? datasetId : null;

  if (source?.delay_status === "complete") {
    await hydratePersistedResult(source.version_id, datasetId);
  }
};

const handleSourceChange = (versionId: string) => {
  const datasetId = activeDatasetId.value;
  if (!datasetId) return;
  rememberedSourceByDataset.set(datasetId, versionId);
  void selectDelaySource(versionId, datasetId);
};

const chooseDefaultDelaySource = (
  datasetId: string,
  activeVersionId: string | undefined,
  nodes: DatasetVersionNode[]
) => {
  const eligible = nodes.filter(isDelayEligibleVersion);
  const rememberedId = rememberedSourceByDataset.get(datasetId);
  return eligible.find((version) => version.id === rememberedId)?.id
    ?? eligible.find((version) => version.id === activeVersionId)?.id
    ?? [...eligible].sort(
      (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
    )[0]?.id
    ?? null;
};

const initializeFromActiveDataset = async () => {
  const activeDataset = datasetStore.activeDataset;
  const request = ++delaySourcesRequest;
  rehydrationRequest += 1;
  loadingSources.value = false;
  restoringResult.value = false;
  delaySources.value = [];
  versionNodes.value = [];
  selectedSourceVersionId.value = null;
  sourceInputColumns.value = [];
  result.value = null;
  errorMessage.value = "";

  if (!activeDataset?.id) {
    form.version_id = "";
    form.dataset_id = null;
    form.input_columns = [];
    inputColumnsText.value = "";
    return;
  }

  form.dataset_id = activeDataset.id;
  form.input_columns = [...activeDataset.input_columns];
  inputColumnsText.value = activeDataset.input_columns.join(",");
  if (activeDataset.output_column) form.output_column = activeDataset.output_column;
  loadingSources.value = true;
  try {
    const [data, versions] = await Promise.all([
      getDelaySourceVersions(activeDataset.id),
      getDatasetVersions(activeDataset.id),
    ]);
    if (request !== delaySourcesRequest) return;
    delaySources.value = data.sources;
    versionNodes.value = versions.nodes;
    const defaultVersionId = chooseDefaultDelaySource(
      activeDataset.id,
      activeDataset.version_id || activeDataset.latest_version_id,
      versions.nodes
    );
    await selectDelaySource(defaultVersionId, activeDataset.id);
  } catch (error) {
    if (request !== delaySourcesRequest) return;
    errorMessage.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (request === delaySourcesRequest) loadingSources.value = false;
  }
};

const handleEstimate = async () => {
  rehydrationRequest += 1;
  restoringResult.value = false;
  errorMessage.value = "";
  if (!selectedSource.value || form.version_id !== selectedSource.value.version_id) {
    errorMessage.value = "请先选择一个 Cleaning 历史版本。";
    return;
  }
  form.input_columns = inputColumnsText.value
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (!form.input_columns.length) {
    errorMessage.value = "请至少指定一个输入变量。";
    return;
  }

  loading.value = true;
  try {
    result.value = await calculateDelay(form);
    const source = delaySources.value.find(
      (item) => item.version_id === selectedSourceVersionId.value
    );
    if (source) {
      source.delay_status = "complete";
      source.latest_complete_delay_run_id = result.value.processing_run_id;
    }
    ElMessage.success("时滞估计完成");
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};

const handleApply = async () => {
  if (!result.value || !applyReady.value || applying.value || confirmingApply.value) {
    if (result.value && !applyReady.value) {
      ElMessage.error("请先完成所有 UNCERTAIN 通道的人工复核，并确认最终时滞为非负整数。");
    }
    return;
  }
  const datasetId = form.dataset_id ?? activeDatasetId.value;
  if (!datasetId) return;
  const sourceVersionId = form.version_id;
  const lagMap = Object.fromEntries(
    hitlRows.value.map((row) => [row.column, finalLagByColumn.value[row.column]!])
  );
  const recommendationSource = hasManualReview.value ? "manual" : "delay_analysis";
  const evidenceSummary = Object.fromEntries(
    hitlRows.value.map((row) => {
      const finalLag = lagMap[row.column];
      if (row.unavailable) {
        return finalLag === 0
          ? [row.column, "No reliable Delay Analyze recommendation; system recommendation = 0 (no compensation); user confirmed system recommendation."]
          : [row.column, `No reliable Delay Analyze recommendation; system recommendation = 0; manual override final = ${finalLag}.`];
      }
      if (!row.uncertain) {
        return [row.column, `Delay Analyze validation-refined recommendation = ${row.refined}; algorithm confirmed.`];
      }
      return finalLag === row.refined
        ? [row.column, `UNCERTAIN; human reviewed and adopted Delay Analyze validation-refined recommendation = ${row.refined}.`]
        : [row.column, `UNCERTAIN; human override: Delay Analyze validation-refined recommendation = ${row.refined}; adopted = ${finalLag}.`];
    })
  );

  confirmingApply.value = true;
  try {
    await ElMessageBox.confirm(
      `将按以下最终时滞方案创建新的不可变 DatasetVersion：\n${applySummary.value}\n\n源版本不会被覆盖。是否继续？`,
      "确认时滞补偿",
      { type: "warning", confirmButtonText: "确认生成", cancelButtonText: "取消" }
    );
    if (
      !applyReady.value ||
      form.version_id !== sourceVersionId ||
      (form.dataset_id ?? activeDatasetId.value) !== datasetId
    ) {
      ElMessage.error("应用前的 Dataset 或时滞来源已变化，请重新复核后再提交。");
      return;
    }
    applying.value = true;
    const applied = await applyLagCompensation({
      version_id: sourceVersionId,
      dataset_id: datasetId,
      lag_map: lagMap,
      user_confirmed: true,
      recommendation_source: recommendationSource,
      evidence_summary: evidenceSummary,
    });
    appliedVersionId.value = applied.result_version_id;
    ElMessage.success(`已创建时滞补偿版本：${applied.result_version_id}`);
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err instanceof ApiError ? err.message : String(err));
  } finally {
    applying.value = false;
    confirmingApply.value = false;
  }
};

const delayRows = computed(() => {
  if (!result.value) return [];
  return form.input_columns.map((column) => {
    const candidates = result.value?.candidate_peaks[column] ?? [];
    return {
      column,
      refined: result.value?.best_delays[column] ?? 0,
      candidates,
      uncertain: result.value?.uncertain_columns.includes(column) ?? false,
      prewhiteningOrder: result.value?.prewhitening_orders[column],
    };
  });
});

const hitlRows = computed(() => {
  if (!result.value) return [];
  const columns = sourceInputColumns.value.length ? sourceInputColumns.value : form.input_columns;
  return columns.map((column) => {
    const hasRecommendation = Object.prototype.hasOwnProperty.call(result.value!.best_delays, column);
    const refined = hasRecommendation ? result.value!.best_delays[column] : null;
    const uncertain = hasRecommendation && result.value!.uncertain_columns.includes(column);
    const unavailable = !hasRecommendation;
    return {
      column,
      refined,
      hasRecommendation,
      uncertain,
      unavailable,
      requiresManualReview: uncertain || unavailable,
    };
  });
});

const chartOptions = computed(() => {
  if (!result.value) return {};
  const columns = Object.keys(result.value.correlations);
  const maxLength = Math.max(...columns.map((c) => result.value!.correlations[c].length), 1);
  const tickInterval = maxLength <= 16 ? 0 : maxLength <= 40 ? 2 : Math.ceil(maxLength / 12);
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params: any[]) => {
        const points = Array.isArray(params) ? params : [params];
        const lag = points[0]?.axisValueLabel ?? points[0]?.axisValue ?? "—";
        return [
          `Lag ${lag}（滞后步数）`,
          ...points.map((point) => `${point.marker}${point.seriesName}: ${Number(point.value).toFixed(3)}`),
        ].join("<br/>");
      },
    },
    legend: { data: columns, top: "2%" },
    grid: { left: "3%", right: "4%", bottom: 106, top: "14%", containLabel: true },
    xAxis: {
      type: "category",
      name: "滞后步数 Lag (samples)",
      nameLocation: "middle",
      nameGap: 42,
      data: Array.from({ length: maxLength }, (_, i) => `${i}`),
      axisLabel: { interval: tickInterval, margin: 12 },
    },
    yAxis: { type: "value", name: "预白化互相关 r" },
    series: columns.map((column, index) => ({
      name: column,
      type: "line",
      showSymbol: false,
      color: PALETTE[index % PALETTE.length],
      lineStyle: { width: 2 },
      data: result.value!.correlations[column],
      markPoint: {
        symbol: "circle",
        symbolSize: 10,
        label: { show: false },
        itemStyle: { color: PALETTE[index % PALETTE.length] },
        tooltip: { formatter: "{b}<br/>correlation r = {c}" },
        data: (result.value!.candidate_peaks[column] ?? []).map((peak, rank) => ({
          name: `${column} · candidate #${rank + 1} · lag ${peak.lag}`,
          coord: [String(peak.lag), peak.correlation],
          value: peak.correlation,
        })),
      },
      markLine: {
        symbol: "none",
        silent: true,
        lineStyle: { type: "dashed", color: PALETTE[index % PALETTE.length] },
        label: { show: false },
        data: [
          {
            name: `${column} · validation-refined best lag`,
            xAxis: String(result.value!.best_delays[column] ?? 0),
          },
        ],
      },
    })),
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, filterMode: "none", height: 16, bottom: 8 },
    ],
  };
});

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
};

onMounted(() => void initializeFromActiveDataset());

watch(result, (nextResult) => resetHitlReview(nextResult));

watch(
  () => datasetStore.activeDataset?.id,
  (datasetId, previousDatasetId) => {
    if (datasetId !== previousDatasetId) void initializeFromActiveDataset();
  }
);

const formatInteger = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "N/A";
  return `${value}`;
};
</script>

<style scoped>
.delay-view {
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

/* Primary analysis workspace: parameters beside the spectrum only. */
.delay-primary-workspace {
  display: grid;
  grid-template-columns: minmax(300px, 28%) minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.delay-parameters-panel,
.delay-spectrum-panel {
  min-width: 0;
}

.rail-card {
  padding: 18px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.theory-box {
  margin-top: 16px;
  padding: 12px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.t-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  letter-spacing: normal;
  margin-bottom: 6px;
}

.delay-view .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.t-p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

.alert-gap {
  margin-top: 12px;
}

.source-alert {
  margin: -2px 0 10px;
}

.source-form-item :deep(.el-form-item__content) {
  width: 100%;
}

.source-helper {
  width: 100%;
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.45;
}

.source-option {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 3px 0;
  line-height: 1.35;
}

.source-option-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-weight: 700;
}

.source-option-meta {
  color: var(--text-muted);
  font-size: 10px;
  font-family: var(--font-sans);
  letter-spacing: normal;
}

:global(.delay-source-select-popper .el-select-dropdown__item) {
  height: auto;
  min-height: 48px;
  padding-top: 5px;
  padding-bottom: 5px;
  line-height: normal;
}

.source-status,
.selected-source-status {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.4;
  padding: 2px 6px;
}

.source-status.complete,
.selected-source-status.complete {
  background: #ecfdf5;
  color: #047857;
}

.source-status.not_analyzed,
.selected-source-status.not_analyzed {
  background: #eff6ff;
  color: #1d4ed8;
}

.source-status.unrehydratable,
.selected-source-status.unrehydratable {
  background: #fffbeb;
  color: #b45309;
}

.selected-source-detail {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: -2px 0 12px;
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.45;
}

.selected-source-kicker {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
}

.selected-source-name {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.selected-source-facts {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 1px 0 0;
}

.selected-source-facts > div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}

.selected-source-facts dt,
.selected-source-facts dd {
  margin: 0;
}

.selected-source-facts dt {
  color: var(--text-muted);
}

.selected-source-facts dd {
  min-width: 0;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}

.selected-source-description {
  padding-top: 7px;
  border-top: 1px solid var(--border-light);
}

.restore-alert {
  margin: 0;
}

/* Right analysis column keeps the Spectrum and channel result cards together. */
.delay-spectrum-panel {
  display: flex;
  flex-direction: column;
  align-self: start;
  width: 100%;
  gap: 14px;
}

.delay-results-section {
  min-width: 0;
  width: 100%;
}

/* Channel Tiles Array */
.channel-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.channel-tile {
  padding: 16px;
  background: #ffffff;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 0;
  border-top: 3px solid var(--color-primary);
}

.channel-tile.uncertain {
  border-top-color: #d97706;
}

.channel-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.channel-name {
  font-size: 14px;
  font-weight: 800;
  color: var(--text-primary);
}

.channel-status-pill {
  font-size: 9px;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  padding: 1px 5px;
  border-radius: 3px;
}

.channel-status-pill.uncertain {
  color: #b45309;
  background: #fffbeb;
}

.channel-main-lag {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.lag-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.lag-num {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-primary);
  line-height: 1.1;
}

.lag-unit {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
}

.channel-candidates {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
}

.c-label {
  font-size: 9px;
  color: var(--text-muted);
  font-weight: 700;
}

.c-chips {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.c-chip {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  padding: 2px 6px;
  border-radius: 4px;
}

.c-chip.matches-refined {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 700;
}

.c-unavailable {
  font-size: 10px;
  color: var(--text-muted);
}

.channel-evidence {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
}

.evidence-label {
  font-size: 9px;
  color: var(--text-muted);
  font-weight: 700;
}

.evidence-value {
  font-size: 12px;
  color: var(--text-primary);
}

/* Studio Spectrum */
.studio-spectrum-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.spectrum-metrics {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 11px;
  color: var(--text-muted);
}

.spectrum-explainer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 2px 0 12px;
  padding: 8px 10px;
  border-left: 3px solid var(--color-primary);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
}

.spectrum-explainer strong {
  color: var(--text-primary);
}

/* Human review between the immutable analysis result and Delay Apply. */
.hitl-review-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.hitl-review-note,
.hitl-review-hint {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
}

.hitl-review-head,
.hitl-review-row {
  display: grid;
  grid-template-columns: minmax(64px, 0.65fr) minmax(88px, 0.9fr) minmax(138px, 1.4fr) minmax(108px, 1fr) minmax(118px, 1.25fr) minmax(116px, 1.15fr);
  align-items: center;
  gap: 12px;
}

.hitl-review-head {
  margin-top: 12px;
  padding: 0 10px 7px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
}

.hitl-review-row {
  min-height: 52px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: 12px;
}

.hitl-review-row.uncertain {
  background: #fffbeb;
}

.hitl-status {
  color: #047857;
  font-size: 11px;
  font-weight: 700;
}

.hitl-status.uncertain,
.manual-source {
  color: #b45309;
}

.review-lag-input {
  width: 100%;
}

.reviewed-algorithm {
  color: var(--text-muted);
  font-size: 11px;
}

.hitl-review-hint {
  margin-top: 10px;
}

/* Studio Apply Strip */
.studio-apply-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  margin-bottom: 0;
  gap: 20px;
}

.apply-h {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: normal;
  margin-bottom: 3px;
}

.apply-d {
  font-size: 12px;
  color: var(--text-secondary);
}

.studio-empty-card {
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

.studio-empty-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.studio-empty-card p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 420px;
}

@media (max-width: 960px) {
  .delay-primary-workspace {
    grid-template-columns: 1fr;
  }
  .studio-apply-strip {
    flex-direction: column;
    align-items: stretch;
  }
  .hitl-review-head {
    display: none;
  }
  .hitl-review-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px 14px;
  }
  .studio-spectrum-card .industrial-card-header {
    align-items: flex-start;
    gap: 8px;
  }
  .spectrum-metrics {
    justify-content: flex-start;
  }
}
</style>
