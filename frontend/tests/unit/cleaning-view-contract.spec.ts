import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { defineComponent, h } from "vue";
import CleaningView from "../../src/views/CleaningView.vue";
import { cleanDataset } from "../../src/api/preprocessing";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../../src/api/datasets";
import { ApiError } from "../../src/api/client";

const datasetId = "f4c27bd2-f27f-40eb-aa61-04988f71f616";
const versionId = "c13979a1-206e-4a8f-8e37-a22e12f6027d";
const cleanVersionId = "caee11ea-9a81-4c85-9d95-4c66b10c3473";
const lagVersionId = "3eeef5a3-ed99-401d-9495-d303ee095f28";
const featureVersionId = "b13979a1-206e-4a8f-8e37-a22e12f6027d";
const routeState = vi.hoisted(() => ({
  query: {
    dataset_id: "f4c27bd2-f27f-40eb-aa61-04988f71f616",
    version_id: "c13979a1-206e-4a8f-8e37-a22e12f6027d",
  } as Record<string, string>,
}));

vi.mock("../../src/api/preprocessing", () => ({ cleanDataset: vi.fn() }));
vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetVersions: vi.fn(),
  listDatasets: vi.fn(),
  getCleaningVersionCompareChannels: vi.fn(),
  getCleaningVersionCompare: vi.fn(),
}));
vi.mock("vue-router", () => ({
  useRoute: () => routeState,
}));
const messages = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("element-plus", () => ({ ElMessage: messages }));

const mockedCleanDataset = vi.mocked(cleanDataset);
const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);
const mockedListDatasets = vi.mocked(listDatasets);
const chartDispatchAction = vi.fn();
const chartConvertToPixel = vi.fn();
const chartContainPixel = vi.fn();
const chartGetSize = vi.fn();

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

const ChartContainerStub = defineComponent({
  name: "ChartContainer",
  props: { options: { type: Object, required: true } },
  emits: ["chart-click", "chart-viewport-change"],
  setup(_props, { expose }) {
    expose({
      dispatchAction: chartDispatchAction,
      convertToPixel: chartConvertToPixel,
      containPixel: chartContainPixel,
      getSize: chartGetSize,
    });
    return () => h("div", { "data-test": "cleaning-chart" });
  },
});

const CleaningVersionCompareWorkbenchStub = defineComponent({
  name: "CleaningVersionCompareWorkbench",
  props: ["dataset", "versions", "currentVersionId"],
  template: '<div data-test="cleaning-version-compare-stub" />',
});

const stubs = {
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<div>{{ label }}<slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-input-number": true,
  "el-radio-group": { template: "<div><slot /></div>" },
  "el-radio": { template: "<label><slot /></label>" },
  "el-select": {
    props: ["modelValue"],
    emits: ["update:modelValue"],
    template: "<select :value=\"modelValue\" @change=\"$emit('update:modelValue', $event.target.value)\"><slot /></select>",
  },
  "el-option": { props: ["label", "value"], template: "<option :value=\"value\">{{ label }}</option>" },
  "el-button": {
    props: ["disabled", "loading"],
    template: "<button :disabled=\"disabled || loading\" @click=\"$emit('click')\"><slot /></button>",
  },
  "el-tag": { template: "<span><slot /></span>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  "el-popover": ElPopoverStub,
  ChartContainer: ChartContainerStub,
  CleaningVersionCompareWorkbench: CleaningVersionCompareWorkbenchStub,
  Operation: true,
  MagicStick: true,
  DataAnalysis: true,
  ArrowRight: true,
  ArrowDown: true,
};

const datasetDetail = (activeVersionId = versionId) => ({
    id: datasetId,
    name: "S4 清洗验收数据",
    source: "simulation",
    status: "ready",
    version_id: activeVersionId,
    latest_version_id: activeVersionId,
    file_size_bytes: 0,
    row_count: 1200,
    column_count: 4,
    col_count: 4,
    created_at: "2026-08-20T00:00:00Z",
    preview: { columns: [], rows: [] },
  } as never);

function setupApi() {
  const detail = datasetDetail();
  const versions = {
    dataset_id: datasetId,
    active_version_id: versionId,
    nodes: [
      {
        id: versionId,
        name: "V0 · 仿真原始数据",
        tool: "simulation_generate",
        parent_version_id: null,
        created_at: "2026-08-20T00:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "simulation/test.csv",
      },
      {
        id: cleanVersionId,
        name: "V1 · 清洗规整",
        tool: "preprocessing.clean",
        parent_version_id: versionId,
        created_at: "2026-08-20T01:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "derived/clean.csv",
      },
      {
        id: lagVersionId,
        name: "V2 · 时滞补偿",
        tool: "preprocessing.lag_compensation",
        parent_version_id: cleanVersionId,
        created_at: "2026-08-20T02:00:00Z",
        row_count: 1191,
        column_count: 4,
        artifact_path: "derived/lag.csv",
      },
      {
        id: featureVersionId,
        name: "V3 · 特征优选",
        tool: "preprocessing.feature_selection",
        parent_version_id: lagVersionId,
        created_at: "2026-08-20T03:00:00Z",
        row_count: 1191,
        column_count: 3,
        artifact_path: "derived/feature.csv",
      },
    ],
    edges: [],
  };
  mockedListDatasets.mockResolvedValue({ items: [detail] });
  mockedGetDatasetDetail.mockResolvedValue(detail);
  mockedGetDatasetVersions.mockResolvedValue(versions as never);
  return { detail, versions };
}

const interactiveCleaningResponse = () => {
  const timestamps = [
    "2026-01-01T00:09:18Z",
    "2026-01-01T00:09:19Z",
    "2026-01-01T00:09:20Z",
    "2026-01-01T00:09:21Z",
    "2026-01-01T00:09:22Z",
  ];
  return {
    timestamps,
    response: {
      dataset_id: datasetId,
      source_version_id: versionId,
      effective_version_id: cleanVersionId,
      derived_version_id: cleanVersionId,
      new_version_id: cleanVersionId,
      created_new_version: true,
      no_op: false,
      converged: false,
      reused_existing_version: false,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      primary_column: "y",
      raw_series: [1, null, 40.213881, 4, 5],
      cleaned_series: [1, 2, 7.8326741, 4.25, 5.5],
      replaced_indices: [1, 2, 3, 4],
      series: [
        {
          column: "u1",
          timestamps,
          raw_series: [4, 5, 6, 7, 8],
          cleaned_series: [4, 5, 6.5, 7, 8],
          replaced_indices: [2],
          interpolation_changed_indices: [],
          outlier_replacement_indices: [2],
          smoothing_changed_indices: [],
        },
        {
          column: "y",
          timestamps,
          raw_series: [1, null, 40.213881, 4, 5],
          cleaned_series: [1, 2, 7.8326741, 4.25, 5.5],
          replaced_indices: [1, 2, 3, 4],
          interpolation_changed_indices: [1, 4],
          outlier_replacement_indices: [2, 4],
          smoothing_changed_indices: [3, 4],
        },
      ],
      total_cleaned_points: 4,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 4 } },
    },
  };
};

describe("CleaningView request contract", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    chartConvertToPixel.mockReturnValue([120, 300]);
    chartContainPixel.mockReturnValue(true);
    chartGetSize.mockReturnValue({ width: 640, height: 420 });
    routeState.query = { dataset_id: datasetId, version_id: versionId };
    setupApi();
  });

  it("mounts the additive version compare workbench with existing dataset context", async () => {
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    const workbench = wrapper.getComponent(CleaningVersionCompareWorkbenchStub);
    expect(workbench.props("dataset")).toEqual(expect.objectContaining({ id: datasetId }));
    expect(workbench.props("versions")).toHaveLength(4);
    expect(workbench.props("currentVersionId")).toBe(versionId);
  });

  it("shows full lineage eligibility and serializes the selected source with canonical API fields", async () => {
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      new_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      source_version_id: versionId,
      effective_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      derived_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      created_new_version: true,
      no_op: true,
      converged: true,
      reused_existing_version: false,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      raw_series: [],
      cleaned_series: [],
      replaced_indices: [],
      total_cleaned_points: 0,
      warnings: [],
      recommended_downsample_factor: 1,
      series: [],
      summary: {},
      task: {} as never,
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(4);
    expect(wrapper.get(`[data-version-id='${versionId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${cleanVersionId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${lagVersionId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${featureVersionId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${lagVersionId}']`).text()).toContain("已进入后续处理阶段");
    expect(wrapper.text()).not.toContain(versionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain("初始版本");
    await wrapper.get("[data-test='clean-submit']").trigger("click");

    expect(mockedCleanDataset).toHaveBeenCalledWith({
      dataset_id: datasetId,
      version_id: versionId,
      target_sample_period_seconds: 1,
      interpolation: "linear",
      anomaly_detector: "hampel",
      hampel_window: 5,
    });
  });

  it("uses the backend primary series, real timestamps, and classified repair evidence", async () => {
    const timestamps = [
      "2026-01-01T00:09:18Z",
      "2026-01-01T00:09:19Z",
      "2026-01-01T00:09:20Z",
      "2026-01-01T00:09:21Z",
      "2026-01-01T00:09:22Z",
    ];
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: versionId,
      effective_version_id: cleanVersionId,
      derived_version_id: cleanVersionId,
      new_version_id: cleanVersionId,
      created_new_version: true,
      no_op: false,
      converged: false,
      reused_existing_version: false,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      primary_column: "y",
      raw_series: [1, null, 40.213881, 4, 5],
      cleaned_series: [1, 2, 7.8326741, 4.25, 5.5],
      replaced_indices: [1, 2, 3, 4],
      series: [
        {
          column: "u1",
          timestamps,
          raw_series: [4, 5, 6, 7, 8],
          cleaned_series: [4, 5, 6.5, 7, 8],
          replaced_indices: [2],
          interpolation_changed_indices: [],
          outlier_replacement_indices: [2],
          smoothing_changed_indices: [],
        },
        {
          column: "y",
          timestamps,
          raw_series: [1, null, 40.213881, 4, 5],
          cleaned_series: [1, 2, 7.8326741, 4.25, 5.5],
          replaced_indices: [1, 2, 3, 4],
          interpolation_changed_indices: [1, 4],
          outlier_replacement_indices: [2],
          smoothing_changed_indices: [3, 4],
        },
      ],
      total_cleaned_points: 4,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 4 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    const options = chart.props("options") as {
      xAxis: { data: string[]; axisLabel: { formatter: (value: string) => string } };
      dataZoom: Array<Record<string, unknown>>;
      legend: { data: string[] };
      series: Array<{
        id: string;
        name: string;
        type: string;
        xAxisIndex: number;
        symbol?: string;
        symbolSize?: number;
        color?: string;
        z?: number;
        tooltip?: { show: boolean };
        itemStyle?: Record<string, unknown>;
        data: Array<Record<string, unknown>> | number[];
      }>;
      tooltip: { formatter: (params: unknown) => string };
    };
    expect(wrapper.get("[data-test='cleaning-chart-channel-select']").element.value).toBe("y");
    expect(options.xAxis.data).toEqual(timestamps);
    expect(options.xAxis.axisLabel.formatter(timestamps[2])).toBe("00:09:20");
    expect(options.dataZoom).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: "cleaning-inside-zoom",
        type: "inside",
        xAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: "ctrl",
        moveOnMouseWheel: false,
      }),
      expect.objectContaining({
        id: "cleaning-slider-zoom",
        type: "slider",
        xAxisIndex: 0,
        filterMode: "none",
      }),
    ]));
    expect(options.series.every((item) => item.xAxisIndex === 0)).toBe(true);
    expect(options.legend.data).toEqual([
      "原始序列 Raw",
      "清洗后序列 Cleaned",
      "插值填补",
      "异常替换",
      "平滑调整",
    ]);
    expect(options.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "原始序列 Raw", type: "line" }),
      expect.objectContaining({ name: "清洗后序列 Cleaned", type: "line" }),
      expect.objectContaining({
        id: "cleaning-repair-interpolation",
        name: "插值填补",
        symbol: "circle",
        color: "#B5965D",
        data: [expect.objectContaining({
          value: [timestamps[1], 2],
          repairPoint: true,
          projectedIndex: 1,
          repairTypes: ["interpolation"],
          markerCategory: "interpolation",
        })],
      }),
      expect.objectContaining({
        id: "cleaning-repair-outlier",
        name: "异常替换",
        symbol: "diamond",
        color: "#A76155",
        data: [expect.objectContaining({
          value: [timestamps[2], 7.8326741],
          projectedIndex: 2,
          repairTypes: ["outlier"],
        })],
      }),
      expect.objectContaining({
        id: "cleaning-repair-smoothing",
        name: "平滑调整",
        symbol: "triangle",
        color: "#768A8D",
        data: [expect.objectContaining({
          value: [timestamps[3], 4.25],
          projectedIndex: 3,
          repairTypes: ["smoothing"],
        })],
      }),
      expect.objectContaining({
        id: "cleaning-repair-combined",
        name: "组合修复",
        symbol: "circle",
        color: "#4E6759",
        data: [expect.objectContaining({
          value: [timestamps[4], 5.5],
          projectedIndex: 4,
          repairTypes: ["interpolation", "smoothing"],
          markerCategory: "combined",
        })],
      }),
    ]));
    const visualMarkerIds = [
      "cleaning-repair-interpolation",
      "cleaning-repair-outlier",
      "cleaning-repair-smoothing",
      "cleaning-repair-combined",
    ];
    for (const seriesId of visualMarkerIds) {
      const markerSeries = options.series.find((item) => item.id === seriesId);
      expect(markerSeries?.z).toBeGreaterThan(3);
      for (const [dataIndex, datum] of (markerSeries?.data ?? []).entries()) {
        expect(datum).toEqual(expect.objectContaining({
          repairPoint: true,
          projectedIndex: expect.any(Number),
          repairTypes: expect.any(Array),
          markerCategory: expect.any(String),
          visualSeriesId: seriesId,
          visualDataIndex: dataIndex,
        }));
      }
    }
    const hitAreaSeries = options.series.find(
      (item) => item.id === "cleaning-repair-hit-area"
    );
    expect(hitAreaSeries).toEqual(expect.objectContaining({
      type: "scatter",
      symbolSize: 20,
      z: 20,
      tooltip: { show: false },
      itemStyle: { color: "rgba(0, 0, 0, 0.001)" },
    }));
    expect(hitAreaSeries?.data).toHaveLength(4);
    expect(options.legend.data).not.toContain("cleaning-repair-hit-area");
    expect(options.tooltip.formatter([{ axisValue: timestamps[1] }])).toContain(
      "时间：2026-01-01 00:09:19<br/>处理前：缺失<br/>处理后：2<br/>修复：<br/>· 插值填补"
    );
    expect(options.tooltip.formatter([{ axisValue: timestamps[2] }])).toContain(
      "处理前：40.2139<br/>处理后：7.8327<br/>修复：<br/>· 异常替换"
    );
    expect(options.tooltip.formatter([{ axisValue: timestamps[4] }])).toContain(
      "修复：<br/>· 插值填补<br/>· 平滑调整"
    );

    await wrapper.get("[data-test='cleaning-chart-channel-select']").setValue("u1");
    await flushPromises();
    const switchedOptions = chart.props("options") as { series: Array<{ name: string; data: unknown }> };
    expect(switchedOptions.series.find((item) => item.name === "异常替换")?.data).toEqual([
      expect.objectContaining({ value: [timestamps[2], 6.5], projectedIndex: 2 }),
    ]);
  });

  it("resets the shared x-axis zoom without requesting another clean", async () => {
    const { response } = interactiveCleaningResponse();
    mockedCleanDataset.mockResolvedValue(response as never);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    chartDispatchAction.mockClear();
    await wrapper.get("[data-test='cleaning-reset-zoom']").trigger("click");

    expect(chartDispatchAction).toHaveBeenCalledWith({
      type: "dataZoom",
      start: 0,
      end: 100,
    });
    expect(mockedCleanDataset).toHaveBeenCalledTimes(1);
  });

  it("accepts every visual repair category and maps the transparent hit area to its visual marker", async () => {
    const { response } = interactiveCleaningResponse();
    mockedCleanDataset.mockResolvedValue(response as never);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-raw-line",
      dataIndex: 1,
      data: null,
    });
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-cleaned-line",
      dataIndex: 1,
      data: 2,
    });
    await flushPromises();
    expect(wrapper.find("[data-test='repair-detail-card']").exists()).toBe(false);

    const options = chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    };
    const categoryIds = [
      "cleaning-repair-interpolation",
      "cleaning-repair-outlier",
      "cleaning-repair-smoothing",
      "cleaning-repair-combined",
    ];
    for (const seriesId of categoryIds) {
      const datum = options.series.find((series) => series.id === seriesId)?.data[0];
      expect(datum).toBeDefined();
      chart.vm.$emit("chart-click", { seriesId, dataIndex: 0, data: datum });
      await flushPromises();
      expect(wrapper.get("[data-test='repair-detail-card']").attributes("aria-hidden")).toBe("false");
      expect(chartDispatchAction).toHaveBeenLastCalledWith({
        type: "highlight",
        seriesId,
        dataIndex: 0,
      });
    }

    const hitArea = options.series.find(
      (series) => series.id === "cleaning-repair-hit-area"
    );
    const smoothingHit = hitArea?.data.find(
      (datum) => datum.markerCategory === "smoothing"
    );
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-repair-hit-area",
      dataIndex: hitArea?.data.indexOf(smoothingHit ?? {}) ?? -1,
      data: smoothingHit,
    });
    await flushPromises();

    expect(wrapper.get("[data-test='repair-detail-card']").text()).toContain("平滑调整");
    expect(chartDispatchAction).toHaveBeenLastCalledWith({
      type: "highlight",
      seriesId: "cleaning-repair-smoothing",
      dataIndex: 0,
    });
  });

  it("anchors the detail card to data pixels, avoids edges, and follows viewport changes", async () => {
    const { timestamps, response } = interactiveCleaningResponse();
    mockedCleanDataset.mockResolvedValue(response as never);
    chartConvertToPixel.mockReturnValue([100, 300]);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-repair-hit-area",
      dataIndex: 0,
      data: {
        value: [timestamps[1], 2],
        repairPoint: true,
        projectedIndex: 1,
        repairTypes: ["interpolation"],
        markerCategory: "interpolation",
        visualSeriesId: "cleaning-repair-interpolation",
        visualDataIndex: 0,
      },
    });
    await flushPromises();

    let detail = wrapper.get("[data-test='repair-detail-card']");
    expect(chartConvertToPixel).toHaveBeenCalledWith(
      { xAxisIndex: 0, yAxisIndex: 0 },
      [timestamps[1], 2]
    );
    expect(chartContainPixel).toHaveBeenCalledWith({ gridIndex: 0 }, [100, 300]);
    expect(detail.attributes("data-horizontal-placement")).toBe("right");
    expect(detail.attributes("data-vertical-placement")).toBe("above");
    expect(detail.attributes("style")).toContain("left: 116px");

    chartConvertToPixel.mockReturnValue([540, 50]);
    chart.vm.$emit("chart-viewport-change");
    await flushPromises();
    detail = wrapper.get("[data-test='repair-detail-card']");
    expect(detail.attributes("data-horizontal-placement")).toBe("left");
    expect(detail.attributes("data-vertical-placement")).toBe("below");
    expect(detail.attributes("style")).toContain("left: 272px");
    expect(detail.attributes("style")).toContain("top: 66px");

    const cardRectSpy = vi.spyOn(detail.element, "getBoundingClientRect").mockReturnValue({
      width: 700,
      height: 500,
      top: 0,
      right: 700,
      bottom: 500,
      left: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    chartConvertToPixel.mockReturnValue([630, 410]);
    chart.vm.$emit("chart-viewport-change");
    await flushPromises();
    expect(wrapper.get("[data-test='repair-detail-card']").attributes("style")).toContain("left: 8px");
    expect(wrapper.get("[data-test='repair-detail-card']").attributes("style")).toContain("top: 8px");
    cardRectSpy.mockRestore();

    chartContainPixel.mockReturnValue(false);
    chart.vm.$emit("chart-viewport-change");
    await flushPromises();
    detail = wrapper.get("[data-test='repair-detail-card']");
    expect(detail.attributes("aria-hidden")).toBe("true");
    expect(detail.text()).toContain("插值填补");

    chartContainPixel.mockReturnValue(true);
    chartConvertToPixel.mockReturnValue([160, 300]);
    chart.vm.$emit("chart-viewport-change");
    await flushPromises();
    detail = wrapper.get("[data-test='repair-detail-card']");
    expect(detail.attributes("aria-hidden")).toBe("false");
    expect(detail.attributes("style")).toContain("left: 176px");

    chartConvertToPixel.mockReturnValue([520, 300]);
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-repair-smoothing",
      dataIndex: 0,
      data: {
        value: [timestamps[3], 4.25],
        repairPoint: true,
        projectedIndex: 3,
        repairTypes: ["smoothing"],
        markerCategory: "smoothing",
        visualSeriesId: "cleaning-repair-smoothing",
        visualDataIndex: 0,
      },
    });
    await flushPromises();
    detail = wrapper.get("[data-test='repair-detail-card']");
    expect(detail.text()).toContain("平滑调整");
    expect(detail.attributes("data-horizontal-placement")).toBe("left");
    expect(detail.attributes("style")).toContain("left: 252px");

    chartConvertToPixel.mockClear();
    await wrapper.get("[data-test='cleaning-reset-zoom']").trigger("click");
    await flushPromises();
    expect(chartConvertToPixel).toHaveBeenCalled();
    expect(detail.text()).toContain("平滑调整");
  });

  it("opens repair evidence only for stable repair series metadata and keeps it through zoom reset", async () => {
    const { timestamps, response } = interactiveCleaningResponse();
    mockedCleanDataset.mockResolvedValue(response as never);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-cleaned-line",
      dataIndex: 1,
      data: 2,
    });
    await flushPromises();
    expect(wrapper.find("[data-test='repair-detail-card']").exists()).toBe(false);

    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-repair-interpolation",
      dataIndex: 0,
      data: {
        value: [timestamps[1], 2],
        repairPoint: true,
        projectedIndex: 1,
        repairTypes: ["interpolation"],
        markerCategory: "interpolation",
        visualSeriesId: "cleaning-repair-interpolation",
        visualDataIndex: 0,
      },
    });
    await flushPromises();

    const detail = wrapper.get("[data-test='repair-detail-card']");
    expect(detail.text()).toContain("插值填补");
    expect(detail.text()).toContain("y");
    expect(detail.text()).toContain("2026-01-01 00:09:19");
    expect(detail.text()).toContain("缺失");
    expect(detail.text()).toContain("2");
    expect(chartDispatchAction).toHaveBeenLastCalledWith({
      type: "highlight",
      seriesId: "cleaning-repair-interpolation",
      dataIndex: 0,
    });

    chart.vm.$emit("chart-viewport-change");
    await flushPromises();
    expect(wrapper.find("[data-test='repair-detail-card']").exists()).toBe(true);

    await wrapper.get("[data-test='cleaning-reset-zoom']").trigger("click");
    expect(wrapper.find("[data-test='repair-detail-card']").exists()).toBe(true);
    expect(mockedCleanDataset).toHaveBeenCalledTimes(1);

    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-repair-combined",
      dataIndex: 0,
      data: {
        value: [timestamps[4], 5.5],
        repairPoint: true,
        projectedIndex: 4,
        repairTypes: ["interpolation", "outlier", "smoothing"],
        markerCategory: "combined",
        visualSeriesId: "cleaning-repair-combined",
        visualDataIndex: 0,
      },
    });
    await flushPromises();
    expect(wrapper.get("[data-test='repair-detail-card']").text()).toContain(
      "插值填补 · 异常替换 · 平滑调整"
    );
    expect(chartDispatchAction).toHaveBeenCalledWith({
      type: "downplay",
      seriesId: "cleaning-repair-interpolation",
      dataIndex: 0,
    });
    expect(chartDispatchAction).toHaveBeenLastCalledWith({
      type: "highlight",
      seriesId: "cleaning-repair-combined",
      dataIndex: 0,
    });

    await wrapper.get("[data-test='repair-detail-close']").trigger("click");
    expect(wrapper.find("[data-test='repair-detail-card']").exists()).toBe(false);
    expect(chartDispatchAction).toHaveBeenLastCalledWith({
      type: "downplay",
      seriesId: "cleaning-repair-combined",
      dataIndex: 0,
    });
  });

  it("shows every repair type for a combined point and clears selection on channel switch", async () => {
    const { timestamps, response } = interactiveCleaningResponse();
    mockedCleanDataset.mockResolvedValue(response as never);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    chart.vm.$emit("chart-click", {
      seriesId: "cleaning-repair-combined",
      dataIndex: 0,
      data: {
        value: [timestamps[4], 5.5],
        repairPoint: true,
        projectedIndex: 4,
        repairTypes: ["interpolation", "outlier", "smoothing"],
        markerCategory: "combined",
        visualSeriesId: "cleaning-repair-combined",
        visualDataIndex: 0,
      },
    });
    await flushPromises();

    const detail = wrapper.get("[data-test='repair-detail-card']");
    expect(detail.text()).toContain("插值填补 · 异常替换 · 平滑调整");
    expect(detail.text()).toContain("5");
    expect(detail.text()).toContain("5.5");

    await wrapper.get("[data-test='cleaning-chart-channel-select']").setValue("u1");
    await flushPromises();

    expect(wrapper.find("[data-test='repair-detail-card']").exists()).toBe(false);
    expect(chartDispatchAction).toHaveBeenLastCalledWith({
      type: "downplay",
      seriesId: "cleaning-repair-combined",
      dataIndex: 0,
    });
  });

  it("does not default to an active downstream version and selects the newest eligible source", async () => {
    routeState.query = { dataset_id: datasetId };
    const detail = datasetDetail(featureVersionId);
    mockedListDatasets.mockResolvedValue({ items: [detail] });
    mockedGetDatasetDetail.mockResolvedValue(detail);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(cleanVersionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain(
      "可再次执行清洗规整"
    );
  });

  it("reloads lineage and advances the source to a newly created effective version", async () => {
    const { versions } = setupApi();
    const newVersionId = "e13979a1-206e-4a8f-8e37-a22e12f6027d";
    mockedGetDatasetDetail
      .mockResolvedValueOnce(datasetDetail())
      .mockResolvedValueOnce(datasetDetail(newVersionId));
    mockedGetDatasetVersions
      .mockResolvedValueOnce(versions as never)
      .mockResolvedValueOnce({
        ...versions,
        active_version_id: newVersionId,
        nodes: [
          ...versions.nodes,
          {
            id: newVersionId,
            name: "V4 · 清洗规整",
            tool: "preprocessing.clean",
            parent_version_id: versionId,
            created_at: "2026-08-20T04:00:00Z",
            row_count: 1200,
            column_count: 4,
            artifact_path: "derived/new-clean.csv",
          },
        ],
      } as never);
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      new_version_id: newVersionId,
      effective_version_id: newVersionId,
      created_new_version: true,
      no_op: false,
      converged: false,
      reused_existing_version: false,
      raw_series: [1],
      cleaned_series: [1],
      replaced_indices: [],
      total_cleaned_points: 0,
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.find(".cleaning-summary").exists()).toBe(true);
    expect(messages.success).toHaveBeenCalledWith(
      `成功生成清洗后数据版本: ${newVersionId}`
    );
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(5);
    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(newVersionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain(
      "V4 · 清洗规整"
    );
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    expect(mockedCleanDataset).toHaveBeenLastCalledWith(expect.objectContaining({
      dataset_id: datasetId,
      version_id: newVersionId,
    }));
  });

  it("shows convergence without adding lineage or changing the selected Cleaning source", async () => {
    routeState.query = { dataset_id: datasetId, version_id: cleanVersionId };
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: cleanVersionId,
      effective_version_id: cleanVersionId,
      derived_version_id: null,
      new_version_id: null,
      created_new_version: false,
      no_op: true,
      converged: true,
      reused_existing_version: false,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      raw_series: [1],
      cleaned_series: [1],
      replaced_indices: [],
      total_cleaned_points: 0,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 0 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    const nodeCount = wrapper.findAll("[data-test='lineage-node']").length;

    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='cleaning-converged-badge']").text()).toBe("已收敛");
    expect(wrapper.get(".cleaning-summary").text()).toContain(
      "清洗结果已收敛，本次未产生新的数据版本"
    );
    expect(wrapper.get(".cleaning-summary").text()).toContain("当前有效版本：V1 · 清洗规整");
    expect(wrapper.get(".cleaning-summary").text()).toContain("修改单元：0");
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(nodeCount);
    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(cleanVersionId);
    expect(messages.success).toHaveBeenCalledWith(
      "清洗结果已收敛，本次未产生新的数据版本。"
    );
  });

  it("reloads lineage and advances to an idempotently reused Cleaning version", async () => {
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: versionId,
      effective_version_id: cleanVersionId,
      derived_version_id: null,
      new_version_id: null,
      created_new_version: false,
      no_op: false,
      converged: false,
      reused_existing_version: true,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      raw_series: [1],
      cleaned_series: [2],
      replaced_indices: [0],
      total_cleaned_points: 1,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 1 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    const nodeCount = wrapper.findAll("[data-test='lineage-node']").length;

    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='cleaning-reused-badge']").text()).toBe("已复用");
    expect(wrapper.get(".cleaning-summary").text()).toContain(
      "相同清洗结果已存在，已复用现有数据版本"
    );
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(nodeCount);
    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(cleanVersionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain(
      "V1 · 清洗规整"
    );
    expect(messages.success).toHaveBeenCalledWith(
      "相同清洗结果已存在，已复用现有数据版本。"
    );
  });

  it("distinguishes first-clean zero-change certification from repeated convergence", async () => {
    const newVersionId = "e13979a1-206e-4a8f-8e37-a22e12f6027d";
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: versionId,
      effective_version_id: newVersionId,
      derived_version_id: newVersionId,
      new_version_id: newVersionId,
      created_new_version: true,
      no_op: true,
      converged: true,
      reused_existing_version: false,
      raw_series: [1],
      cleaned_series: [1],
      replaced_indices: [],
      total_cleaned_points: 0,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 0 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("清洗认证完成");
    expect(wrapper.get(".cleaning-summary").text()).toContain(
      "数据无需修复，已完成清洗认证并生成 Cleaning Version"
    );
    expect(messages.success).toHaveBeenCalledWith(
      "数据无需修复，已完成清洗认证并生成 Cleaning Version。"
    );
  });

  it("preserves branching lineage and renders an empty state when no source is eligible", async () => {
    const response = await mockedGetDatasetVersions(datasetId);
    const branchId = "aa3979a1-206e-4a8f-8e37-a22e12f6027d";
    mockedGetDatasetVersions.mockResolvedValue({
      ...response,
      nodes: [
        ...response.nodes,
        {
          id: branchId,
          name: "V4 · 清洗分支",
          tool: "preprocessing.clean",
          parent_version_id: versionId,
          created_at: "2026-08-20T04:00:00Z",
          row_count: 1200,
          column_count: 4,
          artifact_path: "derived/clean-branch.csv",
        },
      ],
    });
    let wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    expect(wrapper.get(`[data-version-id='${branchId}']`).attributes("data-parent-id")).toBe(versionId);

    wrapper.unmount();
    routeState.query = { dataset_id: datasetId };
    const detail = datasetDetail(featureVersionId);
    mockedListDatasets.mockResolvedValue({ items: [detail] });
    mockedGetDatasetDetail.mockResolvedValue(detail);
    mockedGetDatasetVersions.mockResolvedValue({
      ...response,
      active_version_id: featureVersionId,
      nodes: response.nodes.filter((item) =>
        item.tool === "preprocessing.lag_compensation" ||
        item.tool === "preprocessing.feature_selection"
      ),
    });
    wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    expect(wrapper.get("[data-test='no-eligible-source']").text()).toContain(
      "暂无可用于清洗规整的数据版本"
    );
    expect(wrapper.get<HTMLButtonElement>("[data-test='clean-submit']").element.disabled).toBe(true);
  });

  it("shows a field-level validation error and prevents duplicate in-flight submissions", async () => {
    let resolveRequest: ((value: never) => void) | undefined;
    mockedCleanDataset.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve; }));
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    const button = wrapper.get("[data-test='clean-submit']");
    await button.trigger("click");
    await button.trigger("click");
    expect(mockedCleanDataset).toHaveBeenCalledTimes(1);

    resolveRequest!(undefined as never);
    await flushPromises();
    mockedCleanDataset.mockRejectedValueOnce(new ApiError(
      "REQUEST_VALIDATION_FAILED",
      "请求参数校验失败",
      "request-id",
      { issues: [{ loc: ["body", "version_id"], msg: "Input should be a valid UUID", type: "uuid_parsing" }] },
    ));
    await button.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("清洗失败 [REQUEST_VALIDATION_FAILED]");
    expect(wrapper.text()).toContain("version_id：Input should be a valid UUID");
  });
});
