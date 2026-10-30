<template>
  <div class="page-container arx-view">
    <PageHeader
      eyebrow="SYSTEM IDENTIFICATION / ARX & FIR"
      title="ARX / FIR 系统辨识与模型评价"
      description="辨识过程动态或正则化脉冲响应，用验证集自由仿真误差检查模型质量"
    />

    <div class="modeling-layout">
      <section class="industrial-card source-context-card" aria-labelledby="arx-source-title">
        <div class="source-context-header">
          <div>
            <span class="source-context-eyebrow">MODELING CONTEXT</span>
            <h3 id="arx-source-title">ARX 建模上下文</h3>
          </div>
          <p>仅可信时滞补偿版本，或其特征优选后代，可进入 ARX 辨识。</p>
        </div>

        <div class="source-control-grid">
          <div class="source-control">
            <label for="arx-dataset">数据集</label>
            <el-select
              id="arx-dataset"
              v-model="selectedDatasetId"
              data-test="arx-dataset-select"
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
            <label>建模源版本</label>
            <VersionLineagePicker
              data-test="arx-source-picker"
              :dataset-name="selectedDataset?.name ?? ''"
              :versions="versionNodes"
              :selected-version-id="selectedVersionId"
              :loading="loadingVersions"
              context-label="具备可信时滞补偿血缘的版本可用于 ARX 建模"
              eligible-label="可用于 ARX 建模"
              empty-state-text="暂无可用于 ARX 建模的数据版本。"
              empty-state-hint="请先完成时滞补偿。"
              placeholder="选择 ARX 建模源版本"
              :is-eligible="isArxEligibleVersion"
              :disabled-reason="arxDisabledReason"
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

        <div v-if="selectedVersion" class="source-summary" data-test="arx-source-summary">
          <div><span>当前建模源</span><strong>{{ versionDisplayName(selectedVersion) }}</strong></div>
          <div><span>数据集</span><strong>{{ selectedDataset?.name }}</strong></div>
          <div><span>创建时间</span><strong>{{ formatVersionDate(selectedVersion.created_at) }}</strong></div>
          <div><span>来源</span><strong>{{ selectedParent ? versionDisplayName(selectedParent) : "初始版本" }}</strong></div>
          <div><span>版本 ID</span><strong class="font-mono">{{ shortVersionId(selectedVersion.id) }}</strong></div>
          <div><span>ARX 状态</span><strong class="source-ready">{{ arxReadyLabel(selectedVersion) }}</strong></div>
        </div>

        <p v-if="selectedVersion" class="dataset-meta">
          过程输入：<span class="code-inline">{{ inputCols.join(", ") }}</span> |
          目标输出：<span class="code-inline">{{ selectedDataset?.output_column }}</span>
        </p>
      </section>

      <!-- Model Config Card -->
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Cpu /></el-icon> 模型结构与求解器设置
          </div>
        </div>

        <el-form :model="form" class="parameter-form-grid">
          <el-form-item label="模型类型">
            <el-select v-model="form.model_type" @change="handleModelFamilyChange">
              <el-option label="ARX" value="ARX" />
              <el-option label="正则 FIR" value="FIR" />
              <el-option label="多步模拟 OE（实验）" value="OE" />
            </el-select>
          </el-form-item>
          <el-form-item label="输出阶数 na" v-if="form.model_type !== 'FIR'">
            <el-input-number v-model="form.na" :min="1" :max="form.model_type === 'OE' ? 4 : 100" />
          </el-form-item>

          <el-form-item
            v-for="(col, idx) in inputCols"
            :key="'nb_' + col"
            :label="`输入 ${col} 阶数 nb`"
          >
            <el-input-number v-model="form.nb[idx]" :min="1" :max="100" />
          </el-form-item>

          <el-form-item
            v-for="(col, idx) in inputCols"
            :key="'delay_' + col"
            :label="`输入 ${col} 滞后 d`"
          >
            <el-input-number v-model="form.delays[idx]" :min="0" :max="20" />
          </el-form-item>

          <el-form-item label="求解算法" v-if="form.model_type !== 'OE'">
            <el-select v-model="form.estimation_method" :disabled="form.model_type === 'FIR'">
              <el-option label="最小二乘 (OLS)" value="ols" />
              <el-option label="岭回归 (Ridge)" value="ridge" />
              <el-option label="鲁棒回归 (Huber)" value="huber" />
            </el-select>
          </el-form-item>

          <el-form-item label="模拟训练" v-if="form.model_type === 'OE'">
            <span>同时拟合 1、16、64 步及整段模拟，约束模型稳定。每个连续训练片段至少需 16 行且多于参数数；仅支持 0/1 样本权重。</span>
          </el-form-item>

          <el-form-item label="脉冲响应衰减 β" v-if="form.model_type === 'FIR'">
            <el-input-number v-model="form.kernel_decay" :min="0.1" :max="0.99" :step="0.05" />
          </el-form-item>
          <el-form-item label="预测初始基线">
            <el-select v-model="form.initialization_policy" :disabled="form.model_type === 'OE'">
              <el-option label="使用训练基线" value="fixed" />
              <el-option label="用预测前历史估计持续扰动" value="past_residual" />
            </el-select>
          </el-form-item>
          <el-form-item label="历史样本数" v-if="form.initialization_policy === 'past_residual'">
            <el-input-number v-model="form.initialization_window" :min="8" :max="128" />
            <span>自由仿真期间冻结补偿量；ARX 须稳定，并假设预测期间扰动持续。</span>
          </el-form-item>
          <el-form-item label="岭惩罚 α" v-if="form.estimation_method === 'ridge'">
            <el-input-number v-model="form.ridge_alpha" :min="0.001" :max="10" :step="0.1" />
          </el-form-item>

          <el-form-item class="parameter-form-actions">
            <el-button
              data-test="arx-fit-button"
              type="primary"
              :loading="loading"
              :disabled="!selectedVersion || loadingVersions || loading"
              icon="VideoPlay"
              @click="handleFit"
            >
              运行 ARX 辨识
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- Evaluation Metrics -->
      <div class="industrial-card" v-if="fitResult">
        <InputSupportWarning :support="fitResult.validation?.input_support" />
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Trophy /></el-icon> 辨识结果与训练 / 验证指标
          </div>
          <el-tag type="success">验证集自由仿真 FIT: {{ pct(fitResult.metrics.val_free_run_fit) }}</el-tag>
        </div>

        <div class="metrics-grid">
          <div class="metric-box highlight">
            <div class="name">验证集自由仿真 FIT (主指标)</div>
            <div class="val">{{ pct(fitResult.metrics.val_free_run_fit) }}</div>
          </div>
          <div class="metric-box">
            <div class="name">验证集一步预测 FIT (诊断)</div>
            <div class="val">{{ pct(fitResult.metrics.val_fit) }}</div>
          </div>
          <div class="metric-box" :class="{ warn: (fitResult.validation?.fit_gap ?? 0) > 10 }">
            <div class="name">FIT 差值 (一步 − 自由仿真)</div>
            <div class="val">{{ num(fitResult.validation?.fit_gap) }}</div>
          </div>
          <div class="metric-box">
            <div class="name">训练样本数</div>
            <div class="val">{{ fitResult.training_rows }}</div>
          </div>
        </div>

        <el-alert
          v-if="(fitResult.validation?.fit_gap ?? 0) > 10"
          type="warning"
          :closable="false"
          show-icon
          class="alert-gap"
        >
          <template #title>
            一步预测 FIT 显著高于自由仿真 FIT（差值
            {{ num(fitResult.validation?.fit_gap) }}），说明模型主要依赖输出自相关
            “抄上一时刻”，多步预测能力不足，不建议直接用于 APC 部署。
          </template>
        </el-alert>

        <el-descriptions :column="4" border size="small" style="margin-top: 14px">
          <el-descriptions-item label="模型稳定性">
            <el-tag :type="fitResult.validation?.stable ? 'success' : 'danger'" size="small">
              {{ fitResult.validation?.stable ? "稳定" : "不稳定" }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="最大极点模">
            {{ num(fitResult.validation?.max_pole_modulus) }}
          </el-descriptions-item>
          <el-descriptions-item label="残差白度">
            {{ pct(residualWhitenessPercent) }}
          </el-descriptions-item>
          <el-descriptions-item label="AIC / BIC">
            {{ num(fitResult.metrics.aic) }} / {{ num(fitResult.metrics.bic) }}
          </el-descriptions-item>
          <el-descriptions-item label="稳态增益" :span="4">
            <el-tag
              v-for="(gain, name) in fitResult.validation?.steady_state_gains ?? {}"
              :key="name"
              size="small"
              effect="plain"
              class="gain-tag"
            >
              K({{ name }}) = {{ num(gain) }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <el-divider />

        <div class="coefficients-box">
          <h4>估计参数方程:</h4>
          <p class="code-inline">
            A(q⁻¹)y(t) = ∑ B_i(q⁻¹)u_i(t-d_i) + e(t)
          </p>
          <p>a 系数: {{ fitResult.a_coefficients.join(", ") }}</p>
          <p>b 系数: {{ JSON.stringify(fitResult.b_coefficients) }}</p>
        </div>
      </div>

      <!-- Fitting Plot -->
      <div class="industrial-card" v-if="fitResult">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><TrendCharts /></el-icon> 训练 / 验证区间：真实输出 y(t) vs 辨识预测 ŷ(t)
          </div>
        </div>
        <ChartContainer :options="plotOptions" height="380px" />
        <p class="plot-note">
          连续仿真曲线从全序列起点初始化；验证集 FIT 在验证预测起点单独初始化。
          带偏移的 FIR 使用该预测起点之前的历史数据估计基线。
        </p>

        <div style="margin-top: 16px; display: flex; justify-content: flex-end">
          <el-button type="warning" icon="RefreshRight" @click="$router.push('/modeling/optimization')">
            进入 Optuna 闭环参数自动寻优 ->
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { Cpu, VideoPlay, Trophy, TrendCharts, RefreshRight } from "@element-plus/icons-vue";
import PageHeader from "../components/common/PageHeader.vue";
import InputSupportWarning from "../components/InputSupportWarning.vue";
import ChartContainer from "../components/ChartContainer.vue";
import VersionLineagePicker from "../components/versioning/VersionLineagePicker.vue";
import { fitARXModel } from "../api/modeling";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../api/datasets";
import type {
  ARXFitRequest,
  ARXFitResponse,
  DatasetItem,
  DatasetVersionNode,
} from "../types/api";
import { useDatasetStore } from "../stores/datasetStore";
import { ElMessage } from "element-plus";
import { ApiError } from "../api/client";
import {
  formatVersionDate,
  shortVersionId,
  versionDisplayName,
} from "../utils/versionOperation";

const datasetStore = useDatasetStore();
const loading = ref(false);
const loadingDatasets = ref(false);
const loadingVersions = ref(false);
const fitResult = ref<ARXFitResponse | null>(null);
const contextError = ref("");
const datasetOptions = ref<DatasetItem[]>([]);
const selectedDatasetId = ref<string | null>(null);
const selectedDataset = ref<DatasetItem | null>(null);
const versionNodes = ref<DatasetVersionNode[]>([]);
const selectedVersionId = ref<string | null>(null);
const rememberedSourceByDataset = new Map<string, string>();
let contextRequestId = 0;

const selectedVersion = computed(
  () => versionNodes.value.find((node) => node.id === selectedVersionId.value) ?? null
);
const selectedParent = computed(() => {
  const parentId = selectedVersion.value?.parent_version_id;
  return parentId
    ? versionNodes.value.find((node) => node.id === parentId) ?? null
    : null;
});

const isLagDescendantFeature = (version: DatasetVersionNode) => {
  if (version.tool !== "preprocessing.feature_selection") return false;
  const byId = new Map(versionNodes.value.map((node) => [node.id, node]));
  const visited = new Set<string>();
  let current: DatasetVersionNode | undefined = version;
  while (current?.parent_version_id && !visited.has(current.id)) {
    visited.add(current.id);
    const parent = byId.get(current.parent_version_id);
    if (!parent) return false;
    if (parent.tool === "preprocessing.lag_compensation") return true;
    if (parent.tool !== "preprocessing.feature_selection") return false;
    current = parent;
  }
  return false;
};

const isArxEligibleVersion = (version: DatasetVersionNode) =>
  version.tool === "preprocessing.lag_compensation" || isLagDescendantFeature(version);

const arxDisabledReason = (version: DatasetVersionNode) => {
  if (version.tool === "simulation_generate" || version.tool === "raw_upload") {
    return "需先完成清洗与时滞补偿";
  }
  if (version.tool === "preprocessing.clean") return "需先完成时滞补偿";
  if (version.tool === "preprocessing.feature_selection") return "缺少可信时滞补偿来源";
  return "该处理阶段不符合 ARX 建模源要求";
};

const arxReadyLabel = (version: DatasetVersionNode) =>
  version.tool === "preprocessing.feature_selection"
    ? "特征优选后，可用于 ARX 建模"
    : "可用于 ARX 建模";

const stringArray = (value: unknown): string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string") ? value : [];

const versionInputColumns = (version: DatasetVersionNode | null) => {
  if (!version) return [];
  if (version.tool === "preprocessing.feature_selection") {
    const kept = stringArray(version.parameters?.kept_input_columns);
    if (kept.length) return kept;
  }
  if (version.tool === "preprocessing.lag_compensation") {
    const lagMap = version.parameters?.lag_map;
    if (lagMap && typeof lagMap === "object" && !Array.isArray(lagMap)) {
      const columns = Object.keys(lagMap);
      if (columns.length) return columns;
    }
  }
  return selectedDataset.value?.input_columns ?? [];
};

const inputCols = computed(() => {
  const columns = versionInputColumns(selectedVersion.value);
  return columns.length ? columns : ["u1"];
});

const form = reactive<ARXFitRequest>({
  dataset_id: "",
  version_id: "",
  model_type: "ARX",
  regularization_kernel: "identity",
  kernel_decay: 0.9,
  initialization_policy: "fixed",
  initialization_window: 32,
  na: 2,
  nb: [2],
  delays: [3],
  estimation_method: "ols",
  ridge_alpha: 0.1,
  evaluate_test: false,
});

const handleModelFamilyChange = () => {
  const fir = form.model_type === "FIR";
  const oe = form.model_type === "OE";
  form.na = fir ? 0 : 2;
  form.regularization_kernel = fir ? "tc" : "identity";
  form.estimation_method = fir || oe ? "ridge" : "ols";
  form.fit_intercept = true;
  if (oe) {
    form.initialization_policy = "fixed";
    form.ridge_alpha = 0.001;
    form.simulation_horizons = [1, 16, 64, 0];
  }
  form.standardize = true;
  form.nb = Array(inputCols.value.length).fill(fir ? 16 : 2);
};

const clearSourceContext = () => {
  versionNodes.value = [];
  selectedVersionId.value = null;
  form.dataset_id = "";
  form.version_id = "";
  fitResult.value = null;
};

const syncFormWithSource = () => {
  form.dataset_id = selectedDataset.value?.id ?? "";
  form.version_id = selectedVersion.value?.id ?? "";
  const count = inputCols.value.length;
  form.nb = Array(count).fill(form.model_type === "FIR" ? 16 : 2);
  form.delays = Array(count).fill(3);
};

const handleVersionSelect = (versionId: string) => {
  const version = versionNodes.value.find((node) => node.id === versionId);
  if (!version || !isArxEligibleVersion(version) || !selectedDatasetId.value) return;
  selectedVersionId.value = versionId;
  rememberedSourceByDataset.set(selectedDatasetId.value, versionId);
  fitResult.value = null;
  contextError.value = "";
  syncFormWithSource();
};

const chooseDefaultVersion = (dataset: DatasetItem, nodes: DatasetVersionNode[]) => {
  const eligible = nodes.filter(isArxEligibleVersion);
  const rememberedId = rememberedSourceByDataset.get(dataset.id);
  const activeVersionId = datasetStore.activeDataset?.id === dataset.id
    ? datasetStore.activeDataset.version_id || datasetStore.activeDataset.latest_version_id
    : dataset.version_id || dataset.latest_version_id;
  const preferred = eligible.find((node) => node.id === rememberedId)
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
    selectedDataset.value = dataset;
    versionNodes.value = versions.nodes;
    datasetStore.setActiveDataset(dataset);
    chooseDefaultVersion(dataset, versions.nodes);
  } catch (error) {
    if (requestId !== contextRequestId) return;
    selectedDataset.value = null;
    contextError.value = error instanceof ApiError ? error.message : String(error);
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
    const active = datasetStore.activeDataset;
    if (active && response.items.some((dataset) => dataset.id === active.id)) {
      selectedDatasetId.value = active.id;
      await loadDatasetContext(active.id);
    }
  } catch (error) {
    contextError.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    loadingDatasets.value = false;
  }
};

onMounted(() => {
  void initializeDatasets();
});

const handleFit = async () => {
  if (!selectedDataset.value || !selectedVersion.value || !isArxEligibleVersion(selectedVersion.value)) {
    ElMessage.error("请先选择具备可信时滞补偿血缘的 ARX 建模源版本。");
    return;
  }
  form.dataset_id = selectedDataset.value.id;
  form.version_id = selectedVersion.value.id;
  loading.value = true;
  try {
    const res = await fitARXModel({ ...form, evaluate_test: false });
    fitResult.value = res;
    ElMessage.success(
      `ARX 辨识成功：验证集自由仿真 FIT = ${pct(res.metrics.val_free_run_fit)}`
    );
  } catch (err: any) {
    fitResult.value = null;
    ElMessage.error(`ARX 辨识失败 [${err.code || "ERR"}]: ${err.message}`);
  } finally {
    loading.value = false;
  }
};

const residualWhitenessPercent = computed(() => {
  const ratio = fitResult.value?.validation?.residual_whiteness_ratio;
  return ratio === null || ratio === undefined ? null : ratio * 100;
});

const pct = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(2)}%`;

const num = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : Math.abs(value) >= 10000
      ? value.toExponential(2)
      : value.toFixed(4);

const plotOptions = computed(() => {
  if (!fitResult.value) return {};
  const data = fitResult.value.plot_data;
  const xData = data.indices.map(String);

  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["实测输出 y(t)", "一步预测 ŷ(t)", "全序列连续仿真 ŷ_sim(t)"] },
    grid: { left: "3%", right: "4%", bottom: "10%", containLabel: true },
    xAxis: { type: "category", name: "样本索引", data: xData },
    yAxis: { type: "value" },
    series: [
      {
        name: "实测输出 y(t)",
        type: "line",
        color: "#1E6091",
        data: data.y_true,
      },
      {
        name: "一步预测 ŷ(t)",
        type: "line",
        color: "#E76F51",
        showSymbol: false,
        lineStyle: { type: "dashed" },
        data: data.y_pred,
      },
      {
        name: "全序列连续仿真 ŷ_sim(t)",
        type: "line",
        color: "#2A9D8F",
        showSymbol: false,
        data: fitResult.value.free_run_series,
      },
    ],
  };
});
</script>

<style scoped>
.arx-view {
  min-height: 100%;
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

.dataset-meta {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.modeling-layout {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.metric-box {
  background: var(--bg-subtle);
  padding: 12px;
  border-radius: 6px;
  border: 1px solid var(--border-light);
  text-align: center;
}

.metric-box.warn {
  border-color: var(--danger);
}

.alert-gap {
  margin-top: 12px;
}

.gain-tag {
  margin-right: 6px;
}

.metric-box.highlight {
  background: var(--surface-2);
  border-color: var(--accent-border);
}

.metric-box .name {
  font-size: 12px;
  color: var(--text-secondary);
}

.metric-box .val {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-sans);
  letter-spacing: normal;
  margin-top: 4px;
}

.coefficients-box {
  background: var(--bg-subtle);
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-primary);
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

  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
