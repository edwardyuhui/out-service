import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import ARXModelingView from "../../src/views/ARXModelingView.vue";
import { fitARXModel } from "../../src/api/modeling";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../../src/api/datasets";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type { DatasetItem, DatasetVersionNode } from "../../src/types/api";

vi.mock("../../src/api/modeling", () => ({ fitARXModel: vi.fn() }));
vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetVersions: vi.fn(),
  listDatasets: vi.fn(),
}));

const messages = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("element-plus", () => ({ ElMessage: messages }));

const mockedFitARXModel = vi.mocked(fitARXModel);
const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);
const mockedListDatasets = vi.mocked(listDatasets);

const datasetId = "dataset-arx";
const rawId = "raw-00000000-0000-4000-8000-000000000001";
const cleanId = "clean-00000000-0000-4000-8000-000000000002";
const lagId = "lag-00000000-0000-4000-8000-000000000099";
const featureId = "feature-00000000-0000-4000-8000-000000000003";
const orphanFeatureId = "feature-00000000-0000-4000-8000-000000000004";

const dataset = (versionId = featureId): DatasetItem => ({
  id: datasetId,
  name: "ARX lineage acceptance",
  version_id: versionId,
  latest_version_id: versionId,
  file_size_bytes: 1200,
  row_count: 1000,
  col_count: 4,
  created_at: "2026-09-04T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2"],
  output_column: "y",
});

const node = (
  id: string,
  name: string,
  tool: string,
  parentVersionId: string | null,
  createdAt: string,
  parameters: Record<string, unknown> = {}
): DatasetVersionNode => ({
  id,
  name,
  tool,
  parent_version_id: parentVersionId,
  created_at: createdAt,
  row_count: 1000,
  column_count: 4,
  artifact_path: `${id}.csv`,
  parameters,
});

const fullLineage = () => [
  node(rawId, "V0 · 仿真原始数据", "simulation_generate", null, "2026-09-04T00:00:00Z"),
  node(cleanId, "V8 · 清洗规整", "preprocessing.clean", rawId, "2026-09-04T01:00:00Z"),
  node(
    lagId,
    "V99 · 时滞补偿",
    "preprocessing.lag_compensation",
    cleanId,
    "2026-09-04T02:00:00Z",
    { lag_map: { u1: 3, u2: 8 } }
  ),
  node(
    featureId,
    "V3 · 特征优选",
    "preprocessing.feature_selection",
    lagId,
    "2026-09-04T03:00:00Z",
    { kept_input_columns: ["u1"] }
  ),
  node(
    orphanFeatureId,
    "V2 · 无 Lag 来源特征版本",
    "preprocessing.feature_selection",
    cleanId,
    "2026-09-04T04:00:00Z",
    { kept_input_columns: ["u1"] }
  ),
  node(
    "unknown-branch",
    "V4 · 自定义处理",
    "custom.operation",
    lagId,
    "2026-09-04T05:00:00Z"
  ),
];

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
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
  PageHeader: true,
  ChartContainer: true,
  "el-popover": ElPopoverStub,
  "el-select": { template: "<select><slot /></select>" },
  "el-option": true,
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<label>{{ label }}<slot /></label>" },
  "el-input-number": true,
  "el-button": ElButtonStub,
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-descriptions": { template: "<div><slot /></div>" },
  "el-descriptions-item": { props: ["label"], template: "<div>{{ label }}<slot /></div>" },
  "el-divider": true,
  "el-icon": { template: "<span><slot /></span>" },
  ArrowDown: true,
  Cpu: true,
  VideoPlay: true,
  Trophy: true,
  TrendCharts: true,
  RefreshRight: true,
};

let active: DatasetItem;
let versions: DatasetVersionNode[];

const fitResponse = {
  model_id: "model-1",
  task: {},
  estimator: "ols",
  dataset_id: datasetId,
  version_id: featureId,
  coefficients: {},
  a_coefficients: [0.5],
  b_coefficients: { u1: [0.2] },
  metrics: { val_free_run_fit: 70, val_fit: 75, aic: 2, bic: 3 },
  plot_data: { indices: [1], y_true: [1], y_pred: [1], residuals: [0], splits: {}, split_indices: null },
  residual_diagnostics: { acf_values: [], confidence_interval: null },
  artifact_uri: "model.json",
  validation: {
    fit_gap: 5,
    stable: true,
    max_pole_modulus: 0.5,
    steady_state_gains: { u1: 1 },
    residual_whiteness_ratio: 0.9,
  },
  prior_violations: [],
  training_rows: 600,
  free_run_series: [1],
} as never;

const installApi = () => {
  mockedListDatasets.mockResolvedValue({ items: [active] });
  mockedGetDatasetDetail.mockImplementation(async () => active);
  mockedGetDatasetVersions.mockImplementation(async () => ({
    dataset_id: datasetId,
    active_version_id: active.version_id,
    nodes: versions,
    edges: [],
  }));
  mockedFitARXModel.mockResolvedValue(fitResponse);
};

const mountView = async () => {
  const pinia = createPinia();
  setActivePinia(pinia);
  useDatasetStore().setActiveDataset(active);
  const wrapper = mount(ARXModelingView, { global: { plugins: [pinia], stubs } });
  await flushPromises();
  return wrapper;
};

describe("ARXModelingView VersionLineagePicker source contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    active = dataset(featureId);
    versions = fullLineage();
    installApi();
  });

  it("uses parent lineage eligibility and defaults to an active FeatureSet with a Lag ancestor", async () => {
    const wrapper = await mountView();

    expect(wrapper.text()).toContain("具备可信时滞补偿血缘的版本可用于 ARX 建模");
    expect(wrapper.text()).not.toContain("可信时滞补偿 lineage 可用于 ARX 建模");
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(6);
    expect(wrapper.get(`[data-version-id='${rawId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${cleanId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${lagId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${featureId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${orphanFeatureId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${orphanFeatureId}']`).text()).toContain("缺少可信时滞补偿来源");
    expect(wrapper.get("[data-test='arx-source-picker']").attributes("data-selected-version-id")).toBe(featureId);
    expect(wrapper.get("[data-test='arx-source-summary']").text()).toContain("V99 · 时滞补偿");
    expect(wrapper.get("[data-test='arx-source-summary']").text()).toContain("特征优选后，可用于 ARX 建模");
  });

  it("does not infer eligibility from a version number and preserves branching plus unknown operations", async () => {
    const wrapper = await mountView();

    expect(wrapper.get(`[data-version-id='${lagId}']`).text()).toContain("V99 · 时滞补偿");
    expect(wrapper.get(`[data-version-id='${lagId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${orphanFeatureId}']`).text()).toContain("V2 · 无 Lag 来源特征版本");
    expect(wrapper.get(`[data-version-id='${orphanFeatureId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get("[data-version-id='unknown-branch']").attributes("data-parent-id")).toBe(lagId);
    expect(wrapper.get("[data-version-id='unknown-branch']").attributes("aria-disabled")).toBe("true");
  });

  it("chooses the newest eligible source when the active version is not eligible", async () => {
    active = dataset("unknown-branch");
    installApi();
    const wrapper = await mountView();

    expect(wrapper.get("[data-test='arx-source-picker']").attributes("data-selected-version-id")).toBe(featureId);
  });

  it("fits with the selected UUID and clears the old model when the source changes", async () => {
    const wrapper = await mountView();
    await wrapper.get("[data-test='arx-fit-button']").trigger("click");
    await flushPromises();

    expect(mockedFitARXModel).toHaveBeenCalledWith(expect.objectContaining({
      dataset_id: datasetId,
      version_id: featureId,
      nb: [2],
      delays: [3],
      evaluate_test: false,
    }));
    expect(wrapper.text()).toContain("辨识结果与训练 / 验证指标");

    await wrapper.get(`[data-version-id='${lagId}']`).trigger("click");
    expect(wrapper.text()).not.toContain("辨识结果与训练 / 验证指标");
    expect(wrapper.get("[data-test='arx-source-picker']").attributes("data-selected-version-id")).toBe(lagId);
  });

  it("shows an empty source state when no Lag-ready lineage exists", async () => {
    active = dataset(cleanId);
    versions = fullLineage().filter((item) => [rawId, cleanId, orphanFeatureId, "unknown-branch"].includes(item.id));
    installApi();
    const wrapper = await mountView();

    expect(wrapper.get("[data-test='no-eligible-source']").text()).toContain("暂无可用于 ARX 建模的数据版本");
    expect(wrapper.get<HTMLButtonElement>("[data-test='arx-fit-button']").element.disabled).toBe(true);
  });
});
