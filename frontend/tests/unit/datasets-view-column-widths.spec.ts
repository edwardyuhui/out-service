import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DatasetsView from "../../src/views/DatasetsView.vue";
import { getDatasets } from "../../src/api/datasets";

const context = vi.hoisted(() => ({
  store: {
    setDatasetsList: vi.fn(),
    setActiveDataset: vi.fn(),
  },
  push: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: context.push }),
}));
vi.mock("../../src/stores/datasetStore", () => ({
  useDatasetStore: () => context.store,
}));
vi.mock("../../src/api/datasets", () => ({
  getDatasets: vi.fn(),
  deleteDataset: vi.fn(),
  uploadDataset: vi.fn(),
  configureDataset: vi.fn(),
}));
vi.mock("element-plus", async (importOriginal) => {
  const original = await importOriginal<typeof import("element-plus")>();
  return {
    ...original,
    ElMessage: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
  };
});

const STORAGE_KEY = "indusopt.dataset-table.column-widths.v1";
const doLayout = vi.fn();

const ElTableStub = defineComponent({
  name: "ElTable",
  props: {
    data: { type: Array, default: () => [] },
    border: Boolean,
    stripe: Boolean,
  },
  emits: ["header-dragend"],
  setup(_props, { expose, slots }) {
    expose({ doLayout });
    return () => h("div", { class: "el-table-stub" }, slots.default?.());
  },
});

const ElTableColumnStub = defineComponent({
  name: "ElTableColumn",
  props: {
    columnKey: String,
    label: String,
    prop: String,
    width: [Number, String],
    minWidth: [Number, String],
    fixed: [Boolean, String],
    resizable: { type: Boolean, default: true },
    showOverflowTooltip: Boolean,
  },
  setup(props) {
    return () => h("div", { "data-column-key": props.columnKey });
  },
});

const stubs = {
  PageHeader: true,
  AppEmptyState: true,
  "el-table": ElTableStub,
  "el-table-column": ElTableColumnStub,
  "el-upload": { template: "<div><slot /><slot name='tip' /></div>" },
  "el-button": { template: "<button @click='$emit(\"click\")'><slot /></button>" },
  "el-dialog": { template: "<div><slot /><slot name='footer' /></div>" },
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { template: "<label><slot /></label>" },
  "el-input": true,
  "el-tag": { template: "<span><slot /></span>" },
  "el-tooltip": { template: "<span><slot /></span>" },
  "el-icon": { template: "<span><slot /></span>" },
  Upload: true,
  List: true,
  UploadFilled: true,
};

const mockedGetDatasets = vi.mocked(getDatasets);

const mountView = async () => {
  const wrapper = mount(DatasetsView, {
    global: {
      stubs,
      directives: { loading: () => undefined },
    },
  });
  await flushPromises();
  return wrapper;
};

describe("DatasetsView resizable columns", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    window.localStorage.clear();
    mockedGetDatasets.mockResolvedValue({ items: [] } as never);
  });

  it("uses native bordered columns and keeps the action column fixed and non-resizable", async () => {
    const wrapper = await mountView();
    const table = wrapper.findComponent(ElTableStub);
    const columns = wrapper.findAllComponents(ElTableColumnStub);

    expect(table.props("border")).toBe(true);
    expect(columns).toHaveLength(7);
    expect(columns.slice(0, 6).every((column) => column.props("resizable") === true)).toBe(true);
    expect(columns[6].props("columnKey")).toBe("actions");
    expect(columns[6].props("fixed")).toBe("right");
    expect(columns[6].props("resizable")).toBe(false);
    expect(columns[6].props("width")).toBe(250);
  });

  it("restores only valid persisted widths and falls back per invalid field", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        dataset_name: 420,
        active_version: 200,
        row_count: 20,
        variable_config: 900,
        removed_column: 333,
      }),
    );

    const wrapper = await mountView();
    const widths = (wrapper.vm as any).columnWidths;

    expect(widths.dataset_name).toBe(420);
    expect(widths.active_version).toBe(200);
    expect(widths.row_count).toBe(120);
    expect(widths.variable_config).toBe(280);
    expect(widths.column_count).toBe(105);
  });

  it("clamps one resized column, preserves the others and persists only six widths", async () => {
    const wrapper = await mountView();
    const vm = wrapper.vm as any;
    const column = { columnKey: "dataset_name", width: 900, realWidth: 900 };

    vm.handleColumnResize(900, 250, column);
    await nextTick();

    expect(vm.columnWidths.dataset_name).toBe(520);
    expect(vm.columnWidths.active_version).toBe(150);
    expect(column.width).toBe(520);
    expect(column.realWidth).toBe(520);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!)).toEqual({
      dataset_name: 520,
      active_version: 150,
      row_count: 120,
      column_count: 105,
      time_column: 140,
      variable_config: 280,
    });
    expect(doLayout).toHaveBeenCalled();
  });

  it("resets widths without refetching the dataset list", async () => {
    const wrapper = await mountView();
    const vm = wrapper.vm as any;
    vm.handleColumnResize(
      400,
      250,
      { columnKey: "dataset_name", width: 400, realWidth: 400 },
    );
    await nextTick();
    expect(mockedGetDatasets).toHaveBeenCalledTimes(1);

    const resetButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("恢复默认列宽"));
    expect(resetButton).toBeDefined();
    await resetButton!.trigger("click");
    await nextTick();

    expect(vm.columnWidths).toMatchObject({
      dataset_name: 250,
      active_version: 150,
      row_count: 120,
      column_count: 105,
      time_column: 140,
      variable_config: 280,
    });
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(mockedGetDatasets).toHaveBeenCalledTimes(1);
  });

  it("survives invalid JSON and unavailable browser storage", async () => {
    window.localStorage.setItem(STORAGE_KEY, "not-json");
    const invalidWrapper = await mountView();
    expect((invalidWrapper.vm as any).columnWidths.dataset_name).toBe(250);
    invalidWrapper.unmount();

    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new DOMException("denied");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("denied");
    });
    const deniedWrapper = await mountView();
    const vm = deniedWrapper.vm as any;
    expect(vm.columnWidths.dataset_name).toBe(250);
    expect(() =>
      vm.handleColumnResize(
        360,
        250,
        { columnKey: "dataset_name", width: 360, realWidth: 360 },
      )
    ).not.toThrow();
    expect(vm.columnWidths.dataset_name).toBe(360);
  });
});
