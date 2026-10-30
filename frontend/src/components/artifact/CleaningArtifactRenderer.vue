<template>
  <section class="cleaning-artifact" data-test="cleaning-artifact-renderer">
    <header v-if="!compact" class="cleaning-artifact__header">
      <h3>数据清洗详情</h3>
      <p v-if="summary" data-test="cleaning-summary">{{ summary }}</p>
    </header>

    <section v-if="statusCards.length" class="cleaning-section" data-test="cleaning-status">
      <h4>执行状态</h4>
      <div class="cleaning-status-grid">
        <article v-for="card in statusCards" :key="card.label" class="cleaning-status-card">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </article>
      </div>
    </section>

    <section v-if="impactCards.length" class="cleaning-section" data-test="cleaning-impact-overview">
      <h4>清洗影响概览</h4>
      <div class="cleaning-impact-grid">
        <article v-for="card in impactCards" :key="card.key" class="cleaning-impact-card">
          <span>{{ card.label }}</span>
          <strong class="tabular-nums">{{ card.value }}</strong>
        </article>
      </div>
    </section>

    <section v-if="hasRecordedActionCounts" class="cleaning-section" data-test="cleaning-action-distribution">
      <div class="cleaning-section__heading">
        <h4>处理类型分布</h4>
        <span>各类处理的独立事实计数</span>
      </div>
      <ChartContainer
        v-if="actionMetrics.length"
        data-test="cleaning-action-chart"
        :options="actionChartOptions"
        :height="actionChartHeight"
      />
      <p v-else class="cleaning-chart-empty" data-test="cleaning-action-empty">
        {{ compact ? "本次清洗未修改数据" : "本次未记录具体清洗动作计数。" }}
      </p>
      <p v-if="countsMayOverlap" class="cleaning-overlap-note" data-test="cleaning-overlap-note">
        各类计数可能重叠，不表示占比构成。
      </p>
    </section>

    <section v-if="rowsUnchanged" class="cleaning-row-unchanged" data-test="cleaning-row-count-unchanged">
      <strong>样本规模保持不变</strong>
      <span class="tabular-nums">{{ rowsUnchanged.before.toLocaleString("zh-CN") }} → {{ rowsUnchanged.after.toLocaleString("zh-CN") }}</span>
    </section>

    <section v-if="rowCounts && !rowsUnchanged" class="cleaning-section" data-test="cleaning-row-count-chart">
      <div class="cleaning-section__heading">
        <h4>样本规模变化</h4>
        <span>清洗前后事实行数</span>
      </div>
      <ChartContainer :options="rowCountChartOptions" height="180px" />
    </section>

    <section v-if="missingCounts" class="cleaning-section" data-test="cleaning-missing-count-chart">
      <div class="cleaning-section__heading">
        <h4>缺失数据变化</h4>
        <span>仅展示明确提供的清洗前后计数</span>
      </div>
      <ChartContainer :options="missingCountChartOptions" height="180px" />
    </section>

    <section v-if="metricRows.length || otherMetricRows.length" class="cleaning-section" data-test="cleaning-metrics">
      <h4>清洗指标明细</h4>
      <div v-if="metricRows.length" class="cleaning-metric-table" role="table" aria-label="清洗指标明细">
        <div class="cleaning-metric-table__header" role="row">
          <span role="columnheader">指标</span>
          <span role="columnheader">当前值</span>
          <span role="columnheader">说明</span>
        </div>
        <div v-for="row in metricRows" :key="row.key" class="cleaning-metric-row" role="row">
          <span role="cell">{{ row.label }}</span>
          <strong role="cell">{{ row.value }}</strong>
          <span role="cell">{{ row.description }}</span>
        </div>
      </div>
      <div v-if="otherMetricRows.length" class="cleaning-other" data-test="cleaning-other-metrics">
        <h5>其他清洗指标</h5>
        <div v-for="row in otherMetricRows" :key="row.key" class="cleaning-other__row">
          <code>{{ row.key }}</code>
          <span>{{ row.value }}</span>
        </div>
      </div>
    </section>

    <section v-if="processingRunId && !compact" class="cleaning-section" data-test="cleaning-provenance">
      <h4>技术追溯</h4>
      <div class="cleaning-provenance-row">
        <span>Processing Run</span>
        <code :title="processingRunId">{{ shortId(processingRunId) }}</code>
      </div>
    </section>

    <p v-if="!hasStructuredContent" class="cleaning-artifact__empty" data-test="cleaning-empty">
      暂无可结构化展示的数据清洗结果
    </p>

    <div v-if="!compact" class="cleaning-raw">
      <button
        type="button"
        class="cleaning-raw__toggle"
        :aria-expanded="rawExpanded"
        @click="rawExpanded = !rawExpanded"
      >
        {{ rawExpanded ? "收起原始数据" : "查看原始数据" }}
      </button>
      <pre v-if="rawExpanded" class="cleaning-raw__content font-mono" data-test="cleaning-raw-data">{{ rawPayload }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import ChartContainer, { type ChartOption } from "../ChartContainer.vue";

type CleaningState = "changed" | "created_no_change" | "converged" | "reused";

type MetricDefinition = {
  label: string;
  description: string;
};

type CountPair = {
  before: number;
  after: number;
};

const props = defineProps<{
  payload?: Record<string, unknown> | null;
  compact?: boolean;
}>();

const compact = computed(() => props.compact ?? false);

const rawExpanded = ref(false);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const finiteCount = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && Number.isInteger(value)
    ? value
    : null;

const nonEmptyString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const rootPayload = computed<Record<string, unknown>>(() =>
  isRecord(props.payload) ? props.payload : {}
);

const resultPayload = computed<Record<string, unknown>>(() =>
  isRecord(rootPayload.value.result) ? rootPayload.value.result : rootPayload.value
);

const state = computed<CleaningState | null>(() => {
  const result = resultPayload.value;
  if (result.reused_existing_version === true) return "reused";
  if (result.created_new_version === true) {
    return result.no_op === true ? "created_no_change" : "changed";
  }
  if (
    result.created_new_version === false
    && result.no_op === true
    && result.converged === true
    && result.reused_existing_version !== true
  ) return "converged";
  return null;
});

const derivedSummary = computed(() => {
  switch (state.value) {
    case "changed":
      return "本次清洗已生成新的数据版本，并对数据内容进行了实际修正。";
    case "created_no_change":
      return "本次清洗完成零变化认证，并生成了新的数据版本。";
    case "converged":
      return "清洗结果已收敛，本次未生成新的数据版本。";
    case "reused":
      return "相同清洗结果已存在，本次复用现有数据版本。";
    default:
      return "";
  }
});

const summary = computed(() => {
  const explicit = rootPayload.value.summary ?? resultPayload.value.summary;
  return typeof explicit === "string" && explicit.trim() ? explicit.trim() : derivedSummary.value;
});

const statusCards = computed(() => {
  switch (state.value) {
    case "changed":
      return [
        { label: "版本处理", value: "已生成新版本" },
        { label: "数据结果", value: "结果有变化" },
        { label: "执行语义", value: "正常清洗" },
      ];
    case "created_no_change":
      return [
        { label: "版本处理", value: "已生成新版本" },
        { label: "数据结果", value: "数据状态不变" },
        { label: "执行语义", value: "零变化认证" },
      ];
    case "converged":
      return [
        { label: "版本处理", value: "未生成新版本" },
        { label: "数据结果", value: "数据状态不变" },
        { label: "执行语义", value: "已收敛" },
      ];
    case "reused":
      return [
        { label: "版本处理", value: "复用既有版本" },
        { label: "数据结果", value: "结果有变化" },
        { label: "执行语义", value: "幂等复用" },
      ];
    default:
      return [];
  }
});

const processingRunId = computed(() => nonEmptyString(resultPayload.value.processing_run_id));

const summaryPayload = computed<Record<string, unknown>>(() =>
  isRecord(resultPayload.value.summary) ? resultPayload.value.summary : {}
);

const changeSummary = computed<Record<string, unknown> | null>(() => {
  if (isRecord(summaryPayload.value.changes)) return summaryPayload.value.changes;
  if (isRecord(resultPayload.value.change_summary)) return resultPayload.value.change_summary;
  return null;
});

const METRIC_DEFINITIONS: Record<string, MetricDefinition> = {
  unique_changed_cells: {
    label: "修改单元格",
    description: "本次 Cleaning 中发生实际修改的唯一单元格数量",
  },
  missing_value_fills: {
    label: "缺失填补",
    description: "通过已配置缺失值处理实际填补的单元格数量",
  },
  outlier_replacements: {
    label: "异常替换",
    description: "通过已配置异常处理策略实际替换的单元格数量",
  },
  duplicate_timestamps_processed: {
    label: "重复时间戳处理",
    description: "清洗期间按配置规则处理的重复时间戳数量",
  },
  resampling_empty_rows_created: {
    label: "重采样空行",
    description: "时间重采样过程创建的空数据行数量",
  },
  smoothing_changes: {
    label: "平滑修改",
    description: "平滑处理实际改变的单元格数量",
  },
  overlapping_changed_cells: {
    label: "重叠修改单元格",
    description: "多类处理同时影响同一单元格产生的重叠计数",
  },
  source_missing_cells: {
    label: "源数据缺失单元格",
    description: "进入清洗流程前源数据中的缺失单元格数量",
  },
  aligned_missing_cells_before_interpolation: {
    label: "插值前缺失单元格",
    description: "对齐与重采样后、执行插值前的缺失单元格数量",
  },
};

const IMPACT_KEYS = [
  "unique_changed_cells",
  "missing_value_fills",
  "outlier_replacements",
  "duplicate_timestamps_processed",
  "resampling_empty_rows_created",
  "smoothing_changes",
] as const;

const ACTION_KEYS = [
  "missing_value_fills",
  "outlier_replacements",
  "duplicate_timestamps_processed",
  "resampling_empty_rows_created",
  "smoothing_changes",
] as const;

const KNOWN_CHANGE_KEYS = new Set(Object.keys(METRIC_DEFINITIONS));
const RESERVED_CHANGE_KEYS = new Set([
  "count_unit",
  "category_counts_may_overlap",
  "breakdown_status",
  "remaining_missing_cells",
  "missing_before",
  "missing_after",
]);

const hasOwn = (record: Record<string, unknown> | null, key: string): boolean =>
  Boolean(record && Object.prototype.hasOwnProperty.call(record, key));

const countMetric = (key: string): number | null =>
  changeSummary.value ? finiteCount(changeSummary.value[key]) : null;

const impactCards = computed(() => IMPACT_KEYS.flatMap((key) => {
  if (!hasOwn(changeSummary.value, key)) return [];
  const value = countMetric(key);
  if (value === null) return [];
  return [{ key, label: METRIC_DEFINITIONS[key].label, value: value.toLocaleString("zh-CN") }];
}));

const actionMetrics = computed(() => ACTION_KEYS.flatMap((key) => {
  if (!hasOwn(changeSummary.value, key)) return [];
  const value = countMetric(key);
  if (value === null || value === 0) return [];
  return [{ key, label: METRIC_DEFINITIONS[key].label, value }];
}));

const hasRecordedActionCounts = computed(() =>
  ACTION_KEYS.some((key) => hasOwn(changeSummary.value, key) && countMetric(key) !== null)
);

const countsMayOverlap = computed(() => changeSummary.value?.category_counts_may_overlap === true);

const metricRows = computed(() => Object.entries(METRIC_DEFINITIONS).flatMap(([key, definition]) => {
  if (!hasOwn(changeSummary.value, key)) return [];
  const value = countMetric(key);
  if (value === null) return [];
  return [{ key, ...definition, value: value.toLocaleString("zh-CN") }];
}));

const scalarText = (value: unknown): string | null => {
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return value === null ? "null" : null;
};

const otherMetricRows = computed(() => {
  if (!changeSummary.value) return [];
  return Object.entries(changeSummary.value).flatMap(([key, value]) => {
    if (KNOWN_CHANGE_KEYS.has(key) || RESERVED_CHANGE_KEYS.has(key)) return [];
    const displayValue = scalarText(value);
    return displayValue === null ? [] : [{ key, value: displayValue }];
  });
});

const countFrom = (records: Record<string, unknown>[], key: string): number | null => {
  for (const record of records) {
    if (Object.prototype.hasOwnProperty.call(record, key)) return finiteCount(record[key]);
  }
  return null;
};

const rowCounts = computed<CountPair | null>(() => {
  const records = [summaryPayload.value, resultPayload.value];
  const before = countFrom(records, "rows_before");
  const after = countFrom(records, "rows_after");
  return before !== null && after !== null ? { before, after } : null;
});

const rowsUnchanged = computed<CountPair | null>(() =>
  rowCounts.value && rowCounts.value.before === rowCounts.value.after ? rowCounts.value : null
);

const missingCounts = computed<CountPair | null>(() => {
  const nestedMissing = isRecord(summaryPayload.value.missing) ? summaryPayload.value.missing : {};
  const nestedBefore = finiteCount(nestedMissing.before);
  const nestedAfter = finiteCount(nestedMissing.after);
  if (nestedBefore !== null && nestedAfter !== null) {
    return { before: nestedBefore, after: nestedAfter };
  }

  const records = [nestedMissing, changeSummary.value ?? {}, summaryPayload.value, resultPayload.value];
  const explicitBefore = countFrom(records, "missing_before");
  const explicitAfter = countFrom(records, "missing_after");
  if (explicitBefore !== null && explicitAfter !== null) {
    return { before: explicitBefore, after: explicitAfter };
  }

  const sourceMissing = countFrom(records, "source_missing_cells");
  const remainingMissing = countFrom(records, "remaining_missing_cells");
  return sourceMissing !== null && remainingMissing !== null
    ? { before: sourceMissing, after: remainingMissing }
    : null;
});

const independentBarOptions = (
  labels: string[],
  values: number[],
  horizontal: boolean
): ChartOption => ({
  animation: false,
  grid: horizontal
    ? { left: 96, right: 48, top: 10, bottom: 24 }
    : { left: 50, right: 24, top: 16, bottom: 40 },
  tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
  xAxis: horizontal
    ? {
        type: "value",
        min: 0,
        minInterval: 1,
        axisLabel: { color: "#8E8E93", fontSize: 10 },
        axisLine: { lineStyle: { color: "#DDE3DA" } },
        splitLine: { lineStyle: { color: "#EEF1EC" } },
      }
    : {
        type: "category",
        data: labels,
        axisLabel: { color: "#596157", fontSize: 10 },
        axisLine: { lineStyle: { color: "#DDE3DA" } },
        axisTick: { show: false },
      },
  yAxis: horizontal
    ? {
        type: "category",
        data: labels,
        axisLabel: { color: "#596157", fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false },
      }
    : {
        type: "value",
        min: 0,
        minInterval: 1,
        axisLabel: { color: "#8E8E93", fontSize: 10 },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "#EEF1EC" } },
      },
  series: [{
    type: "bar",
    data: values,
    barMaxWidth: 22,
    itemStyle: { color: "#82A978", borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] },
    label: { show: true, position: horizontal ? "right" : "top", color: "#596157", fontSize: 10 },
  }],
});

const actionChartOptions = computed<ChartOption>(() => independentBarOptions(
  actionMetrics.value.map((metric) => metric.label),
  actionMetrics.value.map((metric) => metric.value),
  true
));

const actionChartHeight = computed(() => `${Math.min(240, Math.max(150, actionMetrics.value.length * 34 + 54))}px`);

const rowCountChartOptions = computed<ChartOption>(() => independentBarOptions(
  ["清洗前", "清洗后"],
  rowCounts.value ? [rowCounts.value.before, rowCounts.value.after] : [],
  false
));

const missingCountChartOptions = computed<ChartOption>(() => independentBarOptions(
  ["清洗前", "清洗后"],
  missingCounts.value ? [missingCounts.value.before, missingCounts.value.after] : [],
  false
));

const shortId = (value: string): string =>
  value.length > 12 ? `${value.slice(0, 8)}…` : value;

const hasStructuredContent = computed(() => Boolean(
  summary.value
  || statusCards.value.length
  || impactCards.value.length
  || metricRows.value.length
  || otherMetricRows.value.length
  || rowCounts.value
  || missingCounts.value
  || processingRunId.value
));

const rawPayload = computed(() => {
  try {
    return JSON.stringify(props.payload ?? {}, null, 2) ?? String(props.payload ?? {});
  } catch {
    return String(props.payload ?? {});
  }
});
</script>

<style scoped>
.cleaning-artifact { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.cleaning-artifact__header h3,
.cleaning-section h4,
.cleaning-other h5 { margin: 0; font-family: var(--font-sans); color: var(--text-primary); }
.cleaning-artifact__header h3 { font-size: 15px; font-weight: 600; }
.cleaning-artifact__header p { margin: 6px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.cleaning-section { min-width: 0; padding-top: 14px; border-top: 1px solid var(--border-subtle); }
.cleaning-section h4 { margin-bottom: 8px; font-size: 13px; font-weight: 600; }
.cleaning-section__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.cleaning-section__heading h4 { margin-bottom: 0; }
.cleaning-section__heading span { color: var(--text-muted); font-size: 10px; text-align: right; }
.cleaning-status-grid,
.cleaning-impact-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.cleaning-status-card,
.cleaning-impact-card { min-width: 0; padding: 10px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: var(--surface-2); }
.cleaning-status-card span,
.cleaning-impact-card span { display: block; color: var(--text-tertiary); font-size: 10px; }
.cleaning-status-card strong,
.cleaning-impact-card strong { display: block; margin-top: 4px; color: var(--text-primary); font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.cleaning-impact-card strong { font-size: 18px; font-weight: 700; }
.cleaning-chart-empty { margin: 0; padding: 14px 12px; border: 1px dashed var(--border-default); border-radius: 7px; color: var(--text-muted); font-size: 11px; text-align: center; }
.cleaning-row-unchanged { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: var(--surface-2); }
.cleaning-row-unchanged strong { color: var(--text-primary); font-size: 12px; }
.cleaning-row-unchanged span { color: var(--text-secondary); font-size: 11px; }
.cleaning-overlap-note { margin: 7px 0 0; color: var(--text-muted); font-size: 10px; line-height: 1.5; }
.cleaning-metric-table { overflow: hidden; border: 1px solid var(--border-default); border-radius: 7px; }
.cleaning-metric-table__header,
.cleaning-metric-row { display: grid; grid-template-columns: minmax(108px, 0.8fr) minmax(72px, auto) minmax(170px, 1.6fr); gap: 10px; align-items: center; padding: 8px 10px; }
.cleaning-metric-table__header { background: var(--surface-2); color: var(--text-tertiary); font-size: 10px; font-weight: 600; }
.cleaning-metric-row { border-top: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 11px; line-height: 1.45; }
.cleaning-metric-row strong { color: var(--text-primary); font-size: 11px; font-weight: 600; }
.cleaning-other { margin-top: 12px; }
.cleaning-other h5 { margin-bottom: 6px; font-size: 12px; font-weight: 600; }
.cleaning-other__row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; padding: 6px 0; border-top: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 11px; overflow-wrap: anywhere; }
.cleaning-other__row code,
.cleaning-provenance-row code { color: var(--text-primary); font-family: var(--font-mono); font-size: 11px; overflow-wrap: anywhere; }
.cleaning-provenance-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 9px 11px; border: 1px solid var(--border-default); border-radius: 7px; color: var(--text-secondary); font-family: var(--font-sans); font-size: 11px; }
.cleaning-artifact__empty { margin: 0; padding: 18px 12px; border: 1px dashed var(--border-default); border-radius: 7px; color: var(--text-muted); font-size: 12px; text-align: center; }
.cleaning-raw { padding-top: 12px; border-top: 1px solid var(--border-subtle); }
.cleaning-raw__toggle { border: 0; background: transparent; color: var(--accent-dark); font-family: var(--font-sans); font-size: 12px; font-weight: 600; cursor: pointer; }
.cleaning-raw__content { max-width: 100%; max-height: 240px; overflow: auto; margin: 10px 0 0; padding: 12px; border: 1px solid var(--border-default); border-radius: 6px; background: #F7F8F5; color: var(--text-secondary); font-size: 10px; line-height: 1.55; white-space: pre; }
@media (max-width: 520px) {
  .cleaning-status-grid,
  .cleaning-impact-grid { grid-template-columns: 1fr; }
  .cleaning-section__heading { align-items: flex-start; flex-direction: column; gap: 2px; }
  .cleaning-section__heading span { text-align: left; }
  .cleaning-metric-table__header { display: none; }
  .cleaning-metric-row { grid-template-columns: minmax(0, 1fr); gap: 3px; padding-block: 10px; }
}
</style>
