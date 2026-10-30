<template>
  <section class="model-evaluation" data-test="model-evaluation-artifact-renderer">
    <header class="evaluation-header">
      <div class="evaluation-header__title">
        <h3>最终测试集评价</h3>
        <span class="evaluation-scope" data-test="evaluation-scope-badge">Held-out Test</span>
      </div>
      <p data-test="evaluation-leakage-note">
        该测试集仅用于最终评价，未参与模型训练、参数选择或闭环寻优。
      </p>
    </header>

    <InputSupportWarning :support="modelHealth.input_support" />

    <div class="prediction-mode" role="group" aria-label="预测模式" data-test="prediction-mode">
      <button
        type="button"
        :class="{ 'is-active': predictionMode === 'free_run' }"
        data-test="prediction-mode-free-run"
        @click="predictionMode = 'free_run'"
      >Free-run</button>
      <button
        type="button"
        :class="{ 'is-active': predictionMode === 'one_step' }"
        data-test="prediction-mode-one-step"
        @click="predictionMode = 'one_step'"
      >One-step</button>
    </div>

    <div class="evaluation-metrics" data-test="evaluation-metrics" :data-mode="predictionMode">
      <article v-for="metric in selectedMetrics" :key="metric.label">
        <span>{{ metric.label }}</span>
        <strong class="tabular-nums">{{ metric.value }}</strong>
      </article>
    </div>

    <section class="evaluation-section" data-test="evaluation-prediction-section">
      <div class="evaluation-section__heading">
        <div>
          <h4>测试集真实值与预测值</h4>
          <p>{{ predictionMode === "free_run" ? "自由运行预测" : "单步预测" }} · 使用完整 held-out Test 序列</p>
        </div>
        <span>{{ predictionData?.usesTimestamps ? "时间轴" : "样本索引" }}</span>
      </div>
      <ChartContainer
        v-if="predictionData"
        ref="predictionChartRef"
        :options="predictionChartOptions"
        height="250px"
        data-test="evaluation-prediction-chart"
        @chart-viewport-change="syncResidualViewport"
      />
      <p v-else class="evaluation-empty" data-test="evaluation-prediction-empty">
        该历史评价未保存测试序列，因此无法恢复预测曲线。
      </p>
    </section>

    <section class="evaluation-section" data-test="evaluation-residual-section">
      <div class="evaluation-section__heading">
        <div>
          <h4>测试集一步预测残差</h4>
          <p>固定使用 Test one-step residual，不随上方预测模式切换</p>
        </div>
        <span>Residual</span>
      </div>
      <ChartContainer
        v-if="residualData"
        ref="residualChartRef"
        :options="residualChartOptions"
        height="190px"
        data-test="evaluation-residual-chart"
        @chart-viewport-change="syncPredictionViewport"
      />
      <p v-else class="evaluation-empty" data-test="evaluation-residual-empty">
        该历史评价未保存一步预测残差序列。
      </p>
    </section>

    <section class="evaluation-section" data-test="evaluation-diagnostics">
      <div class="evaluation-section__heading">
        <div>
          <h4>Test diagnostics</h4>
          <p>残差白度来自 Test one-step residual；不设置前端判定阈值</p>
        </div>
      </div>
      <div class="diagnostic-grid">
        <article>
          <span>残差白度</span>
          <strong class="tabular-nums">{{ formatNumber(testWhiteness) }}</strong>
          <small>ratio</small>
        </article>
        <article>
          <span>模型稳定性</span>
          <strong>{{ stabilityLabel }}</strong>
          <small>当前 evaluated model</small>
        </article>
        <article>
          <span>最大极点模</span>
          <strong class="tabular-nums">{{ formatNumber(maxPoleModulus) }}</strong>
        </article>
        <article>
          <span>测试样本数</span>
          <strong class="tabular-nums">{{ sampleCountLabel }}</strong>
        </article>
      </div>
    </section>

    <section class="evaluation-section" data-test="evaluation-acf-section">
      <div class="evaluation-section__heading">
        <div>
          <h4>测试集一步预测残差自相关</h4>
          <p>Test one-step residual · 虚线为后端返回的 95% 置信边界</p>
        </div>
        <span>ACF</span>
      </div>
      <ChartContainer
        v-if="acfValues.length"
        :options="acfChartOptions"
        height="210px"
        data-test="evaluation-acf-chart"
      />
      <p v-else class="evaluation-empty" data-test="evaluation-diagnostics-empty">
        该历史评价未保存残差诊断数据。
      </p>
    </section>

    <details class="evaluation-technical" data-test="model-evaluation-technical-details">
      <summary>查看技术详情</summary>
      <div class="evaluation-technical__body">
        <dl v-if="technicalMetadata.length" class="evaluation-metadata">
          <div v-for="item in technicalMetadata" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd class="font-mono">{{ item.value }}</dd>
          </div>
        </dl>
        <div v-if="modelStructure" class="evaluation-structure">
          <h5>Model structure</h5>
          <pre class="font-mono">{{ JSON.stringify(modelStructure, null, 2) }}</pre>
        </div>
        <pre class="evaluation-raw font-mono" data-test="model-evaluation-raw-json">{{ rawPayload }}</pre>
      </div>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import InputSupportWarning from "../InputSupportWarning.vue";
import ChartContainer, {
  type ChartOption,
  type ChartViewportChange,
} from "../ChartContainer.vue";

type PredictionMode = "free_run" | "one_step";
type ChartExpose = {
  dispatchAction: (action: {
    type: "dataZoom";
    start?: number;
    end?: number;
    startValue?: number | string | Date;
    endValue?: number | string | Date;
  }) => void;
};

type AlignedPredictionData = {
  axis: Array<string | number>;
  usesTimestamps: boolean;
  actual: number[];
  prediction: number[];
};

type AlignedResidualData = {
  axis: Array<string | number>;
  usesTimestamps: boolean;
  residual: number[];
};

const props = defineProps<{
  payload?: Record<string, unknown> | null;
}>();

const predictionMode = ref<PredictionMode>("free_run");
const predictionChartRef = ref<ChartExpose | null>(null);
const residualChartRef = ref<ChartExpose | null>(null);
let viewportSyncActive = false;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const finiteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const nonEmptyString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const finiteNumberArray = (value: unknown): number[] | null => {
  if (!Array.isArray(value) || !value.length) return null;
  return value.every((entry) => finiteNumber(entry) !== null) ? [...value] as number[] : null;
};

const sampleIndexArray = (value: unknown): number[] | null => {
  const values = finiteNumberArray(value);
  return values?.every((entry) => Number.isInteger(entry) && entry >= 0) ? values : null;
};

const timestampArray = (value: unknown): string[] | null => {
  if (!Array.isArray(value) || !value.length) return null;
  return value.every((entry) => typeof entry === "string" && Boolean(entry.trim()))
    ? [...value] as string[]
    : null;
};

const rootPayload = computed<Record<string, unknown>>(() =>
  isRecord(props.payload) ? props.payload : {}
);

const artifact = computed<Record<string, unknown>>(() =>
  isRecord(rootPayload.value.result) ? rootPayload.value.result : rootPayload.value
);

const testData = computed<Record<string, unknown>>(() =>
  isRecord(artifact.value.test) ? artifact.value.test : {}
);

const selectedMetricRecord = computed<Record<string, unknown>>(() => {
  const value = testData.value[predictionMode.value];
  return isRecord(value) ? value : {};
});

const numberFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 4,
  minimumFractionDigits: 0,
});

function formatNumber(value: number | null): string {
  return value === null ? "—" : numberFormatter.format(value);
}

const selectedMetrics = computed(() => {
  const metrics = selectedMetricRecord.value;
  const fit = finiteNumber(metrics.fit);
  return [
    { label: "FIT", value: fit === null ? "—" : `${fit.toFixed(2)}%` },
    { label: "R²", value: formatNumber(finiteNumber(metrics.r2)) },
    { label: "RMSE", value: formatNumber(finiteNumber(metrics.rmse)) },
    { label: "MAE", value: formatNumber(finiteNumber(metrics.mae)) },
    { label: "NRMSE", value: formatNumber(finiteNumber(metrics.nrmse)) },
  ];
});

const seriesData = computed<Record<string, unknown>>(() =>
  isRecord(artifact.value.series) ? artifact.value.series : {}
);

const resolveAxis = (length: number): { axis: Array<string | number>; usesTimestamps: boolean } | null => {
  const timestamps = timestampArray(seriesData.value.timestamps);
  if (timestamps?.length === length) return { axis: timestamps, usesTimestamps: true };
  const sampleIndices = sampleIndexArray(seriesData.value.sample_indices);
  if (sampleIndices?.length === length) return { axis: sampleIndices, usesTimestamps: false };
  return null;
};

const predictionData = computed<AlignedPredictionData | null>(() => {
  const actual = finiteNumberArray(seriesData.value.y_true);
  const prediction = finiteNumberArray(
    predictionMode.value === "free_run"
      ? seriesData.value.free_run_prediction
      : seriesData.value.one_step_prediction
  );
  if (!actual || !prediction || actual.length !== prediction.length) return null;
  const axis = resolveAxis(actual.length);
  return axis ? { ...axis, actual, prediction } : null;
});

const residualData = computed<AlignedResidualData | null>(() => {
  const residual = finiteNumberArray(seriesData.value.one_step_residual);
  if (!residual) return null;
  const axis = resolveAxis(residual.length);
  return axis ? { ...axis, residual } : null;
});

const chartFontFamily = "IndusOpt Sans, system-ui, sans-serif";

const formatTimestamp = (value: string): string => {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
};

const commonDataZoom = () => ([
  {
    type: "inside",
    xAxisIndex: 0,
    filterMode: "none",
    zoomOnMouseWheel: "ctrl",
    moveOnMouseWheel: false,
    moveOnMouseMove: true,
  },
  {
    type: "slider",
    xAxisIndex: 0,
    filterMode: "none",
    height: 13,
    bottom: 5,
    borderColor: "#DDE3DA",
    fillerColor: "rgba(120, 148, 111, 0.16)",
    handleStyle: { color: "#78946F" },
  },
]);

const xAxisOption = (data: AlignedPredictionData | AlignedResidualData) => ({
  type: "category" as const,
  data: data.axis,
  boundaryGap: false,
  axisLabel: {
    color: "#8E8E93",
    fontSize: 10,
    hideOverlap: true,
    formatter: (value: string | number) =>
      data.usesTimestamps ? formatTimestamp(String(value)) : String(value),
  },
  axisLine: { lineStyle: { color: "#DDE3DA" } },
  axisTick: { show: false },
});

const predictionChartOptions = computed<ChartOption>(() => {
  const data = predictionData.value;
  if (!data) return {} as ChartOption;
  const predictionLabel = predictionMode.value === "free_run" ? "自由运行预测" : "单步预测";
  return {
    animation: false,
    textStyle: { fontFamily: chartFontFamily },
    legend: {
      data: ["真实值", predictionLabel],
      top: 0,
      left: "center",
      itemGap: 18,
      textStyle: { color: "#596157", fontSize: 10 },
    },
    grid: { left: 48, right: 18, top: 34, bottom: 46 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#FFFFFF",
      borderColor: "#E5E5E8",
      textStyle: { color: "#171717", fontSize: 10 },
      valueFormatter: (value: unknown) => formatNumber(finiteNumber(value)),
    },
    dataZoom: commonDataZoom(),
    xAxis: xAxisOption(data),
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#8E8E93", fontSize: 10 },
      splitLine: { lineStyle: { color: "#EEF1EC" } },
    },
    series: [
      {
        name: "真实值",
        type: "line",
        data: data.actual,
        symbol: "none",
        lineStyle: { color: "#425466", width: 1.6 },
      },
      {
        name: predictionLabel,
        type: "line",
        data: data.prediction,
        symbol: "none",
        lineStyle: { color: "#78946F", width: 1.5 },
      },
    ],
  } as ChartOption;
});

const residualChartOptions = computed<ChartOption>(() => {
  const data = residualData.value;
  if (!data) return {} as ChartOption;
  return {
    animation: false,
    textStyle: { fontFamily: chartFontFamily },
    grid: { left: 48, right: 18, top: 12, bottom: 46 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#FFFFFF",
      borderColor: "#E5E5E8",
      textStyle: { color: "#171717", fontSize: 10 },
      valueFormatter: (value: unknown) => formatNumber(finiteNumber(value)),
    },
    dataZoom: commonDataZoom(),
    xAxis: xAxisOption(data),
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#8E8E93", fontSize: 10 },
      splitLine: { lineStyle: { color: "#EEF1EC" } },
    },
    series: [{
      name: "一步预测残差",
      type: "line",
      data: data.residual,
      symbol: "none",
      lineStyle: { color: "#8A7565", width: 1.2 },
      markLine: {
        silent: true,
        symbol: "none",
        label: { show: false },
        lineStyle: { color: "#AEB5AC", width: 1 },
        data: [{ yAxis: 0 }],
      },
    }],
  } as ChartOption;
});

const syncViewport = (target: ChartExpose | null, change: ChartViewportChange) => {
  if (viewportSyncActive || change.reason !== "datazoom" || !target) return;
  const range = change.ranges[0];
  if (!range) return;
  viewportSyncActive = true;
  target.dispatchAction({
    type: "dataZoom",
    ...(range.start !== undefined ? { start: range.start } : {}),
    ...(range.end !== undefined ? { end: range.end } : {}),
    ...(range.startValue !== undefined ? { startValue: range.startValue } : {}),
    ...(range.endValue !== undefined ? { endValue: range.endValue } : {}),
  });
  queueMicrotask(() => {
    viewportSyncActive = false;
  });
};

const syncResidualViewport = (change: ChartViewportChange) =>
  syncViewport(residualChartRef.value, change);

const syncPredictionViewport = (change: ChartViewportChange) =>
  syncViewport(predictionChartRef.value, change);

const residualDiagnostics = computed<Record<string, unknown>>(() =>
  isRecord(artifact.value.residual_diagnostics) ? artifact.value.residual_diagnostics : {}
);

const modelHealth = computed<Record<string, unknown>>(() =>
  isRecord(artifact.value.model_health) ? artifact.value.model_health : {}
);

const testWhiteness = computed(() =>
  finiteNumber(residualDiagnostics.value.residual_whiteness_ratio)
);

const maxPoleModulus = computed(() => finiteNumber(modelHealth.value.max_pole_modulus));

const stabilityLabel = computed(() => {
  const stable = modelHealth.value.stable;
  return typeof stable === "boolean" ? (stable ? "稳定" : "不稳定") : "—";
});

const sampleCountLabel = computed(() => {
  const count = finiteNumber(testData.value.n_samples);
  return count !== null && Number.isInteger(count) && count >= 0
    ? count.toLocaleString("zh-CN")
    : "—";
});

const acfValues = computed(() => finiteNumberArray(residualDiagnostics.value.acf_values) ?? []);
const confidenceInterval = computed(() => finiteNumber(residualDiagnostics.value.confidence_interval));

const acfChartOptions = computed<ChartOption>(() => ({
  animation: false,
  textStyle: { fontFamily: chartFontFamily },
  grid: { left: 46, right: 18, top: 12, bottom: 34 },
  tooltip: {
    trigger: "axis",
    axisPointer: { type: "shadow" },
    valueFormatter: (value: unknown) => formatNumber(finiteNumber(value)),
  },
  xAxis: {
    type: "category",
    data: acfValues.value.map((_, index) => index),
    name: "Lag",
    nameTextStyle: { color: "#8E8E93", fontSize: 10 },
    axisLabel: { color: "#8E8E93", fontSize: 10 },
    axisLine: { lineStyle: { color: "#DDE3DA" } },
    axisTick: { show: false },
  },
  yAxis: {
    type: "value",
    min: -1,
    max: 1,
    axisLabel: { color: "#8E8E93", fontSize: 10 },
    splitLine: { lineStyle: { color: "#EEF1EC" } },
  },
  series: [{
    name: "ACF",
    type: "bar",
    data: acfValues.value,
    barMaxWidth: 8,
    itemStyle: { color: "#78946F", borderRadius: [2, 2, 0, 0] },
    ...(confidenceInterval.value !== null
      ? {
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { color: "#B07D69", type: "dashed", width: 1 },
            data: [
              { yAxis: confidenceInterval.value },
              { yAxis: -confidenceInterval.value },
            ],
          },
        }
      : {}),
  }],
}) as ChartOption);

const modelStructure = computed(() =>
  isRecord(artifact.value.model_structure) ? artifact.value.model_structure : null
);

const technicalMetadata = computed(() => ([
  ["Model ID", nonEmptyString(artifact.value.model_id)],
  ["Source Version", nonEmptyString(artifact.value.source_version_id)],
  ["Processing Run", nonEmptyString(artifact.value.processing_run_id)],
  ["Evaluation Scope", nonEmptyString(artifact.value.evaluation_scope)],
] as const).flatMap(([label, value]) => value ? [{ label, value }] : []));

const rawPayload = computed(() => {
  try {
    return JSON.stringify(props.payload ?? {}, null, 2) ?? String(props.payload ?? {});
  } catch {
    return String(props.payload ?? {});
  }
});
</script>

<style scoped>
.model-evaluation {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
  font-family: var(--font-sans);
}

.evaluation-header {
  display: grid;
  grid-template-columns: minmax(0, 0.85fr) minmax(190px, 1.15fr);
  gap: 16px;
  align-items: end;
}

.evaluation-header__title {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 8px;
  align-items: center;
}

.model-evaluation h3,
.model-evaluation h4,
.model-evaluation h5,
.model-evaluation p {
  margin: 0;
}

.model-evaluation h3 {
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 700;
}

.evaluation-scope {
  padding: 2px 6px;
  border: 1px solid #CBD8C6;
  border-radius: 4px;
  background: #F1F5EF;
  color: #516A4D;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.evaluation-header p {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.6;
}

.prediction-mode {
  display: inline-flex;
  align-self: flex-start;
  padding: 2px;
  border: 1px solid var(--border-default);
  border-radius: 7px;
  background: var(--surface-2);
}

.prediction-mode button {
  min-width: 78px;
  padding: 5px 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-tertiary);
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease, box-shadow 160ms ease;
}

.prediction-mode button:hover {
  color: var(--text-primary);
}

.prediction-mode button:focus-visible {
  outline: 2px solid #8DA985;
  outline-offset: 2px;
}

.prediction-mode button.is-active {
  background: #FFFFFF;
  color: var(--accent-dark);
  box-shadow: 0 1px 2px rgba(47, 73, 46, 0.08);
}

.evaluation-metrics,
.diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 7px;
}

.evaluation-metrics article,
.diagnostic-grid article {
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.evaluation-metrics article:first-child {
  border-color: #C7D6C1;
  background: #F2F6F0;
}

.evaluation-metrics span,
.diagnostic-grid span {
  display: block;
  color: var(--text-tertiary);
  font-size: 10px;
}

.evaluation-metrics strong,
.diagnostic-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 700;
}

.diagnostic-grid small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
}

.evaluation-section,
.evaluation-technical {
  min-width: 0;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}

.evaluation-section__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.evaluation-section__heading h4 {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.evaluation-section__heading p {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.5;
}

.evaluation-section__heading > span {
  color: var(--text-tertiary);
  font-size: 9px;
  white-space: nowrap;
}

.evaluation-empty {
  padding: 13px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}

.evaluation-technical summary {
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.evaluation-technical__body {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.evaluation-metadata {
  display: grid;
  gap: 5px;
  margin: 0;
}

.evaluation-metadata div {
  display: grid;
  grid-template-columns: 108px minmax(0, 1fr);
  gap: 8px;
}

.evaluation-metadata dt {
  color: var(--text-tertiary);
  font-size: 9px;
}

.evaluation-metadata dd {
  overflow: hidden;
  margin: 0;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evaluation-structure h5 {
  margin-bottom: 5px;
  color: var(--text-secondary);
  font-size: 10px;
}

.evaluation-structure pre,
.evaluation-raw {
  max-height: 300px;
  margin: 0;
  overflow: auto;
  padding: 10px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: #F8F9F7;
  color: var(--text-secondary);
  font-size: 10px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 560px) {
  .evaluation-header {
    grid-template-columns: 1fr;
    gap: 7px;
  }

  .prediction-mode {
    width: 100%;
  }

  .prediction-mode button {
    flex: 1;
  }
}
</style>
