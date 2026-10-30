import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import SegmentationView from "../../src/views/SegmentationView.vue";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../../src/api/datasets";
import { segmentDataset } from "../../src/api/preprocessing";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type { DatasetItem, DatasetVersionNode } from "../../src/types/api";

vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetVersions: vi.fn(),
  listDatasets: vi.fn(),
}));
vi.mock("../../src/api/preprocessing", () => ({ segmentDataset: vi.fn() }));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn() } }));

const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);
const mockedListDatasets = vi.mocked(listDatasets);
const mockedSegmentDataset = vi.mocked(segmentDataset);

const dataset: DatasetItem = {
  id: "dataset-phase2",
  name: "accept_collinearity_phase2",
  version_id: "lag-version-v2",
  latest_version_id: "lag-version-v2",
  source: "simulation",
  status: "ready",
  file_size_bytes: 1024,
  row_count: 2000,
  col_count: 6,
  created_at: "2026-09-03T18:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2", "u3", "u4"],
  output_column: "y",
};

const rawVersion: DatasetVersionNode = {
  id: "raw-version-v0",
  name: "V0 · 仿真原始",
  tool: "simulation_generate",
  parent_version_id: null,
  created_at: "2026-09-03T18:00:00Z",
  row_count: 2000,
  column_count: 6,
  artifact_path: "datasets/raw.csv",
};

const cleanVersion: DatasetVersionNode = {
  id: "2eb39a88-57d7-46e5-8ace-b43232cf9fbd",
  name: "V1 · 清洗规整",
  tool: "preprocessing.clean",
  parent_version_id: rawVersion.id,
  created_at: "2026-09-03T18:10:00Z",
  row_count: 2000,
  column_count: 6,
  artifact_path: "datasets/clean.csv",
};

const lagVersion: DatasetVersionNode = {
  id: "f7b9b88c-d7ba-4c09-bc81-980a2dc01c35",
  name: "V2 · 时滞补偿",
  tool: "preprocessing.lag_compensation",
  parent_version_id: cleanVersion.id,
  created_at: "2026-09-03T18:20:00Z",
  row_count: 1991,
  column_count: 6,
  artifact_path: "datasets/lag.csv",
};

const ElSelectStub = defineComponent({
  name: "ElSelect",
  inheritAttrs: false,
  props: { modelValue: String, disabled: Boolean, loading: Boolean },
  emits: ["update:modelValue", "change"],
  setup(props, { attrs, slots }) {
    return () => h("div", {
      ...attrs,
      role: "combobox",
      "data-model-value": props.modelValue ?? "",
      "aria-disabled": String(props.disabled),
    }, slots.default?.());
  },
});

const ElOptionStub = defineComponent({
  name: "ElOption",
  props: { label: String, value: String },
  setup(props, { slots }) {
    return () => h("div", { "data-option-value": props.value }, slots.default?.() ?? props.label);
  },
});

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  props: { visible: Boolean, disabled: Boolean },
  emits: ["update:visible"],
  setup(_props, { slots }) {
    return () => h("div", { class: "popover-stub" }, [slots.reference?.(), slots.default?.()]);
  },
});

const ElButtonStub = defineComponent({
  name: "ElButton",
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ["click"],
  setup(props, { attrs, emit, slots }) {
    return () => h("button", {
      ...attrs,
      type: "button",
      disabled: props.disabled || props.loading,
      onClick: () => emit("click"),
    }, slots.default?.());
  },
});

const stubs = {
  "el-select": ElSelectStub,
  "el-option": ElOptionStub,
  "el-popover": ElPopoverStub,
  "el-button": ElButtonStub,
  "el-input": {
    inheritAttrs: false,
    props: ["modelValue", "placeholder", "size"],
    emits: ["update:modelValue"],
    template: "<input :value='modelValue' @input='$emit(\"update:modelValue\", $event.target.value)' />",
  },
  "el-input-number": true,
  "el-alert": { template: "<div><slot name='title' /><slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-table": { template: "<div><slot /></div>" },
  "el-table-column": true,
  ChartContainer: { template: "<div class='chart-stub' />" },
  ArrowDown: true,
  Crop: true,
  DataLine: true,
  Filter: true,
  TrendCharts: true,
};

const resultFixture = {
  dataset_id: dataset.id,
  source_version_id: cleanVersion.id,
  task: { task_id: "segment-task", status: "completed", stage: "completed", progress: 1 },
  series: { y: [1, 2] },
  segments: [],
  gated_windows: [],
  selection: {
    candidate_count: 1,
    gated_count: 1,
    selected_count: 1,
    coverage_ratio: 0.5,
    design_matrix_condition_number: 2,
    excitation_satisfied: true,
  },
} as never;

const installApi = (nodes: DatasetVersionNode[]) => {
  mockedListDatasets.mockResolvedValue({ items: [dataset] });
  mockedGetDatasetDetail.mockResolvedValue(dataset);
  mockedGetDatasetVersions.mockResolvedValue({
    dataset_id: dataset.id,
    active_version_id: dataset.version_id,
    nodes,
    edges: nodes
      .filter((node) => node.parent_version_id)
      .map((node) => ({ source: node.parent_version_id!, target: node.id })),
  });
  mockedSegmentDataset.mockResolvedValue(resultFixture);
};

const mountView = async (nodes: DatasetVersionNode[]) => {
  const pinia = createPinia();
  setActivePinia(pinia);
  useDatasetStore().setActiveDataset(dataset);
  installApi(nodes);
  const wrapper = mount(SegmentationView, {
    global: { plugins: [pinia], stubs, mocks: { $router: { push: vi.fn() } } },
  });
  await flushPromises();
  return wrapper;
};

describe("SegmentationView lineage source picker", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows the real lineage, disables non-Cleaning versions, and executes against Cleaning instead of active V2", async () => {
    const wrapper = await mountView([lagVersion, rawVersion, cleanVersion]);

    expect(wrapper.text()).toContain("数据集");
    expect(wrapper.text()).toContain("分析源版本");
    expect(wrapper.text()).toContain("查看版本血缘");
    expect(wrapper.text()).not.toContain("数据版本 ID");

    const nodes = wrapper.findAll("[data-test='lineage-node']");
    expect(nodes).toHaveLength(3);
    expect(nodes.map((node) => node.attributes("data-version-id"))).toEqual([
      rawVersion.id,
      cleanVersion.id,
      lagVersion.id,
    ]);
    expect(nodes[1]?.attributes("data-parent-id")).toBe(rawVersion.id);
    expect(nodes[2]?.attributes("data-parent-id")).toBe(cleanVersion.id);
    expect(nodes[0]?.attributes("aria-disabled")).toBe("true");
    expect(nodes[1]?.attributes("aria-disabled")).toBe("false");
    expect(nodes[2]?.attributes("aria-disabled")).toBe("true");
    expect(nodes[1]?.text()).toContain("可用于 D-最优");
    expect(nodes[0]?.text()).toContain("需先完成清洗规整");
    expect(nodes[2]?.text()).toContain("已进入后续阶段");

    const summary = wrapper.get("[data-test='source-summary']");
    expect(summary.text()).toContain("V1 · 清洗规整");
    expect(summary.text()).toContain("V0 · 仿真原始");
    expect(summary.text()).toContain("2eb39a88…9fbd");
    expect(summary.text()).not.toContain(cleanVersion.id);

    await wrapper.findAll("button")[0]!.trigger("click");
    expect(mockedSegmentDataset).toHaveBeenCalledWith(expect.objectContaining({ version_id: cleanVersion.id }));
    expect(mockedSegmentDataset).not.toHaveBeenCalledWith(expect.objectContaining({ version_id: lagVersion.id }));
  });

  it("uses parent_version_id for branches, survives unknown operations, and clears results when the source changes", async () => {
    const cleanBranch = {
      ...cleanVersion,
      id: "clean-branch-a",
      name: "V1A · 清洗规整",
      created_at: "2026-09-03T18:05:00Z",
    };
    const cleanLatest = {
      ...cleanVersion,
      id: "clean-branch-b",
      name: "V1B · 清洗规整",
      created_at: "2026-09-03T18:15:00Z",
    };
    const unknown = {
      ...lagVersion,
      id: "unknown-child",
      name: "",
      tool: "custom.transform",
      parent_version_id: cleanLatest.id,
    };
    const wrapper = await mountView([unknown, cleanLatest, rawVersion, cleanBranch]);

    expect(wrapper.get("[data-test='source-summary']").text()).toContain("V1B · 清洗规整");
    const unknownNode = wrapper.get("[data-version-id='unknown-child']");
    expect(unknownNode.attributes("data-parent-id")).toBe(cleanLatest.id);
    expect(unknownNode.text()).toContain("custom.transform");
    expect(unknownNode.attributes("aria-disabled")).toBe("true");

    await wrapper.findAll("button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.find(".hud-kpi-bar").exists()).toBe(true);

    await wrapper.get("[data-version-id='clean-branch-a']").trigger("click");
    expect(wrapper.get("[data-test='source-summary']").text()).toContain("V1A · 清洗规整");
    expect(wrapper.find(".hud-kpi-bar").exists()).toBe(false);
  });

  it("shows a guided empty state and keeps Analyze disabled when no Cleaning version exists", async () => {
    const wrapper = await mountView([rawVersion, { ...lagVersion, parent_version_id: rawVersion.id }]);

    const empty = wrapper.get("[data-test='no-eligible-source']");
    expect(empty.text()).toContain("暂无可用于 D-最优分析的清洗规整版本");
    expect(empty.text()).toContain("请先完成 Stage 02 时间清洗");
    expect(wrapper.find("[data-test='source-summary']").exists()).toBe(false);
    expect(wrapper.findAll("button")[0]?.attributes()).toHaveProperty("disabled");
    expect(mockedSegmentDataset).not.toHaveBeenCalled();
  });
});
