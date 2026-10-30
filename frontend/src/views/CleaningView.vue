<template>
  <div class="page-container cleaning-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge">STAGE 02 · DATA CLEANING LAB</div>
      <div class="stage-links">
        <span class="stage-link active">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/segmentation')">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/delay')">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/collinearity')">05 VIF 降维</span>
      </div>
    </div>

    <!-- Page Header -->
    <div class="cleaning-hero-bar">
      <div>
        <span class="page-eyebrow">EQUISPACED RESAMPLING & 3-SIGMA TRIAGE</span>
        <h2>时间规整与清洗实验室</h2>
        <p class="subtitle">消除采样不均匀、补全缺失值并过滤尖峰异常点，生成可追溯的清洗规整版本。</p>
      </div>
    </div>

    <section class="industrial-card source-context-card" aria-labelledby="cleaning-source-title">
      <div class="source-context-header">
        <div>
          <span class="source-context-eyebrow">CLEANING CONTEXT</span>
          <h3 id="cleaning-source-title">清洗规整上下文</h3>
        </div>
        <p>原始版本与清洗规整版本可作为新的清洗输入。</p>
      </div>

      <div class="source-control-grid">
        <div class="source-control">
          <label for="cleaning-dataset">数据集</label>
          <el-select
            id="cleaning-dataset"
            v-model="selectedDatasetId"
            data-test="cleaning-dataset-select"
            placeholder="选择数据集"
            :loading="loadingDatasets"
            filterable
            @change="handleDatasetChange"
          >
            <el-option
              v-for="dataset in datasetOptions"
              :key="dataset.id"
              :label="dataset.name"
              :value="dataset.id"
            >
              <div class="dataset-option">
                <span>{{ dataset.name }}</span>
                <small>{{ dataset.row_count }} rows · {{ dataset.col_count }} cols</small>
              </div>
            </el-option>
          </el-select>
        </div>

        <div class="source-control">
          <label>源数据版本</label>
          <VersionLineagePicker
            data-test="cleaning-source-picker"
            :dataset-name="sourceDataset?.name ?? ''"
            :versions="versionNodes"
            :selected-version-id="selectedVersionId"
            :loading="loadingVersions"
            context-label="原始或清洗规整版本可作为清洗输入"
            eligible-label="可用于清洗规整"
            empty-state-text="暂无可用于清洗规整的数据版本。"
            empty-state-hint="请先上传数据或生成仿真数据。"
            placeholder="选择清洗源版本"
            :is-eligible="isCleaningEligibleVersion"
            :disabled-reason="cleaningDisabledReason"
            @select="handleVersionSelect"
          />
        </div>
      </div>

      <el-alert
        v-if="contextError"
        type="error"
        :title="contextError"
        :closable="false"
        show-icon
        class="context-alert"
      />

      <div v-if="sourceVersion" class="source-summary" data-test="cleaning-source-summary">
        <div><span>当前清洗源</span><strong>{{ versionDisplayName(sourceVersion) }}</strong></div>
        <div><span>数据集</span><strong>{{ sourceDataset?.name }}</strong></div>
        <div><span>创建时间</span><strong>{{ formatVersionDate(sourceVersion.created_at) }}</strong></div>
        <div><span>来源</span><strong>{{ selectedParent ? versionDisplayName(selectedParent) : "初始版本" }}</strong></div>
        <div><span>版本 ID</span><strong class="font-mono">{{ shortVersionId(sourceVersion.id) }}</strong></div>
        <div>
          <span>清洗状态</span>
          <strong class="source-ready">
            {{ sourceVersion.tool === "preprocessing.clean" ? "可再次执行清洗规整" : "可执行清洗规整" }}
          </strong>
        </div>
      </div>
    </section>

    <!-- FORMAT 1: Horizontal High-Density Control Strip (横向参数控制中枢) -->
    <section class="cleaning-toolbar industrial-card">
      <div class="toolbar-section">
        <span class="tb-label">重采样周期 Ts (s)</span>
        <el-input-number v-model="form.target_sample_period_seconds" :min="0.1" :max="60" :step="0.5" size="default" />
      </div>

      <div class="tb-divider"></div>

      <div class="toolbar-section">
        <span class="tb-label">异常值检测算法</span>
        <el-select v-model="form.anomaly_detector" size="default" style="width: 190px">
          <el-option label="Hampel Filter (3σ 稳健)" value="hampel" />
          <el-option label="IQR 四分位距" value="iqr" />
          <el-option label="Z-Score 阈值" value="z_score" />
        </el-select>
      </div>

      <div class="tb-divider" v-if="form.anomaly_detector === 'hampel'"></div>

      <div class="toolbar-section" v-if="form.anomaly_detector === 'hampel'">
        <span class="tb-label">Hampel 滑窗 k</span>
        <el-input-number v-model="form.hampel_window" :min="3" :max="21" :step="2" size="default" />
      </div>

      <div class="tb-divider"></div>

      <div class="toolbar-section">
        <span class="tb-label">缺失值插值策略</span>
        <el-select v-model="form.interpolation" size="default" style="width: 170px">
          <el-option label="线性插值 (Linear)" value="linear" />
          <el-option label="前向填充 (Forward)" value="forward_fill" />
          <el-option label="后向填充 (Backward)" value="backward_fill" />
        </el-select>
      </div>

      <div class="tb-actions">
        <el-button
          data-test="clean-submit"
          type="primary"
          size="default"
          :loading="loading"
          :disabled="!sourceVersion || loading"
          icon="MagicStick"
          @click="handleClean"
        >
          执行时间规整与清洗
        </el-button>
      </div>
    </section>

    <el-alert v-if="errorMessage" type="error" :title="errorMessage" :closable="false" show-icon>
      <ul v-if="validationIssues.length" class="validation-issues">
        <li v-for="issue in validationIssues" :key="issue">{{ issue }}</li>
      </ul>
    </el-alert>

    <!-- FORMAT 1: Full-Width Dual-Track Waveform Inspection Deck (全宽双轨波形对账) -->
    <section class="industrial-card waveform-inspection-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><DataAnalysis /></el-icon>
          <span>多通道时序规整波形对比 (RAW VS CLEANED)</span>
        </div>
        <div v-if="selectedChartSeries" class="chart-channel-control">
          <label for="cleaning-chart-channel">观察通道</label>
          <el-select
            id="cleaning-chart-channel"
            v-model="selectedChartColumn"
            data-test="cleaning-chart-channel-select"
            size="small"
            style="width: 150px"
          >
            <el-option
              v-for="series in cleanedData?.series ?? []"
              :key="series.column"
              :label="series.column"
              :value="series.column"
            />
          </el-select>
          <el-button
            data-test="cleaning-reset-zoom"
            size="small"
            plain
            @click="resetChartZoom"
          >重置视图</el-button>
        </div>
        <div class="header-pills" v-if="cleanedData">
          <el-tag
            v-if="cleanedData.reused_existing_version"
            type="success"
            effect="light"
            data-test="cleaning-reused-badge"
          >已复用</el-tag>
          <el-tag
            v-else-if="cleanedData.converged && !cleanedData.created_new_version"
            type="success"
            effect="light"
            data-test="cleaning-converged-badge"
          >已收敛</el-tag>
          <el-tag
            v-else-if="cleanedData.no_op"
            type="success"
            effect="light"
          >清洗认证完成</el-tag>
          <el-tag v-else type="success" effect="light">
            已修复 {{ cleanedData.total_cleaned_points }} 个唯一数据单元格
          </el-tag>
        </div>
      </div>

      <div v-if="cleanedData">
        <el-alert
          class="cleaning-summary"
          type="success"
          :title="cleaningResultSummary"
          :closable="false"
          show-icon
        />
        <div class="cleaning-chart-stage">
          <ChartContainer
            ref="compareChartRef"
            :options="compareChartOptions"
            height="420px"
            @chart-click="handleChartClick"
            @chart-viewport-change="updateRepairDetailPosition"
          />
          <aside
            v-if="selectedRepairPoint"
            ref="repairDetailCardRef"
            class="repair-detail-card"
            :class="{ 'is-anchor-hidden': !repairDetailPosition }"
            :style="repairDetailCardStyle"
            data-test="repair-detail-card"
            :data-horizontal-placement="repairDetailPosition?.horizontal ?? ''"
            :data-vertical-placement="repairDetailPosition?.vertical ?? ''"
            :aria-hidden="!repairDetailPosition"
            aria-live="polite"
          >
            <div class="repair-detail-card__header">
              <div>
                <span class="repair-detail-card__eyebrow">REPAIR EVIDENCE</span>
                <h4>修复详情</h4>
              </div>
              <button
                type="button"
                class="repair-detail-card__close"
                data-test="repair-detail-close"
                aria-label="关闭修复详情"
                @click="clearSelectedRepair"
              >×</button>
            </div>
            <strong class="repair-detail-card__category">{{ selectedRepairTitle }}</strong>
            <dl class="repair-detail-card__fields">
              <div><dt>通道</dt><dd>{{ selectedRepairPoint.channel }}</dd></div>
              <div><dt>时间</dt><dd>{{ formatTooltipTimestamp(selectedRepairPoint.timestamp) }}</dd></div>
              <div><dt>处理前</dt><dd>{{ formatChartValue(selectedRepairPoint.rawValue) }}</dd></div>
              <div class="repair-detail-card__arrow" aria-hidden="true">↓</div>
              <div><dt>处理后</dt><dd>{{ formatChartValue(selectedRepairPoint.cleanedValue) }}</dd></div>
            </dl>
            <div class="repair-detail-card__types">
              <span>修复类型</span>
              <ul>
                <li v-for="type in selectedRepairPoint.repairTypes" :key="type">
                  <i aria-hidden="true">{{ REPAIR_TYPE_SYMBOLS[type] }}</i>
                  {{ REPAIR_TYPE_LABELS[type] }}
                </li>
              </ul>
            </div>
          </aside>
        </div>
      </div>

      <div class="clean-empty-state" v-else>
        <div class="clean-empty-icon">
          <el-icon><Operation /></el-icon>
        </div>
        <h4>等待清洗触发</h4>
        <p>在上方工具栏调整重采样周期与 3σ 滤波参数，点击「执行规整」在此生成高分辨率对账波形。</p>
      </div>
    </section>

    <CleaningVersionCompareWorkbench
      :dataset="sourceDataset"
      :versions="versionNodes"
      :current-version-id="selectedVersionId"
    />

    <!-- FORMAT 1: Bottom 3-Card Telemetry Triage Strip (底部修复三联卡) -->
    <div class="triage-cards-grid">
      <div class="triage-card industrial-card">
        <div class="triage-num">01</div>
        <div class="triage-content">
          <div class="triage-title">HAMPEL 3-SIGMA FILTER</div>
          <div class="triage-desc">计算滑窗中位数绝对差 (MAD)，自适应截断偏离 3σ 的高频孤立尖峰，避免极大异常值拉偏最小二乘超平面。</div>
        </div>
      </div>

      <div class="triage-card industrial-card">
        <div class="triage-num">02</div>
        <div class="triage-content">
          <div class="triage-title">EQUISPACED RESAMPLING</div>
          <div class="triage-desc">重构严格单调递增的等间隔时间轴，统一多源 DCS 采样率，为后续差分方程辨识提供稳定的时间步长基准。</div>
        </div>
      </div>

      <div class="triage-card industrial-card next-triage-card" @click="$router.push('/preprocessing/segmentation')">
        <div class="triage-num">03</div>
        <div class="triage-content">
          <div class="triage-title">NEXT STEP · D-OPTIMAL</div>
          <div class="triage-desc">清洗数据已固化至当前资产树。点击直接进入质量门控与 D-最优高动态区间优选 →</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { Operation, MagicStick, DataAnalysis } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import CleaningVersionCompareWorkbench from "../components/cleaning/CleaningVersionCompareWorkbench.vue";
import VersionLineagePicker from "../components/versioning/VersionLineagePicker.vue";
import { cleanDataset } from "../api/preprocessing";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../api/datasets";
import { useDatasetStore } from "../stores/datasetStore";
import { ApiError } from "../api/client";
import type { CleanRequest, CleanResponse, DatasetItem, DatasetVersionNode } from "../types/api";
import { ElMessage } from "element-plus";
import {
  formatVersionDate,
  shortVersionId,
  versionDisplayName,
} from "../utils/versionOperation";

type CleaningForm = Pick<
  CleanRequest,
  "target_sample_period_seconds" | "interpolation" | "anomaly_detector" | "hampel_window"
>;

const route = useRoute();
const datasetStore = useDatasetStore();
const loading = ref(false);
const loadingDatasets = ref(false);
const loadingVersions = ref(false);
const cleanedData = ref<CleanResponse | null>(null);
const sourceDataset = ref<DatasetItem | null>(null);
const datasetOptions = ref<DatasetItem[]>([]);
const selectedDatasetId = ref<string | null>(null);
const versionNodes = ref<DatasetVersionNode[]>([]);
const selectedVersionId = ref<string | null>(null);
const selectedChartColumn = ref<string | null>(null);
type ChartAction = {
  type: string;
  seriesId?: string;
  dataIndex?: number;
  start?: number;
  end?: number;
};
type CoordinateFinder = {
  gridIndex?: number;
  xAxisIndex?: number;
  yAxisIndex?: number;
};
type ChartContainerExpose = {
  dispatchAction: (action: ChartAction) => void;
  convertToPixel: (finder: CoordinateFinder, value: unknown) => number | number[] | null;
  containPixel: (finder: CoordinateFinder, value: number[]) => boolean;
  getSize: () => { width: number; height: number };
};
const compareChartRef = ref<ChartContainerExpose | null>(null);
const repairDetailCardRef = ref<HTMLElement | null>(null);
const rememberedSourceByDataset = new Map<string, string>();
const contextError = ref("");
const errorMessage = ref("");
const validationIssues = ref<string[]>([]);
let contextRequestId = 0;

const form = reactive<CleaningForm>({
  target_sample_period_seconds: 1.0,
  interpolation: "linear",
  anomaly_detector: "hampel",
  hampel_window: 5,
});

const queryValue = (name: "dataset_id" | "version_id") => {
  const value = route.query[name];
  return typeof value === "string" && value ? value : undefined;
};

const sourceVersion = computed(
  () => versionNodes.value.find((node) => node.id === selectedVersionId.value) ?? null
);
const selectedChartSeries = computed(() => {
  const response = cleanedData.value;
  if (!response) return null;
  const series = response.series ?? [];
  return series.find((item) => item.column === selectedChartColumn.value)
    ?? series.find((item) => item.column === response.primary_column)
    ?? series[0]
    ?? null;
});
const selectedParent = computed(() => {
  const parentId = sourceVersion.value?.parent_version_id;
  return parentId
    ? versionNodes.value.find((node) => node.id === parentId) ?? null
    : null;
});

const CLEANING_SOURCE_OPERATIONS = new Set([
  "raw_upload",
  "simulation_generate",
  "preprocessing.clean",
]);

const isCleaningEligibleVersion = (version: DatasetVersionNode) =>
  CLEANING_SOURCE_OPERATIONS.has(version.tool);

const cleaningDisabledReason = (version: DatasetVersionNode) => {
  if (
    version.tool === "preprocessing.lag_compensation" ||
    version.tool === "preprocessing.feature_selection"
  ) {
    return "已进入后续处理阶段，不作为新的清洗源";
  }
  return "该处理阶段不符合清洗规整源要求";
};

const clearSourceContext = () => {
  clearSelectedRepair();
  versionNodes.value = [];
  selectedVersionId.value = null;
  selectedChartColumn.value = null;
  cleanedData.value = null;
  errorMessage.value = "";
  validationIssues.value = [];
};

const handleVersionSelect = (versionId: string) => {
  const version = versionNodes.value.find((node) => node.id === versionId);
  if (!version || !isCleaningEligibleVersion(version) || !selectedDatasetId.value) return;
  clearSelectedRepair();
  selectedVersionId.value = versionId;
  rememberedSourceByDataset.set(selectedDatasetId.value, versionId);
  selectedChartColumn.value = null;
  cleanedData.value = null;
  errorMessage.value = "";
  validationIssues.value = [];
};

const chooseDefaultVersion = (dataset: DatasetItem, nodes: DatasetVersionNode[]) => {
  const eligible = nodes.filter(isCleaningEligibleVersion);
  const rememberedId = rememberedSourceByDataset.get(dataset.id);
  const routeVersionId = queryValue("dataset_id") === dataset.id ? queryValue("version_id") : undefined;
  const activeVersionId = datasetStore.activeDataset?.id === dataset.id
    ? datasetStore.activeDataset.version_id || datasetStore.activeDataset.latest_version_id
    : dataset.version_id || dataset.latest_version_id;
  const preferred = eligible.find((node) => node.id === rememberedId)
    ?? eligible.find((node) => node.id === routeVersionId)
    ?? eligible.find((node) => node.id === activeVersionId)
    ?? [...eligible].sort(
      (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
    )[0];
  if (preferred) handleVersionSelect(preferred.id);
};

const loadDatasetContext = async (datasetId: string) => {
  const requestId = ++contextRequestId;
  clearSourceContext();
  contextError.value = "";
  loadingVersions.value = true;
  try {
    const [dataset, versions] = await Promise.all([
      getDatasetDetail(datasetId),
      getDatasetVersions(datasetId),
    ]);
    if (requestId !== contextRequestId) return;
    sourceDataset.value = dataset;
    versionNodes.value = versions.nodes;
    datasetStore.setActiveDataset(dataset);
    chooseDefaultVersion(dataset, versions.nodes);
  } catch (error) {
    if (requestId !== contextRequestId) return;
    sourceDataset.value = null;
    contextError.value = error instanceof ApiError
      ? `源版本加载失败 [${error.code}]：${error.message}`
      : "源版本加载失败，请确认后端服务和数据资产状态。";
  } finally {
    if (requestId === contextRequestId) loadingVersions.value = false;
  }
};

const refreshDatasetContextAfterClean = async (
  datasetId: string,
  effectiveVersionId: string
) => {
  const requestId = ++contextRequestId;
  contextError.value = "";
  loadingVersions.value = true;
  try {
    const [dataset, versions] = await Promise.all([
      getDatasetDetail(datasetId),
      getDatasetVersions(datasetId),
    ]);
    if (requestId !== contextRequestId || selectedDatasetId.value !== datasetId) return;
    sourceDataset.value = dataset;
    versionNodes.value = versions.nodes;
    datasetStore.setActiveDataset(dataset);
    const effectiveVersion = versions.nodes.find(
      (version) => version.id === effectiveVersionId
    );
    if (effectiveVersion && isCleaningEligibleVersion(effectiveVersion)) {
      selectedVersionId.value = effectiveVersion.id;
      rememberedSourceByDataset.set(datasetId, effectiveVersion.id);
    } else {
      contextError.value = "清洗已完成，但当前有效版本未出现在版本血缘中。";
    }
  } catch (error) {
    if (requestId !== contextRequestId || selectedDatasetId.value !== datasetId) return;
    contextError.value = error instanceof ApiError
      ? `清洗已完成，但版本列表刷新失败 [${error.code}]：${error.message}`
      : "清洗已完成，但版本列表刷新失败。";
  } finally {
    if (requestId === contextRequestId) loadingVersions.value = false;
  }
};

const handleDatasetChange = (datasetId: string) => {
  if (!datasetId) {
    ++contextRequestId;
    sourceDataset.value = null;
    clearSourceContext();
    return;
  }
  void loadDatasetContext(datasetId);
};

const initializeDatasets = async () => {
  loadingDatasets.value = true;
  contextError.value = "";
  try {
    const response = await listDatasets({ page: 1, page_size: 100 });
    datasetOptions.value = response.items;
    datasetStore.setDatasetsList(response.items);
    const initialDatasetId = queryValue("dataset_id") || datasetStore.activeDataset?.id;
    if (initialDatasetId && response.items.some((dataset) => dataset.id === initialDatasetId)) {
      selectedDatasetId.value = initialDatasetId;
      await loadDatasetContext(initialDatasetId);
    }
  } catch (error) {
    contextError.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    loadingDatasets.value = false;
  }
};

const formatValidationIssues = (error: unknown): string[] => {
  if (!(error instanceof ApiError) || !Array.isArray(error.details?.issues)) return [];
  return error.details.issues.map((issue: { loc?: unknown; msg?: unknown }) => {
    const location = Array.isArray(issue.loc)
      ? issue.loc.filter((item) => item !== "body").join(".")
      : "请求参数";
    return `${location || "请求参数"}：${typeof issue.msg === "string" ? issue.msg : "参数无效"}`;
  });
};

const handleClean = async () => {
  if (loading.value || !sourceDataset.value || !sourceVersion.value) return;
  loading.value = true;
  errorMessage.value = "";
  validationIssues.value = [];
  try {
    const datasetId = sourceDataset.value.id;
    const sourceVersionId = sourceVersion.value.id;
    const request: CleanRequest = {
      dataset_id: datasetId,
      version_id: sourceVersionId,
      target_sample_period_seconds: form.target_sample_period_seconds,
      interpolation: form.interpolation,
      anomaly_detector: form.anomaly_detector,
      hampel_window: form.hampel_window,
    };
    const res = await cleanDataset(request);
    cleanedData.value = res;
    selectedChartColumn.value = res.primary_column ?? res.series?.[0]?.column ?? null;
    await refreshDatasetContextAfterClean(datasetId, res.effective_version_id);
    if (res.reused_existing_version) {
      ElMessage.success("相同清洗结果已存在，已复用现有数据版本。");
    } else if (!res.created_new_version && res.converged) {
      ElMessage.success("清洗结果已收敛，本次未产生新的数据版本。");
    } else if (res.no_op) {
      ElMessage.success("数据无需修复，已完成清洗认证并生成 Cleaning Version。");
    } else {
      ElMessage.success(`成功生成清洗后数据版本: ${res.new_version_id}`);
    }
  } catch (error) {
    cleanedData.value = null;
    const code = error instanceof ApiError ? error.code : "ERR";
    const message = error instanceof Error ? error.message : "未知错误";
    validationIssues.value = formatValidationIssues(error);
    errorMessage.value = `清洗失败 [${code}]: ${message}`;
    ElMessage.error(errorMessage.value);
  } finally {
    loading.value = false;
  }
};

const REPAIR_TYPE_LABELS = {
  interpolation: "插值填补",
  outlier: "异常替换",
  smoothing: "平滑调整",
} as const;

type RepairType = keyof typeof REPAIR_TYPE_LABELS;

const REPAIR_TYPE_SYMBOLS: Record<RepairType, string> = {
  interpolation: "●",
  outlier: "◆",
  smoothing: "▲",
};

type RepairMarkerCategory = RepairType | "combined";

type RepairMarkerDatum = {
  value: [string, number];
  repairPoint: true;
  projectedIndex: number;
  repairTypes: RepairType[];
  markerCategory: RepairMarkerCategory;
  visualSeriesId: string;
  visualDataIndex: number;
};

type SelectedRepairPoint = {
  channel: string;
  projectedIndex: number;
  timestamp: string;
  rawValue: number | null;
  cleanedValue: number | null;
  repairTypes: RepairType[];
  markerCategory: RepairMarkerCategory;
  seriesId: string;
  dataIndex: number;
};

type ChartClickEvent = {
  seriesId?: string;
  dataIndex?: number;
  data?: unknown;
};

type RepairDetailPosition = {
  left: number;
  top: number;
  horizontal: "left" | "right";
  vertical: "above" | "below";
};

const REPAIR_VISUAL_SERIES_IDS: Record<RepairMarkerCategory, string> = {
  interpolation: "cleaning-repair-interpolation",
  outlier: "cleaning-repair-outlier",
  smoothing: "cleaning-repair-smoothing",
  combined: "cleaning-repair-combined",
};
const REPAIR_HIT_AREA_SERIES_ID = "cleaning-repair-hit-area";
const REPAIR_SERIES_IDS = new Set([
  ...Object.values(REPAIR_VISUAL_SERIES_IDS),
  REPAIR_HIT_AREA_SERIES_ID,
]);
const REPAIR_CARD_GAP = 16;
const REPAIR_CARD_INSET = 8;
const REPAIR_CARD_FALLBACK_WIDTH = 252;
const REPAIR_CARD_FALLBACK_HEIGHT = 238;
const selectedRepairPoint = ref<SelectedRepairPoint | null>(null);
const repairDetailPosition = ref<RepairDetailPosition | null>(null);
let repairPositionRequestId = 0;
const selectedRepairTitle = computed(() =>
  selectedRepairPoint.value?.repairTypes
    .map((type) => REPAIR_TYPE_LABELS[type])
    .join(" · ") ?? ""
);
const repairDetailCardStyle = computed(() => {
  const position = repairDetailPosition.value;
  return position
    ? { left: `${position.left}px`, top: `${position.top}px` }
    : { left: "0", top: "0" };
});

const formatChartValue = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "缺失";
  const magnitude = Math.abs(value);
  if (magnitude > 0 && magnitude < 0.0001) {
    return value.toExponential(4).replace(/\.0+(?=e)/, "");
  }
  return value.toLocaleString("en-US", {
    useGrouping: false,
    maximumFractionDigits: 4,
  });
};

const formatAxisTimestamp = (timestamp: string) => {
  const match = timestamp.match(/[T ](\d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp;
};

const formatTooltipTimestamp = (timestamp: string) => {
  const match = timestamp.replace("T", " ").match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp.replace("T", " ");
};

const repairTypesByIndex = (series: NonNullable<typeof selectedChartSeries.value>) => {
  const result = new Map<number, RepairType[]>();
  const add = (indices: number[], type: RepairType) => {
    for (const index of indices) {
      if (index < 0 || index >= series.timestamps.length) continue;
      const types = result.get(index) ?? [];
      if (!types.includes(type)) types.push(type);
      result.set(index, types);
    }
  };
  add(series.interpolation_changed_indices, "interpolation");
  add(series.outlier_replacement_indices, "outlier");
  add(series.smoothing_changed_indices, "smoothing");
  return result;
};

const isRepairMarkerDatum = (value: unknown): value is RepairMarkerDatum => {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<RepairMarkerDatum>;
  return candidate.repairPoint === true
    && Number.isInteger(candidate.projectedIndex)
    && Array.isArray(candidate.repairTypes)
    && candidate.repairTypes.every((type) => type in REPAIR_TYPE_LABELS)
    && typeof candidate.markerCategory === "string"
    && typeof candidate.visualSeriesId === "string"
    && Number.isInteger(candidate.visualDataIndex);
};

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), Math.max(minimum, maximum));

const placeRepairDetailCard = (
  point: number[],
  chartSize: { width: number; height: number },
  cardSize: { width: number; height: number }
): RepairDetailPosition => {
  const horizontal: RepairDetailPosition["horizontal"] = point[0] < chartSize.width / 2
    ? "right"
    : "left";
  const preferredLeft = horizontal === "right"
    ? point[0] + REPAIR_CARD_GAP
    : point[0] - cardSize.width - REPAIR_CARD_GAP;
  const aboveTop = point[1] - cardSize.height - REPAIR_CARD_GAP;
  const vertical: RepairDetailPosition["vertical"] = aboveTop >= REPAIR_CARD_INSET
    ? "above"
    : "below";
  const preferredTop = vertical === "above"
    ? aboveTop
    : point[1] + REPAIR_CARD_GAP;

  return {
    left: clamp(
      preferredLeft,
      REPAIR_CARD_INSET,
      chartSize.width - cardSize.width - REPAIR_CARD_INSET
    ),
    top: clamp(
      preferredTop,
      REPAIR_CARD_INSET,
      chartSize.height - cardSize.height - REPAIR_CARD_INSET
    ),
    horizontal,
    vertical,
  };
};

const updateRepairDetailPosition = async () => {
  const requestId = ++repairPositionRequestId;
  const selected = selectedRepairPoint.value;
  if (!selected) {
    repairDetailPosition.value = null;
    return;
  }

  await nextTick();
  if (requestId !== repairPositionRequestId || selected !== selectedRepairPoint.value) return;

  const chart = compareChartRef.value;
  const card = repairDetailCardRef.value;
  if (!chart || !card || selected.cleanedValue === null) {
    repairDetailPosition.value = null;
    return;
  }
  const converted = chart.convertToPixel(
    { xAxisIndex: 0, yAxisIndex: 0 },
    [selected.timestamp, selected.cleanedValue]
  );
  if (
    !Array.isArray(converted)
    || converted.length < 2
    || !converted.every((coordinate) => Number.isFinite(coordinate))
    || !chart.containPixel({ gridIndex: 0 }, converted)
  ) {
    repairDetailPosition.value = null;
    return;
  }

  const chartSize = chart.getSize();
  const cardRect = card.getBoundingClientRect();
  if (chartSize.width <= 0 || chartSize.height <= 0) {
    repairDetailPosition.value = null;
    return;
  }
  repairDetailPosition.value = placeRepairDetailCard(converted, chartSize, {
    width: cardRect.width || REPAIR_CARD_FALLBACK_WIDTH,
    height: cardRect.height || REPAIR_CARD_FALLBACK_HEIGHT,
  });
};

const dispatchRepairState = (
  type: "highlight" | "downplay",
  repairPoint: SelectedRepairPoint
) => {
  compareChartRef.value?.dispatchAction({
    type,
    seriesId: repairPoint.seriesId,
    dataIndex: repairPoint.dataIndex,
  });
};

const clearSelectedRepair = () => {
  const previous = selectedRepairPoint.value;
  if (previous) dispatchRepairState("downplay", previous);
  ++repairPositionRequestId;
  selectedRepairPoint.value = null;
  repairDetailPosition.value = null;
};

const handleChartClick = (params: unknown) => {
  const event = params as ChartClickEvent;
  if (
    typeof event.seriesId !== "string"
    || !REPAIR_SERIES_IDS.has(event.seriesId)
    || typeof event.dataIndex !== "number"
    || !isRepairMarkerDatum(event.data)
  ) return;

  const selected = selectedChartSeries.value;
  const index = event.data.projectedIndex;
  if (!selected || index < 0 || index >= selected.timestamps.length) return;

  const previous = selectedRepairPoint.value;
  if (previous) dispatchRepairState("downplay", previous);

  const next: SelectedRepairPoint = {
    channel: selected.column,
    projectedIndex: index,
    timestamp: selected.timestamps[index],
    rawValue: selected.raw_series[index] ?? null,
    cleanedValue: selected.cleaned_series[index] ?? null,
    repairTypes: [...event.data.repairTypes],
    markerCategory: event.data.markerCategory,
    seriesId: event.data.visualSeriesId,
    dataIndex: event.data.visualDataIndex,
  };
  repairDetailPosition.value = null;
  selectedRepairPoint.value = next;
  dispatchRepairState("highlight", next);
  void updateRepairDetailPosition();
};

const resetChartZoom = () => {
  compareChartRef.value?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  void updateRepairDetailPosition();
};

watch(selectedChartColumn, (column, previousColumn) => {
  if (column !== previousColumn && selectedRepairPoint.value) clearSelectedRepair();
});

const compareChartOptions = computed(() => {
  const selected = selectedChartSeries.value;
  if (!selected) return {};
  const repairs = repairTypesByIndex(selected);
  const markerData: Record<RepairMarkerCategory, RepairMarkerDatum[]> = {
    interpolation: [],
    outlier: [],
    smoothing: [],
    combined: [],
  };
  for (const [index, repairTypes] of repairs) {
    const cleanedValue = selected.cleaned_series[index];
    if (cleanedValue === null) continue;
    const markerType: RepairType | "combined" = repairTypes.length > 1
      ? "combined"
      : repairTypes[0] ?? "combined";
    const visualDataIndex = markerData[markerType].length;
    markerData[markerType].push({
      value: [selected.timestamps[index], cleanedValue],
      repairPoint: true,
      projectedIndex: index,
      repairTypes: [...repairTypes],
      markerCategory: markerType,
      visualSeriesId: REPAIR_VISUAL_SERIES_IDS[markerType],
      visualDataIndex,
    });
  }
  const repairHitAreaData = Object.values(markerData).flat();

  return {
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(248, 248, 244, 0.97)",
      borderColor: "#C5CEC6",
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: "#34443A", fontSize: 12, lineHeight: 20 },
      formatter: (params: unknown) => {
        const first = (Array.isArray(params) ? params[0] : params) as { axisValue?: unknown } | undefined;
        const timestamp = typeof first?.axisValue === "string" ? first.axisValue : "";
        const index = selected.timestamps.indexOf(timestamp);
        const repairTypes = index >= 0 ? repairs.get(index) ?? [] : [];
        const repairLine = repairTypes.length
          ? `<br/>修复：<br/>${repairTypes.map((type) => `· ${REPAIR_TYPE_LABELS[type]}`).join("<br/>")}`
          : "";
        const raw = index >= 0 ? selected.raw_series[index] : null;
        const cleaned = index >= 0 ? selected.cleaned_series[index] : null;
        return [
          `通道：${selected.column}`,
          `时间：${formatTooltipTimestamp(timestamp)}`,
          `处理前：${formatChartValue(raw)}`,
          `处理后：${formatChartValue(cleaned)}`,
        ].join("<br/>") + repairLine;
      },
    },
    legend: {
      data: ["原始序列 Raw", "清洗后序列 Cleaned", "插值填补", "异常替换", "平滑调整"],
      top: 2,
      left: "center",
      itemGap: 18,
      itemWidth: 20,
      itemHeight: 9,
      textStyle: { color: "#536158", fontSize: 11 },
    },
    grid: { left: "3%", right: "4%", bottom: 72, top: "16%", containLabel: true },
    dataZoom: [
      {
        id: "cleaning-inside-zoom",
        type: "inside",
        xAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: "ctrl",
        moveOnMouseWheel: false,
        moveOnMouseMove: true,
        preventDefaultMouseMove: false,
      },
      {
        id: "cleaning-slider-zoom",
        type: "slider",
        xAxisIndex: 0,
        filterMode: "none",
        height: 18,
        bottom: 8,
        showDetail: false,
        brushSelect: false,
        backgroundColor: "#F2F5F1",
        borderColor: "#CDD5CE",
        fillerColor: "rgba(85, 117, 98, 0.18)",
        dataBackground: {
          lineStyle: { color: "#AEB9B0", opacity: 0.55 },
          areaStyle: { color: "#E4E9E4", opacity: 0.45 },
        },
        selectedDataBackground: {
          lineStyle: { color: "#667D6E", opacity: 0.8 },
          areaStyle: { color: "#BFCBC1", opacity: 0.45 },
        },
        handleSize: "90%",
        handleStyle: {
          color: "#F8F9F6",
          borderColor: "#738579",
          borderWidth: 1,
        },
        moveHandleStyle: { color: "#85968A", opacity: 0.65 },
      },
    ],
    xAxis: {
      type: "category",
      data: selected.timestamps,
      axisLabel: { formatter: formatAxisTimestamp, hideOverlap: true },
    },
    yAxis: { type: "value" },
    series: [
      {
        id: "cleaning-raw-line",
        name: "原始序列 Raw",
        type: "line",
        xAxisIndex: 0,
        color: "#A8665E",
        lineStyle: { type: "dashed", width: 1.8, opacity: 0.72 },
        symbol: "none",
        z: 2,
        data: selected.raw_series,
      },
      {
        id: "cleaning-cleaned-line",
        name: "清洗后序列 Cleaned",
        type: "line",
        xAxisIndex: 0,
        color: "#557562",
        lineStyle: { width: 2.6 },
        symbol: "none",
        z: 3,
        data: selected.cleaned_series,
      },
      {
        id: REPAIR_VISUAL_SERIES_IDS.interpolation,
        name: "插值填补",
        type: "scatter",
        xAxisIndex: 0,
        symbol: "circle",
        symbolSize: 8,
        color: "#B5965D",
        itemStyle: { borderColor: "#FAF8F1", borderWidth: 1.4 },
        emphasis: {
          scale: 1.35,
          itemStyle: { borderColor: "#40564A", borderWidth: 2.5 },
        },
        z: 7,
        data: markerData.interpolation,
      },
      {
        id: REPAIR_VISUAL_SERIES_IDS.outlier,
        name: "异常替换",
        type: "scatter",
        xAxisIndex: 0,
        symbol: "diamond",
        symbolSize: 11,
        color: "#A76155",
        itemStyle: { borderColor: "#FAF6F3", borderWidth: 1.4 },
        emphasis: {
          scale: 1.35,
          itemStyle: { borderColor: "#40564A", borderWidth: 2.5 },
        },
        z: 8,
        data: markerData.outlier,
      },
      {
        id: REPAIR_VISUAL_SERIES_IDS.smoothing,
        name: "平滑调整",
        type: "scatter",
        xAxisIndex: 0,
        symbol: "triangle",
        symbolSize: 9,
        color: "#768A8D",
        itemStyle: { borderColor: "#F4F7F6", borderWidth: 1.4 },
        emphasis: {
          scale: 1.35,
          itemStyle: { borderColor: "#40564A", borderWidth: 2.5 },
        },
        z: 7,
        data: markerData.smoothing,
      },
      {
        id: REPAIR_VISUAL_SERIES_IDS.combined,
        name: "组合修复",
        type: "scatter",
        xAxisIndex: 0,
        symbol: "circle",
        symbolSize: 12,
        color: "#4E6759",
        itemStyle: { borderColor: "#DCE4DD", borderWidth: 3 },
        emphasis: {
          scale: 1.3,
          itemStyle: { borderColor: "#40564A", borderWidth: 4 },
        },
        z: 9,
        data: markerData.combined,
      },
      {
        id: REPAIR_HIT_AREA_SERIES_ID,
        type: "scatter",
        xAxisIndex: 0,
        symbol: "circle",
        symbolSize: 20,
        silent: false,
        legendHoverLink: false,
        tooltip: { show: false },
        itemStyle: { color: "rgba(0, 0, 0, 0.001)" },
        emphasis: { disabled: true },
        z: 20,
        data: repairHitAreaData,
      },
    ],
    animation: false,
  };
});

const cleaningResultSummary = computed(() => {
  if (!cleanedData.value) return "";
  const effectiveVersion = versionNodes.value.find(
    (version) => version.id === cleanedData.value?.effective_version_id
  );
  const effectiveLabel = effectiveVersion
    ? versionDisplayName(effectiveVersion)
    : shortVersionId(cleanedData.value.effective_version_id);
  if (cleanedData.value.reused_existing_version) {
    return `相同清洗结果已存在，已复用现有数据版本。当前有效版本：${effectiveLabel}。`;
  }
  if (!cleanedData.value.created_new_version && cleanedData.value.converged) {
    return `清洗结果已收敛，本次未产生新的数据版本。当前有效版本：${effectiveLabel}；修改单元：0。`;
  }
  if (cleanedData.value.no_op) {
    return `数据无需修复，已完成清洗认证并生成 Cleaning Version。当前有效版本：${effectiveLabel}；修改单元：0。`;
  }
  const changes = cleanedData.value.summary?.changes;
  if (!changes || changes.breakdown_status === "not_recorded") {
    return `共修复 ${cleanedData.value.total_cleaned_points} 个唯一数据单元格；历史结果未记录分类明细。`;
  }
  const parts = [
    `缺失值填补 ${changes.missing_value_fills ?? 0} 个`,
    `异常值替换 ${changes.outlier_replacements ?? 0} 个`,
    `平滑修改 ${changes.smoothing_changes ?? 0} 个`,
  ];
  const rowOperations = [
    `重复时间戳处理 ${changes.duplicate_timestamps_processed ?? 0} 行`,
    `重采样新增空行 ${changes.resampling_empty_rows_created ?? 0} 行`,
  ];
  const overlap = changes.category_counts_may_overlap
    ? "各类别可能重叠，总数按唯一变更单元格去重。"
    : "";
  return `共修复 ${changes.unique_changed_cells ?? cleanedData.value.total_cleaned_points} 个唯一数据单元格：${parts.join("、")}；另有${rowOperations.join("、")}。${overlap}`;
});

onMounted(() => {
  void initializeDatasets();
});
</script>

<style scoped>
.cleaning-view {
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

/* Hero Bar */
.cleaning-hero-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}

.source-context-card {
  padding: 20px 24px;
  background: #ffffff;
}

.source-context-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.source-context-header h3,
.source-context-header p {
  margin: 0;
}

.source-context-header h3 {
  margin-top: 5px;
  font-size: 16px;
}

.source-context-header p {
  font-size: 12px;
  color: var(--text-muted);
}

.source-context-eyebrow {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: normal;
  font-family: var(--font-sans);
  color: var(--color-primary);
}

.source-control-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(320px, 1.2fr);
  gap: 16px;
  padding-top: 16px;
}

.source-control {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.source-control > label {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.source-control :deep(.el-select) {
  width: 100%;
}

.dataset-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.dataset-option small {
  color: var(--text-faint);
}

.context-alert {
  margin-top: 14px;
}

.source-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
  padding: 13px 14px;
  border: 1px solid #dce7da;
  border-radius: 8px;
  background: #f7faf6;
}

.source-summary > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.source-summary span {
  font-size: 10px;
  color: var(--text-muted);
}

.source-summary strong {
  overflow: hidden;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-summary .source-ready {
  color: #466f43;
}

/* Format 1: Horizontal Toolbar */
.cleaning-toolbar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 20px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
  flex-wrap: wrap;
}

.toolbar-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tb-label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.cleaning-view .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.tb-divider {
  width: 1px;
  height: 38px;
  background: var(--border-light);
}

.tb-actions {
  margin-left: auto;
  display: flex;
  align-items: flex-end;
  padding-top: 18px;
}

/* Full-width Waveform Deck */
.waveform-inspection-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.chart-channel-control {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.chart-channel-control label {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.header-pills {
  margin-left: 12px;
}

.cleaning-chart-stage {
  position: relative;
}

.repair-detail-card {
  position: absolute;
  z-index: 12;
  width: min(252px, calc(100% - 44px));
  box-sizing: border-box;
  padding: 14px 15px;
  border: 1px solid #cbd5cc;
  border-radius: 8px;
  background: rgba(250, 250, 247, 0.96);
  box-shadow: 0 8px 22px rgba(49, 65, 54, 0.13);
  color: var(--text-primary);
  backdrop-filter: blur(3px);
}

.repair-detail-card.is-anchor-hidden {
  visibility: hidden;
  pointer-events: none;
}

.repair-detail-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.repair-detail-card__eyebrow {
  display: block;
  margin-bottom: 2px;
  font-family: var(--font-sans);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: normal;
  color: #65796b;
}

.repair-detail-card h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
}

.repair-detail-card__close {
  display: grid;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: #748178;
  font: 18px/1 var(--font-sans);
  cursor: pointer;
  place-items: center;
}

.repair-detail-card__close:hover,
.repair-detail-card__close:focus-visible {
  border-color: #c7d0c8;
  background: #eef2ed;
  color: #40564a;
  outline: none;
}

.repair-detail-card__category {
  display: block;
  margin-top: 10px;
  padding: 5px 8px;
  border-left: 3px solid #73887a;
  background: #eef3ed;
  font-size: 12px;
  font-weight: 650;
  color: #40564a;
}

.repair-detail-card__fields {
  display: grid;
  gap: 7px;
  margin: 12px 0;
}

.repair-detail-card__fields > div:not(.repair-detail-card__arrow) {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
}

.repair-detail-card dt,
.repair-detail-card__types > span {
  font-size: 10px;
  color: var(--text-muted);
}

.repair-detail-card dd {
  overflow-wrap: anywhere;
  margin: 0;
  font-family: var(--font-sans);
  font-size: 11px;
  color: #34443a;
}

.repair-detail-card__arrow {
  padding-left: 55px;
  color: #819087;
  font-size: 11px;
  line-height: 0.7;
}

.repair-detail-card__types {
  padding-top: 10px;
  border-top: 1px solid #dce3dc;
}

.repair-detail-card__types ul {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 10px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.repair-detail-card__types li {
  font-size: 11px;
  color: #45564b;
}

.repair-detail-card__types i {
  margin-right: 3px;
  color: #687d6f;
  font-style: normal;
}

.clean-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 70px 20px;
  text-align: center;
}

.clean-empty-icon {
  width: 50px;
  height: 50px;
  border-radius: 12px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  margin-bottom: 12px;
}

.clean-empty-state h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.clean-empty-state p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 440px;
}

/* 3-Card Triage */
.triage-cards-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.triage-card {
  display: flex;
  gap: 14px;
  padding: 16px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.triage-num {
  font-size: 13px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.triage-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.triage-title {
  font-size: 11px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: normal;
  font-family: var(--font-sans);
}

.triage-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.next-triage-card {
  cursor: pointer;
  border-color: var(--border-default);
  background: var(--surface-1);
  transition: all 0.2s ease;
}

.next-triage-card:hover {
  transform: translateY(-2px);
  background: var(--surface-2);
  border-color: var(--border-strong);
}

.validation-issues {
  margin: 6px 0 0;
  padding-left: 16px;
  font-size: 12px;
}

@media (max-width: 1000px) {
  .source-context-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .source-control-grid,
  .source-summary {
    grid-template-columns: 1fr;
  }
  .cleaning-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .tb-divider {
    display: none;
  }
  .tb-actions {
    margin-left: 0;
    padding-top: 0;
  }
  .triage-cards-grid {
    grid-template-columns: 1fr;
  }
}
</style>
