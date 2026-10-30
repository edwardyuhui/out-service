<template>
  <section class="anomaly-artifact" data-test="anomaly-artifact-renderer">
    <header v-if="!compact" class="anomaly-artifact__header">
      <h3>异常检测详情</h3>
      <p v-if="summary" data-test="anomaly-summary">{{ summary }}</p>
    </header>

    <div v-if="overviewCards.length" class="anomaly-overview" data-test="anomaly-overview">
      <article v-for="card in overviewCards" :key="card.key" class="anomaly-overview__card">
        <span>{{ card.label }}</span>
        <strong class="tabular-nums">{{ card.value }}</strong>
      </article>
    </div>

    <section v-if="zeroAnomalyState" class="anomaly-zero-state" data-test="anomaly-zero-state">
      <strong>本次未检出疑似异常点</strong>
      <span>异常比例 {{ ((ratio ?? 0) * 100).toFixed(2) }}%</span>
    </section>

    <section v-if="ratio !== null && !zeroAnomalyState" class="anomaly-section" data-test="anomaly-ratio-chart">
      <div class="anomaly-section__heading">
        <h4>疑似异常占比</h4>
        <span>真实 0%–100% 比例</span>
      </div>
      <ChartContainer :options="ratioChartOptions" height="112px" />
    </section>

    <section v-if="knownMetricRows.length || otherMetricRows.length" class="anomaly-section" data-test="anomaly-metrics">
      <div class="anomaly-section__heading">
        <h4>指标明细</h4>
      </div>
      <div class="anomaly-metric-table" role="table" aria-label="异常检测指标明细">
        <div class="anomaly-metric-table__header" role="row">
          <span role="columnheader">指标</span>
          <span role="columnheader">当前值</span>
          <span role="columnheader">说明</span>
        </div>
        <div v-for="row in knownMetricRows" :key="row.key" class="anomaly-metric-row" role="row">
          <span role="cell">{{ row.label }}</span>
          <strong role="cell">{{ row.value }}</strong>
          <span role="cell">{{ row.description }}</span>
        </div>
      </div>

      <div v-if="otherMetricRows.length" class="anomaly-other" data-test="anomaly-other-metrics">
        <h5>其他指标</h5>
        <div v-for="row in otherMetricRows" :key="row.key" class="anomaly-other__row">
          <code>{{ row.key }}</code>
          <span>{{ row.value }}</span>
        </div>
      </div>
    </section>

    <p v-if="!hasStructuredContent" class="anomaly-artifact__empty" data-test="anomaly-empty">
      暂无可结构化展示的异常检测结果
    </p>

    <div v-if="!compact" class="anomaly-raw">
      <button
        type="button"
        class="anomaly-raw__toggle"
        :aria-expanded="rawExpanded"
        @click="rawExpanded = !rawExpanded"
      >
        {{ rawExpanded ? "收起原始数据" : "查看原始数据" }}
      </button>
      <pre v-if="rawExpanded" class="anomaly-raw__content font-mono" data-test="anomaly-raw-data">{{ rawPayload }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import ChartContainer, { type ChartOption } from "../ChartContainer.vue";

type MetricRow = {
  key: string;
  label: string;
  value: string;
  description: string;
};

const props = defineProps<{
  payload?: Record<string, unknown> | null;
  compact?: boolean;
}>();

const compact = computed(() => props.compact ?? false);

const rawExpanded = ref(false);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const finiteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const rootPayload = computed<Record<string, unknown>>(() =>
  isRecord(props.payload) ? props.payload : {}
);

const resultPayload = computed<Record<string, unknown>>(() =>
  isRecord(rootPayload.value.result) ? rootPayload.value.result : rootPayload.value
);

const summary = computed(() => {
  const value = rootPayload.value.summary ?? resultPayload.value.summary;
  return typeof value === "string" && value.trim() ? value.trim() : "";
});

const count = computed(() => {
  const value = finiteNumber(resultPayload.value.anomaly_count);
  return value !== null && value >= 0 && Number.isInteger(value) ? value : null;
});

const ratio = computed(() => {
  const value = finiteNumber(resultPayload.value.anomaly_ratio);
  return value !== null && value >= 0 && value <= 1 ? value : null;
});

const zeroAnomalyState = computed(() => count.value === 0);
const ratioPercent = computed(() => (ratio.value ?? 0) * 100);
const sampleTotal = computed(() => {
  const explicit = finiteNumber(
    resultPayload.value.total
      ?? resultPayload.value.n_samples
      ?? resultPayload.value.sample_count
  );
  if (explicit !== null && explicit >= 0 && Number.isInteger(explicit)) return explicit;
  if (count.value !== null && count.value > 0 && ratio.value !== null && ratio.value > 0) {
    const derived = Math.round(count.value / ratio.value);
    return derived > 0 ? derived : null;
  }
  return null;
});

const ratioTooltip = (): string => {
  const lines = [`异常比例：${ratioPercent.value.toFixed(2)}%`];
  if (count.value !== null && sampleTotal.value !== null) {
    lines.push(
      `异常样本：${count.value.toLocaleString("zh-CN")} / ${sampleTotal.value.toLocaleString("zh-CN")} 个样本`
    );
  } else if (count.value !== null) {
    lines.push(`异常样本：${count.value.toLocaleString("zh-CN")} 个`);
  }
  return lines.join("<br/>");
};

const ratioChartOptions = computed<ChartOption>(() => ({
  animation: false,
  grid: { left: 70, right: 28, top: 8, bottom: 26 },
  tooltip: {
    trigger: "item",
    formatter: (_params: unknown) => ratioTooltip(),
  },
  xAxis: {
    type: "value",
    min: 0,
    max: 100,
    interval: 20,
    axisLabel: { formatter: "{value}%", color: "#8E8E93", fontSize: 10 },
    axisLine: { lineStyle: { color: "#DDE3DA" } },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: "#EEF1EC" } },
  },
  yAxis: {
    type: "category",
    data: ["异常比例"],
    axisLabel: { color: "#596157", fontSize: 10 },
    axisLine: { show: false },
    axisTick: { show: false },
  },
  series: [{
    type: "bar",
    data: [ratioPercent.value],
    barWidth: 14,
    itemStyle: { color: "#82A978", borderRadius: [0, 3, 3, 0] },
  }],
}));

const overviewCards = computed(() => {
  if (zeroAnomalyState.value) return [];
  const cards: Array<{ key: string; label: string; value: string }> = [];
  if (count.value !== null) {
    cards.push({ key: "anomaly_count", label: "异常点数量", value: Math.round(count.value).toLocaleString("zh-CN") });
  }
  if (ratio.value !== null) {
    cards.push({ key: "anomaly_ratio", label: "异常比例", value: `${(ratio.value * 100).toFixed(2)}%` });
  }
  return cards;
});

const formatRawValue = (value: unknown): string => {
  if (value === undefined) return "不可用";
  if (value === null) return "null";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (["string", "boolean", "number"].includes(typeof value)) return String(value);
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
};

const knownMetricRows = computed<MetricRow[]>(() => {
  const rows: MetricRow[] = [];
  if (Object.prototype.hasOwnProperty.call(resultPayload.value, "anomaly_count")) {
    rows.push({
      key: "anomaly_count",
      label: "异常点数量",
      value: count.value === null ? formatRawValue(resultPayload.value.anomaly_count) : Math.round(count.value).toLocaleString("zh-CN"),
      description: "Hampel 检测标记的疑似异常样本数量",
    });
  }
  if (Object.prototype.hasOwnProperty.call(resultPayload.value, "anomaly_ratio")) {
    rows.push({
      key: "anomaly_ratio",
      label: "异常比例",
      value: ratio.value === null ? formatRawValue(resultPayload.value.anomaly_ratio) : `${(ratio.value * 100).toFixed(2)}%`,
      description: "疑似异常样本数量占输出序列样本数的比例",
    });
  }
  return rows;
});

const RESERVED_KEYS = new Set([
  "summary",
  "result",
  "duration_ms",
  "error_code",
  "total",
  "n_samples",
  "sample_count",
]);
const KNOWN_KEYS = new Set(["anomaly_count", "anomaly_ratio"]);

const otherMetricRows = computed(() => Object.entries(resultPayload.value)
  .filter(([key]) => !KNOWN_KEYS.has(key) && !RESERVED_KEYS.has(key))
  .map(([key, value]) => ({ key, value: formatRawValue(value) })));

const hasStructuredContent = computed(() =>
  Boolean(summary.value || overviewCards.value.length || knownMetricRows.value.length || otherMetricRows.value.length)
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
.anomaly-artifact { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.anomaly-artifact__header h3,
.anomaly-section__heading h4,
.anomaly-other h5 { margin: 0; font-family: var(--font-sans); color: var(--text-primary); }
.anomaly-artifact__header h3 { font-size: 15px; font-weight: 600; }
.anomaly-artifact__header p { margin: 6px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.anomaly-overview { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.anomaly-overview__card { min-width: 0; padding: 11px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: var(--surface-2); }
.anomaly-overview__card span { display: block; color: var(--text-tertiary); font-size: 10px; }
.anomaly-overview__card strong { display: block; margin-top: 4px; color: var(--text-primary); font-size: 18px; font-weight: 700; }
.anomaly-section { min-width: 0; padding-top: 14px; border-top: 1px solid var(--border-subtle); }
.anomaly-section__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.anomaly-section__heading h4 { font-size: 13px; font-weight: 600; }
.anomaly-section__heading span { color: var(--text-muted); font-size: 10px; text-align: right; }
.anomaly-metric-table { overflow: hidden; border: 1px solid var(--border-default); border-radius: 7px; }
.anomaly-metric-table__header,
.anomaly-metric-row { display: grid; grid-template-columns: minmax(92px, 0.8fr) minmax(72px, auto) minmax(150px, 1.5fr); gap: 10px; align-items: center; padding: 8px 10px; }
.anomaly-metric-table__header { background: var(--surface-2); color: var(--text-tertiary); font-size: 10px; font-weight: 600; }
.anomaly-metric-row { border-top: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 11px; line-height: 1.45; }
.anomaly-metric-row strong { color: var(--text-primary); font-size: 11px; font-weight: 600; }
.anomaly-other { margin-top: 12px; }
.anomaly-other h5 { margin-bottom: 6px; font-size: 12px; font-weight: 600; }
.anomaly-other__row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; padding: 6px 0; border-top: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 11px; overflow-wrap: anywhere; }
.anomaly-other__row code { color: var(--text-primary); font-family: var(--font-mono); }
.anomaly-artifact__empty { margin: 0; padding: 18px 12px; border: 1px dashed var(--border-default); border-radius: 7px; color: var(--text-muted); font-size: 12px; text-align: center; }
.anomaly-zero-state { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: var(--surface-2); }
.anomaly-zero-state strong { color: var(--text-primary); font-size: 12px; }
.anomaly-zero-state span { color: var(--text-secondary); font-size: 11px; }
.anomaly-raw { padding-top: 12px; border-top: 1px solid var(--border-subtle); }
.anomaly-raw__toggle { border: 0; background: transparent; color: var(--accent-dark); font-family: var(--font-sans); font-size: 12px; font-weight: 600; cursor: pointer; }
.anomaly-raw__content { max-width: 100%; max-height: 240px; overflow: auto; margin: 10px 0 0; padding: 12px; border: 1px solid var(--border-default); border-radius: 6px; background: #F7F8F5; color: var(--text-secondary); font-size: 10px; line-height: 1.55; white-space: pre; }
@media (max-width: 520px) {
  .anomaly-overview { grid-template-columns: 1fr; }
  .anomaly-section__heading { align-items: flex-start; flex-direction: column; gap: 2px; }
  .anomaly-section__heading span { text-align: left; }
  .anomaly-metric-table__header { display: none; }
  .anomaly-metric-row { grid-template-columns: minmax(0, 1fr); gap: 3px; padding-block: 10px; }
}
</style>
