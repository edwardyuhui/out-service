import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DeliverablesView from "../../src/views/DeliverablesView.vue";
import { getDatasetDetail, getDatasetVersions } from "../../src/api/datasets";
import { getDeliveryStudies } from "../../src/api/delivery";

const context = vi.hoisted(() => ({
  query: {} as Record<string, string>,
  store: null as any,
}));

vi.mock("vue-router", () => ({ useRoute: () => ({ query: context.query }) }));
vi.mock("../../src/stores/datasetStore", () => ({
  useDatasetStore: () => context.store,
}));
vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetVersions: vi.fn(),
}));
vi.mock("../../src/api/delivery", () => ({
  exportDataset: vi.fn(),
  generateReport: vi.fn(),
  getDeliveryStudies: vi.fn(),
}));
vi.mock("element-plus", () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
}));

const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);
const mockedGetDeliveryStudies = vi.mocked(getDeliveryStudies);

const datasets = [
  {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    name: "同名数据集",
    source: "simulation",
    status: "ready",
    version_id: "a-active",
    latest_version_id: "a-active",
    row_count: 100,
    col_count: 3,
    file_size_bytes: 1000,
    created_at: "2026-09-01T00:00:00Z",
    time_column: "timestamp",
    input_columns: ["u1"],
    output_column: "y",
  },
  {
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    name: "同名数据集",
    source: "upload",
    status: "ready",
    version_id: "b-active",
    latest_version_id: "b-active",
    row_count: 200,
    col_count: 3,
    file_size_bytes: 2000,
    created_at: "2026-09-02T00:00:00Z",
    time_column: "timestamp",
    input_columns: ["u1"],
    output_column: "y",
  },
] as any[];

const versionNode = (id: string) => ({
  id,
  name: id,
  tool: "simulation_generate",
  parent_version_id: null,
  created_at: "2026-09-01T00:00:00Z",
  row_count: 100,
  column_count: 3,
  artifact_path: `${id}.csv`,
  input_columns: ["u1"],
  output_column: "y",
});

const study = (studyId: string, datasetId: string, versionId: string) => ({
  study_id: studyId,
  dataset_id: datasetId,
  version_id: versionId,
  finished_at: "2026-09-03T00:00:00Z",
  best_trial_number: 3,
  best_value: 88,
  optimized_model_id: `model-${studyId}`,
  input_columns: ["u1"],
  output_column: "y",
});

const stubs = {
  PageHeader: true,
  VersionLineagePicker: true,
  ExportDownloadActions: true,
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<label>{{ label }}<slot /></label>" },
  "el-select": { template: "<div><slot /></div>" },
  "el-option": { props: ["label"], template: "<span>{{ label }}</span>" },
  "el-button": { template: "<button><slot /></button>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-descriptions": { template: "<div><slot /></div>" },
  "el-descriptions-item": { props: ["label"], template: "<div>{{ label }}<slot /></div>" },
  "el-table": { template: "<div><slot /></div>" },
  "el-table-column": true,
  Document: true,
  Download: true,
  Finished: true,
  Printer: true,
};

const mountView = async () => {
  const wrapper = mount(DeliverablesView, { global: { stubs } });
  await flushPromises();
  return wrapper;
};

describe("DeliverablesView scoped selectors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    context.query = {};
    context.store = {
      datasetsList: datasets,
      activeDataset: null,
      ensureDatasetNamesLoaded: vi.fn().mockResolvedValue(undefined),
      setActiveDataset: vi.fn(),
    };
    mockedGetDatasetDetail.mockImplementation(async (id) =>
      datasets.find((item) => item.id === id) as never
    );
    mockedGetDatasetVersions.mockImplementation(async (id) => ({
      dataset_id: id,
      active_version_id: id.startsWith("a") ? "a-active" : "b-active",
      nodes: id.startsWith("a")
        ? [versionNode("a-active"), versionNode("a-history")]
        : [versionNode("b-active"), versionNode("b-history")],
      edges: [],
    }));
  });

  it("does not silently choose the first dataset without a legal context", async () => {
    const wrapper = await mountView();

    expect(mockedGetDatasetDetail).not.toHaveBeenCalled();
    expect((wrapper.vm as any).selectedDatasetId).toBeNull();
  });

  it("uses active_version_id and ignores a stale A response after switching to B", async () => {
    let resolveA!: (value: any) => void;
    let resolveB!: (value: any) => void;
    mockedGetDeliveryStudies.mockImplementation((datasetId, versionId) =>
      new Promise((resolve) => {
        if (datasetId.startsWith("a")) resolveA = resolve;
        else resolveB = resolve;
      }) as never
    );
    const wrapper = await mountView();
    const vm = wrapper.vm as any;

    const pendingA = vm.handleDatasetChange(datasets[0].id);
    await flushPromises();
    const pendingB = vm.handleDatasetChange(datasets[1].id);
    await flushPromises();
    resolveB({
      dataset_id: datasets[1].id,
      version_id: "b-active",
      items: [study("study-b", datasets[1].id, "b-active")],
    });
    await pendingB;
    resolveA({
      dataset_id: datasets[0].id,
      version_id: "a-active",
      items: [study("study-a", datasets[0].id, "a-active")],
    });
    await pendingA;

    expect(vm.selectedDatasetId).toBe(datasets[1].id);
    expect(vm.selectedVersionId).toBe("b-active");
    expect(vm.selectedStudyId).toBe("study-b");
  });

  it("clears the old Study immediately when a historical version is selected", async () => {
    mockedGetDeliveryStudies.mockResolvedValue({
      dataset_id: datasets[1].id,
      version_id: "b-active",
      items: [study("study-b", datasets[1].id, "b-active")],
    });
    const wrapper = await mountView();
    const vm = wrapper.vm as any;
    await vm.handleDatasetChange(datasets[1].id);
    expect(vm.selectedStudyId).toBe("study-b");

    let resolveHistory!: (value: any) => void;
    mockedGetDeliveryStudies.mockImplementationOnce(
      () => new Promise((resolve) => { resolveHistory = resolve; }) as never
    );
    vm.handleVersionChange("b-history");
    expect(vm.selectedStudyId).toBeNull();
    resolveHistory({
      dataset_id: datasets[1].id,
      version_id: "b-history",
      items: [study("study-history", datasets[1].id, "b-history")],
    });
    await flushPromises();
    expect(vm.selectedStudyId).toBe("study-history");
  });

  it("disambiguates duplicate names without displaying a full UUID", async () => {
    const wrapper = await mountView();
    const label = (wrapper.vm as any).datasetOptionLabel(datasets[0]);

    expect(label).toContain("aaaaaaaa");
    expect(label).not.toContain(datasets[0].id);
  });
});
