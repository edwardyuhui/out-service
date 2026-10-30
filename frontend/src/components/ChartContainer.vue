<template>
  <div class="chart-wrapper">
    <div ref="chartRef" class="chart-canvas" :style="{ height: height || '350px' }"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import * as echarts from "echarts/core";
import { BarChart, CustomChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import type {
  BarSeriesOption,
  CustomSeriesOption,
  HeatmapSeriesOption,
  LineSeriesOption,
  ScatterSeriesOption,
} from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import type {
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
  VisualMapComponentOption,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ComposeOption } from "echarts/core";

// Register only the chart types / components actually used across the app's
// ChartContainer consumers (Cleaning/Segmentation/Delay/Collinearity/
// ARXModeling/Optuna): line, bar, scatter, heatmap and custom series, plus tooltip,
// legend, grid, dataZoom, visualMap and mark line/area/point. This keeps the
// bundle free of unused echarts modules (3D, maps, gl, etc.) that a full
// `import * as echarts from "echarts"` would otherwise pull in.
echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  HeatmapChart,
  CustomChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

export type ChartOption = ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | ScatterSeriesOption
  | HeatmapSeriesOption
  | CustomSeriesOption
  | TooltipComponentOption
  | LegendComponentOption
  | GridComponentOption
  | DataZoomComponentOption
  | VisualMapComponentOption
>;

export type ChartViewportRange = {
  dataZoomIndex: number;
  dataZoomId?: string;
  xAxisIndices: number[];
  start?: number;
  end?: number;
  startValue?: number | string | Date;
  endValue?: number | string | Date;
};

export type ChartViewportChange =
  | { reason: "datazoom"; ranges: ChartViewportRange[] }
  | { reason: "resize" };

const props = defineProps<{
  options: ChartOption;
  height?: string;
}>();
const emit = defineEmits<{
  chartClick: [params: unknown];
  chartViewportChange: [change: ChartViewportChange];
}>();

const chartRef = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

const handleChartClick = (params: unknown) => {
  emit("chartClick", params);
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

const isAxisIndex = (value: unknown): value is number =>
  isFiniteNumber(value) && Number.isInteger(value) && value >= 0;

const isViewportValue = (value: unknown): value is number | string | Date =>
  isFiniteNumber(value)
  || typeof value === "string"
  || (value instanceof Date && Number.isFinite(value.getTime()));

const normalizeXAxisIndices = (value: unknown): number[] => {
  const candidates = Array.isArray(value) ? value : [value];
  return [...new Set(candidates.filter(isAxisIndex))];
};

const normalizeDataZoomRange = (
  option: Record<string, unknown>,
  dataZoomIndex: number
): ChartViewportRange => ({
  dataZoomIndex,
  ...(typeof option.id === "string" ? { dataZoomId: option.id } : {}),
  xAxisIndices: normalizeXAxisIndices(option.xAxisIndex),
  ...(isFiniteNumber(option.start) ? { start: option.start } : {}),
  ...(isFiniteNumber(option.end) ? { end: option.end } : {}),
  ...(isViewportValue(option.startValue)
    ? { startValue: option.startValue }
    : {}),
  ...(isViewportValue(option.endValue) ? { endValue: option.endValue } : {}),
});

const getDataZoomSnapshot = (): ChartViewportRange[] => {
  const option = chartInstance?.getOption();
  const dataZoom: unknown = option?.dataZoom;
  const options: unknown[] = Array.isArray(dataZoom) ? dataZoom : [dataZoom];
  const ranges: ChartViewportRange[] = [];

  options.forEach((option, dataZoomIndex) => {
    if (isRecord(option)) {
      ranges.push(normalizeDataZoomRange(option, dataZoomIndex));
    }
  });

  return ranges;
};

type ChartAction = Parameters<echarts.ECharts["dispatchAction"]>[0];
type CoordinateFinder = Parameters<echarts.ECharts["containPixel"]>[0];

const dispatchAction = (action: ChartAction) => {
  chartInstance?.dispatchAction(action);
};

const convertToPixel = (finder: CoordinateFinder, value: unknown) =>
  chartInstance?.convertToPixel(finder, value as never) ?? null;

const containPixel = (finder: CoordinateFinder, value: number[]) =>
  chartInstance?.containPixel(finder, value) ?? false;

const getSize = () => ({
  width: chartInstance?.getWidth() ?? 0,
  height: chartInstance?.getHeight() ?? 0,
});

const handleDataZoom = () => {
  emit("chartViewportChange", {
    reason: "datazoom",
    ranges: getDataZoomSnapshot(),
  });
};

defineExpose({ dispatchAction, convertToPixel, containPixel, getSize });

const initChart = () => {
  if (!chartRef.value) return;
  chartInstance = echarts.init(chartRef.value);
  chartInstance.setOption(props.options);
  chartInstance.on("click", handleChartClick);
  chartInstance.on("datazoom", handleDataZoom);
};

const handleResize = () => {
  chartInstance?.resize();
  emit("chartViewportChange", { reason: "resize" });
};

watch(
  () => props.options,
  (newOpt) => {
    // Incremental merge instead of a full notMerge rebuild: grid/tooltip/
    // legend/dataZoom state (e.g. current zoom window, legend toggles) is
    // preserved across data updates. `replaceMerge: ["series"]` still fully
    // replaces the series list (rather than merging it item-by-item), which
    // matters because some pages (e.g. DelayView) can change the *number* of
    // series between updates — a plain merge would leave stale series behind.
    chartInstance?.setOption(newOpt, { replaceMerge: ["series"] });
  },
  { deep: true }
);

onMounted(() => {
  initChart();
  window.addEventListener("resize", handleResize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chartInstance?.off("click", handleChartClick);
  chartInstance?.off("datazoom", handleDataZoom);
  chartInstance?.dispose();
});
</script>

<style scoped>
.chart-wrapper {
  width: 100%;
}
.chart-canvas {
  width: 100%;
}
</style>
