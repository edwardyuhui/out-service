import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import DelayView from "../../src/views/DelayView.vue";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type { DatasetItem, DelayResponse } from "../../src/types/api";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return { ...actual, default: { get: api.get, post: api.post, delete: vi.fn() } };
});

vi.mock("element-plus", () => ({
  ElMessage: { success: api.success, error: api.error },
  ElMessageBox: { confirm: api.confirm },
}));

const ElInputNumberStub = defineComponent({
  name: "ElInputNumber",
  inheritAttrs: false,
  props: { modelValue: { type: Number, default: null }, disabled: Boolean, loading: Boolean },
  emits: ["update:modelValue"],
  setup(props, { attrs, emit }) {
    return () =>
      h("input", {
        ...attrs,
        type: "number",
        value: props.modelValue ?? "",
        disabled: props.disabled,
        onInput: (event: Event) => {
          const value = (event.target as HTMLInputElement).value;
          emit("update:modelValue", value === "" ? null : Number(value));
        },
      });
  },
});

const ElButtonStub = defineComponent({
  name: "ElButton",
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean, type: String },
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

const ElSelectStub = defineComponent({
  name: "ElSelect",
  inheritAttrs: false,
  props: { modelValue: String, disabled: Boolean },
  setup(props, { attrs, slots }) {
    return () =>
      h(
        "div",
        {
          ...attrs,
          role: "combobox",
          "aria-disabled": String(props.disabled),
          "data-model-value": props.modelValue ?? "",
        },
        slots.default?.()
      );
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
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

const stubs = {
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": {
    props: ["label"],
    template: "<label><slot name='label'>{{ label }}</slot><slot /></label>",
  },
  "el-select": ElSelectStub,
  "el-option": ElOptionStub,
  "el-popover": ElPopoverStub,
  "el-input": {
    props: ["modelValue"],
    emits: ["update:modelValue"],
    template: "<input :value='modelValue' @input='$emit(\"update:modelValue\", $event.target.value)' />",
  },
  "el-input-number": ElInputNumberStub,
  "el-button": ElButtonStub,
  "el-alert": { template: "<div><slot name='title' /><slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  ChartContainer: { props: ["options", "height"], template: "<div class='chart-stub' />" },
  Timer: true,
  Search: true,
  DataLine: true,
  ArrowDown: true,
};

const cleanVersionId = "2eb39a88-1111-4222-8333-44445555f9bd";
const lagVersionId = "f7b9b88c-d7ba-4c09-bc81-980a2dc01c35";

const activeDataset: DatasetItem = {
  id: "dataset-hitl",
  name: "accept_collinearity_phase2",
  version_id: lagVersionId,
  latest_version_id: lagVersionId,
  file_size_bytes: 100,
  row_count: 1200,
  col_count: 5,
  created_at: "2026-09-03T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2", "u3"],
  output_column: "y",
};

const delayResult = (uncertainColumns = ["u2", "u3"]): DelayResponse => ({
  source_version_id: cleanVersionId,
  processing_run_id: "delay-run-1",
  dataset_id: "dataset-hitl",
  task: { task_id: "task-1", status: "completed", stage: "completed", progress: 1 },
  delays: [3, 8, 6],
  correlations: { u1: [0, 0.1, 0.3, 0.8], u2: [0, 0.2, 0.5, 0.7], u3: [0, 0.1, 0.4, 0.6] },
  best_delays: { u1: 3, u2: 8, u3: 6 },
  candidate_peaks: { u1: [], u2: [], u3: [] },
  validation_fit: 34.8,
  refinement_rounds: 2,
  uncertain_columns: uncertainColumns,
  prewhitening_orders: { u1: 4, u2: 3, u3: 2 },
});

const installApi = (persisted = delayResult(), sourceInputs = ["u1", "u2", "u3"]) => {
  api.get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
    if (url === "/datasets/dataset-hitl/versions") {
      return Promise.resolve({
        dataset_id: "dataset-hitl",
        active_version_id: lagVersionId,
        nodes: [
          {
            id: "raw-v0",
            name: "V0 · 仿真原始数据",
            tool: "simulation_generate",
            parent_version_id: null,
            created_at: "2026-09-03T10:00:00",
            row_count: 1200,
            column_count: 5,
            artifact_path: "raw.csv",
          },
          {
            id: cleanVersionId,
            name: "V1 · 清洗规整",
            tool: "preprocessing.clean",
            parent_version_id: "raw-v0",
            created_at: "2026-09-03T10:20:00",
            row_count: 1200,
            column_count: 5,
            artifact_path: "clean.csv",
          },
          {
            id: lagVersionId,
            name: "V2 · 时滞补偿",
            tool: "preprocessing.lag_compensation",
            parent_version_id: cleanVersionId,
            created_at: "2026-09-03T10:30:00",
            row_count: 1191,
            column_count: 5,
            artifact_path: "lag.csv",
          },
        ],
      });
    }
    if (url === "/datasets/dataset-hitl/delay-sources") {
      return Promise.resolve({
        dataset_id: "dataset-hitl",
        default_source_version_id: cleanVersionId,
        sources: [
          {
            version_id: cleanVersionId,
            version_index: 1,
            name: "V1 · 清洗规整",
            operation_name: "preprocessing.clean",
            parent_version_id: "raw-v0",
            created_at: "2026-09-03T10:20:00",
            input_columns: sourceInputs,
            delay_status: "complete",
            latest_complete_delay_run_id: "delay-run-1",
          },
        ],
      });
    }
    if (url === "/preprocessing/delay/latest") {
      expect(config?.params).toEqual({ version_id: cleanVersionId, dataset_id: "dataset-hitl" });
      return Promise.resolve(persisted);
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  api.post.mockImplementation((url: string) => {
    if (url === "/preprocessing/delay/apply") {
      return Promise.resolve({
        source_version_id: cleanVersionId,
        result_version_id: "lag-v2",
        dataset_id: "dataset-hitl",
        processing_run_id: "lag-run-1",
        operation: "preprocessing.lag_compensation",
        summary: {},
      });
    }
    return Promise.reject(new Error(`Unexpected POST ${url}`));
  });
};

const mountView = async (persisted = delayResult(), sourceInputs = ["u1", "u2", "u3"]) => {
  const pinia = createPinia();
  setActivePinia(pinia);
  useDatasetStore().setActiveDataset(activeDataset);
  installApi(persisted, sourceInputs);
  const wrapper = mount(DelayView, { global: { plugins: [pinia], stubs, mocks: { $router: { push: vi.fn() } } } });
  await flushPromises();
  return wrapper;
};

const applyButton = (wrapper: Awaited<ReturnType<typeof mountView>>) =>
  wrapper.get<HTMLButtonElement>("[data-test='apply-delay-button']");

describe("DelayView UNCERTAIN HITL review and formal Apply", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.confirm.mockResolvedValue(true);
  });

  it("shows the complete lineage while keeping only Cleaning eligible and defaults away from active Lag", async () => {
    const wrapper = await mountView();

    expect(wrapper.get("[data-test='delay-source-label']").text()).toBe("可用时滞源版本");
    expect(wrapper.get("[data-test='delay-source-helper']").text()).toBe(
      "完整版本血缘可见；仅清洗规整版本可进入时滞分析。"
    );

    const lineageNodes = wrapper.findAll("[data-test='lineage-node']");
    expect(lineageNodes).toHaveLength(3);
    expect(lineageNodes[0]?.text()).toContain("V0 · 仿真原始数据");
    expect(lineageNodes[0]?.attributes("aria-disabled")).toBe("true");
    expect(lineageNodes[1]?.text()).toContain("V1 · 清洗规整");
    expect(lineageNodes[1]?.text()).toContain("可用于时滞分析");
    expect(lineageNodes[1]?.attributes("aria-disabled")).toBe("false");
    expect(lineageNodes[2]?.text()).toContain("V2 · 时滞补偿");
    expect(lineageNodes[2]?.attributes("aria-disabled")).toBe("true");

    const currentSource = wrapper.get("[data-test='current-delay-source']");
    expect(currentSource.text()).toContain("当前分析源");
    expect(currentSource.text()).toContain("Delay 状态");
    expect(currentSource.text()).toContain("版本 ID");
    expect(currentSource.text()).toContain("创建时间");
    expect(currentSource.text()).toContain("2eb39a88…f9bd");
    expect(currentSource.text()).toContain("已完成 · 可恢复");
    expect(currentSource.text()).not.toContain("来源 V0");
  });

  it("keeps parameters on the left and groups Spectrum with result cards in the right analysis column", async () => {
    const wrapper = await mountView();
    const primaryWorkspace = wrapper.get("[data-test='delay-primary-workspace']");
    const parametersColumn = wrapper.get("[data-test='delay-parameters-column']");
    const analysisColumn = wrapper.get("[data-test='delay-analysis-column']");
    const spectrumCard = wrapper.get("[data-test='delay-spectrum-card']");
    const resultsSection = wrapper.get("[data-test='delay-results-section']");
    const parametersCard = wrapper.get("[data-test='delay-parameters-card']");
    const prewhiteningNote = wrapper.get("[data-test='prewhitening-note']");
    const hitlReview = wrapper.get("[data-test='delay-hitl-review']");
    const applyStrip = wrapper.get("[data-test='delay-apply-strip']");
    const pageSections = Array.from(wrapper.get(".delay-view").element.children);

    expect(primaryWorkspace.find("[data-test='delay-parameters-column']").exists()).toBe(true);
    expect(primaryWorkspace.find("[data-test='delay-analysis-column']").exists()).toBe(true);
    expect(analysisColumn.find("[data-test='delay-spectrum-card']").exists()).toBe(true);
    expect(analysisColumn.find("[data-test='delay-results-section']").exists()).toBe(true);
    expect(resultsSection.element.closest("[data-test='delay-primary-workspace']")).toBe(primaryWorkspace.element);
    expect(resultsSection.element.closest("[data-test='delay-spectrum-card']")).toBeNull();
    expect(spectrumCard.element.parentElement).toBe(analysisColumn.element);
    expect(resultsSection.element.parentElement).toBe(analysisColumn.element);
    expect(parametersCard.element.closest("[data-test='delay-parameters-column']")).toBe(parametersColumn.element);
    expect(prewhiteningNote.element.closest("[data-test='delay-parameters-card']")).toBe(parametersCard.element);
    expect(pageSections.indexOf(primaryWorkspace.element)).toBeLessThan(pageSections.indexOf(hitlReview.element));
    expect(pageSections.indexOf(hitlReview.element)).toBeLessThan(pageSections.indexOf(applyStrip.element));
  });

  it("rehydrates the real persisted result without automatically re-running Delay Analyze", async () => {
    const wrapper = await mountView();

    expect(wrapper.get("[data-test='delay-hitl-review']").text()).toContain("时滞参数复核");
    expect(wrapper.get("[data-test='final-lag-u2']").element.value).toBe("8");
    expect(applyButton(wrapper).element.disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("does not treat a default UNCERTAIN recommendation as human confirmation", async () => {
    const wrapper = await mountView();

    expect(wrapper.get("[data-test='lag-source-u2']").text()).toBe("待人工复核");
    expect(wrapper.get("[data-test='review-lag-u2']").text()).toContain("确认采用该值");
    expect(applyButton(wrapper).element.disabled).toBe(true);
  });

  it("enables Apply only after every UNCERTAIN channel is explicitly reviewed", async () => {
    const wrapper = await mountView();
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    expect(applyButton(wrapper).element.disabled).toBe(true);

    await wrapper.get("[data-test='review-lag-u3']").trigger("click");
    expect(applyButton(wrapper).element.disabled).toBe(false);
  });

  it("uses the reviewed final lag map and records manual review provenance in the formal payload", async () => {
    const wrapper = await mountView();
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='final-lag-u3']").setValue("5");
    await wrapper.get("[data-test='review-lag-u3']").trigger("click");
    await applyButton(wrapper).trigger("click");
    await flushPromises();

    expect(api.confirm).toHaveBeenCalledWith(
      expect.stringContaining("源版本不会被覆盖。是否继续？"),
      "确认时滞补偿",
      { type: "warning", confirmButtonText: "确认生成", cancelButtonText: "取消" }
    );
    expect(api.post).toHaveBeenCalledWith("/preprocessing/delay/apply", {
      version_id: cleanVersionId,
      dataset_id: "dataset-hitl",
      lag_map: { u1: 3, u2: 8, u3: 5 },
      user_confirmed: true,
      recommendation_source: "manual",
      evidence_summary: {
        u1: "Delay Analyze validation-refined recommendation = 3; algorithm confirmed.",
        u2: "UNCERTAIN; human reviewed and adopted Delay Analyze validation-refined recommendation = 8.",
        u3: "UNCERTAIN; human override: Delay Analyze validation-refined recommendation = 6; adopted = 5.",
      },
    });
    expect(wrapper.get("[data-test='lag-source-u3']").text()).toBe("人工覆盖");
    expect(wrapper.get("[data-test='apply-success']").text()).toContain("lag-v2");
  });

  it("uses delay_analysis only when all channels are confirmed and preserves their recommendations", async () => {
    const wrapper = await mountView(delayResult([]));
    expect(applyButton(wrapper).element.disabled).toBe(false);

    await applyButton(wrapper).trigger("click");
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith(
      "/preprocessing/delay/apply",
      expect.objectContaining({
        lag_map: { u1: 3, u2: 8, u3: 6 },
        recommendation_source: "delay_analysis",
      })
    );
  });

  it.each([-1, 5.5, null])("blocks invalid final lag %s", async (value) => {
    const wrapper = await mountView();
    await wrapper.get("[data-test='final-lag-u2']").setValue(value === null ? "" : String(value));
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='review-lag-u3']").trigger("click");

    expect(applyButton(wrapper).element.disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires a new review after an UNCERTAIN value changes", async () => {
    const wrapper = await mountView();
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='final-lag-u2']").setValue("7");

    expect(wrapper.get("[data-test='lag-source-u2']").text()).toBe("待人工复核");
    expect(applyButton(wrapper).element.disabled).toBe(true);
  });

  it("prevents duplicate Apply requests while the formal request is in flight", async () => {
    const wrapper = await mountView();
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='review-lag-u3']").trigger("click");
    let resolveApply!: (value: Record<string, unknown>) => void;
    api.post.mockImplementation(
      (url: string) =>
        url === "/preprocessing/delay/apply"
          ? new Promise((resolve) => {
              resolveApply = resolve;
            })
          : Promise.reject(new Error(`Unexpected POST ${url}`))
    );

    const first = applyButton(wrapper).trigger("click");
    const second = applyButton(wrapper).trigger("click");
    await flushPromises();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(applyButton(wrapper).attributes("data-loading")).toBe("true");

    resolveApply({
      source_version_id: cleanVersionId,
      result_version_id: "lag-v2",
      dataset_id: "dataset-hitl",
      processing_run_id: "lag-run-1",
      operation: "preprocessing.lag_compensation",
      summary: {},
    });
    await Promise.all([first, second]);
    await flushPromises();
    expect(wrapper.get("[data-test='apply-success']").text()).toContain("lag-v2");
  });

  it("shows an unestimated source input with its explicit no-compensation system recommendation", async () => {
    const wrapper = await mountView(delayResult(), ["u1", "u2", "u3", "u4"]);

    expect(wrapper.get("[data-test='final-lag-u4']").element.value).toBe("0");
    expect(wrapper.text()).toContain("UNAVAILABLE · 无可靠估计");
    expect(wrapper.get("[data-test='lag-source-u4']").text()).toBe("系统建议 · 暂不补偿");
    expect(applyButton(wrapper).element.disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires explicit review before applying the zero no-compensation system recommendation", async () => {
    const wrapper = await mountView(delayResult(), ["u1", "u2", "u3", "u4"]);
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='review-lag-u3']").trigger("click");
    expect(applyButton(wrapper).element.disabled).toBe(true);

    await wrapper.get("[data-test='review-lag-u4']").trigger("click");
    expect(wrapper.get("[data-test='lag-source-u4']").text()).toBe("人工确认系统建议（暂不补偿）");
    expect(applyButton(wrapper).element.disabled).toBe(false);

    await applyButton(wrapper).trigger("click");
    await flushPromises();
    expect(api.post).toHaveBeenCalledWith(
      "/preprocessing/delay/apply",
      expect.objectContaining({
        lag_map: { u1: 3, u2: 8, u3: 6, u4: 0 },
        recommendation_source: "manual",
        evidence_summary: expect.objectContaining({
          u4: "No reliable Delay Analyze recommendation; system recommendation = 0 (no compensation); user confirmed system recommendation.",
        }),
      })
    );
  });

  it.each([-1, 5.5, null])("blocks invalid manually specified lag %s for an unestimated input", async (value) => {
    const wrapper = await mountView(delayResult(), ["u1", "u2", "u3", "u4"]);
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='review-lag-u3']").trigger("click");
    await wrapper.get("[data-test='final-lag-u4']").setValue(value === null ? "" : String(value));
    await wrapper.get("[data-test='review-lag-u4']").trigger("click");

    expect(applyButton(wrapper).element.disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires review of the human-specified lag and submits it with distinct evidence", async () => {
    const wrapper = await mountView(delayResult(), ["u1", "u2", "u3", "u4"]);
    await wrapper.get("[data-test='review-lag-u2']").trigger("click");
    await wrapper.get("[data-test='final-lag-u3']").setValue("5");
    await wrapper.get("[data-test='review-lag-u3']").trigger("click");
    await wrapper.get("[data-test='final-lag-u4']").setValue("11");
    expect(applyButton(wrapper).element.disabled).toBe(true);
    expect(wrapper.get("[data-test='lag-source-u4']").text()).toBe("待人工复核（将覆盖系统建议 0）");
    await wrapper.get("[data-test='review-lag-u4']").trigger("click");
    expect(applyButton(wrapper).element.disabled).toBe(false);

    await applyButton(wrapper).trigger("click");
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith(
      "/preprocessing/delay/apply",
      expect.objectContaining({
        lag_map: { u1: 3, u2: 8, u3: 5, u4: 11 },
        recommendation_source: "manual",
        evidence_summary: expect.objectContaining({
          u2: "UNCERTAIN; human reviewed and adopted Delay Analyze validation-refined recommendation = 8.",
          u3: "UNCERTAIN; human override: Delay Analyze validation-refined recommendation = 6; adopted = 5.",
          u4: "No reliable Delay Analyze recommendation; system recommendation = 0; manual override final = 11.",
        }),
      })
    );
    expect(wrapper.get("[data-test='lag-source-u4']").text()).toBe("人工覆盖（原系统建议 0）");
    expect(api.post).toHaveBeenCalledTimes(1);
  });
});
