<template>
  <section class="arx-model" data-test="arx-model-artifact-renderer">
    <header class="arx-model__header">
      <div>
        <h3>ARX 模型结果</h3>
      </div>
      <p>当前模型基于训练数据完成参数估计，并使用验证集评估模型选择效果。</p>
    </header>

    <div v-if="summaryCards.length" class="arx-summary" data-test="arx-model-summary">
      <article v-for="card in summaryCards" :key="card.label" class="arx-summary__card">
        <span>{{ card.label }}</span>
        <strong class="tabular-nums">{{ card.value }}</strong>
        <small v-if="card.note">{{ card.note }}</small>
      </article>
    </div>

    <section v-if="modelStructure" class="arx-section" data-test="arx-model-structure">
      <div class="arx-section__heading">
        <div>
          <h4>模型结构</h4>
          <p>输入通道阶次与时滞来自已保存的模型配置</p>
        </div>
      </div>
      <div class="arx-flow" aria-label="ARX 输入输出结构">
        <div class="arx-flow__inputs">
          <article v-for="channel in channelRows" :key="channel.name" class="arx-flow__channel">
            <strong>{{ channel.name }}</strong>
            <span>nb = {{ displayInteger(channel.nb) }}</span>
            <span>delay = {{ displayInteger(channel.delay) }}</span>
          </article>
        </div>
        <span class="arx-flow__arrow" aria-hidden="true">→</span>
        <article class="arx-flow__core">
          <strong>{{ modelStructure.modelType ?? "ARX" }}</strong>
          <span>na = {{ displayInteger(modelStructure.na) }}</span>
        </article>
        <span class="arx-flow__arrow" aria-hidden="true">→</span>
        <article class="arx-flow__output">
          <span>输出</span>
          <strong>{{ modelStructure.outputColumn ?? "—" }}</strong>
        </article>
      </div>

      <div class="arx-table-wrap">
        <table class="arx-table" data-test="arx-channel-table">
          <thead>
            <tr>
              <th>变量</th>
              <th>nb</th>
              <th>delay</th>
              <th>稳态增益</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="channel in channelRows" :key="channel.name">
              <td>{{ channel.name }}</td>
              <td class="tabular-nums">{{ displayInteger(channel.nb) }}</td>
              <td class="tabular-nums">{{ displayInteger(channel.delay) }}</td>
              <td class="tabular-nums">{{ formatNumber(channel.steadyStateGain) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <p v-else class="arx-empty" data-test="arx-model-structure-empty">
      该历史任务未记录完整模型结构，可在技术详情中查看原始结果。
    </p>

    <section v-if="validationMetrics.length" class="arx-section" data-test="arx-validation">
      <InputSupportWarning :support="validation.input_support" />
      <div class="arx-section__heading">
        <div>
          <h4>验证集 · 模型选择依据</h4>
          <p>优先使用正式验证集结果；不包含 Held-out Test 结果。</p>
        </div>
      </div>
      <div class="arx-validation-grid">
        <article v-for="metric in validationMetrics" :key="metric.label">
          <span>{{ metric.label }}</span>
          <strong class="tabular-nums">{{ metric.value }}</strong>
          <small v-if="metric.note">{{ metric.note }}</small>
        </article>
      </div>
    </section>

    <section v-if="coefficientEntries.length" class="arx-section" data-test="arx-coefficients">
      <div class="arx-section__heading">
        <div>
          <h4>模型系数</h4>
          <p>系数名称保持后端原始定义；具体输入时滞见上方模型结构</p>
        </div>
      </div>
      <ChartContainer :options="coefficientChartOptions" :height="coefficientChartHeight" />
    </section>

    <details class="arx-technical" data-test="arx-model-technical-details">
      <summary>查看技术详情</summary>
      <div class="arx-technical__body">
        <dl v-if="technicalMetadata.length" class="arx-metadata">
          <div v-for="item in technicalMetadata" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd class="font-mono">{{ item.value }}</dd>
          </div>
        </dl>
        <div v-if="technicalMetrics.length" class="arx-technical-metrics">
          <span v-for="item in technicalMetrics" :key="item.label">
            {{ item.label }} <strong class="tabular-nums">{{ item.value }}</strong>
          </span>
        </div>
        <div v-if="priorViolations.length" class="arx-priors">
          <h5>Prior violations</h5>
          <pre class="font-mono">{{ JSON.stringify(priorViolations, null, 2) }}</pre>
        </div>
        <pre class="arx-raw font-mono" data-test="arx-model-raw-json">{{ rawPayload }}</pre>
      </div>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import ChartContainer, { type ChartOption } from "../ChartContainer.vue";
import InputSupportWarning from "../InputSupportWarning.vue";

type ModelStructureView = {
  modelType: string | null;
  initializationPolicy: string | null;
  initializationWindow: number | null;
  inputColumns: string[];
  outputColumn: string | null;
  na: number | null;
  nb: Record<string, number>;
  delays: Record<string, number>;
  estimator: string | null;
  ridgeAlpha: number | null;
  parameterCount: number | null;
};

const props = defineProps<{
  payload?: Record<string, unknown> | null;
}>();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const finiteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const integer = (value: unknown): number | null => {
  const numeric = finiteNumber(value);
  return numeric !== null && Number.isInteger(numeric) ? numeric : null;
};

const nonEmptyString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const numericRecord = (value: unknown): Record<string, number> => {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, entry]) => {
      const numeric = finiteNumber(entry);
      return numeric === null ? [] : [[key, numeric]];
    })
  );
};

const rootPayload = computed<Record<string, unknown>>(() =>
  isRecord(props.payload) ? props.payload : {}
);

const artifact = computed<Record<string, unknown>>(() =>
  isRecord(rootPayload.value.result) ? rootPayload.value.result : rootPayload.value
);

const modelStructure = computed<ModelStructureView | null>(() => {
  const raw = artifact.value.model_structure;
  if (!isRecord(raw)) return null;
  const inputColumns = Array.isArray(raw.input_columns)
    ? raw.input_columns.filter((value): value is string => typeof value === "string" && Boolean(value))
    : [];
  return {
    modelType: nonEmptyString(raw.model_type),
    initializationPolicy: nonEmptyString(raw.initialization_policy),
    initializationWindow: integer(raw.initialization_window),
    inputColumns,
    outputColumn: nonEmptyString(raw.output_column),
    na: integer(raw.na),
    nb: numericRecord(raw.nb),
    delays: numericRecord(raw.delays),
    estimator: nonEmptyString(raw.estimator),
    ridgeAlpha: finiteNumber(raw.ridge_alpha),
    parameterCount: integer(raw.parameter_count),
  };
});

const validation = computed<Record<string, unknown>>(() =>
  isRecord(artifact.value.validation) ? artifact.value.validation : {}
);

const metrics = computed<Record<string, unknown>>(() =>
  isRecord(artifact.value.metrics) ? artifact.value.metrics : {}
);

const steadyStateGains = computed(() => numericRecord(validation.value.steady_state_gains));

const channelRows = computed(() =>
  (modelStructure.value?.inputColumns ?? []).map((name) => ({
    name,
    nb: finiteNumber(modelStructure.value?.nb[name]),
    delay: finiteNumber(modelStructure.value?.delays[name]),
    steadyStateGain: finiteNumber(steadyStateGains.value[name]),
  }))
);

const estimatorLabel = (value: string | null): string | null => {
  if (!value) return null;
  if (value.toLowerCase() === "ols") return "OLS";
  if (value.toLowerCase() === "ridge") return "Ridge";
  if (value.toLowerCase() === "huber") return "Huber";
  return value;
};

const summaryCards = computed(() => {
  const structure = modelStructure.value;
  const cards: Array<{ label: string; value: string; note?: string }> = [];
  if (structure?.modelType) cards.push({ label: "模型类型", value: structure.modelType });
  if (structure?.initializationPolicy === "past_residual") {
    cards.push({ label: "持续扰动补偿", value: "预测前历史残差估计", note: `使用预测前 ${structure.initializationWindow ?? 32} 个样本；自由仿真时冻结，假设扰动持续` });
  }
  const estimator = structure?.modelType === "OE" ? "稳定多步模拟优化"
    : estimatorLabel(structure?.estimator ?? nonEmptyString(artifact.value.estimator));
  if (estimator) {
    cards.push({
      label: "估计方法",
      value: estimator,
      ...(estimator === "Ridge" && structure?.ridgeAlpha != null
        ? { note: `α = ${formatNumber(structure.ridgeAlpha)}` }
        : {}),
    });
  }
  if (structure) {
    cards.push({ label: "输入通道", value: String(structure.inputColumns.length) });
    if (structure.parameterCount !== null) {
      cards.push({ label: "参数数量", value: structure.parameterCount.toLocaleString("zh-CN") });
    }
  }
  if (typeof validation.value.stable === "boolean") {
    cards.push({ label: "稳定性", value: validation.value.stable ? "稳定" : "不稳定" });
  }
  return cards.slice(0, 5);
});

const numberFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 4,
  minimumFractionDigits: 0,
});

function formatNumber(value: number | null): string {
  return value === null ? "—" : numberFormatter.format(value);
}

function displayInteger(value: number | null): string {
  return value === null ? "—" : String(value);
}

const percentMetric = (value: unknown): string | null => {
  const numeric = finiteNumber(value);
  return numeric === null ? null : `${numeric.toFixed(2)}%`;
};

const decimalMetric = (value: unknown): string | null => {
  const numeric = finiteNumber(value);
  return numeric === null ? null : formatNumber(numeric);
};

const nestedMetric = (
  root: Record<string, unknown>,
  predictionMode: "one_step" | "free_run",
  field: string
): unknown => {
  const mode = root[predictionMode];
  if (!isRecord(mode)) return undefined;
  const partition = mode.validation;
  return isRecord(partition) ? partition[field] : undefined;
};

const validationMetrics = computed(() => {
  const values = [
    {
      label: "Free-run FIT",
      value: percentMetric(
        validation.value.free_run_fit
          ?? metrics.value.val_free_run_fit
          ?? nestedMetric(metrics.value, "free_run", "fit")
      ),
      note: "多步自由运行",
    },
    {
      label: "Free-run RMSE",
      value: decimalMetric(
        validation.value.free_run_rmse ?? nestedMetric(metrics.value, "free_run", "rmse")
      ),
    },
    {
      label: "One-step FIT",
      value: percentMetric(
        validation.value.one_step_fit
          ?? metrics.value.val_fit
          ?? nestedMetric(metrics.value, "one_step", "fit")
      ),
      note: "一步预测",
    },
    {
      label: "Fit Gap",
      value: (() => {
        const numeric = finiteNumber(validation.value.fit_gap);
        return numeric === null ? null : `${numeric.toFixed(2)} pp`;
      })(),
    },
    {
      label: "Residual Whiteness",
      value: decimalMetric(validation.value.residual_whiteness_ratio),
      note: "Validation one-step residual",
    },
  ];
  return values.filter((item): item is { label: string; value: string; note?: string } =>
    item.value !== null
  );
});

const coefficientEntries = computed(() => {
  const entries = Object.entries(numericRecord(artifact.value.coefficients)).map(([name, value]) => ({ name, value }));
  const intercept = finiteNumber(artifact.value.intercept);
  if (intercept !== null) entries.push({ name: "偏置", value: intercept });
  return entries;
});

const chartFontFamily = "IndusOpt Sans, system-ui, sans-serif";

const coefficientChartOptions = computed<ChartOption>(() => ({
  animation: false,
  textStyle: { fontFamily: chartFontFamily },
  grid: { left: 88, right: 62, top: 8, bottom: 30 },
  tooltip: {
    trigger: "axis",
    axisPointer: { type: "shadow" },
    valueFormatter: (value: unknown) => finiteNumber(value)?.toFixed(6) ?? "",
  },
  xAxis: {
    type: "value",
    axisLabel: { color: "#8E8E93", fontSize: 10 },
    axisLine: { lineStyle: { color: "#DDE3DA" } },
    splitLine: { lineStyle: { color: "#EEF1EC" } },
  },
  yAxis: {
    type: "category",
    inverse: true,
    data: coefficientEntries.value.map((entry) => entry.name),
    axisLabel: { color: "#596157", fontSize: 10 },
    axisLine: { show: false },
    axisTick: { show: false },
  },
  series: [{
    name: "系数",
    type: "bar",
    data: coefficientEntries.value.map((entry) => entry.value),
    barMaxWidth: 14,
    itemStyle: { color: "#78946F", borderRadius: 2 },
    label: {
      show: true,
      position: "right",
      color: "#596157",
      fontSize: 10,
      formatter: ({ value }: { value: unknown }) => finiteNumber(value)?.toFixed(4) ?? "",
    },
  }],
}) as ChartOption);

const coefficientChartHeight = computed(() =>
  `${Math.min(420, Math.max(170, coefficientEntries.value.length * 27 + 54))}px`
);

const technicalMetadata = computed(() => ([
  ["Model ID", nonEmptyString(artifact.value.model_id)],
  ["Version ID", nonEmptyString(artifact.value.version_id)],
  ["Processing Run", nonEmptyString(artifact.value.processing_run_id)],
  ["Artifact URI", nonEmptyString(artifact.value.artifact_uri)],
] as const).flatMap(([label, value]) => value ? [{ label, value }] : []));

const technicalMetrics = computed(() => ([
  ["AIC", decimalMetric(metrics.value.aic)],
  ["BIC", decimalMetric(metrics.value.bic)],
] as const).flatMap(([label, value]) => value ? [{ label, value }] : []));

const priorViolations = computed(() =>
  Array.isArray(artifact.value.prior_violations) ? artifact.value.prior_violations : []
);

const rawPayload = computed(() => {
  try {
    return JSON.stringify(props.payload ?? {}, null, 2) ?? String(props.payload ?? {});
  } catch {
    return String(props.payload ?? {});
  }
});
</script>

<style scoped>
.arx-model {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
  font-family: var(--font-sans);
}

.arx-model__header {
  display: grid;
  grid-template-columns: minmax(0, 0.8fr) minmax(190px, 1.2fr);
  gap: 16px;
  align-items: end;
}

.arx-model h3,
.arx-model h4,
.arx-model h5,
.arx-model p {
  margin: 0;
}

.arx-model h3 {
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 700;
}

.arx-model__header p {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.6;
}

.arx-summary,
.arx-validation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
  gap: 7px;
}

.arx-summary__card,
.arx-validation-grid article {
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.arx-summary span,
.arx-validation-grid span {
  display: block;
  color: var(--text-tertiary);
  font-size: 10px;
}

.arx-summary strong,
.arx-validation-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 700;
}

.arx-summary small,
.arx-validation-grid small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
  line-height: 1.4;
}

.arx-section,
.arx-technical {
  min-width: 0;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}

.arx-section__heading {
  margin-bottom: 10px;
}

.arx-section__heading h4 {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.arx-section__heading p {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.5;
}

.arx-flow {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) auto minmax(74px, 0.65fr) auto minmax(64px, 0.55fr);
  gap: 8px;
  align-items: center;
  padding: 12px;
  border: 1px solid #E3E8E0;
  border-radius: 8px;
  background: #F7F9F5;
}

.arx-flow__inputs {
  display: grid;
  gap: 5px;
}

.arx-flow__channel,
.arx-flow__core,
.arx-flow__output {
  min-width: 0;
  border: 1px solid #DCE4D8;
  border-radius: 6px;
  background: #FFFFFF;
}

.arx-flow__channel {
  display: grid;
  grid-template-columns: minmax(48px, 1fr) auto auto;
  gap: 8px;
  align-items: center;
  padding: 6px 8px;
}

.arx-flow strong {
  max-width: 100%;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arx-flow span {
  color: var(--text-muted);
  font-size: 9px;
  white-space: nowrap;
}

.arx-flow__core,
.arx-flow__output {
  display: flex;
  min-height: 58px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 7px;
  text-align: center;
}

.arx-flow__core {
  border-color: #AFC4A8;
  background: #EEF4EB;
}

.arx-flow__arrow {
  color: #78946F;
  font-size: 16px;
}

.arx-table-wrap {
  margin-top: 10px;
  overflow-x: auto;
}

.arx-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.arx-table th,
.arx-table td {
  padding: 7px 9px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
}

.arx-table th {
  color: var(--text-tertiary);
  font-size: 9px;
  font-weight: 600;
}

.arx-table td {
  color: var(--text-secondary);
}

.arx-empty {
  padding: 13px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}

.arx-technical summary {
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.arx-technical__body {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.arx-metadata {
  display: grid;
  gap: 5px;
  margin: 0;
}

.arx-metadata div {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 8px;
}

.arx-metadata dt {
  color: var(--text-tertiary);
  font-size: 9px;
}

.arx-metadata dd {
  overflow: hidden;
  margin: 0;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arx-technical-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  color: var(--text-tertiary);
  font-size: 10px;
}

.arx-technical-metrics strong {
  margin-left: 4px;
  color: var(--text-primary);
}

.arx-priors h5 {
  margin-bottom: 5px;
  color: var(--text-secondary);
  font-size: 10px;
}

.arx-priors pre,
.arx-raw {
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
  .arx-model__header {
    grid-template-columns: 1fr;
    gap: 7px;
  }

  .arx-flow {
    grid-template-columns: 1fr;
  }

  .arx-flow__arrow {
    transform: rotate(90deg);
    justify-self: center;
  }
}
</style>
