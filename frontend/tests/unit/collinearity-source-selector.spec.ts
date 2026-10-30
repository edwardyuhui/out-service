import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import CollinearityView from "../../src/views/CollinearityView.vue";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type {
  CollinearityResponse,
  CollinearitySourceStatus,
  CollinearitySourceVersionItem,
  CollinearitySourceVersionsData,
  DatasetItem,
} from "../../src/types/api";

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    default: {
      get: apiMocks.get,
      post: apiMocks.post,
      delete: vi.fn(),
    },
  };
});

vi.mock("element-plus", () => ({
  ElMessage: { success: apiMocks.messageSuccess, error: apiMocks.messageError },
  ElMessageBox: { confirm: apiMocks.confirm },
}));

const ElSelectStub = defineComponent({
  name: "ElSelect",
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: "" },
    disabled: Boolean,
    loading: Boolean,
  },
  emits: ["update:modelValue", "change"],
  setup(props, { attrs, emit, slots }) {
    return () =>
      h(
        "select",
        {
          ...attrs,
          value: props.modelValue ?? "",
          disabled: props.disabled,
          "data-loading": String(props.loading),
          onChange: (event: Event) => {
            const value = (event.target as HTMLSelectElement).value;
            emit("update:modelValue", value);
            emit("change", value);
          },
        },
        [h("option", { value: "" }, "请选择"), slots.default?.()]
      );
  },
});

const ElOptionStub = defineComponent({
  name: "ElOption",
  props: { label: String, value: String },
  setup(props) {
    return () => h("option", { value: props.value }, props.label);
  },
});

const ElInputStub = defineComponent({
  name: "ElInput",
  inheritAttrs: false,
  props: { modelValue: { type: String, default: "" } },
  emits: ["update:modelValue"],
  setup(props, { attrs, emit }) {
    return () => {
      const inputAttrs = { ...attrs };
      delete inputAttrs.size;
      return h("input", {
        ...inputAttrs,
        value: props.modelValue,
        onInput: (event: Event) =>
          emit("update:modelValue", (event.target as HTMLInputElement).value),
      });
    };
  },
});

const ElInputNumberStub = defineComponent({
  name: "ElInputNumber",
  inheritAttrs: false,
  props: { modelValue: Number },
  emits: ["update:modelValue"],
  setup(props, { attrs, emit }) {
    return () => {
      const inputAttrs = { ...attrs };
      delete inputAttrs.size;
      return h("input", {
        ...inputAttrs,
        type: "number",
        value: props.modelValue,
        onInput: (event: Event) =>
          emit("update:modelValue", Number((event.target as HTMLInputElement).value)),
      });
    };
  },
});

const ElButtonStub = defineComponent({
  name: "ElButton",
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ["click"],
  setup(props, { attrs, emit, slots }) {
    return () =>
      h(
        "button",
        {
          ...attrs,
          type: "button",
          disabled: props.disabled,
          "data-loading": String(props.loading),
          onClick: () => emit("click"),
        },
        slots.default?.()
      );
  },
});

const ElAlertStub = defineComponent({
  name: "ElAlert",
  props: { title: String, description: String },
  setup(props, { slots }) {
    return () =>
      h("div", { class: "el-alert-stub" }, [
        slots.title?.() ?? props.title,
        props.description ? h("span", props.description) : null,
      ]);
  },
});

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

const ChartContainerStub = defineComponent({
  name: "ChartContainer",
  inheritAttrs: false,
  props: {
    options: { type: Object, required: true },
    height: String,
  },
  setup(props, { attrs }) {
    return () =>
      h("div", {
        ...attrs,
        class: "chart-container-stub",
        "data-height": props.height,
      });
  },
});

const simpleSlotStub = { template: "<span><slot /></span>" };
const stubs = {
  "el-select": ElSelectStub,
  "el-option": ElOptionStub,
  "el-input": ElInputStub,
  "el-input-number": ElInputNumberStub,
  "el-button": ElButtonStub,
  "el-alert": ElAlertStub,
  "el-popover": ElPopoverStub,
  "el-icon": simpleSlotStub,
  "el-tag": simpleSlotStub,
  ChartContainer: ChartContainerStub,
  ArrowDown: true,
};

const dataset = (id: string, name = id): DatasetItem => ({
  id,
  name,
  version_id: `${id}-active-version`,
  latest_version_id: `${id}-latest-version`,
  file_size_bytes: 100,
  row_count: 120,
  col_count: 3,
  created_at: "2026-09-01T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2"],
  output_column: "y",
});

const source = (
  versionId: string,
  status: CollinearitySourceStatus,
  index = 2,
  inputColumns = ["u1", "u2"]
): CollinearitySourceVersionItem => ({
  version_id: versionId,
  version_index: index,
  name: `V${index} · 时滞补偿`,
  operation_name: "preprocessing.lag_compensation",
  parent_version_id: `${versionId}-parent`,
  created_at: "2026-09-01T02:00:00Z",
  input_columns: inputColumns,
  collinearity_status: status,
  latest_complete_collinearity_run_id: status === "complete" ? `${versionId}-run` : null,
});

const analysisResult = (
  sourceVersionId: string,
  datasetId: string,
  variables = ["u1", "u2"]
): CollinearityResponse => ({
  source_version_id: sourceVersionId,
  processing_run_id: `${sourceVersionId}-processing-run`,
  dataset_id: datasetId,
  task: { task_id: "task-id", status: "completed", stage: "completed", progress: 1 },
  variables,
  matrix: [
    [1, 0.2],
    [0.2, 1],
  ],
  spearman_matrix: [
    [1, 0.18],
    [0.18, 1],
  ],
  vif_scores: { [variables[0]]: 1.1, [variables[1]]: null },
  condition_number: 2.4,
  correlated_groups: [],
  recommendations: variables.map((variable) => ({
    variable,
    action: "keep" as const,
    reason: "stable",
    related_variables: [],
  })),
  input_diagnostics: variables.map((column) => ({
    column,
    status: "analyzable" as const,
    reason: "数值方差充足，可参与相关性、VIF 与条件数诊断。",
    variance: 1,
  })),
});

const sourceData = (
  datasetId: string,
  sources: ReturnType<typeof source>[],
  defaultSourceVersionId: string | null
): CollinearitySourceVersionsData => ({
  dataset_id: datasetId,
  default_source_version_id: defaultSourceVersionId,
  sources,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

let datasetsResponse: DatasetItem[];
let detailResponses: Map<string, DatasetItem | Promise<DatasetItem>>;
let sourceResponses: Map<
  string,
  Array<CollinearitySourceVersionsData | Promise<CollinearitySourceVersionsData>>
>;
let sourceCallCounts: Map<string, number>;
let latestResponses: Map<string, CollinearityResponse | Promise<CollinearityResponse>>;

const lineageResponse = (data: CollinearitySourceVersionsData) => ({
  dataset_id: data.dataset_id,
  active_version_id: `${data.dataset_id}-active-version`,
  nodes: [
    {
      id: `${data.dataset_id}-raw`,
      name: "V0 · 仿真原始数据",
      tool: "simulation_generate",
      parent_version_id: null,
      created_at: "2026-09-01T00:00:00Z",
      row_count: 120,
      column_count: 3,
      artifact_path: "raw.csv",
    },
    {
      id: `${data.dataset_id}-clean`,
      name: "V1 · 清洗规整",
      tool: "preprocessing.clean",
      parent_version_id: `${data.dataset_id}-raw`,
      created_at: "2026-09-01T01:00:00Z",
      row_count: 120,
      column_count: 3,
      artifact_path: "clean.csv",
    },
    ...data.sources.map((item, index) => ({
      id: item.version_id,
      name: item.name,
      tool: item.operation_name,
      parent_version_id: `${data.dataset_id}-clean`,
      created_at: new Date(Date.parse(item.created_at) + index * 60_000).toISOString(),
      row_count: 120,
      column_count: 3,
      artifact_path: `${item.version_id}.csv`,
    })),
  ],
});

type LineageResponse = ReturnType<typeof lineageResponse>;
let versionResponses: Map<string, Array<LineageResponse | Promise<LineageResponse>>>;
let versionCallCounts: Map<string, number>;

const installApiBehavior = () => {
  apiMocks.get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
    if (url === "/datasets?page=1&page_size=100") {
      return Promise.resolve({ items: datasetsResponse });
    }
    if (url === "/preprocessing/collinearity/latest") {
      const versionId = config?.params?.version_id ?? "";
      const response = latestResponses.get(versionId);
      if (!response) return Promise.reject(new Error(`Missing latest response for ${versionId}`));
      return response instanceof Promise ? response : Promise.resolve(response);
    }
    const versionsMatch = url.match(/^\/datasets\/([^/]+)\/versions$/);
    if (versionsMatch) {
      const datasetId = versionsMatch[1];
      const explicitQueue = versionResponses.get(datasetId);
      if (explicitQueue?.length) {
        const callIndex = versionCallCounts.get(datasetId) ?? 0;
        versionCallCounts.set(datasetId, callIndex + 1);
        return Promise.resolve(explicitQueue[Math.min(callIndex, explicitQueue.length - 1)]);
      }
      const response = sourceResponses.get(datasetId)?.[0];
      if (!response) return Promise.reject(new Error(`Missing versions response for ${datasetId}`));
      return response instanceof Promise
        ? response.then(lineageResponse)
        : Promise.resolve(lineageResponse(response));
    }
    const sourceMatch = url.match(/^\/datasets\/([^/]+)\/collinearity-sources$/);
    if (sourceMatch) {
      const datasetId = sourceMatch[1];
      const queue = sourceResponses.get(datasetId) ?? [];
      const callIndex = sourceCallCounts.get(datasetId) ?? 0;
      sourceCallCounts.set(datasetId, callIndex + 1);
      const response = queue[Math.min(callIndex, queue.length - 1)];
      if (!response) return Promise.reject(new Error(`Missing source response for ${datasetId}`));
      return response instanceof Promise ? response : Promise.resolve(response);
    }
    const detailMatch = url.match(/^\/datasets\/([^/]+)$/);
    if (detailMatch) {
      const response = detailResponses.get(detailMatch[1]);
      if (!response) return Promise.reject(new Error(`Missing detail response for ${detailMatch[1]}`));
      return response instanceof Promise ? response : Promise.resolve(response);
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
};

const mountView = (activeDataset: DatasetItem | null = null) => {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useDatasetStore();
  store.setActiveDataset(activeDataset);
  const wrapper = mount(CollinearityView, {
    global: {
      plugins: [pinia],
      stubs,
      mocks: { $router: { push: vi.fn() } },
    },
  });
  return { wrapper, store };
};

const chartOptions = <T,>(wrapper: VueWrapper, testId: string): T => {
  const chart = wrapper
    .findAllComponents(ChartContainerStub)
    .find((candidate) => candidate.attributes("data-test") === testId);
  if (!chart) throw new Error(`Missing chart ${testId}`);
  return chart.props("options") as T;
};

interface CorrelationChartOptions {
  tooltip: { formatter: (params: { value: [number, number] | [number, number, number]; data?: { unavailable?: boolean; reason?: string } }) => string };
  series: Array<{ data: any[] }>;
}

interface VifChartOptions {
  tooltip: {
    formatter: (params: Array<{ axisValue: string }>) => string;
  };
  xAxis: { axisLabel: { formatter: (name: string) => string } };
  series: Array<{
    data: Array<{
      value: number | null;
      label: { show: boolean; formatter?: string };
    }>;
  }>;
}

describe("CollinearityView dataset and Lag Compensation source context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    datasetsResponse = [];
    detailResponses = new Map();
    sourceResponses = new Map();
    sourceCallCounts = new Map();
    versionResponses = new Map();
    versionCallCounts = new Map();
    latestResponses = new Map();
    apiMocks.post.mockRejectedValue(new Error("Unexpected POST"));
    installApiBehavior();
  });

  it("loads datasets, preselects a valid active Dataset ID, selects the default source, and rehydrates complete results", async () => {
    const active = { ...dataset("dataset-a", "生产数据 A"), version_id: "version-not-a-dataset" };
    datasetsResponse = [active, dataset("dataset-b", "生产数据 B")];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", analysisResult("lag-a", "dataset-a"));

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(apiMocks.get).toHaveBeenCalledWith("/datasets?page=1&page_size=100");
    expect(wrapper.get<HTMLSelectElement>('[data-test="dataset-select"]').element.value).toBe(
      "dataset-a"
    );
    expect(wrapper.get('[data-test="source-select"]').attributes("data-selected-version-id")).toBe("lag-a");
    const lineageNodes = wrapper.findAll("[data-test='lineage-node']");
    expect(lineageNodes[0]?.text()).toContain("V0 · 仿真原始数据");
    expect(lineageNodes[0]?.attributes("aria-disabled")).toBe("true");
    expect(lineageNodes[1]?.text()).toContain("V1 · 清洗规整");
    expect(lineageNodes[1]?.attributes("aria-disabled")).toBe("true");
    expect(wrapper.get("[data-version-id='lag-a']").text()).toContain("可用于共线性诊断");
    expect(wrapper.get("[data-version-id='lag-a']").attributes("aria-disabled")).toBe("false");
    expect(apiMocks.get).toHaveBeenCalledWith("/datasets/dataset-a/collinearity-sources");
    expect(apiMocks.get).not.toHaveBeenCalledWith(
      "/datasets/version-not-a-dataset/collinearity-sources"
    );
    expect(apiMocks.get).toHaveBeenCalledWith("/preprocessing/collinearity/latest", {
      params: { version_id: "lag-a", dataset_id: "dataset-a" },
    });
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);
  });

  it("switches the rehydrated heatmap between Pearson and Spearman without analyzing again", async () => {
    const active = dataset("dataset-a");
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", analysisResult("lag-a", "dataset-a"));

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.get('[data-test="correlation-title"]').text()).toBe(
      "Pearson 相关系数矩阵"
    );
    expect(wrapper.get('[data-test="correlation-mode-pearson"]').attributes("aria-pressed")).toBe(
      "true"
    );
    let options = chartOptions<CorrelationChartOptions>(wrapper, "correlation-chart");
    expect(options.series[0].data).toContainEqual([1, 0, 0.2]);
    expect(options.tooltip.formatter({ value: [1, 0, 0.2] })).toContain("Pearson r");

    await wrapper.get('[data-test="correlation-mode-spearman"]').trigger("click");
    expect(wrapper.get('[data-test="correlation-title"]').text()).toBe(
      "Spearman 秩相关系数矩阵"
    );
    options = chartOptions<CorrelationChartOptions>(wrapper, "correlation-chart");
    expect(options.series[0].data).toContainEqual([1, 0, 0.18]);
    expect(options.tooltip.formatter({ value: [1, 0, 0.18] })).toContain(
      "Spearman correlation"
    );
    expect(apiMocks.post).not.toHaveBeenCalled();

    await wrapper.get('[data-test="correlation-mode-pearson"]').trigger("click");
    options = chartOptions<CorrelationChartOptions>(wrapper, "correlation-chart");
    expect(options.series[0].data).toContainEqual([1, 0, 0.2]);
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("shows an explicit unavailable state when a historical result has no Spearman matrix", async () => {
    const active = dataset("dataset-a");
    const legacyResult = {
      ...analysisResult("lag-a", "dataset-a"),
      spearman_matrix: undefined,
    } as unknown as CollinearityResponse;
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", legacyResult);

    const { wrapper } = mountView(active);
    await flushPromises();
    expect(wrapper.find('[data-test="correlation-chart"]').exists()).toBe(true);

    await wrapper.get('[data-test="correlation-mode-spearman"]').trigger("click");
    expect(wrapper.find('[data-test="correlation-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="matrix-unavailable"]').text()).toContain("N/A");
    expect(wrapper.get('[data-test="matrix-unavailable"]').text()).toContain(
      "当前历史结果没有可用的 Spearman 秩相关系数矩阵"
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("renders nullable VIF as N/A without creating a zero-height value", async () => {
    const active = dataset("dataset-a");
    const persisted = analysisResult("lag-a", "dataset-a");
    persisted.recommendations[1] = {
      variable: "u2",
      action: "drop",
      reason: "backend recommendation",
      related_variables: ["u1"],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", persisted);

    const { wrapper } = mountView(active);
    await flushPromises();

    const options = chartOptions<VifChartOptions>(wrapper, "vif-chart");
    expect(options.series[0].data[0].value).toBe(1.1);
    expect(options.series[0].data[1].value).toBeNull();
    expect(options.series[0].data[1].value).not.toBe(0);
    expect(options.series[0].data[1].label).toMatchObject({
      show: true,
      formatter: "N/A",
    });
    expect(options.xAxis.axisLabel.formatter("u2")).toContain("N/A");
    expect(options.tooltip.formatter([{ axisValue: "u1" }])).toContain("VIF: 1.10");
    expect(options.tooltip.formatter([{ axisValue: "u2" }])).toContain("VIF: N/A");
    expect(options.tooltip.formatter([{ axisValue: "u2" }])).toContain("无法可靠计算 VIF");
    expect(wrapper.get('[data-test="decision-row-u2"]').text()).toContain("N/A");
  });

  it("resets correlation mode to Pearson when the source or Dataset changes", async () => {
    const firstDataset = { ...dataset("dataset-a"), version_id: "lag-a" };
    const secondDataset = dataset("dataset-b");
    datasetsResponse = [firstDataset, secondDataset];
    detailResponses.set("dataset-a", firstDataset);
    detailResponses.set("dataset-b", secondDataset);
    sourceResponses.set("dataset-a", [
      sourceData(
        "dataset-a",
        [source("lag-a", "complete", 2), source("lag-a-next", "complete", 3)],
        "lag-a"
      ),
    ]);
    sourceResponses.set("dataset-b", [
      sourceData("dataset-b", [source("lag-b", "complete")], "lag-b"),
    ]);
    latestResponses.set("lag-a", analysisResult("lag-a", "dataset-a"));
    latestResponses.set("lag-a-next", analysisResult("lag-a-next", "dataset-a"));
    latestResponses.set("lag-b", analysisResult("lag-b", "dataset-b"));

    const { wrapper } = mountView(firstDataset);
    await flushPromises();
    await wrapper.get('[data-test="correlation-mode-spearman"]').trigger("click");
    await wrapper.get("[data-version-id='lag-a-next']").trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-test="correlation-title"]').text()).toBe(
      "Pearson 相关系数矩阵"
    );

    await wrapper.get('[data-test="correlation-mode-spearman"]').trigger("click");
    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-b");
    await flushPromises();
    expect(wrapper.get('[data-test="correlation-title"]').text()).toBe(
      "Pearson 相关系数矩阵"
    );
  });

  it("does not treat a stale active DatasetVersion ID as a Dataset ID", async () => {
    const active = { ...dataset("stale-dataset"), version_id: "dataset-b" };
    datasetsResponse = [dataset("dataset-b", "生产数据 B")];

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.get<HTMLSelectElement>('[data-test="dataset-select"]').element.value).toBe("");
    expect(apiMocks.get).not.toHaveBeenCalledWith("/datasets/dataset-b");
    expect(apiMocks.get).not.toHaveBeenCalledWith("/datasets/dataset-b/collinearity-sources");
  });

  it("clears a complete result when switching sources and never auto-POSTs not_analyzed or unrehydratable sources", async () => {
    const active = { ...dataset("dataset-a"), version_id: "lag-complete" };
    const sources = [
      source("lag-complete", "complete", 2),
      source("lag-new", "not_analyzed", 3),
      source("lag-legacy", "unrehydratable", 4),
    ];
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [sourceData("dataset-a", sources, "lag-complete")]);
    latestResponses.set("lag-complete", analysisResult("lag-complete", "dataset-a"));

    const { wrapper } = mountView(active);
    await flushPromises();
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);

    await wrapper.get("[data-version-id='lag-new']").trigger("click");
    await flushPromises();
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(false);
    expect(wrapper.text()).toContain("该时滞补偿版本尚未进行共线性分析。");
    expect(apiMocks.post).not.toHaveBeenCalled();
    expect(
      apiMocks.get.mock.calls.filter(([url]) => url === "/preprocessing/collinearity/latest")
    ).toHaveLength(1);

    await wrapper.get("[data-version-id='lag-legacy']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain(
      "该版本存在历史分析记录，但结果无法按当前格式完整恢复，可重新执行分析。"
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
    expect(
      apiMocks.get.mock.calls.filter(([url]) => url === "/preprocessing/collinearity/latest")
    ).toHaveLength(1);
  });

  it("shows the explicit no-source state and disables Analyze without falling back", async () => {
    const active = dataset("dataset-a");
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [sourceData("dataset-a", [], null)]);

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.text()).toContain("该数据集暂无可用于共线性分析的时滞补偿版本。");
    expect(wrapper.text()).toContain("请先完成时滞补偿后再进行共线性分析。");
    expect(wrapper.get<HTMLButtonElement>('[data-test="analyze-button"]').element.disabled).toBe(
      true
    );
    expect(apiMocks.get).not.toHaveBeenCalledWith(
      "/preprocessing/collinearity/latest",
      expect.anything()
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("keeps Dataset-detail inputs and Analyze available for a not_analyzed source from the older selector contract", async () => {
    const active = { ...dataset("dataset-a"), input_columns: ["u1", "u2", "u3", "u4"] };
    const oldSelectorSource = {
      ...source("lag-a", "not_analyzed", 2, ["u1", "u2", "u3", "u4"]),
      input_columns: undefined,
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [oldSelectorSource], "lag-a"),
    ]);

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.get('[data-test="input-columns"]').text()).toContain("u4");
    expect(wrapper.text()).toContain("该时滞补偿版本尚未进行共线性分析。");
    expect(wrapper.get<HTMLButtonElement>('[data-test="analyze-button"]').element.disabled).toBe(false);
    expect(wrapper.find('[data-test="legacy-qualification-warning"]').exists()).toBe(false);
    expect(apiMocks.get).not.toHaveBeenCalledWith(
      "/preprocessing/collinearity/latest",
      expect.anything()
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("shows a reanalyze warning rather than crashing when a legacy persisted result lacks input diagnostics", async () => {
    const active = dataset("dataset-a");
    const legacy = {
      ...analysisResult("lag-a", "dataset-a"),
      input_diagnostics: undefined,
      recommendations: [],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", legacy);

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.find('.collin-tri-grid').exists()).toBe(true);
    expect(wrapper.get('[data-test="legacy-qualification-warning"]').text()).toContain(
      "该历史分析结果缺少输入资格诊断信息，建议重新执行分析"
    );
    expect(wrapper.find('[data-test="input-qualification"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="decision-recommendations-empty"]').text()).toContain(
      "当前结果未提供特征决策建议"
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("clears Dataset A results immediately, requests Dataset B sources, and updates the SPA context", async () => {
    const active = dataset("dataset-a", "数据集 A");
    const next = dataset("dataset-b", "数据集 B");
    const nextDetail = deferred<DatasetItem>();
    datasetsResponse = [active, next];
    detailResponses.set("dataset-a", active);
    detailResponses.set("dataset-b", nextDetail.promise);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    sourceResponses.set("dataset-b", [
      sourceData("dataset-b", [source("lag-b", "not_analyzed")], "lag-b"),
    ]);
    latestResponses.set("lag-a", analysisResult("lag-a", "dataset-a"));

    const { wrapper, store } = mountView(active);
    await flushPromises();
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);

    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-b");
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(false);
    expect(wrapper.get('[data-test="source-select"]').attributes("data-selected-version-id")).toBe("");

    nextDetail.resolve(next);
    await flushPromises();
    expect(apiMocks.get).toHaveBeenCalledWith("/datasets/dataset-b/collinearity-sources");
    expect(wrapper.get('[data-test="source-select"]').attributes("data-selected-version-id")).toBe("lag-b");
    expect(store.activeDataset?.id).toBe("dataset-b");
  });

  it("ignores an older Dataset detail request that resolves after a newer selection", async () => {
    const first = dataset("dataset-a", "数据集 A");
    const second = dataset("dataset-b", "数据集 B");
    const firstDetail = deferred<DatasetItem>();
    datasetsResponse = [first, second];
    detailResponses.set("dataset-a", firstDetail.promise);
    detailResponses.set("dataset-b", second);
    sourceResponses.set("dataset-b", [
      sourceData("dataset-b", [source("lag-b", "not_analyzed")], "lag-b"),
    ]);

    const { wrapper, store } = mountView();
    await flushPromises();
    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-a");
    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-b");
    await flushPromises();

    firstDetail.resolve(first);
    await flushPromises();

    expect(wrapper.get<HTMLSelectElement>('[data-test="dataset-select"]').element.value).toBe(
      "dataset-b"
    );
    expect(wrapper.get('[data-test="source-select"]').attributes("data-selected-version-id")).toBe("lag-b");
    expect(store.activeDataset?.id).toBe("dataset-b");
    expect(apiMocks.get).not.toHaveBeenCalledWith("/datasets/dataset-a/collinearity-sources");
  });

  it("ignores an older complete-result rehydrate after the user selects a newer source", async () => {
    const active = { ...dataset("dataset-a"), version_id: "lag-old" };
    const firstLatest = deferred<CollinearityResponse>();
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData(
        "dataset-a",
        [
          source("lag-old", "complete", 2, ["old-u1", "old-u2"]),
          source("lag-new", "complete", 3, ["new-u1", "new-u2"]),
        ],
        "lag-old"
      ),
    ]);
    latestResponses.set("lag-old", firstLatest.promise);
    latestResponses.set(
      "lag-new",
      analysisResult("lag-new", "dataset-a", ["new-u1", "new-u2"])
    );

    const { wrapper } = mountView(active);
    await flushPromises();
    await wrapper.get("[data-version-id='lag-new']").trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-test="input-columns"]').text()).toContain("u1");

    firstLatest.resolve(analysisResult("lag-old", "dataset-a", ["old-u1", "old-u2"]));
    await flushPromises();
    expect(wrapper.get('[data-test="source-select"]').attributes("data-selected-version-id")).toBe("lag-new");
    expect(wrapper.get('[data-test="input-columns"]').text()).toContain("u1");
  });

  it("POSTs Analyze with the selected source version, refreshes its status, and exposes no manual version input", async () => {
    const active = dataset("dataset-a");
    const sourceInputs = ["u1", "u2", "u3", "u4"];
    const pendingSource = source("lag-selected", "not_analyzed", 2, sourceInputs);
    const completeSource = source("lag-selected", "complete", 2, sourceInputs);
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [pendingSource], "lag-selected"),
      sourceData("dataset-a", [completeSource], "lag-selected"),
    ]);
    apiMocks.post.mockImplementation((url: string) => {
      if (url === "/preprocessing/collinearity") {
        return Promise.resolve(analysisResult("lag-selected", "dataset-a"));
      }
      return Promise.reject(new Error(`Unexpected POST ${url}`));
    });

    const { wrapper } = mountView(active);
    await flushPromises();
    expect(apiMocks.post).not.toHaveBeenCalled();
    expect(wrapper.find('input[data-test="input-columns"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="input-columns"]').text()).toContain("u4");

    await wrapper.get('[data-test="analyze-button"]').trigger("click");
    await flushPromises();

    expect(apiMocks.post).toHaveBeenCalledWith("/preprocessing/collinearity", {
      version_id: "lag-selected",
      dataset_id: "dataset-a",
      input_columns: sourceInputs,
      correlation_threshold: 0.85,
      vif_threshold: 10,
    });
    expect(sourceCallCounts.get("dataset-a")).toBe(2);
    expect(wrapper.get('[data-test="source-select"]').attributes("data-selected-version-id")).toBe("lag-selected");
    expect(wrapper.text()).toContain("已完成，可恢复");
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);
    expect(wrapper.get('[data-test="correlation-title"]').text()).toBe(
      "Pearson 相关系数矩阵"
    );

    await wrapper.get('[data-test="correlation-mode-spearman"]').trigger("click");
    const options = chartOptions<CorrelationChartOptions>(wrapper, "correlation-chart");
    expect(options.series[0].data).toContainEqual([1, 0, 0.18]);
    expect(apiMocks.post).toHaveBeenCalledTimes(1);
  });

  it("keeps Feature Apply bound to the selected Lag source and its persisted result provenance", async () => {
    const active = { ...dataset("dataset-a"), version_id: "lag-a" };
    const persisted = {
      ...analysisResult("lag-a", "dataset-a"),
      recommendations: [
        { variable: "u1", action: "keep" as const, reason: "stable", related_variables: [] },
        { variable: "u2", action: "drop" as const, reason: "redundant", related_variables: ["u1"] },
      ],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    const sources = sourceData("dataset-a", [source("lag-a", "complete")], "lag-a");
    sourceResponses.set("dataset-a", [sources]);
    const initialLineage = lineageResponse(sources);
    versionResponses.set("dataset-a", [
      initialLineage,
      {
        ...initialLineage,
        active_version_id: "feature-v3",
        nodes: [
          ...initialLineage.nodes,
          {
            id: "feature-v3",
            name: "V3 · 冗余变量剔除",
            tool: "preprocessing.feature_selection",
            parent_version_id: "lag-a",
            created_at: "2026-09-01T03:00:00Z",
            row_count: 120,
            column_count: 2,
            artifact_path: "feature-v3.csv",
          },
        ],
      },
    ]);
    latestResponses.set("lag-a", persisted);
    apiMocks.confirm.mockResolvedValue(true);
    apiMocks.post.mockResolvedValue({
      source_version_id: "lag-a",
      result_version_id: "feature-v3",
      dataset_id: "dataset-a",
      processing_run_id: "feature-run",
      operation: "preprocessing.feature_selection",
      summary: {},
    });

    const { wrapper } = mountView(active);
    await flushPromises();
    expect(wrapper.find("[data-version-id='feature-v3']").exists()).toBe(false);
    await wrapper.get("[data-test='feature-apply-button']").trigger("click");
    await flushPromises();

    expect(apiMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining("u2：redundant"),
      "确认变量筛选",
      { type: "warning", confirmButtonText: "确认生成", cancelButtonText: "取消" }
    );
    expect(apiMocks.post).toHaveBeenCalledWith("/preprocessing/features/apply", expect.objectContaining({
      version_id: "lag-a",
      dataset_id: "dataset-a",
      drop_columns: ["u2"],
      user_confirmed: true,
      recommendation_source: "collinearity_analysis",
    }));
    expect(apiMocks.post).toHaveBeenCalledTimes(1);
    expect(
      apiMocks.post.mock.calls.filter(([url]) => url === "/preprocessing/collinearity")
    ).toHaveLength(0);
    expect(
      apiMocks.get.mock.calls.filter(([url]) => url === "/datasets/dataset-a")
    ).toHaveLength(2);
    expect(versionCallCounts.get("dataset-a")).toBe(2);
    expect(sourceCallCounts.get("dataset-a")).toBe(2);
    expect(wrapper.get("[data-test='source-select']").attributes("data-selected-version-id")).toBe("lag-a");
    const featureNode = wrapper.get("[data-version-id='feature-v3']");
    expect(featureNode.text()).toContain("V3 · 冗余变量剔除");
    expect(featureNode.text()).toContain("已进入后续特征版本");
    expect(featureNode.attributes("aria-disabled")).toBe("true");
    expect(wrapper.get("[data-test='feature-apply-button']").text()).toBe("确认剔除并生成特征选择版本");
  });

  it("reports a post-success lineage refresh failure without misreporting Feature Apply as failed", async () => {
    const active = { ...dataset("dataset-a"), version_id: "lag-a" };
    const persisted = {
      ...analysisResult("lag-a", "dataset-a"),
      recommendations: [
        { variable: "u1", action: "keep" as const, reason: "stable", related_variables: [] },
        { variable: "u2", action: "drop" as const, reason: "redundant", related_variables: ["u1"] },
      ],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", persisted);
    apiMocks.confirm.mockResolvedValue(true);
    apiMocks.post.mockResolvedValue({
      source_version_id: "lag-a",
      result_version_id: "feature-v3",
      dataset_id: "dataset-a",
      processing_run_id: "feature-run",
      operation: "preprocessing.feature_selection",
      summary: {},
    });

    const { wrapper } = mountView(active);
    await flushPromises();
    detailResponses.set("dataset-a", Promise.reject(new Error("refresh unavailable")));

    await wrapper.get("[data-test='feature-apply-button']").trigger("click");
    await flushPromises();

    expect(apiMocks.post).toHaveBeenCalledTimes(1);
    expect(apiMocks.messageSuccess).toHaveBeenCalledWith("已创建变量筛选版本：feature-v3");
    expect(apiMocks.messageError).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain(
      "变量筛选版本已创建，但版本血缘刷新失败：Error: refresh unavailable"
    );
    expect(wrapper.get("[data-test='source-select']").attributes("data-selected-version-id")).toBe("lag-a");
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);
  });

  it("rehydrates a constant formal input as N/A without issuing a new Analyze POST", async () => {
    const active = dataset("dataset-a");
    const sourceInputs = ["u1", "u2", "u3", "u4"];
    const persisted: CollinearityResponse = {
      ...analysisResult("lag-a", "dataset-a"),
      variables: sourceInputs,
      matrix: [
        [1, 0.2, 0.1, null],
        [0.2, 1, 0.3, null],
        [0.1, 0.3, 1, null],
        [null, null, null, null],
      ],
      spearman_matrix: [
        [1, 0.18, 0.08, null],
        [0.18, 1, 0.25, null],
        [0.08, 0.25, 1, null],
        [null, null, null, null],
      ],
      vif_scores: { u1: 1.1, u2: 1.2, u3: 1.3, u4: null },
      recommendations: [
        { variable: "u1", action: "keep", reason: "stable", related_variables: [] },
        { variable: "u2", action: "keep", reason: "stable", related_variables: [] },
        { variable: "u3", action: "keep", reason: "stable", related_variables: [] },
        { variable: "u4", action: "drop", reason: "常量/近常量特征，信息量不足", related_variables: [] },
      ],
      input_diagnostics: [
        ...sourceInputs.slice(0, 3).map((column) => ({
          column,
          status: "analyzable" as const,
          reason: "可参与诊断",
          variance: 1,
        })),
        {
          column: "u4",
          status: "constant_or_near_constant",
          reason: "常量或近常量特征，方差不足。",
          variance: 0,
        },
      ],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete", 2, sourceInputs)], "lag-a"),
    ]);
    latestResponses.set("lag-a", persisted);

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.get('[data-test="input-columns"]').text()).toContain("u4");
    expect(wrapper.get('[data-test="input-qualification"]').text()).toContain("常量 / 近常量 · N/A");
    const heatmap = chartOptions<CorrelationChartOptions>(wrapper, "correlation-chart");
    expect(heatmap.series[0].data).not.toContainEqual([3, 3, 0]);
    expect(heatmap.series[1].data).toContainEqual(
      expect.objectContaining({ value: [3, 3], unavailable: true })
    );
    expect(
      heatmap.tooltip.formatter({
        value: [3, 3],
        data: { unavailable: true, reason: "常量或近常量特征，方差不足。" },
      })
    ).toContain("N/A");

    expect(wrapper.text()).toContain("特征决策检查");
    for (const variable of sourceInputs) {
      expect(wrapper.find(`[data-test="decision-row-${variable}"]`).exists()).toBe(true);
    }
    for (const variable of ["u1", "u2", "u3"]) {
      expect(wrapper.get(`[data-test="decision-action-${variable}"]`).text()).toBe("保留");
      expect(wrapper.get(`[data-test="decision-reason-${variable}"]`).text()).toBe("stable");
    }
    expect(wrapper.get('[data-test="decision-action-u4"]').text()).toBe("建议剔除");
    expect(wrapper.text()).not.toContain("建议删除");
    expect(wrapper.get('[data-test="decision-reason-u4"]').text()).toBe("常量/近常量特征，信息量不足");
    expect(wrapper.get('[data-test="feature-apply-summary"]').text()).toContain("u4");
    expect(wrapper.get('[data-test="feature-apply-summary"]').text()).toContain("常量/近常量特征，信息量不足");
    expect(wrapper.get('[data-test="feature-apply-button"]').text()).toBe("确认剔除并生成特征选择版本");

    await wrapper.get('[data-test="decision-toggle-u1"]').trigger("click");
    const keepDetails = wrapper.get('[data-test="decision-details-u1"]');
    expect(keepDetails.text()).toContain("数据资格");
    expect(keepDetails.text()).toContain("可参与诊断");
    expect(keepDetails.text()).toContain("VIF");
    expect(keepDetails.text()).toContain("1.10");
    expect(keepDetails.text()).toContain("全局诊断");
    expect(keepDetails.text()).toContain("Condition Number = 2.40");
    expect(keepDetails.text()).toContain("系统建议保留");
    expect(keepDetails.text()).toContain("决策原因stable");
    expect(keepDetails.text()).toContain("相关变量无");
    expect(wrapper.get('[data-test="decision-pearson-u1"]').text()).toContain("u1 ↔ u2");
    expect(wrapper.get('[data-test="decision-pearson-u1"]').text()).toContain("0.200");
    expect(wrapper.get('[data-test="decision-spearman-u1"]').text()).toContain("0.180");

    await wrapper.get('[data-test="decision-toggle-u4"]').trigger("click");
    const dropDetails = wrapper.get('[data-test="decision-details-u4"]');
    expect(dropDetails.text()).toContain("常量 / 近常量");
    expect(dropDetails.text()).toContain("常量或近常量特征，方差不足。");
    expect(dropDetails.text()).toContain("系统建议建议剔除");
    expect(dropDetails.text()).toContain("决策原因常量/近常量特征，信息量不足");
    expect(dropDetails.text()).toContain("相关变量无");
    expect(wrapper.get('[data-test="decision-pearson-u4"]').text()).toContain("N/A");
    expect(wrapper.get('[data-test="decision-spearman-u4"]').text()).toContain("N/A");
    expect(dropDetails.text()).toContain("VIFN/A");
    expect(wrapper.get('[data-test="decision-qualification-note-u4"]').text()).toContain(
      "因低方差 / 信息不足被建议剔除，并非由于检测到严重共线性"
    );
    expect(wrapper.text()).not.toContain("u4 是严重共线性特征");
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("localizes the u4 Feature Apply confirmation and does not apply after cancellation", async () => {
    const active = { ...dataset("dataset-a"), input_columns: ["u1", "u4"] };
    const persisted: CollinearityResponse = {
      ...analysisResult("lag-a", "dataset-a", ["u1", "u4"]),
      matrix: [[1, null], [null, null]],
      spearman_matrix: [[1, null], [null, null]],
      vif_scores: { u1: 1.1, u4: null },
      recommendations: [
        { variable: "u1", action: "keep", reason: "输入信息有效", related_variables: [] },
        { variable: "u4", action: "drop", reason: "低方差，信息量不足", related_variables: [] },
      ],
      input_diagnostics: [
        { column: "u1", status: "analyzable", reason: "数值方差充足", variance: 1 },
        { column: "u4", status: "constant_or_near_constant", reason: "无有效激励", variance: 0 },
      ],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete", 2, ["u1", "u4"])], "lag-a"),
    ]);
    latestResponses.set("lag-a", persisted);
    apiMocks.confirm.mockRejectedValueOnce("cancel");

    const { wrapper } = mountView(active);
    await flushPromises();
    await wrapper.get('[data-test="feature-apply-button"]').trigger("click");
    await flushPromises();

    expect(apiMocks.confirm).toHaveBeenCalledWith(
      expect.stringMatching(
        /将在新的特征选择版本中剔除：[\s\S]*u4：低方差，信息量不足[\s\S]*源版本不会被覆盖。[\s\S]*确认继续生成新的特征选择版本吗？/
      ),
      "确认变量筛选",
      { type: "warning", confirmButtonText: "确认生成", cancelButtonText: "取消" }
    );
    expect(apiMocks.post).not.toHaveBeenCalledWith(
      "/preprocessing/features/apply",
      expect.anything()
    );
  });

  it("keeps formal inputs visible when recommendations are missing", async () => {
    const active = dataset("dataset-a");
    const persisted = {
      ...analysisResult("lag-a", "dataset-a"),
      recommendations: [],
    };
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", persisted);

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.find('[data-test="decision-row-u1"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="decision-row-u2"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="decision-action-u2"]').text()).toBe("未提供");
    expect(wrapper.get('[data-test="decision-reason-u2"]').text()).toBe(
      "当前结果未提供该变量的决策建议。"
    );
    expect(wrapper.get('[data-test="decision-recommendations-empty"]').text()).toContain(
      "当前结果未提供特征决策建议。"
    );
    expect(wrapper.find('[data-test="feature-apply-button"]').exists()).toBe(false);
  });
});
