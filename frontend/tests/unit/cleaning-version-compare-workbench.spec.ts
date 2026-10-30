import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import CleaningVersionCompareWorkbench from "../../src/components/cleaning/CleaningVersionCompareWorkbench.vue";
import VersionLineagePicker from "../../src/components/versioning/VersionLineagePicker.vue";
import {
  getCleaningVersionCompare,
  getCleaningVersionCompareChannels,
} from "../../src/api/datasets";
import { ApiError } from "../../src/api/client";
import type {
  CleaningVersionCompareChannelsData,
  CleaningVersionCompareData,
  DatasetItem,
  DatasetVersionNode,
} from "../../src/types/api";

vi.mock("../../src/api/datasets", () => ({
  getCleaningVersionCompare: vi.fn(),
  getCleaningVersionCompareChannels: vi.fn(),
}));

const mockedCompare = vi.mocked(getCleaningVersionCompare);
const mockedChannels = vi.mocked(getCleaningVersionCompareChannels);
const chartDispatchAction = vi.fn();
const chartConvertToPixel = vi.fn();
const chartContainPixel = vi.fn();
const chartGetSize = vi.fn();

const ChartContainerStub = defineComponent({
  name: "ChartContainer",
  props: { options: { type: Object, required: true }, height: String },
  emits: ["chartClick", "chartViewportChange"],
  setup(_props, { expose }) {
    expose({
      dispatchAction: chartDispatchAction,
      convertToPixel: chartConvertToPixel,
      containPixel: chartContainPixel,
      getSize: chartGetSize,
    });
    return () => h("div", { "data-test": "version-compare-chart" });
  },
});

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

const stubs = {
  "el-popover": ElPopoverStub,
  "el-icon": { template: "<span><slot /></span>" },
  "el-select": {
    props: ["modelValue", "disabled", "loading"],
    emits: ["update:modelValue"],
    template: '<select :value="modelValue ?? \'\'" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  "el-option": { props: ["label", "value"], template: '<option :value="value">{{ label }}</option>' },
  "el-button": {
    props: ["disabled", "loading"],
    template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
  },
  "el-tag": { template: "<span><slot /></span>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  ChartContainer: ChartContainerStub,
  ArrowDown: true,
};

const dataset: DatasetItem = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  name: "accept_collinearity_phase2",
  version_id: "",
  latest_version_id: "",
  file_size_bytes: 0,
  row_count: 4,
  col_count: 3,
  created_at: "2026-09-06T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1"],
  output_column: "y",
};

const raw: DatasetVersionNode = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "V0 · 原始数据",
  tool: "raw_upload",
  parent_version_id: null,
  created_at: "2026-09-06T00:00:00Z",
  row_count: 4,
  column_count: 3,
  artifact_path: "raw.csv",
};
const clean: DatasetVersionNode = {
  ...raw,
  id: "22222222-2222-4222-8222-222222222222",
  name: "V1 · 清洗规整",
  tool: "preprocessing.clean",
  parent_version_id: raw.id,
  artifact_path: "clean.csv",
};
const branch: DatasetVersionNode = {
  ...clean,
  id: "33333333-3333-4333-8333-333333333333",
  name: "V1B · 清洗规整",
  artifact_path: "branch.csv",
};
const simulation: DatasetVersionNode = {
  ...raw,
  id: "44444444-4444-4444-8444-444444444444",
  name: "V0B · 仿真数据",
  tool: "simulation_generate",
  artifact_path: "simulation.csv",
};
const lag: DatasetVersionNode = {
  ...clean,
  id: "55555555-5555-4555-8555-555555555555",
  name: "V2 · 时滞补偿",
  tool: "preprocessing.lag_compensation",
  parent_version_id: clean.id,
  artifact_path: "lag.csv",
};
const feature: DatasetVersionNode = {
  ...lag,
  id: "66666666-6666-4666-8666-666666666666",
  name: "V3 · 特征优选",
  tool: "preprocessing.feature_selection",
  parent_version_id: lag.id,
  artifact_path: "feature.csv",
};

const channelResponse = (
  baselineId = raw.id,
  compareId = clean.id,
  names = ["u1", "y"],
  warnings: string[] = []
): CleaningVersionCompareChannelsData => ({
  dataset_id: dataset.id,
  baseline_version_id: baselineId,
  compare_version_id: compareId,
  channels: names.map((name) => ({
    name,
    baseline_inferred_type: "float",
    compare_inferred_type: "float",
    unit: null,
  })),
  warnings,
});

const compareResponse = (overrides: Partial<CleaningVersionCompareData> = {}): CleaningVersionCompareData => ({
  dataset_id: dataset.id,
  baseline: {
    version_id: raw.id,
    name: raw.name,
    operation_name: raw.tool,
    parent_version_id: null,
    created_at: raw.created_at,
    row_count: 4,
    column_count: 3,
    sha256: "a".repeat(64),
  },
  compare: {
    version_id: clean.id,
    name: clean.name,
    operation_name: clean.tool,
    parent_version_id: raw.id,
    created_at: clean.created_at,
    row_count: 4,
    column_count: 3,
    sha256: "b".repeat(64),
  },
  relation: "DIRECT_PARENT",
  direction: "BASELINE_TO_COMPARE",
  channel: { name: "u1", inferred_type: "float", unit: null },
  baseline_series: {
    input_point_count: 3,
    returned_point_count: 3,
    projected: false,
    points: [
      { timestamp: "2026-01-01T00:00:00Z", occurrence_index: 0, value: 1 },
      { timestamp: "2026-01-01T00:00:01Z", occurrence_index: 0, value: 2 },
      { timestamp: "2026-01-01T00:00:03Z", occurrence_index: 0, value: 4 },
    ],
  },
  compare_series: {
    input_point_count: 3,
    returned_point_count: 3,
    projected: false,
    points: [
      { timestamp: "2026-01-01T00:00:00Z", occurrence_index: 0, value: 1.5 },
      { timestamp: "2026-01-01T00:00:01Z", occurrence_index: 0, value: 2 },
      { timestamp: "2026-01-01T00:00:02Z", occurrence_index: 0, value: 3 },
    ],
  },
  difference_points: [
    {
      timestamp: "2026-01-01T00:00:00Z",
      difference_kind: "VALUE_CHANGED",
      baseline_value: 1,
      compare_value: 1.5,
      absolute_delta: 0.5,
      baseline_occurrences: [],
      compare_occurrences: [],
    },
    {
      timestamp: "2026-01-01T00:00:02Z",
      difference_kind: "POINT_ADDED",
      baseline_value: null,
      compare_value: 3,
      absolute_delta: null,
      baseline_occurrences: [],
      compare_occurrences: [{ timestamp: "2026-01-01T00:00:02Z", occurrence_index: 0, value: 3 }],
    },
    {
      timestamp: "2026-01-01T00:00:03Z",
      difference_kind: "POINT_REMOVED",
      baseline_value: 4,
      compare_value: null,
      absolute_delta: null,
      baseline_occurrences: [{ timestamp: "2026-01-01T00:00:03Z", occurrence_index: 0, value: 4 }],
      compare_occurrences: [],
    },
    {
      timestamp: "2026-01-01T00:00:04Z",
      difference_kind: "AMBIGUOUS_ALIGNMENT",
      baseline_value: null,
      compare_value: null,
      absolute_delta: null,
      baseline_occurrences: [
        { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 0, value: 4 },
        { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 1, value: 5 },
      ],
      compare_occurrences: [{ timestamp: "2026-01-01T00:00:04Z", occurrence_index: 0, value: 4.5 }],
    },
  ],
  difference_points_truncated: false,
  generic_diff_summary: {
    scope: "selected_channel",
    baseline_point_count: 4,
    compare_point_count: 4,
    unique_matched_timestamps: 2,
    unchanged_values: 1,
    changed_values: 1,
    added_points: 1,
    removed_points: 1,
    ambiguous_timestamp_groups: 1,
    baseline_duplicate_occurrences: 1,
    compare_duplicate_occurrences: 0,
    contains_null_transitions: false,
  },
  direct_derivation_summary: null,
  convergence_evidence: { baseline: null, compare: null },
  artifacts_identical: false,
  projection: {
    applied: false,
    max_points: 10_000,
    strategy: "none",
    diff_computed_before_projection: true,
  },
  warnings: [],
  ...overrides,
});

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

const mountWorkbench = (versions: DatasetVersionNode[], currentVersionId: string) =>
  mount(CleaningVersionCompareWorkbench, {
    props: { dataset, versions, currentVersionId },
    global: { stubs },
  });

describe("CleaningVersionCompareWorkbench", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedChannels.mockResolvedValue(channelResponse());
    mockedCompare.mockResolvedValue(compareResponse());
    chartConvertToPixel.mockImplementation((_finder, value) => Array.isArray(value) ? [120, 160] : 120);
    chartContainPixel.mockReturnValue(true);
    chartGetSize.mockReturnValue({ width: 720, height: 420 });
  });

  it("uses two independent lineage pickers with the exact eligibility contract", async () => {
    const wrapper = mountWorkbench([raw, clean, simulation, lag, feature], clean.id);
    await flushPromises();
    const pickers = wrapper.findAllComponents(VersionLineagePicker);

    expect(pickers).toHaveLength(2);
    expect(pickers[0].props("selectedVersionId")).toBe(raw.id);
    expect(pickers[1].props("selectedVersionId")).toBe(clean.id);
    expect(pickers[0].props("selectedBadgeLabel")).toBe("比较基线");
    expect(pickers[1].props("selectedBadgeLabel")).toBe("对照版本");
    const eligible = pickers[0].props("isEligible") as (version: DatasetVersionNode) => boolean;
    expect([raw, clean, simulation].every(eligible)).toBe(true);
    expect([lag, feature].some(eligible)).toBe(false);

    pickers[0].vm.$emit("select", clean.id);
    await flushPromises();
    expect(pickers[0].props("selectedVersionId")).toBe(clean.id);
    expect(pickers[1].props("selectedVersionId")).toBe(clean.id);
  });

  it("implements all four deterministic default-pair cases", async () => {
    let wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    let pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, clean.id]);
    wrapper.unmount();

    wrapper = mountWorkbench([raw, clean], raw.id);
    await flushPromises();
    pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, clean.id]);
    wrapper.unmount();

    mockedChannels.mockClear();
    wrapper = mountWorkbench([raw, clean, branch], raw.id);
    await flushPromises();
    pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, null]);
    expect(mockedChannels).not.toHaveBeenCalled();
    wrapper.unmount();

    wrapper = mountWorkbench([raw], raw.id);
    await flushPromises();
    pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, raw.id]);
  });

  it("loads channels for pair changes, ignores stale metadata, and handles empty/warning states", async () => {
    const first = deferred<CleaningVersionCompareChannelsData>();
    const second = deferred<CleaningVersionCompareChannelsData>();
    mockedChannels.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    const pickers = wrapper.findAllComponents(VersionLineagePicker);

    pickers[0].vm.$emit("select", clean.id);
    await flushPromises();
    second.resolve(channelResponse(clean.id, clean.id, ["y"], ["unit metadata warning"]));
    await flushPromises();
    first.resolve(channelResponse(raw.id, clean.id, ["u1"]));
    await flushPromises();

    expect(wrapper.get<HTMLSelectElement>("[data-test='version-compare-channel']").element.value).toBe("y");
    expect(wrapper.text()).toContain("unit metadata warning");

    mockedChannels.mockResolvedValueOnce(channelResponse(clean.id, raw.id, []));
    pickers[1].vm.$emit("select", raw.id);
    await flushPromises();
    expect(wrapper.text()).toContain("两个版本没有可共同比较的数值通道");
    expect(wrapper.get<HTMLButtonElement>("[data-test='version-compare-submit']").element.disabled).toBe(true);
  });

  it("executes only on explicit submit and clears a result when the channel changes", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    expect(mockedCompare).not.toHaveBeenCalled();

    await wrapper.get("[data-test='version-compare-channel']").setValue("y");
    await flushPromises();
    expect(mockedCompare).not.toHaveBeenCalled();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect(mockedCompare).toHaveBeenCalledWith(dataset.id, {
      baseline_version_id: raw.id,
      compare_version_id: clean.id,
      channel: "y",
      max_points: 10_000,
    });
    expect(wrapper.find("[data-test='version-compare-result']").exists()).toBe(true);

    await wrapper.get("[data-test='version-compare-channel']").setValue("u1");
    await flushPromises();
    expect(wrapper.find("[data-test='version-compare-result']").exists()).toBe(false);
    expect(mockedCompare).toHaveBeenCalledTimes(1);
  });

  it("protects execution results from stale requests", async () => {
    const first = deferred<CleaningVersionCompareData>();
    const second = deferred<CleaningVersionCompareData>();
    mockedCompare.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();

    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await wrapper.get("[data-test='version-compare-channel']").setValue("y");
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    second.resolve(compareResponse({
      channel: { name: "y", inferred_type: "float", unit: null },
      generic_diff_summary: { ...compareResponse().generic_diff_summary, changed_values: 7 },
    }));
    await flushPromises();
    first.resolve(compareResponse({ generic_diff_summary: { ...compareResponse().generic_diff_summary, changed_values: 99 } }));
    await flushPromises();

    expect(wrapper.get(".metric-card.changed").text()).toContain("7");
    expect(wrapper.get(".metric-card.changed").text()).not.toContain("99");
  });

  it("renders relation, summary, identity, projection notices, and the overlay contract", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      artifacts_identical: true,
      projection: { applied: true, max_points: 10_000, strategy: "evenly_spaced_index_with_endpoints", diff_computed_before_projection: true },
      difference_points_truncated: true,
      warnings: ["compare warning"],
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("直接派生");
    expect(wrapper.text()).toContain("Baseline → Compare");
    expect(wrapper.text()).toContain("数据内容一致");
    expect(wrapper.text()).toContain("值变化1");
    expect(wrapper.text()).toContain("新增点1");
    expect(wrapper.text()).toContain("移除点1");
    expect(wrapper.text()).toContain("对齐歧义组1");
    expect(wrapper.text()).toContain("图形已抽样显示，差异统计基于完整数据");
    expect(wrapper.text()).toContain("差异统计完整，图中仅显示部分差异点");
    expect(wrapper.text()).toContain("compare warning");
    expect(wrapper.text()).toContain("未建立 occurrence 间的推测配对");

    const options = wrapper.getComponent(ChartContainerStub).props("options") as {
      xAxis: { type: string };
      dataZoom: Array<{ type: string }>;
      legend: { data: string[] };
      series: Array<{
        id: string;
        name?: string;
        type: string;
        silent?: boolean;
        symbolSize?: number;
        cursor?: string;
        legendHoverLink?: boolean;
        tooltip?: { show: boolean };
        emphasis?: { scale?: number; focus?: string };
        coordinateSystem?: string;
        z?: number;
        renderItem?: (
          params: { coordSys: { type: string; x: number; y: number; width: number; height: number } },
          api: { value: (dimension: number) => string; coord: (value: Array<string | number>) => number[] }
        ) => {
          type: string;
          shape: { x: number; y: number; width: number; height: number };
          style: { fill: string };
          emphasis?: { style?: Record<string, unknown> };
        } | null;
        lineStyle?: { type: string; color: string };
        markLine?: {
          silent: boolean;
          lineStyle: { color: string; width: number };
          emphasis?: { lineStyle: { color: string; width: number; opacity: number } };
          data: Array<Record<string, unknown>>;
        };
        data: Array<{ value?: unknown } | unknown[]>;
      }>;
    };
    expect(options.xAxis.type).toBe("time");
    expect(options.dataZoom.map((zoom) => zoom.type)).toEqual(["inside", "slider"]);
    expect(options.legend.data).toEqual(["Baseline", "Compare"]);
    expect(options.series.find((series) => series.id === "version-compare-baseline")).toEqual(expect.objectContaining({
      name: "Baseline",
      type: "line",
      lineStyle: expect.objectContaining({ type: "dashed", color: "#A8665E" }),
      data: expect.arrayContaining([["2026-01-01T00:00:00Z", 1]]),
    }));
    expect(options.series.find((series) => series.id === "version-compare-target")).toEqual(expect.objectContaining({
      name: "Compare",
      type: "line",
      lineStyle: expect.objectContaining({ type: "solid", color: "#557562" }),
    }));
    expect(options.series.find((series) => series.id === "version-difference-changed")?.data).toHaveLength(1);
    expect(options.series.find((series) => series.id === "version-difference-added")?.data).toHaveLength(1);
    expect(options.series.find((series) => series.id === "version-difference-removed")?.data).toHaveLength(1);
    const hitArea = options.series.find((series) => series.id === "version-difference-hit-area")!;
    expect(hitArea).toEqual(expect.objectContaining({
      silent: false,
      symbolSize: 20,
      cursor: "pointer",
      legendHoverLink: false,
      tooltip: { show: false },
      emphasis: { scale: 1.1, focus: "none" },
    }));
    const hitAreaData = hitArea.data as Array<Record<string, unknown>>;
    const hitByKind = (kind: string) => hitAreaData.find((datum) => datum.differenceKind === kind)!;
    expect(hitByKind("VALUE_CHANGED")).toEqual(expect.objectContaining({
      differencePoint: true,
      differenceIndex: 0,
      differenceKind: "VALUE_CHANGED",
      anchorValue: ["2026-01-01T00:00:00Z", 1.5],
      visualSeriesId: "version-difference-changed",
      visualDataIndex: 0,
      emphasis: {
        itemStyle: {
          color: "#B5965D24",
          borderColor: "#B5965D",
          borderWidth: 2,
          shadowBlur: 6,
          shadowColor: "#B5965D66",
        },
      },
    }));
    expect(hitByKind("POINT_ADDED")).toEqual(expect.objectContaining({
      differenceIndex: 1,
      visualSeriesId: "version-difference-added",
      emphasis: {
        itemStyle: expect.objectContaining({
          color: "#55756224",
          borderColor: "#557562",
          shadowColor: "#55756266",
        }),
      },
    }));
    expect(hitByKind("POINT_REMOVED")).toEqual(expect.objectContaining({
      differenceIndex: 2,
      visualSeriesId: "version-difference-removed",
      emphasis: {
        itemStyle: expect.objectContaining({
          color: "#A8665E24",
          borderColor: "#A8665E",
          shadowColor: "#A8665E66",
        }),
      },
    }));
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);
    const baselineMarkLine = options.series.find((series) => series.id === "version-compare-baseline")?.markLine;
    const compareMarkLine = options.series.find((series) => series.id === "version-compare-target")?.markLine;
    expect(baselineMarkLine).toBeUndefined();
    expect(compareMarkLine).toEqual(expect.objectContaining({
      silent: true,
      lineStyle: expect.objectContaining({ color: "#8E7B55", type: "dashed" }),
      data: [{ name: "对齐歧义", xAxis: "2026-01-01T00:00:04Z" }],
    }));
    expect(compareMarkLine?.data[0]).not.toHaveProperty("yAxis");
    expect(compareMarkLine?.data[0]).not.toHaveProperty("value");
    const ambiguityStrip = options.series.find((series) => series.id === "version-ambiguity-hit-strip")!;
    expect(ambiguityStrip).toEqual(expect.objectContaining({
      name: "version-ambiguity-hit-strip",
      type: "custom",
      coordinateSystem: "cartesian2d",
      silent: false,
      cursor: "pointer",
      legendHoverLink: false,
      tooltip: { show: false },
      z: 21,
    }));
    expect(ambiguityStrip.z).toBeGreaterThan(hitArea.z ?? 0);
    expect(ambiguityStrip.data).toEqual([expect.objectContaining({
      value: ["2026-01-01T00:00:04Z"],
      timestamp: "2026-01-01T00:00:04Z",
      differenceIndex: 3,
      differenceKind: "AMBIGUOUS_ALIGNMENT",
    })]);
    const ambiguityDatum = ambiguityStrip.data[0] as Record<string, unknown>;
    expect(ambiguityDatum).not.toHaveProperty("baselineValue");
    expect(ambiguityDatum).not.toHaveProperty("compareValue");
    expect(ambiguityDatum).not.toHaveProperty("anchorValue");
    const renderedStrip = ambiguityStrip.renderItem?.(
      { coordSys: { type: "cartesian2d", x: 40, y: 52, width: 600, height: 280 } },
      {
        value: () => "2026-01-01T00:00:04Z",
        coord: () => [180, 999],
      }
    );
    expect(renderedStrip).toEqual(expect.objectContaining({
      type: "rect",
      shape: { x: 173, y: 52, width: 14, height: 280 },
      style: { fill: "rgba(142, 123, 85, 0.001)" },
      emphasis: {
        style: {
          fill: "rgba(142, 123, 85, 0.1)",
          shadowBlur: 4,
          shadowColor: "rgba(142, 123, 85, 0.24)",
        },
      },
    }));
    expect(renderedStrip?.emphasis).not.toHaveProperty("shape");
    expect(options.series.filter((series) => series.type === "scatter").flatMap((series) => series.data).some((datum) =>
      !Array.isArray(datum) && datum.value instanceof Array && datum.value[0] === "2026-01-01T00:00:04Z"
    )).toBe(false);

    await wrapper.get("[data-test='version-compare-reset-zoom']").trigger("click");
    expect(chartDispatchAction).toHaveBeenCalledWith({ type: "dataZoom", start: 0, end: 100 });
  });

  it("renders same-version zero diff and scoped API errors without fallback", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      relation: "SAME_VERSION",
      direction: "NONE",
      artifacts_identical: true,
      generic_diff_summary: {
        ...compareResponse().generic_diff_summary,
        changed_values: 0,
        added_points: 0,
        removed_points: 0,
        ambiguous_timestamp_groups: 0,
      },
      difference_points: [],
    }));
    let wrapper = mountWorkbench([raw], raw.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("同一版本，无数据差异");
    wrapper.unmount();

    mockedChannels.mockRejectedValueOnce(new ApiError("DATASET_ARTIFACT_MISSING", "产物不存在", "request"));
    wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    expect(wrapper.text()).toContain("共同通道加载失败 [DATASET_ARTIFACT_MISSING]：产物不存在");
    wrapper.unmount();

    mockedChannels.mockResolvedValueOnce(channelResponse());
    mockedCompare.mockRejectedValueOnce(new ApiError("CLEANING_COMPARE_CHANNEL_INVALID", "观察通道无效", "request"));
    wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("版本比较失败 [CLEANING_COMPARE_CHANNEL_INVALID]：观察通道无效");
    expect(wrapper.get<HTMLSelectElement>("[data-test='version-compare-channel']").element.value).toBe("u1");
  });

  it("maps an ordinary hit target to anchored detail, repositions across viewport changes, and closes cleanly", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    const options = chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    };
    const hitDatum = options.series.find((series) => series.id === "version-difference-hit-area")!.data[0];
    chart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: hitDatum });
    await flushPromises();

    expect(wrapper.get("[data-test='difference-detail-card']").text()).toContain("值变化");
    expect(wrapper.get("[data-test='difference-detail-host']").classes()).not.toContain("is-anchor-hidden");
    expect(chartConvertToPixel).toHaveBeenCalledWith(
      { xAxisIndex: 0, yAxisIndex: 0 },
      ["2026-01-01T00:00:00Z", 1.5]
    );
    expect(chartDispatchAction).toHaveBeenCalledWith({
      type: "highlight",
      seriesId: "version-difference-changed",
      dataIndex: 0,
    });

    chartContainPixel.mockReturnValue(false);
    chart.vm.$emit("chartViewportChange", { reason: "resize" });
    await flushPromises();
    expect(wrapper.get("[data-test='difference-detail-host']").classes()).toContain("is-anchor-hidden");
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(true);

    chartContainPixel.mockReturnValue(true);
    chart.vm.$emit("chartViewportChange", { reason: "resize" });
    await flushPromises();
    expect(wrapper.get("[data-test='difference-detail-host']").classes()).not.toContain("is-anchor-hidden");

    await wrapper.get("[data-test='difference-detail-close']").trigger("click");
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);
    expect(chartDispatchAction).toHaveBeenCalledWith({
      type: "downplay",
      seriesId: "version-difference-changed",
      dataIndex: 0,
    });
  });

  it("maps the ambiguity custom strip to timestamp detail without a business y anchor", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    const options = chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    };
    const hitStripDatum = options.series.find((series) => series.id === "version-ambiguity-hit-strip")!.data[0];
    const realisticEvent = {
      componentType: "series",
      seriesType: "custom",
      seriesName: "version-ambiguity-hit-strip",
      seriesIndex: 6,
      dataIndex: 0,
      data: hitStripDatum,
    };
    const invalidEvents = [
      { ...realisticEvent, seriesType: "line" },
      { ...realisticEvent, seriesName: "other-custom-series" },
      { ...realisticEvent, data: { ...hitStripDatum, differenceKind: "VALUE_CHANGED" } },
      { ...realisticEvent, data: { ...hitStripDatum, differenceIndex: 999 } },
    ];
    for (const event of invalidEvents) {
      chart.vm.$emit("chartClick", event);
      await flushPromises();
      expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);
    }

    chartContainPixel.mockClear();
    chart.vm.$emit("chartClick", realisticEvent);
    await flushPromises();

    const detail = wrapper.get("[data-test='difference-detail-card']");
    expect(detail.text()).toContain("对齐歧义");
    expect(detail.text()).toContain("Baseline occurrences (2)");
    expect(detail.text()).toContain("Compare occurrences (1)");
    expect(detail.text()).toContain("系统未推测 occurrence 配对");
    expect(detail.text()).not.toContain("Absolute delta");
    expect(chartConvertToPixel).toHaveBeenCalledWith(
      { xAxisIndex: 0 },
      "2026-01-01T00:00:04Z"
    );
    expect(wrapper.get("[data-test='difference-detail-host']").classes()).not.toContain("is-anchor-hidden");
    expect(chartContainPixel).not.toHaveBeenCalled();
    expect(chartDispatchAction).not.toHaveBeenCalledWith(expect.objectContaining({ type: "highlight" }));
  });

  it("tracks normalized time windows for ambiguity visibility without losing selection or calling APIs", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    const options = chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    };
    const hitStripDatum = options.series.find((series) => series.id === "version-ambiguity-hit-strip")!.data[0];
    chart.vm.$emit("chartClick", {
      componentType: "series",
      seriesType: "custom",
      seriesName: "version-ambiguity-hit-strip",
      data: hitStripDatum,
    });
    await flushPromises();

    const timestamp = Date.parse("2026-01-01T00:00:04Z");
    const compareCalls = mockedCompare.mock.calls.length;
    const channelCalls = mockedChannels.mock.calls.length;
    const detailHost = () => wrapper.get("[data-test='difference-detail-host']");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 20,
        end: 80,
        startValue: "invalid-start",
        endValue: "invalid-end",
      }],
    });
    await flushPromises();
    expect(detailHost().classes()).not.toContain("is-anchor-hidden");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        dataZoomId: "version-compare-inside-zoom",
        xAxisIndices: [0],
        start: 0,
        end: 50,
        startValue: timestamp - 10_000,
        endValue: timestamp - 1,
      }],
    });
    await flushPromises();
    expect(detailHost().classes()).toContain("is-anchor-hidden");
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(true);

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 10,
        end: 40,
        startValue: "still-invalid",
        endValue: undefined,
      }],
    });
    await flushPromises();
    expect(detailHost().classes()).toContain("is-anchor-hidden");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [
        {
          dataZoomIndex: 0,
          xAxisIndices: [1],
          start: 20,
          end: 80,
          startValue: timestamp + 10_000,
          endValue: timestamp + 20_000,
        },
        {
          dataZoomIndex: 1,
          xAxisIndices: [0],
          start: 20,
          end: 80,
          startValue: "invalid-linked-start",
          endValue: "invalid-linked-end",
        },
        {
          dataZoomIndex: 2,
          xAxisIndices: [0],
          start: 20,
          end: 80,
          startValue: new Date(timestamp - 1_000).toISOString(),
          endValue: new Date(timestamp + 1_000).toISOString(),
        },
      ],
    });
    await flushPromises();
    expect(detailHost().classes()).not.toContain("is-anchor-hidden");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 25,
        end: 75,
        startValue: new Date(timestamp + 1_000),
        endValue: new Date(timestamp - 1_000),
      }],
    });
    await flushPromises();
    expect(detailHost().classes()).not.toContain("is-anchor-hidden");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 0,
        end: 50,
        startValue: timestamp - 10_000,
        endValue: timestamp - 1,
      }],
    });
    await flushPromises();
    chartConvertToPixel.mockClear();
    chart.vm.$emit("chartViewportChange", { reason: "resize" });
    await flushPromises();
    expect(detailHost().classes()).toContain("is-anchor-hidden");
    expect(chartConvertToPixel).not.toHaveBeenCalled();

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 25,
        end: 75,
        startValue: timestamp,
        endValue: timestamp + 2_000,
      }],
    });
    await flushPromises();
    chartConvertToPixel.mockClear();
    chart.vm.$emit("chartViewportChange", { reason: "resize" });
    await flushPromises();
    expect(detailHost().classes()).not.toContain("is-anchor-hidden");
    expect(chartConvertToPixel).toHaveBeenCalledWith({ xAxisIndex: 0 }, "2026-01-01T00:00:04Z");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 0,
        end: 50,
        startValue: timestamp + 1,
        endValue: timestamp + 10_000,
      }],
    });
    await flushPromises();
    expect(detailHost().classes()).toContain("is-anchor-hidden");
    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 0.0000001,
        end: 99.999999,
        startValue: "ignored-invalid-full-start",
        endValue: "ignored-invalid-full-end",
      }],
    });
    await flushPromises();
    expect(detailHost().classes()).not.toContain("is-anchor-hidden");

    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{
        dataZoomIndex: 0,
        xAxisIndices: [0],
        start: 20,
        end: 80,
        startValue: timestamp + 1,
        endValue: timestamp + 10_000,
      }],
    });
    await flushPromises();
    await wrapper.get("[data-test='version-compare-reset-zoom']").trigger("click");
    chart.vm.$emit("chartViewportChange", {
      reason: "datazoom",
      ranges: [{ dataZoomIndex: 0, xAxisIndices: [0], start: 0, end: 100 }],
    });
    await flushPromises();
    expect(detailHost().classes()).not.toContain("is-anchor-hidden");
    expect(chartDispatchAction).toHaveBeenCalledWith({ type: "dataZoom", start: 0, end: 100 });
    expect(mockedCompare).toHaveBeenCalledTimes(compareCalls);
    expect(mockedChannels).toHaveBeenCalledTimes(channelCalls);
  });

  it("keeps every ordinary difference kind on the real two-dimensional containment path", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    const chart = wrapper.getComponent(ChartContainerStub);
    const hitArea = (chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    }).series.find((series) => series.id === "version-difference-hit-area")!;

    for (const differenceKind of ["VALUE_CHANGED", "POINT_ADDED", "POINT_REMOVED"]) {
      const datum = hitArea.data.find((entry) => entry.differenceKind === differenceKind)!;
      chartConvertToPixel.mockClear();
      chartContainPixel.mockClear();
      chart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: datum });
      await flushPromises();
      expect(chartConvertToPixel).toHaveBeenCalledWith(
        { xAxisIndex: 0, yAxisIndex: 0 },
        datum.anchorValue
      );
      expect(chartContainPixel).toHaveBeenCalledWith({ gridIndex: 0 }, [120, 160]);
    }
  });

  it("does not retain temporary compare-click diagnostics in production components", () => {
    const workbenchSource = readFileSync(
      resolve(process.cwd(), "src/components/cleaning/CleaningVersionCompareWorkbench.vue"),
      "utf8"
    );
    const chartContainerSource = readFileSync(resolve(process.cwd(), "src/components/ChartContainer.vue"), "utf8");
    expect(workbenchSource).not.toContain("[CompareClickDebug]");
    expect(workbenchSource).not.toContain("[AmbiguityClickTrace]");
    expect(chartContainerSource).not.toContain("[ChartClickDebug]");
  });

  it("renders direct evidence by property presence and isolates unknown scalar audit fields", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      direct_derivation_summary: {
        from_version_id: raw.id,
        to_version_id: clean.id,
        evidence_source: "persisted",
        scope: "all_numeric_columns",
        changes: {
          unique_changed_cells: 34,
          missing_value_fills: 0,
          outlier_replacements: 34,
          future_scalar: "ready",
          future_nested: { hidden: "must-not-render" },
        },
      },
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    const evidence = wrapper.get("[data-test='direct-cleaning-evidence']");
    expect(evidence.text()).toContain("直接清洗证据 · 全部数值通道");
    expect(evidence.text()).toContain("持久化审计证据");
    expect(evidence.get("[data-evidence-key='unique_changed_cells']").text()).toContain("34");
    expect(evidence.get("[data-evidence-key='missing_value_fills']").text()).toContain("0");
    expect(evidence.find("[data-evidence-key='smoothing_changes']").exists()).toBe(false);
    expect(evidence.get("[data-test='other-audit-fields']").text()).toContain("future_scalar");
    expect(evidence.get("[data-test='other-audit-fields']").text()).toContain("ready");
    expect(evidence.text()).not.toContain("must-not-render");
    expect(wrapper.text()).toContain("Compare 由 Baseline 经一次直接清洗产生");
  });

  it("renders legacy totals without invented breakdown and keeps artifact identity separate from convergence", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      artifacts_identical: true,
      direct_derivation_summary: {
        from_version_id: raw.id,
        to_version_id: clean.id,
        evidence_source: "legacy_total_only",
        scope: "all_numeric_columns",
        changes: { unique_changed_cells: 0 },
      },
      convergence_evidence: {
        baseline: {
          version_id: raw.id,
          processing_run_id: "77777777-7777-4777-8777-777777777777",
          occurred_at: "2026-09-06T12:34:56Z",
          no_op: true,
          converged: true,
          effective_version_id: raw.id,
          unique_changed_cells: 0,
          parameters: {},
        },
        compare: null,
      },
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    const evidence = wrapper.get("[data-test='direct-cleaning-evidence']");
    expect(evidence.text()).toContain("历史总数记录");
    expect(evidence.text()).toContain("唯一修改单元格0");
    expect(evidence.text()).toContain("历史版本未记录完整分类明细");
    expect(evidence.text()).not.toContain("缺失填补");

    const status = wrapper.get("[data-test='version-status-card']");
    expect(status.text()).toContain("数据内容一致");
    expect(status.get("[data-test='convergence-baseline']").text()).toContain("存在正式清洗收敛证据");
    expect(status.get("[data-test='convergence-baseline']").text()).toContain("77777777…");
    expect(status.get("[data-test='convergence-compare']").text()).toContain("无正式收敛运行证据");
    expect(status.text()).not.toContain("未收敛");
    expect((wrapper.text().match(/数据内容一致/g) ?? [])).toHaveLength(1);
  });

  it("renders a status-only identical sibling with two neutral null-convergence states", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      relation: "SIBLING",
      direction: "NONE",
      artifacts_identical: true,
      direct_derivation_summary: null,
      convergence_evidence: { baseline: null, compare: null },
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.find("[data-test='direct-cleaning-evidence']").exists()).toBe(false);
    expect(wrapper.get("[data-test='version-compare-evidence-grid']").classes()).toContain("status-only");
    const status = wrapper.get("[data-test='version-status-card']");
    expect(status.text()).toContain("数据内容一致不等同于存在正式清洗收敛证据");
    expect(status.get("[data-test='convergence-baseline']").text()).toContain("无正式收敛运行证据");
    expect(status.get("[data-test='convergence-compare']").text()).toContain("无正式收敛运行证据");
    expect(status.text()).not.toContain("未收敛");
    expect(wrapper.text()).toContain("两个版本来自同一父版本，不存在直接派生关系");
  });

  it("labels replayed direct evidence and renders Compare convergence independently", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      direct_derivation_summary: {
        from_version_id: raw.id,
        to_version_id: clean.id,
        evidence_source: "replayed",
        scope: "all_numeric_columns",
        changes: { unique_changed_cells: 2 },
      },
      convergence_evidence: {
        baseline: null,
        compare: {
          version_id: clean.id,
          processing_run_id: "88888888-8888-4888-8888-888888888888",
          occurred_at: "2026-09-06T13:00:00Z",
          no_op: true,
          converged: true,
          effective_version_id: clean.id,
          unique_changed_cells: 0,
          parameters: {},
        },
      },
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='direct-cleaning-evidence']").text()).toContain("只读重放恢复");
    expect(wrapper.get("[data-test='convergence-baseline']").text()).toContain("无正式收敛运行证据");
    expect(wrapper.get("[data-test='convergence-compare']").text()).toContain("存在正式清洗收敛证据");
    expect(wrapper.get("[data-test='convergence-compare']").text()).toContain("88888888…");
  });

  it("deduplicates warnings across metadata and result sources while preserving notices", async () => {
    mockedChannels.mockResolvedValueOnce(channelResponse(raw.id, clean.id, ["u1"], ["same warning", "same warning", "channel only"]));
    mockedCompare.mockResolvedValueOnce(compareResponse({
      projection: {
        applied: true,
        max_points: 10_000,
        strategy: "evenly_spaced_index_with_endpoints",
        diff_computed_before_projection: true,
      },
      difference_points_truncated: true,
      warnings: ["same warning", "result only", "result only"],
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect((wrapper.text().match(/same warning/g) ?? [])).toHaveLength(1);
    expect((wrapper.text().match(/channel only/g) ?? [])).toHaveLength(1);
    expect((wrapper.text().match(/result only/g) ?? [])).toHaveLength(1);
    expect(wrapper.text()).toContain("图形已抽样显示，差异统计基于完整数据");
    expect(wrapper.text()).toContain("差异统计完整，图中仅显示部分差异点");
  });

  it("clears selected detail on channel, pair, and new-request transitions", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    const chart = wrapper.getComponent(ChartContainerStub);
    const hitDatum = (chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    }).series.find((series) => series.id === "version-difference-hit-area")!.data[0];
    const openDetail = async () => {
      chart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: hitDatum });
      await flushPromises();
      expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(true);
    };

    await openDetail();
    await wrapper.get("[data-test='version-compare-channel']").setValue("y");
    await flushPromises();
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);

    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    const refreshedHitDatum = (chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    }).series.find((series) => series.id === "version-difference-hit-area")!.data[0];
    chart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: refreshedHitDatum });
    await flushPromises();
    wrapper.findAllComponents(VersionLineagePicker)[0].vm.$emit("select", clean.id);
    await flushPromises();
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);

    mockedCompare.mockResolvedValueOnce(compareResponse());
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    const latestHitDatum = (chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    }).series.find((series) => series.id === "version-difference-hit-area")!.data[0];
    chart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: latestHitDatum });
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);
  });

  it("clears selected detail when Compare or dataset identity changes", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    const chart = wrapper.getComponent(ChartContainerStub);
    const hitDatum = (chart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    }).series.find((series) => series.id === "version-difference-hit-area")!.data[0];
    chart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: hitDatum });
    await flushPromises();
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(true);

    wrapper.findAllComponents(VersionLineagePicker)[1].vm.$emit("select", raw.id);
    await flushPromises();
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);

    wrapper.findAllComponents(VersionLineagePicker)[1].vm.$emit("select", clean.id);
    await flushPromises();
    mockedCompare.mockResolvedValueOnce(compareResponse());
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    const refreshedChart = wrapper.getComponent(ChartContainerStub);
    const refreshedHitDatum = (refreshedChart.props("options") as {
      series: Array<{ id: string; data: Array<Record<string, unknown>> }>;
    }).series.find((series) => series.id === "version-difference-hit-area")!.data[0];
    refreshedChart.vm.$emit("chartClick", { seriesId: "version-difference-hit-area", data: refreshedHitDatum });
    await flushPromises();
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(true);

    await wrapper.setProps({ dataset: { ...dataset, id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" } });
    await flushPromises();
    expect(wrapper.find("[data-test='difference-detail-card']").exists()).toBe(false);
  });

  it.each([
    ["DIRECT_PARENT", "BASELINE_TO_COMPARE", "Compare 由 Baseline 经一次直接处理产生。"],
    ["ANCESTOR_DESCENDANT", "BASELINE_TO_COMPARE", "Compare 是 Baseline 的后代版本，中间包含一个或多个处理步骤。"],
    ["SIBLING", "NONE", "两个版本来自同一父版本，不存在直接派生关系。"],
    ["SAME_VERSION", "NONE", "Baseline 与 Compare 指向同一个不可变版本。"],
    ["UNRELATED_WITHIN_DATASET", "NONE", "两个版本属于同一数据集，但当前血缘中不存在直接祖先或同父关系。"],
  ] as const)("explains %s without inferring from timestamps or names", async (relation, direction, copy) => {
    mockedCompare.mockResolvedValueOnce(compareResponse({ relation, direction }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain(copy);
    wrapper.unmount();
  });
});
