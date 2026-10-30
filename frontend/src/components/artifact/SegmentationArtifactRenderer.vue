<template>
  <section class="segmentation-artifact" data-test="segmentation-artifact-renderer">
    <header class="segmentation-header">
      <h3>区间优选结果</h3>
      <p v-if="businessSummary" data-test="segmentation-summary">{{ businessSummary }}</p>
    </header>

    <div v-if="overviewCards.length" class="segmentation-overview" data-test="segmentation-overview">
      <article v-for="card in overviewCards" :key="card.key" class="segmentation-overview__card">
        <span>{{ card.label }}</span>
        <strong class="tabular-nums">{{ card.value }}</strong>
      </article>
    </div>

    <section
      v-if="coverageIntervals.length && domainSize"
      class="segmentation-section"
      data-test="segmentation-coverage-chart"
    >
      <div class="segmentation-section__heading">
        <div>
          <h4>样本区间覆盖</h4>
          <p>高亮区域为进入建模数据的真实样本区间</p>
        </div>
        <span>{{ usesTimestampAxis ? "时间轴" : "样本索引" }}</span>
      </div>
      <div class="segmentation-coverage__legend" data-test="segmentation-coverage-legend">
        <span>
          <i class="segmentation-coverage__swatch is-axis" aria-hidden="true"></i>
          整体样本轴
        </span>
        <span>
          <i class="segmentation-coverage__swatch is-selected" aria-hidden="true"></i>
          入选建模区间
        </span>
      </div>
      <ChartContainer :options="coverageChartOptions" height="176px" />
    </section>

    <p v-else class="segmentation-empty" data-test="segmentation-empty">
      当前结果未包含可视化区间数据，可在技术详情中查看原始结果。
    </p>

    <section
      v-if="rankedSegments.length"
      class="segmentation-section"
      data-test="segmentation-ranking-chart"
    >
      <div class="segmentation-section__heading">
        <div>
          <h4 data-test="segmentation-ranking-title">
            入选区间信息增益{{ showsTopEight ? " Top 8" : "" }}
          </h4>
          <p>按后端持久化的 D-最优信息增益展示</p>
          <p v-if="showsTopEight" data-test="segmentation-ranking-limit-note">
            共入选 {{ selectedIntervalCount?.toLocaleString("zh-CN") }} 个区间，当前展示信息增益最高的前 8 个。
          </p>
        </div>
        <span>bit</span>
      </div>
      <ChartContainer :options="rankingChartOptions" :height="rankingChartHeight" />
    </section>

    <section class="segmentation-technical" data-test="segmentation-technical-details">
      <button
        type="button"
        class="segmentation-technical__toggle"
        :aria-expanded="technicalExpanded"
        @click="technicalExpanded = !technicalExpanded"
      >
        <span>{{ technicalExpanded ? "收起技术详情" : "查看技术详情" }}</span>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
          :class="{ 'is-expanded': technicalExpanded }"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      <div v-if="technicalExpanded" class="segmentation-technical__body">
        <dl v-if="technicalMetadata.length" class="segmentation-metadata">
          <div v-for="item in technicalMetadata" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd class="font-mono" :title="item.value">{{ item.value }}</dd>
          </div>
        </dl>
        <pre class="segmentation-raw font-mono" data-test="segmentation-raw-data">{{ rawPayload }}</pre>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import ChartContainer, { type ChartOption } from "../ChartContainer.vue";
import {
  mergeSelectedSampleIndices,
  type SampleInterval,
} from "../../utils/segmentationArtifact";

type DisplayInterval = SampleInterval & {
  label: string;
  startTime: string | null;
  endTime: string | null;
  informationGain: number | null;
};

type RankedSegment = {
  label: string;
  value: number;
};

const props = defineProps<{
  payload?: Record<string, unknown> | null;
}>();

const technicalExpanded = ref(false);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const finiteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const nonNegativeInteger = (value: unknown): number | null => {
  const numeric = finiteNumber(value);
  return numeric !== null && numeric >= 0 && Number.isInteger(numeric) ? numeric : null;
};

const validRatio = (value: unknown): number | null => {
  const numeric = finiteNumber(value);
  return numeric !== null && numeric >= 0 && numeric <= 1 ? numeric : null;
};

const nonEmptyString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const rootPayload = computed<Record<string, unknown>>(() =>
  isRecord(props.payload) ? props.payload : {}
);

const resultPayload = computed<Record<string, unknown>>(() =>
  isRecord(rootPayload.value.result) ? rootPayload.value.result : rootPayload.value
);

const selection = computed<Record<string, unknown>>(() =>
  isRecord(resultPayload.value.selection)
    ? resultPayload.value.selection
    : isRecord(rootPayload.value.selection)
      ? rootPayload.value.selection
      : {}
);

const timestamps = computed<string[]>(() => {
  const values = resultPayload.value.timestamps ?? rootPayload.value.timestamps;
  return Array.isArray(values)
    ? values.filter((value): value is string => typeof value === "string")
    : [];
});

const projectedSampleCount = computed(() => {
  const lengths = [timestamps.value.length];
  if (isRecord(resultPayload.value.series)) {
    Object.values(resultPayload.value.series).forEach((values) => {
      if (Array.isArray(values)) lengths.push(values.length);
    });
  }
  return Math.max(0, ...lengths);
});

const explicitSelectedRows = computed(() => nonNegativeInteger(selection.value.selected_rows));
const explicitCoverageRatio = computed(() => validRatio(selection.value.coverage_ratio));

const metricSampleCount = computed(() => {
  if (
    explicitSelectedRows.value === null
    || explicitSelectedRows.value === 0
    || explicitCoverageRatio.value === null
    || explicitCoverageRatio.value === 0
  ) return 0;
  return Math.max(
    explicitSelectedRows.value,
    Math.round(explicitSelectedRows.value / explicitCoverageRatio.value)
  );
});

const knownSampleCount = computed<number | null>(() => {
  const count = Math.max(projectedSampleCount.value, metricSampleCount.value);
  return count > 0 ? count : null;
});

const rawSelectedIndices = computed(() => {
  const candidates = [
    resultPayload.value.selected_indices,
    resultPayload.value.selected_sample_indices,
    rootPayload.value.selected_indices,
    rootPayload.value.selected_sample_indices,
  ];
  return candidates.find((value) => Array.isArray(value) && value.length)
    ?? candidates.find(Array.isArray)
    ?? [];
});

const indexIntervals = computed(() =>
  mergeSelectedSampleIndices(rawSelectedIndices.value, knownSampleCount.value)
);

const segmentIntervals = computed<DisplayInterval[]>(() => {
  if (!Array.isArray(resultPayload.value.segments)) return [];
  const upperBound = knownSampleCount.value;
  return resultPayload.value.segments.flatMap((value, index) => {
    if (!isRecord(value)) return [];
    const startIndex = nonNegativeInteger(value.start_index);
    const endIndex = nonNegativeInteger(value.end_index);
    if (
      startIndex === null
      || endIndex === null
      || endIndex < startIndex
      || (upperBound !== null && (startIndex >= upperBound || endIndex >= upperBound))
    ) return [];

    const rank = nonNegativeInteger(value.rank);
    const informationGain = finiteNumber(
      value.information_gain_bits ?? value.dynamic_score
    );
    return [{
      startIndex,
      endIndex,
      count: nonNegativeInteger(value.n_rows) ?? endIndex - startIndex + 1,
      label: `区间 ${String(rank && rank > 0 ? rank : index + 1).padStart(2, "0")}`,
      startTime: nonEmptyString(value.start_time),
      endTime: nonEmptyString(value.end_time),
      informationGain,
    }];
  });
});

const coverageIntervals = computed<DisplayInterval[]>(() => {
  if (segmentIntervals.value.length) return segmentIntervals.value;
  return indexIntervals.value.map((interval, index) => ({
    ...interval,
    label: `区间 ${String(index + 1).padStart(2, "0")}`,
    startTime: timestamps.value[interval.startIndex] ?? null,
    endTime: timestamps.value[interval.endIndex] ?? null,
    informationGain: null,
  }));
});

const domainSize = computed(() => {
  if (knownSampleCount.value !== null) return knownSampleCount.value;
  const endIndices = coverageIntervals.value.map((interval) => interval.endIndex + 1);
  return Math.max(0, ...endIndices);
});

const usesTimestampAxis = computed(() =>
  domainSize.value > 0
  && timestamps.value.length >= domainSize.value
  && coverageIntervals.value.every((interval) => interval.endIndex < timestamps.value.length)
);

const selectedRows = computed(() => {
  if (explicitSelectedRows.value !== null) return explicitSelectedRows.value;
  if (indexIntervals.value.length) {
    return indexIntervals.value.reduce((total, interval) => total + interval.count, 0);
  }
  return null;
});

const selectedIntervalCount = computed(() => {
  const explicit = nonNegativeInteger(selection.value.selected_count);
  if (explicit !== null) return explicit;
  return coverageIntervals.value.length || null;
});

const showsTopEight = computed(() =>
  selectedIntervalCount.value !== null && selectedIntervalCount.value > 8
);

const candidateCount = computed(() => nonNegativeInteger(selection.value.candidate_count));

const overviewCards = computed(() => {
  const cards: Array<{ key: string; label: string; value: string }> = [];
  if (selectedRows.value !== null) {
    cards.push({
      key: "selected_rows",
      label: "入选样本数",
      value: selectedRows.value.toLocaleString("zh-CN"),
    });
  }
  if (selectedIntervalCount.value !== null) {
    cards.push({
      key: "selected_count",
      label: "入选区间数",
      value: selectedIntervalCount.value.toLocaleString("zh-CN"),
    });
  }
  if (explicitCoverageRatio.value !== null) {
    cards.push({
      key: "coverage_ratio",
      label: "全量可建模样本覆盖率",
      value: `${(explicitCoverageRatio.value * 100).toFixed(2)}%`,
    });
  }
  if (candidateCount.value !== null) {
    cards.push({
      key: "candidate_count",
      label: "候选窗口数",
      value: candidateCount.value.toLocaleString("zh-CN"),
    });
  }
  return cards.slice(0, 4);
});

const businessSummary = computed(() => {
  if (selectedRows.value === null && selectedIntervalCount.value === null) return "";
  if (selectedRows.value !== null && selectedIntervalCount.value !== null) {
    return `本次在训练分区中筛选出 ${selectedIntervalCount.value.toLocaleString("zh-CN")} 个有效动态区间，共覆盖 ${selectedRows.value.toLocaleString("zh-CN")} 个去重建模样本，用于后续 ARX 参数估计。`;
  }
  if (selectedRows.value !== null) {
    return `本次共筛选出 ${selectedRows.value.toLocaleString("zh-CN")} 个去重建模样本，用于后续 ARX 参数估计。`;
  }
  return `本次共筛选出 ${selectedIntervalCount.value?.toLocaleString("zh-CN")} 个有效动态区间，用于后续 ARX 参数估计。`;
});

const formatTime = (value: string): string => {
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

const intervalTooltip = (interval: DisplayInterval): string => {
  const lines = [interval.label];
  if (interval.startTime && interval.endTime) {
    lines.push(`起始时间：${formatTime(interval.startTime)}`);
    lines.push(`结束时间：${formatTime(interval.endTime)}`);
  }
  lines.push(`样本索引：${interval.startIndex}–${interval.endIndex}`);
  lines.push(`样本数：${interval.count.toLocaleString("zh-CN")}`);
  if (interval.informationGain !== null) {
    lines.push(`信息增益：${interval.informationGain.toFixed(4)} bit`);
  }
  return lines.join("<br/>");
};

const axisValue = (index: number): number | string =>
  usesTimestampAxis.value ? timestamps.value[index]! : index;

const axisEndValue = (index: number): number | string =>
  usesTimestampAxis.value ? timestamps.value[index]! : index + 1;

const chartFontFamily = "IndusOpt Sans, system-ui, sans-serif";

const coverageChartOptions = computed<ChartOption>(() => ({
  animation: false,
  textStyle: { fontFamily: chartFontFamily },
  grid: { left: 42, right: 22, top: 24, bottom: 42 },
  tooltip: {
    trigger: "item",
    appendTo: "body",
    confine: false,
    backgroundColor: "#FFFFFF",
    borderColor: "#E5E5E8",
    textStyle: { color: "#171717", fontFamily: chartFontFamily, fontSize: 11 },
  },
  xAxis: usesTimestampAxis.value
    ? {
        type: "category",
        data: timestamps.value.slice(0, domainSize.value),
        boundaryGap: false,
        axisLabel: {
          color: "#8E8E93",
          fontFamily: chartFontFamily,
          fontSize: 10,
          formatter: (value: string) => formatTime(value),
        },
        axisLine: { lineStyle: { color: "#DDE3DA" } },
        axisTick: { show: false },
      }
    : {
        type: "value",
        min: 0,
        max: Math.max(1, domainSize.value),
        minInterval: 1,
        axisLabel: { color: "#8E8E93", fontFamily: chartFontFamily, fontSize: 10 },
        axisLine: { lineStyle: { color: "#DDE3DA" } },
        splitLine: { lineStyle: { color: "#EEF1EC" } },
      },
  yAxis: {
    type: "value",
    min: 0,
    max: 1,
    show: false,
  },
  series: [{
    type: "line",
    data: usesTimestampAxis.value
      ? timestamps.value.slice(0, domainSize.value).map(() => 0.5)
      : [[0, 0.5], [Math.max(1, domainSize.value), 0.5]],
    symbol: "none",
    silent: true,
    lineStyle: { color: "#E8ECE6", width: 20 },
    markArea: {
      silent: false,
      label: { show: false },
      itemStyle: { color: "rgba(74, 124, 89, 0.62)" },
      emphasis: { itemStyle: { color: "rgba(47, 73, 46, 0.78)" } },
      data: coverageIntervals.value.map((interval) => ([
        {
          name: interval.label,
          xAxis: axisValue(interval.startIndex),
          tooltip: { formatter: () => intervalTooltip(interval) },
        },
        { xAxis: axisEndValue(interval.endIndex) },
      ])),
    },
  }],
}) as ChartOption);

const rankedSegments = computed<RankedSegment[]>(() =>
  segmentIntervals.value
    .filter((interval) => interval.informationGain !== null)
    .map((interval) => ({ label: interval.label, value: interval.informationGain! }))
    .slice(0, 8)
);

const rankingChartOptions = computed<ChartOption>(() => ({
  animation: false,
  textStyle: { fontFamily: chartFontFamily },
  grid: { left: 72, right: 54, top: 10, bottom: 28 },
  tooltip: {
    trigger: "axis",
    axisPointer: { type: "shadow" },
    appendTo: "body",
    confine: false,
    valueFormatter: (value: unknown) =>
      typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(4)} bit` : "",
  },
  xAxis: {
    type: "value",
    min: Math.min(0, ...rankedSegments.value.map((segment) => segment.value)),
    axisLabel: { color: "#8E8E93", fontFamily: chartFontFamily, fontSize: 10 },
    axisLine: { lineStyle: { color: "#DDE3DA" } },
    splitLine: { lineStyle: { color: "#EEF1EC" } },
  },
  yAxis: {
    type: "category",
    inverse: true,
    data: rankedSegments.value.map((segment) => segment.label),
    axisLabel: { color: "#596157", fontFamily: chartFontFamily, fontSize: 10 },
    axisLine: { show: false },
    axisTick: { show: false },
  },
  series: [{
    type: "bar",
    data: rankedSegments.value.map((segment) => segment.value),
    barMaxWidth: 16,
    itemStyle: { color: "#82A978", borderRadius: [0, 3, 3, 0] },
    label: {
      show: true,
      position: "right",
      color: "#596157",
      fontFamily: chartFontFamily,
      fontSize: 10,
      formatter: ({ value }: { value: unknown }) =>
        typeof value === "number" ? value.toFixed(3) : "",
    },
  }],
}) as ChartOption);

const rankingChartHeight = computed(() =>
  `${Math.min(260, Math.max(142, rankedSegments.value.length * 32 + 52))}px`
);

const technicalMetadata = computed(() => ([
  ["Source Version", nonEmptyString(resultPayload.value.source_version_id ?? rootPayload.value.source_version_id)],
  ["Processing Run", nonEmptyString(resultPayload.value.processing_run_id ?? rootPayload.value.processing_run_id)],
  ["Dataset", nonEmptyString(resultPayload.value.dataset_id ?? rootPayload.value.dataset_id)],
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
.segmentation-artifact {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
  font-family: var(--font-sans);
}

.segmentation-header h3,
.segmentation-section h4 {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-sans);
}

.segmentation-header h3 {
  font-size: 15px;
  font-weight: 600;
}

.segmentation-header p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.segmentation-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: 8px;
}

.segmentation-overview__card {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.segmentation-overview__card span,
.segmentation-overview__card strong {
  display: block;
}

.segmentation-overview__card span {
  color: var(--text-tertiary);
  font-size: 10px;
}

.segmentation-overview__card strong {
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 700;
}

.segmentation-section,
.segmentation-technical {
  min-width: 0;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}

.segmentation-section__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.segmentation-section__heading h4 {
  font-size: 13px;
  font-weight: 600;
}

.segmentation-section__heading p {
  margin: 3px 0 0;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.5;
}

.segmentation-section__heading > span {
  color: var(--text-tertiary);
  font-size: 10px;
  white-space: nowrap;
}

.segmentation-coverage__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 14px;
  margin: -1px 0 6px;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 10px;
  line-height: 1.5;
}

.segmentation-coverage__legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.segmentation-coverage__swatch {
  width: 16px;
  height: 6px;
  border-radius: 999px;
}

.segmentation-coverage__swatch.is-axis {
  background: #E8ECE6;
}

.segmentation-coverage__swatch.is-selected {
  background: rgba(74, 124, 89, 0.62);
}

.segmentation-empty {
  margin: 0;
  padding: 20px 14px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.segmentation-technical__toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  border: 0;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--accent-dark);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.segmentation-technical__toggle svg {
  width: 13px;
  height: 13px;
  transition: transform var(--transition-fast);
}

.segmentation-technical__toggle svg.is-expanded {
  transform: rotate(180deg);
}

.segmentation-technical__toggle:hover {
  color: var(--accent-hover);
}

.segmentation-technical__toggle:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 3px;
}

.segmentation-technical__body {
  margin-top: 10px;
}

.segmentation-metadata {
  display: grid;
  gap: 6px;
  margin: 0 0 10px;
}

.segmentation-metadata > div {
  display: grid;
  grid-template-columns: minmax(92px, auto) minmax(0, 1fr);
  gap: 10px;
  padding: 7px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
}

.segmentation-metadata dt {
  color: var(--text-tertiary);
  font-size: 10px;
}

.segmentation-metadata dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.segmentation-raw {
  max-width: 100%;
  max-height: 280px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: #F7F8F5;
  color: var(--text-secondary);
  font-size: 10px;
  line-height: 1.55;
  white-space: pre;
}

@media (max-width: 520px) {
  .segmentation-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .segmentation-section__heading {
    flex-direction: column;
    gap: 3px;
  }
}
</style>
