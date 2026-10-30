<template>
  <div class="page-container segmentation-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge">STAGE 03 · D-OPTIMAL SEGMENTATION</div>
      <div class="stage-links">
        <span class="stage-link" @click="$router.push('/preprocessing/cleaning')">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link active">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/delay')">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/collinearity')">05 VIF 降维</span>
      </div>
    </div>

    <!-- Header with Breadcrumb & Quick Action -->
    <div class="page-header-row">
      <div class="page-header">
        <span class="page-eyebrow">FISHER INFORMATION MATRIX DET-MAXIMIZATION</span>
        <h2>质量约束 D-最优区间剪辑工作台</h2>
        <p class="subtitle">先做质量门控过滤稳态与坏段，再由 CELF 延迟贪心算法截取信息量极大化高动态过渡带</p>
      </div>

      <div class="top-segment-trigger">
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          :disabled="!selectedVersion || loadingVersions"
          icon="Search"
          @click="handleSegment"
        >
          执行门控与 D-最优区间剪辑
        </el-button>
      </div>
    </div>

    <section class="industrial-card source-context-card" aria-labelledby="source-context-title">
      <div class="source-context-header">
        <div>
          <span class="source-context-eyebrow">ANALYSIS CONTEXT</span>
          <h3 id="source-context-title">Stage 03 分析上下文</h3>
        </div>
        <p>仅清洗规整完成后的版本可作为 D-最优正式分析源。</p>
      </div>

      <div class="source-control-grid">
        <div class="source-control">
          <label for="segmentation-dataset">数据集</label>
          <el-select
            id="segmentation-dataset"
            v-model="selectedDatasetId"
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
          <label>分析源版本</label>
          <VersionLineagePicker
            :dataset-name="selectedDataset?.name ?? ''"
            :versions="versionNodes"
            :selected-version-id="selectedVersionId"
            :loading="loadingVersions"
            context-label="清洗规整版本可用于 Stage 03"
            eligible-label="可用于 D-最优"
            empty-state-text="暂无可用于 D-最优分析的清洗规整版本。"
            empty-state-hint="请先完成 Stage 02 时间清洗。"
            :is-eligible="isEligibleVersion"
            :disabled-reason="ineligibleReason"
            @select="handleVersionSelect"
          />
        </div>
      </div>

      <el-alert v-if="contextError" type="error" :closable="false" show-icon class="context-alert">
        <template #title>{{ contextError }}</template>
      </el-alert>

      <div v-if="selectedVersion" class="source-summary" data-test="source-summary">
        <div><span>当前分析源</span><strong>{{ versionDisplayName(selectedVersion) }}</strong></div>
        <div><span>数据集</span><strong>{{ selectedDataset?.name }}</strong></div>
        <div><span>创建时间</span><strong>{{ formatVersionDate(selectedVersion.created_at) }}</strong></div>
        <div><span>来源</span><strong>{{ selectedParent ? versionDisplayName(selectedParent) : "初始版本" }}</strong></div>
        <div><span>版本 ID</span><strong class="font-mono">{{ shortVersionId(selectedVersion.id) }}</strong></div>
        <div><span>Stage 03</span><strong class="source-ready">可执行 D-最优区间优选</strong></div>
      </div>
    </section>

    <!-- FORMAT 2: Collapsible Top Parameter Bar with Badges -->
    <div class="industrial-card segment-param-bar">
      <div class="param-grid-row">
        <div class="param-item">
          <label>输入变量 (u)</label>
          <el-input v-model="inputColumnsText" placeholder="u1,u2,u3" size="small" />
        </div>
        <div class="param-item">
          <label>输出变量 (y)</label>
          <el-input v-model="form.output_column" placeholder="y" size="small" />
        </div>
        <div class="param-item">
          <label>窗长 (L)</label>
          <el-input-number v-model="form.window_size" :min="5" :max="2000" :step="10" size="small" />
        </div>
        <div class="param-item">
          <label>保留段数 (K)</label>
          <el-input-number v-model="form.max_segments" :min="1" :max="100" size="small" />
        </div>
        <div class="param-item">
          <label>最低 SNR (dB)</label>
          <el-input-number v-model="form.min_snr_db" :min="-20" :max="60" size="small" />
        </div>
      </div>
    </div>

    <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
      <template #title>优选失败：{{ errorMessage }}</template>
    </el-alert>

    <!-- FORMAT 2: Full-Width Waveform Scrubber with Floating KPI HUD (全景时序切片看板) -->
    <section class="industrial-card scrubber-card">
      <div class="scrubber-header">
        <div class="scrubber-title">
          <el-icon><DataLine /></el-icon>
          <span>全景响应时序与选定过渡带切片 (SELECTED D-OPTIMAL SLICES)</span>
        </div>
        <div class="scrubber-badges" v-if="result && result.selection">
          <el-tag :type="result.selection.excitation_satisfied ? 'success' : 'danger'" effect="light">
            {{ result.selection.excitation_satisfied ? "🟢 持续激励条件满足" : "🔴 持续激励不足" }}
          </el-tag>
        </div>
      </div>

      <!-- Floating 5-KPI HUD -->
      <div class="hud-kpi-bar" v-if="result && result.selection">
        <div class="hud-item">
          <span class="hud-label">CANDIDATES</span>
          <span class="hud-val">{{ result.selection.candidate_count }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label">GATED PASS</span>
          <span class="hud-val text-cyan">{{ result.selection.gated_count }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label">SELECTED SEGMENTS</span>
          <span class="hud-val text-primary">{{ result.selection.selected_count }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label">SAMPLE COVERAGE</span>
          <span class="hud-val text-green">{{ percent(result.selection.coverage_ratio) }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label">COND NUMBER</span>
          <span class="hud-val">{{ formatNumber(result.selection.design_matrix_condition_number) }}</span>
        </div>
      </div>

      <div v-if="result && result.selection">
        <ChartContainer :options="chartOptions" height="340px" />
      </div>
      <div class="scrubber-empty" v-else>
        <el-icon><Crop /></el-icon>
        <p>输入参数后点击右上角「执行门控与 D-最优区间剪辑」，在此高亮渲染全景时序与黄金区间切片。</p>
      </div>
    </section>

    <!-- FORMAT 2: Master-Detail Dual Table & Quality Filter Funnel (主从双表决策看板) -->
    <div class="segment-master-detail-grid" v-if="result && result.selection">
      <!-- Left: Selected Segments Leaderboard -->
      <div class="industrial-card detail-pane">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><TrendCharts /></el-icon>
            <span>优选区间贡献排行榜</span>
          </div>
          <span class="card-tag">RANKED LIST</span>
        </div>

        <el-table :data="result.segments" stripe height="280" style="width: 100%">
          <el-table-column prop="rank" label="排名" width="70">
            <template #default="{ row }">
              <span class="rank-badge">#{{ row.rank }}</span>
            </template>
          </el-table-column>
          <el-table-column label="样本索引区间" width="160">
            <template #default="{ row }">
              <span>[{{ row.start_index }} - {{ row.end_index }}]</span>
            </template>
          </el-table-column>
          <el-table-column label="区间点数" width="100">
            <template #default="{ row }">
              <span><span>{{ row.end_index - row.start_index }}</span> 点</span>
            </template>
          </el-table-column>
          <el-table-column label="信噪比 SNR" width="110">
            <template #default="{ row }">
              <span class="text-green">{{ formatNumber(row.snr_db) }} dB</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- Right: Gated Funnel Breakdown -->
      <div class="industrial-card detail-pane">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Filter /></el-icon>
            <span>质量门控过滤漏斗明细</span>
          </div>
          <el-tag type="info" effect="plain">共扫描 {{ result.gated_windows.length }} 个窗口</el-tag>
        </div>

        <el-table :data="result.gated_windows" stripe height="280" style="width: 100%">
          <el-table-column prop="window_index" label="窗口" width="70" />
          <el-table-column label="样本范围" width="140">
            <template #default="{ row }">
              <span>[{{ row.start_index }} - {{ row.end_index }}]</span>
            </template>
          </el-table-column>
          <el-table-column label="门控状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.accepted ? 'success' : 'info'" size="small">
                {{ row.accepted ? "通过" : "剔除" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="缺失率" width="80">
            <template #default="{ row }">{{ percent(row.missing_ratio) }}</template>
          </el-table-column>
          <el-table-column label="剔除原因">
            <template #default="{ row }">
              <span v-if="!row.rejection_reasons.length">—</span>
              <el-tag
                v-for="reason in row.rejection_reasons"
                :key="reason"
                size="small"
                type="warning"
                effect="plain"
                class="rejection-tag"
              >
                {{ reasonLabel(reason) }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Crop, DataLine, Filter, TrendCharts } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import VersionLineagePicker from "../components/versioning/VersionLineagePicker.vue";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../api/datasets";
import { segmentDataset } from "../api/preprocessing";
import type {
  DatasetItem,
  DatasetVersionNode,
  SegmentRequest,
  SegmentResponse,
} from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage } from "element-plus";
import { useDatasetStore } from "../stores/datasetStore";
import {
  formatVersionDate,
  shortVersionId,
  versionDisplayName,
} from "../utils/versionOperation";

const REASON_LABELS: Record<string, string> = {
  missing_ratio_exceeded: "缺失率超限",
  anomaly_ratio_exceeded: "异常率超限",
  snr_below_threshold: "信噪比不足",
  steady_state_segment: "稳态段",
  no_input_excitation: "输入无激励",
};

const STAGE_03_SOURCE_OPERATION = "preprocessing.clean";

const datasetStore = useDatasetStore();
const loading = ref(false);
const loadingDatasets = ref(false);
const loadingVersions = ref(false);
const result = ref<SegmentResponse | null>(null);
const errorMessage = ref("");
const contextError = ref("");
const inputColumnsText = ref("u1,u2,u3");
const datasetOptions = ref<DatasetItem[]>([]);
const selectedDatasetId = ref<string | null>(null);
const selectedDataset = ref<DatasetItem | null>(null);
const versionNodes = ref<DatasetVersionNode[]>([]);
const selectedVersionId = ref<string | null>(null);
const rememberedSourceByDataset = new Map<string, string>();
let contextRequestId = 0;

const form = reactive<SegmentRequest>({
  version_id: "",
  input_columns: [],
  output_column: "y",
  window_size: 60,
  max_segments: 8,
  min_snr_db: 0,
  max_missing_ratio: 0.2,
  max_anomaly_ratio: 0.1,
});

const activeDataset = computed(() => datasetStore.activeDataset);
const selectedVersion = computed(
  () => versionNodes.value.find((node) => node.id === selectedVersionId.value) ?? null
);
const selectedParent = computed(() => {
  const parentId = selectedVersion.value?.parent_version_id;
  if (!parentId) return null;
  return versionNodes.value.find((node) => node.id === parentId) ?? null;
});
function isEligibleVersion(node: DatasetVersionNode) {
  return node.tool === STAGE_03_SOURCE_OPERATION;
}

const ineligibleReason = (node: DatasetVersionNode) => {
  if (node.tool === "simulation_generate" || node.tool === "raw_upload") {
    return "需先完成清洗规整";
  }
  if (
    node.tool === "preprocessing.lag_compensation" ||
    node.tool === "preprocessing.feature_selection"
  ) {
    return "已进入后续阶段，不作为 D-最优正式分析源";
  }
  return "该处理阶段不符合 D-最优分析源要求";
};

const clearSourceContext = () => {
  versionNodes.value = [];
  selectedVersionId.value = null;
  form.version_id = "";
  result.value = null;
  errorMessage.value = "";
};

const handleVersionSelect = (versionId: string) => {
  const node = versionNodes.value.find((version) => version.id === versionId);
  if (!node || !isEligibleVersion(node) || !selectedDatasetId.value) return;
  selectedVersionId.value = versionId;
  form.version_id = versionId;
  rememberedSourceByDataset.set(selectedDatasetId.value, versionId);
  result.value = null;
  errorMessage.value = "";
};

const chooseDefaultVersion = (nodes: DatasetVersionNode[], dataset: DatasetItem) => {
  const eligible = nodes.filter(isEligibleVersion);
  if (!eligible.length) return;

  const rememberedId = rememberedSourceByDataset.get(dataset.id);
  const activeVersionId = activeDataset.value?.id === dataset.id
    ? activeDataset.value.version_id || activeDataset.value.latest_version_id
    : null;
  const preferred = eligible.find((node) => node.id === rememberedId)
    ?? eligible.find((node) => node.id === activeVersionId)
    ?? [...eligible].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0];

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

    selectedDataset.value = dataset;
    datasetStore.setActiveDataset(dataset);
    inputColumnsText.value = dataset.input_columns.join(",");
    form.output_column = dataset.output_column ?? "y";
    versionNodes.value = versions.nodes;
    chooseDefaultVersion(versions.nodes, dataset);
  } catch (err) {
    if (requestId !== contextRequestId) return;
    selectedDataset.value = null;
    contextError.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    if (requestId === contextRequestId) loadingVersions.value = false;
  }
};

const handleDatasetChange = (datasetId: string) => {
  if (!datasetId) {
    ++contextRequestId;
    selectedDataset.value = null;
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
    const current = activeDataset.value;
    if (current && response.items.some((dataset) => dataset.id === current.id)) {
      selectedDatasetId.value = current.id;
      await loadDatasetContext(current.id);
    }
  } catch (err) {
    contextError.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    loadingDatasets.value = false;
  }
};

onMounted(() => {
  void initializeDatasets();
});

const handleSegment = async () => {
  errorMessage.value = "";
  if (!selectedVersion.value || !isEligibleVersion(selectedVersion.value)) {
    errorMessage.value = "请先选择可用于 D-最优的清洗规整版本。";
    return;
  }
  form.version_id = selectedVersion.value.id;
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
    result.value = await segmentDataset(form);
    ElMessage.success(
      `优选完成：${result.value.selection?.selected_count ?? 0} 个区间，采样占比 ${percent(
        result.value.selection?.coverage_ratio ?? 0
      )}`
    );
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};

const outputSeries = computed<(number | null)[]>(() => {
  if (!result.value) return [];
  return result.value.series[form.output_column] ?? [];
});

const chartOptions = computed(() => {
  const values = outputSeries.value;
  const marks = (result.value?.segments ?? []).map((segment) => [
    { name: `#${segment.rank ?? ""}`, xAxis: segment.start_index },
    { xAxis: segment.end_index },
  ]);
  return {
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "4%", bottom: "12%", top: "8%", containLabel: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 20, bottom: 2 }],
    xAxis: { type: "category", data: values.map((_, index) => index) },
    yAxis: { type: "value", scale: true },
    series: [
      {
        name: form.output_column,
        type: "line",
        showSymbol: false,
        color: "#6E9B69",
        lineStyle: { width: 2 },
        data: values,
        markArea: {
          itemStyle: { color: "rgba(130, 169, 120, 0.15)", borderColor: "rgba(130, 169, 120, 0.35)", borderWidth: 1 },
          data: marks,
        },
      },
    ],
  };
});

const reasonLabel = (reason: string) => REASON_LABELS[reason] ?? reason;

const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10000) return value.toExponential(2);
  return value.toFixed(3);
};
</script>

<style scoped>
.segmentation-view {
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

.page-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}

.source-context-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
}

.source-context-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.source-context-header h3 {
  margin: 3px 0 0;
  font-family: var(--font-sans);
  font-size: 16px;
  font-weight: 650;
  color: var(--text-primary);
}

.source-context-header p {
  margin: 0;
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

/* Format 2: Parameter Bar */
.segment-param-bar {
  padding: 14px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.param-grid-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-item label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.alert-gap {
  margin-top: 4px;
}

/* Scrubber Card */
.scrubber-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.scrubber-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.scrubber-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: normal;
}

.segmentation-view .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.hud-kpi-bar {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 10px 16px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 14px;
}

.hud-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.hud-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.hud-val {
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.hud-sep {
  width: 1px;
  height: 28px;
  background: var(--border-light);
}

.text-primary { color: var(--color-primary); }
.text-cyan { color: #0284c7; }
.text-green { color: #059669; }

.scrubber-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: var(--text-muted);
}

.scrubber-empty .el-icon {
  font-size: 32px;
  margin-bottom: 8px;
  color: var(--color-primary);
}

/* Master-Detail Dual Pane */
.segment-master-detail-grid {
  display: grid;
  grid-template-columns: 1.1fr 1.4fr;
  gap: 20px;
}

.detail-pane {
  padding: 18px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  margin-bottom: 0;
}

.rank-badge {
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 1px 6px;
  border-radius: 4px;
}

.card-tag {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.rejection-tag {
  margin-right: 4px;
}

@media (max-width: 1100px) {
  .source-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .param-grid-row {
    grid-template-columns: repeat(3, 1fr);
  }
  .segment-master-detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .source-context-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .source-control-grid,
  .source-summary {
    grid-template-columns: 1fr;
  }
  .param-grid-row {
    grid-template-columns: 1fr;
  }
  .hud-kpi-bar {
    flex-direction: column;
    gap: 8px;
  }
  .hud-sep {
    display: none;
  }
}
</style>
