<template>
  <section class="profile-artifact" data-test="profile-artifact-renderer">
    <header v-if="!compact" class="profile-artifact__header">
      <h3>数据画像详情</h3>
      <p v-if="summary" data-test="profile-summary">{{ summary }}</p>
    </header>

    <div v-if="overviewCards.length" class="profile-overview" data-test="profile-overview">
      <article v-for="card in overviewCards" :key="card.key" class="profile-overview__card">
        <span>{{ card.label }}</span>
        <strong class="tabular-nums">{{ card.value }}</strong>
      </article>
    </div>

    <section v-if="qualityRatioMetrics.length" class="profile-section" data-test="profile-quality-chart">
      <div class="profile-section__heading">
        <h4>数据质量比例</h4>
        <span>统一按 0%–100% 展示事实比例</span>
      </div>
      <ChartContainer :options="qualityChartOptions" height="180px" />
    </section>

    <section v-if="knownMetricRows.length || otherMetricRows.length" class="profile-section" data-test="profile-metrics">
      <div class="profile-section__heading">
        <h4>指标明细</h4>
      </div>
      <div class="profile-metric-table" role="table" aria-label="数据画像指标明细">
        <div class="profile-metric-table__header" role="row">
          <span role="columnheader">指标</span>
          <span role="columnheader">当前值</span>
          <span role="columnheader">说明</span>
        </div>
        <div v-for="row in knownMetricRows" :key="row.key" class="profile-metric-row" role="row">
          <span role="cell">{{ row.label }}</span>
          <strong role="cell">{{ row.value }}</strong>
          <span role="cell">{{ row.description }}</span>
        </div>
      </div>

      <div v-if="otherMetricRows.length" class="profile-other-metrics" data-test="profile-other-metrics">
        <h5>其他指标</h5>
        <div v-for="row in otherMetricRows" :key="row.key" class="profile-other-row">
          <code>{{ row.key }}</code>
          <span>{{ row.value }}</span>
        </div>
      </div>
    </section>

    <p v-if="!hasStructuredContent" class="profile-artifact__empty" data-test="profile-empty">
      暂无可结构化展示的数据画像结果
    </p>

    <div v-if="!compact" class="profile-raw">
      <button
        type="button"
        class="profile-raw__toggle"
        :aria-expanded="rawExpanded"
        @click="rawExpanded = !rawExpanded"
      >
        {{ rawExpanded ? "收起原始数据" : "查看原始数据" }}
      </button>
      <pre v-if="rawExpanded" class="profile-raw__content font-mono" data-test="profile-raw-data">{{ rawPayload }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import ChartContainer, { type ChartOption } from "../ChartContainer.vue";

type MetricDefinition = {
  label: string;
  description: string;
  format: "percentage" | "decimal";
};

type MetricRow = {
  key: string;
  label: string;
  value: string;
  description: string;
};

const props = defineProps<{
  payload: Record<string, unknown>;
  compact?: boolean;
}>();

const compact = computed(() => props.compact ?? false);

const rawExpanded = ref(false);

const METRIC_DEFINITIONS: Record<string, MetricDefinition> = {
  log_sample_count: {
    label: "样本规模指纹",
    description: "log10(样本数) / 6 的归一化指纹值，不代表原始样本数",
    format: "decimal",
  },
  input_count: {
    label: "输入数量指纹",
    description: "min(输入变量数, 8) / 8 的归一化指纹值，不代表原始输入数量",
    format: "decimal",
  },
  missing_ratio: {
    label: "缺失率",
    description: "输入与输出全部观测值中的非有限值比例",
    format: "percentage",
  },
  anomaly_ratio: {
    label: "画像离群比例",
    description: "输出序列中基于 MAD 3σ 规则识别的离群样本占比，属于数据画像指纹指标，与正式 Hampel 异常检测结果不是同一指标",
    format: "percentage",
  },
  snr_db_scaled: {
    label: "SNR 归一化值",
    description: "估算 SNR 在 0–60 dB 工作范围内归一化并裁剪至 0–1",
    format: "decimal",
  },
  dynamic_ratio: {
    label: "输入动态比例",
    description: "输入序列处于变化状态的样本差分比例",
    format: "percentage",
  },
  output_autocorrelation: {
    label: "输出一阶自相关",
    description: "输出序列的一阶自相关系数，范围为 -1 至 1",
    format: "decimal",
  },
  input_autocorrelation: {
    label: "输入平均一阶自相关",
    description: "各输入序列一阶自相关系数的平均值",
    format: "decimal",
  },
  collinearity_scaled: {
    label: "最大输入相关系数",
    description: "输入变量两两相关系数绝对值的最大值，范围为 0 至 1",
    format: "decimal",
  },
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const finiteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const resultPayload = computed<Record<string, unknown>>(() =>
  isRecord(props.payload.result) ? props.payload.result : props.payload
);

const summary = computed(() => {
  const value = props.payload.summary ?? resultPayload.value.summary;
  return typeof value === "string" && value.trim() ? value.trim() : "";
});

const fingerprint = computed<Record<string, unknown> | null>(() => {
  const value = resultPayload.value.fingerprint;
  return isRecord(value) ? value : null;
});

const fingerprintValues = computed<Record<string, unknown>>(() => {
  const value = fingerprint.value?.values;
  return isRecord(value) ? value : {};
});

const fingerprintKeys = computed(() => {
  const fields = fingerprint.value?.fields;
  const declaredFields = Array.isArray(fields)
    ? fields.filter((field): field is string => typeof field === "string")
    : [];
  return [...new Set([...declaredFields, ...Object.keys(fingerprintValues.value)])];
});

const formatMetricValue = (value: unknown, definition?: MetricDefinition): string => {
  const numeric = finiteNumber(value);
  if (numeric !== null && definition?.format === "percentage" && numeric >= 0 && numeric <= 1) {
    return `${(numeric * 100).toFixed(2)}%`;
  }
  if (numeric !== null) return numeric.toFixed(4);
  if (value === undefined) return "不可用";
  if (value === null) return "null";
  if (["string", "boolean", "number"].includes(typeof value)) return String(value);
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
};

const knownMetricRows = computed<MetricRow[]>(() => fingerprintKeys.value
  .filter((key) => METRIC_DEFINITIONS[key])
  .map((key) => {
    const definition = METRIC_DEFINITIONS[key]!;
    return {
      key,
      label: definition.label,
      value: formatMetricValue(fingerprintValues.value[key], definition),
      description: definition.description,
    };
  }));

const otherMetricRows = computed(() => fingerprintKeys.value
  .filter((key) => !METRIC_DEFINITIONS[key])
  .map((key) => ({ key, value: formatMetricValue(fingerprintValues.value[key]) })));

const validRatio = (key: string): number | null => {
  const value = finiteNumber(fingerprintValues.value[key]);
  return value !== null && value >= 0 && value <= 1 ? value : null;
};

const overviewCards = computed(() => {
  const cards: Array<{ key: string; label: string; value: string }> = [];
  const sampleCount = finiteNumber(resultPayload.value.n_samples);
  if (sampleCount !== null && sampleCount >= 0) {
    cards.push({ key: "n_samples", label: "样本规模", value: Math.round(sampleCount).toLocaleString("zh-CN") });
  }
  const candidates = [
    ["missing_ratio", "缺失率"],
    ["anomaly_ratio", "画像离群比例"],
    ["dynamic_ratio", "输入动态比例"],
  ] as const;
  candidates.forEach(([key, label]) => {
    const value = validRatio(key);
    if (value !== null) cards.push({ key, label, value: `${(value * 100).toFixed(2)}%` });
  });
  return cards.slice(0, 4);
});

const qualityRatioMetrics = computed(() => ([
  { key: "missing_ratio", label: "缺失率" },
  { key: "anomaly_ratio", label: "画像离群比例" },
] as const).flatMap((metric) => {
  const value = validRatio(metric.key);
  return value === null ? [] : [{ ...metric, value: Number((value * 100).toFixed(2)) }];
}));

const qualityChartOptions = computed<ChartOption>(() => ({
  animation: false,
  grid: { left: 58, right: 46, top: 12, bottom: 28 },
  tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
  xAxis: {
    type: "value",
    min: 0,
    max: 100,
    axisLabel: { formatter: "{value}%", color: "#8E8E93", fontSize: 10 },
    axisLine: { lineStyle: { color: "#DDE3DA" } },
    splitLine: { lineStyle: { color: "#EEF1EC" } },
  },
  yAxis: {
    type: "category",
    data: qualityRatioMetrics.value.map((metric) => metric.label),
    axisLabel: { color: "#596157", fontSize: 11 },
    axisLine: { show: false },
    axisTick: { show: false },
  },
  series: [{
    type: "bar",
    data: qualityRatioMetrics.value.map((metric) => metric.value),
    barWidth: 14,
    itemStyle: { color: "#82A978", borderRadius: [0, 3, 3, 0] },
    label: { show: true, position: "right", formatter: "{c}%", color: "#596157", fontSize: 10 },
  }],
}));

const hasStructuredContent = computed(() =>
  Boolean(summary.value || overviewCards.value.length || knownMetricRows.value.length || otherMetricRows.value.length)
);

const rawPayload = computed(() => {
  try {
    return JSON.stringify(props.payload, null, 2) ?? String(props.payload);
  } catch {
    return String(props.payload);
  }
});
</script>

<style scoped>
.profile-artifact {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.profile-artifact__header h3,
.profile-section__heading h4,
.profile-other-metrics h5 {
  margin: 0;
  font-family: var(--font-sans);
  color: var(--text-primary);
}

.profile-artifact__header h3 {
  font-size: 15px;
  font-weight: 600;
}

.profile-artifact__header p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.profile-overview {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.profile-overview__card {
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid var(--border-default);
  border-radius: 7px;
  background: var(--surface-2);
  box-shadow: none;
}

.profile-overview__card span {
  display: block;
  color: var(--text-tertiary);
  font-size: 10px;
}

.profile-overview__card strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 700;
}

.profile-section {
  min-width: 0;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}

.profile-section__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.profile-section__heading h4 {
  font-size: 13px;
  font-weight: 600;
}

.profile-section__heading span {
  color: var(--text-muted);
  font-size: 10px;
  text-align: right;
}

.profile-metric-table {
  overflow: hidden;
  border: 1px solid var(--border-default);
  border-radius: 7px;
}

.profile-metric-table__header,
.profile-metric-row {
  display: grid;
  grid-template-columns: minmax(92px, 0.8fr) minmax(72px, auto) minmax(150px, 1.5fr);
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
}

.profile-metric-table__header {
  background: var(--surface-2);
  color: var(--text-tertiary);
  font-size: 10px;
  font-weight: 600;
}

.profile-metric-row {
  border-top: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.45;
}

.profile-metric-row strong {
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 600;
}

.profile-other-metrics {
  margin-top: 12px;
}

.profile-other-metrics h5 {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
}

.profile-other-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  padding: 6px 0;
  border-top: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.profile-other-row code {
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.profile-artifact__empty {
  margin: 0;
  padding: 18px 12px;
  border: 1px dashed var(--border-default);
  border-radius: 7px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

.profile-raw {
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.profile-raw__toggle {
  border: 0;
  background: transparent;
  color: var(--accent-dark);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.profile-raw__content {
  max-width: 100%;
  max-height: 240px;
  overflow: auto;
  margin: 10px 0 0;
  padding: 12px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: #F7F8F5;
  color: var(--text-secondary);
  font-size: 10px;
  line-height: 1.55;
  white-space: pre;
}

@media (max-width: 520px) {
  .profile-overview {
    grid-template-columns: 1fr;
  }

  .profile-section__heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }

  .profile-section__heading span {
    text-align: left;
  }

  .profile-metric-table__header,
  .profile-metric-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 3px;
  }

  .profile-metric-table__header {
    display: none;
  }

  .profile-metric-row {
    padding-block: 10px;
  }
}
</style>
