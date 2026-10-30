import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import SimulationView from "../../src/views/SimulationView.vue";
import { generateSimulationDataset } from "../../src/api/simulation";

vi.mock("../../src/api/simulation", () => ({ generateSimulationDataset: vi.fn() }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }));

const stubs = {
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<label>{{ label }}<slot /></label>" },
  "el-radio-group": {
    props: ["modelValue"],
    emits: ["update:modelValue", "change"],
    template: `<div>
      <button type="button" data-test="scenario-s1" @click="$emit('update:modelValue', 'S1'); $emit('change', 'S1')">S1</button>
      <button type="button" data-test="scenario-s2" @click="$emit('update:modelValue', 'S2'); $emit('change', 'S2')">S2</button>
      <button type="button" data-test="scenario-s3" @click="$emit('update:modelValue', 'S3'); $emit('change', 'S3')">S3</button>
      <button type="button" data-test="scenario-s6" @click="$emit('update:modelValue', 'S6'); $emit('change', 'S6')">S6</button>
      <slot />
    </div>`,
  },
  "el-radio-button": { template: "<span><slot /></span>" },
  "el-input": {
    props: ["modelValue"],
    emits: ["update:modelValue", "input"],
    template: `<input data-test="dataset-name" :value="modelValue" @input="$emit('update:modelValue', $event.target.value); $emit('input', $event.target.value)" />`,
  },
  "el-input-number": {
    props: ["modelValue", "min", "max", "step"],
    emits: ["update:modelValue"],
    template: `<input
      type="number"
      :value="modelValue"
      :min="min"
      :max="max"
      :step="step"
      @input="$emit('update:modelValue', Math.min(max, Math.max(min, Number($event.target.value))))"
    />`,
  },
  "el-select": {
    props: ["modelValue", "disabled", "placeholder"],
    emits: ["update:modelValue"],
    template: `<select
      data-test="input-count"
      :value="modelValue ?? ''"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.value === '' ? undefined : Number($event.target.value))"
    >
      <option value="">{{ placeholder }}</option>
      <slot />
    </select>`,
  },
  "el-option": {
    props: ["label", "value"],
    template: `<option :value="value">{{ label }}</option>`,
  },
  "el-slider": true,
  "el-button": { template: "<button type='button'><slot /></button>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-descriptions": { template: "<div><slot /></div>" },
  "el-descriptions-item": { template: "<div><slot /></div>" },
  Setting: true,
  Check: true,
  Download: true,
  Cpu: true,
  View: true,
};

const mountView = () => mount(SimulationView, { global: { plugins: [createPinia()], stubs } });
const datasetNameInput = (wrapper: ReturnType<typeof mountView>) =>
  wrapper.get<HTMLInputElement>('[data-test="dataset-name"]');
const inputCountSelect = (wrapper: ReturnType<typeof mountView>) =>
  wrapper.get<HTMLSelectElement>('[data-test="input-count"]');
const seedInput = (wrapper: ReturnType<typeof mountView>) =>
  wrapper.get<HTMLInputElement>('[data-test="simulation-seed"]');

const simulationResponse = {
  dataset_id: "dataset-1",
  dataset_name: "simulation-data",
  version_id: "version-1",
  scenario: "S6",
  file_path: "simulation.csv",
  ground_truth_path: "ground-truth.json",
  manifest_path: "manifest.json",
  download_url: "/download",
  num_rows: 1500,
  num_cols: 6,
  columns: ["timestamp", "u1", "u2", "u3", "u4", "y"],
  ground_truth: {
    system_type: "MISO_ARX",
    true_na: 2,
    true_nb: [2, 2, 2, 2],
    true_delays: [3, 8, 5, 11],
    true_parameters: {},
    dynamic_segments: [],
    noise_level: 0.03,
    seed: 42,
  },
};

const generateButton = (wrapper: ReturnType<typeof mountView>) =>
  wrapper.findAll("button").find((button) => button.text().includes("生成仿真数据集"))!;

describe("SimulationView scenario dataset names", () => {
  beforeEach(() => vi.clearAllMocks());

  it("starts with the S1 default dataset name", () => {
    const wrapper = mountView();
    expect(datasetNameInput(wrapper).element.value).toBe("S1_Single_Input_Baseline");
  });

  it("updates the default dataset name when switching to S2", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s2"]').trigger("click");
    expect(datasetNameInput(wrapper).element.value).toBe("S2_Multi_Input_Delay");
  });

  it("preserves a manually edited dataset name when switching scenarios", async () => {
    const wrapper = mountView();
    await datasetNameInput(wrapper).setValue("Engineer_Custom_Name");
    await wrapper.get('[data-test="scenario-s3"]').trigger("click");
    expect(datasetNameInput(wrapper).element.value).toBe("Engineer_Custom_Name");
  });
});

describe("SimulationView seed range", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(generateSimulationDataset).mockResolvedValue(simulationResponse);
  });

  it("matches the backend seed bounds and preserves the default seed", () => {
    const wrapper = mountView();
    const input = seedInput(wrapper);

    expect(input.attributes("min")).toBe("0");
    expect(input.attributes("max")).toBe("2147483647");
    expect(input.attributes("step")).toBe("1");
    expect(input.element.value).toBe("42");
  });

  it.each([0, 260903, 20260903, 2147483647])(
    "preserves legal seed %i in the generation request",
    async (seed) => {
      const wrapper = mountView();
      await seedInput(wrapper).setValue(String(seed));
      await generateButton(wrapper).trigger("click");
      await flushPromises();

      expect(seedInput(wrapper).element.value).toBe(String(seed));
      expect(generateSimulationDataset).toHaveBeenCalledWith(
        expect.objectContaining({ seed })
      );
    }
  );
});

describe("SimulationView optional input count", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(generateSimulationDataset).mockResolvedValue(simulationResponse);
  });

  it("renders an initially unselected input count with S1 fixed semantics", () => {
    const wrapper = mountView();

    expect(wrapper.text()).toContain("输入变量数量");
    expect(wrapper.text()).toContain("S1 固定为 1 个输入变量");
    expect(wrapper.text()).not.toContain("可选；留空时使用系统默认值（2 个输入变量）");
    expect(inputCountSelect(wrapper).element.value).toBe("");
    expect(inputCountSelect(wrapper).element.disabled).toBe(true);
  });

  it("shows the backend default value in helper text for flexible scenarios", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");

    expect(wrapper.text()).toContain("可选；留空时使用系统默认值（2 个输入变量）");
    expect(wrapper.text()).not.toContain("S1 固定为 1 个输入变量");
  });

  it("omits input_count from the POST body when the optional field is empty", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");
    await generateButton(wrapper).trigger("click");
    await flushPromises();

    expect(generateSimulationDataset).toHaveBeenCalledOnce();
    expect(generateSimulationDataset).toHaveBeenCalledWith(
      expect.not.objectContaining({ input_count: expect.anything() })
    );
    const payload = vi.mocked(generateSimulationDataset).mock.calls[0][0];
    expect(payload).toMatchObject({
      scenario: "S6",
      dataset_name: "S6_Heterogeneous_Excitation",
      num_samples: 1500,
      noise_level: 0,
      seed: 42,
    });
    expect(Object.prototype.hasOwnProperty.call(payload, "input_count")).toBe(false);
    expect(wrapper.text()).toContain("仿真结果与真值");
    expect(wrapper.text()).toContain("dataset-1");
  });

  it("includes an explicitly selected input_count in the POST body", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");
    await inputCountSelect(wrapper).setValue("4");
    await generateButton(wrapper).trigger("click");
    await flushPromises();

    expect(generateSimulationDataset).toHaveBeenCalledWith(
      expect.objectContaining({ scenario: "S6", input_count: 4 })
    );
  });

  it("omits input_count again after the selection is cleared", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");
    await inputCountSelect(wrapper).setValue("4");
    await inputCountSelect(wrapper).setValue("");
    await generateButton(wrapper).trigger("click");
    await flushPromises();

    const payload = vi.mocked(generateSimulationDataset).mock.calls[0][0];
    expect(Object.prototype.hasOwnProperty.call(payload, "input_count")).toBe(false);
  });

  it("clears and disables a custom count when switching to fixed-input S1", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");
    await inputCountSelect(wrapper).setValue("4");
    await wrapper.get('[data-test="scenario-s1"]').trigger("click");

    expect(inputCountSelect(wrapper).element.value).toBe("");
    expect(inputCountSelect(wrapper).element.disabled).toBe(true);
    expect(wrapper.text()).toContain("S1 固定为 1 个输入变量");
  });

  it("preserves a valid custom count when switching between flexible scenarios", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");
    await inputCountSelect(wrapper).setValue("4");
    await wrapper.get('[data-test="scenario-s3"]').trigger("click");

    expect(inputCountSelect(wrapper).element.value).toBe("4");
    expect(inputCountSelect(wrapper).element.disabled).toBe(false);
  });

  it("does not submit an unsupported programmatic input count", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s6"]').trigger("click");
    (wrapper.vm as unknown as { form: { input_count?: number } }).form.input_count = 5;
    await generateButton(wrapper).trigger("click");
    await flushPromises();

    expect(generateSimulationDataset).not.toHaveBeenCalled();
  });
});
