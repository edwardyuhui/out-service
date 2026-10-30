import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import AgentComposer from "../../src/components/composer/AgentComposer.vue";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type { DatasetItem } from "../../src/types/api";

const listDatasetsApi = vi.hoisted(() => vi.fn());
const getDatasetVersionsApi = vi.hoisted(() => vi.fn());
const messageApi = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn() }));

vi.mock("../../src/api/datasets", () => ({
  listDatasets: listDatasetsApi,
  getDatasetVersions: getDatasetVersionsApi,
}));

vi.mock("../../src/components/versioning/VersionLineagePicker.vue", () => ({
  default: {
    name: "VersionLineagePicker",
    props: ["selectedVersionId", "versions", "loading"],
    emits: ["select"],
    template: '<div class="lineage-stub" />',
  },
}));

const versionResponse = (datasetId: string) => ({
  dataset_id: datasetId,
  active_version_id: `${datasetId}-v0`,
  nodes: [0, 1].map(index => ({
    id: `${datasetId}-v${index}`,
    name: `V${index}`,
    tool: index ? "cleaning" : "simulation_generate",
    parent_version_id: index ? `${datasetId}-v0` : null,
    created_at: "2026-09-01T00:00:00Z",
    row_count: 1000,
    column_count: 4,
    artifact_path: `data/${datasetId}-v${index}.csv`,
  })),
});

vi.mock("element-plus", () => ({
  ElMessage: messageApi,
}));

const makeDataset = (index: number): DatasetItem => ({
  id: `dataset-${index}`,
  name: `数据集 ${index}`,
  version_id: `version-${index}`,
  file_size_bytes: 100,
  row_count: 1000 + index,
  col_count: 4,
  created_at: "2026-09-01T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2"],
  output_column: "y",
});

const rect = (values: Partial<DOMRect>): DOMRect =>
  ({
    x: values.left ?? 0,
    y: values.top ?? 0,
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    toJSON: () => ({}),
    ...values,
  }) as DOMRect;

describe("AgentComposer dataset picker viewport positioning", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getDatasetVersionsApi.mockReset();
    getDatasetVersionsApi.mockImplementation(async id => versionResponse(id));
    setActivePinia(createPinia());
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 800 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 600 });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: undefined });
    listDatasetsApi.mockResolvedValue({
      items: Array.from({ length: 40 }, (_, index) => makeDataset(index + 1)),
    });
  });

  it("preserves an explicitly active dataset without loading a default", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useDatasetStore().setActiveDataset(makeDataset(7));

    const wrapper = mount(AgentComposer, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(wrapper.get(".attachment-name").text()).toBe("数据集 7");
    expect(listDatasetsApi).not.toHaveBeenCalled();
  });

  it("does not silently attach the first dataset on mount", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });
    await flushPromises();

    expect(wrapper.find(".composer-attachments").exists()).toBe(false);
    expect(listDatasetsApi).not.toHaveBeenCalled();
  });

  it("defaults to the formal active version and submits an explicitly selected historical version", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useDatasetStore().setActiveDataset(makeDataset(7));
    const wrapper = mount(AgentComposer, { global: { plugins: [pinia] } });
    await flushPromises();
    const picker = wrapper.getComponent({ name: "VersionLineagePicker" });
    expect(picker.props("selectedVersionId")).toBe("dataset-7-v0");
    picker.vm.$emit("select", "foreign-version");
    await wrapper.vm.$nextTick();
    expect(picker.props("selectedVersionId")).toBe("dataset-7-v0");
    picker.vm.$emit("select", "dataset-7-v1");
    await wrapper.get(".composer-textarea").setValue("分析数据");
    expect(wrapper.get(".attachment-version").text()).toContain("V1");
    await wrapper.get(".composer-submit").trigger("click");
    expect(wrapper.emitted("submit")?.[0]).toEqual([{
      message: "分析数据", datasetId: "dataset-7", versionId: "dataset-7-v1",
    }]);
    expect(useDatasetStore().activeDataset?.version_id).toBe("version-7");
    wrapper.unmount();
  });

  it("discards a previous dataset response and blocks submission while versions load", async () => {
    let resolveOld!: (value: ReturnType<typeof versionResponse>) => void;
    getDatasetVersionsApi.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const pinia = createPinia();
    setActivePinia(pinia);
    useDatasetStore().setActiveDataset(makeDataset(7));
    const wrapper = mount(AgentComposer, { global: { plugins: [pinia] } });
    await wrapper.get(".composer-textarea").setValue("分析数据");
    expect(wrapper.get(".composer-submit").attributes("disabled")).toBeDefined();
    await wrapper.get(".composer-btn--dataset").trigger("click");
    await flushPromises();
    await wrapper.get(".dataset-picker__item").trigger("click");
    await flushPromises();
    resolveOld(versionResponse("dataset-7"));
    await flushPromises();
    expect(wrapper.getComponent({ name: "VersionLineagePicker" }).props("selectedVersionId"))
      .toBe("dataset-1-v0");
    await wrapper.get(".composer-submit").trigger("click");
    expect(wrapper.emitted("submit")?.[0]).toEqual([{
      message: "分析数据", datasetId: "dataset-1", versionId: "dataset-1-v0",
    }]);
    wrapper.unmount();
  });

  it("blocks missing active versions and lets a failed load be retried", async () => {
    getDatasetVersionsApi.mockRejectedValueOnce(new Error("unavailable"));
    const pinia = createPinia();
    setActivePinia(pinia);
    useDatasetStore().setActiveDataset(makeDataset(7));
    const wrapper = mount(AgentComposer, { global: { plugins: [pinia] } });
    await flushPromises();
    await wrapper.get(".composer-textarea").setValue("分析数据");
    expect(wrapper.get(".composer-submit").attributes("disabled")).toBeDefined();
    getDatasetVersionsApi.mockResolvedValueOnce({ ...versionResponse("dataset-7"), active_version_id: null });
    await wrapper.get(".composer-version-error button").trigger("click");
    await flushPromises();
    expect(wrapper.get(".composer-submit").attributes("disabled")).toBeDefined();
    const picker = wrapper.getComponent({ name: "VersionLineagePicker" });
    picker.vm.$emit("select", "dataset-7-v0");
    await wrapper.vm.$nextTick();
    expect(wrapper.get(".composer-submit").attributes("disabled")).toBeUndefined();
    await wrapper.get(".attachment-remove").trigger("click");
    expect(wrapper.find(".lineage-stub").exists()).toBe(false);
    wrapper.unmount();
  });

  it("loads datasets only after the picker is opened and allows an explicit choice", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });

    await wrapper.get(".composer-btn--dataset").trigger("click");
    await flushPromises();
    expect(listDatasetsApi).toHaveBeenCalledWith({ page: 1, page_size: 50 });

    await wrapper.get(".dataset-picker__item").trigger("click");
    expect(wrapper.get(".attachment-name").text()).toBe("数据集 1");
    expect(useDatasetStore().activeDataset?.id).toBe("dataset-1");
  });

  it("warns and does not submit when no dataset is attached", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });
    await wrapper.get(".composer-textarea").setValue("建立 ARX 模型");

    await wrapper.get(".composer-submit").trigger("click");

    expect(messageApi.warning).toHaveBeenCalledOnce();
    expect(wrapper.emitted("submit")).toBeUndefined();
  });

  it("keeps the whole composer non-submittable while the parent request is pending", async () => {
    const wrapper = mount(AgentComposer, {
      props: { submitting: true },
      global: { plugins: [createPinia()] },
    });

    expect(wrapper.get(".composer-textarea").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".composer-btn--dataset").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".composer-submit").attributes("disabled")).toBeDefined();
    expect(wrapper.find(".composer-submit .spin").exists()).toBe(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("chooses the safer side, clamps to viewport margins, and keeps a long list internally scrollable", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });
    let composerRect = rect({
      left: -40,
      right: 820,
      width: 860,
      top: 24,
      bottom: 170,
      height: 146,
    });
    vi.spyOn(
      wrapper.get<HTMLElement>(".agent-composer").element,
      "getBoundingClientRect"
    ).mockImplementation(() => composerRect);

    await wrapper.get(".composer-btn--dataset").trigger("click");
    await flushPromises();

    const picker = wrapper.get<HTMLElement>(".dataset-picker");
    expect(picker.classes()).toContain("is-positioned");
    expect(picker.element.style.top).toBe("178px");
    expect(picker.element.style.bottom).toBe("auto");
    expect(picker.element.style.left).toBe("12px");
    expect(picker.element.style.width).toBe("776px");
    expect(picker.element.style.maxHeight).toBe("288px");

    composerRect = rect({
      left: 20,
      right: 780,
      width: 760,
      top: 460,
      bottom: 580,
      height: 120,
    });
    window.dispatchEvent(new Event("scroll"));
    await wrapper.vm.$nextTick();

    expect(picker.element.style.top).toBe("auto");
    expect(picker.element.style.bottom).toBe("148px");
    expect(picker.element.style.maxHeight).toBe("288px");

    Object.defineProperty(window, "innerHeight", { configurable: true, value: 360 });
    composerRect = rect({
      left: 20,
      right: 780,
      width: 760,
      top: 160,
      bottom: 260,
      height: 100,
    });
    window.dispatchEvent(new Event("resize"));
    await wrapper.vm.$nextTick();

    expect(picker.element.style.bottom).toBe("208px");
    expect(picker.element.style.maxHeight).toBe("140px");
    expect(wrapper.findAll(".dataset-picker__item")).toHaveLength(40);

    wrapper.unmount();
  });
});
