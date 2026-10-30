import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import OptunaView from "../../src/views/OptunaView.vue";

const api = vi.hoisted(() => ({ start: vi.fn(), status: vi.fn(), success: vi.fn(), warning: vi.fn() }));
vi.mock("../../src/api/modeling", () => ({ startOptunaStudy: api.start, getOptunaStatus: api.status }));
vi.mock("element-plus", () => ({ ElMessage: { success: api.success, warning: api.warning } }));

const container = { template: '<div><slot /></div>' };
const input = { props: ["modelValue"], emits: ["update:modelValue"],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' };

describe("optimization model quality", () => {
  it.each([
    ["insufficient", "模型效果不足", true, "established"],
    ["inconclusive", "模型效果尚不能确认", true, "established"],
    ["passed", "仍需独立测试和现场工况验证", false, "established"],
    ["no_winner", "本次寻优未得到可用模型", true, "established"],
    ["passed", "仍需独立测试和现场工况验证", false, "disturbance_aware"],
    ["passed", "仍需独立测试和现场工况验证", false, "paired_coverage"],
    ["passed", "仍需独立测试和现场工况验证", false, "validation_guarded"],
  ])("shows %s evidence with %s", async (quality, text, warns, policy) => {
    api.success.mockClear(); api.warning.mockClear();
    api.start.mockResolvedValue({ study_id: "study" });
    api.status.mockResolvedValue({
      best_trial_id: quality === "no_winner" ? null : 0,
      best_value: quality === "no_winner" ? null : .1,
      best_curve: [.1], statistics: {}, param_importances: {},
      best_params: { training_policy: "full_train" }, warm_started_from: null,
      trials: [{ trial_id: 0, metrics: { validation_acceptance: { status: quality } } }],
    });
    const wrapper = mount(OptunaView, { global: { stubs: {
      PageHeader: true, ChartContainer: true, "el-icon": container, "el-form": container,
      "el-form-item": container, "el-input": input, "el-input-number": true,
      "el-checkbox": true,
      "el-select": { props: ["modelValue"], emits: ["update:modelValue"],
        template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>' },
      "el-option": { props: ["value", "label"], template: '<option :value="value">{{ label }}</option>' },
      "el-button": { emits: ["click"], template: '<button @click="$emit(\'click\')"><slot /></button>' },
      "el-alert": { template: '<div><slot name="title" /></div>' },
      "el-descriptions": container, "el-descriptions-item": container, "el-tag": container,
      "el-table": true, "el-table-column": true,
    } } });
    await wrapper.findAll("input")[0]!.setValue("version");
    if (policy !== "established") await wrapper.find("select").setValue(policy);
    await wrapper.find("button").trigger("click");
    await flushPromises();
    expect(api.start).toHaveBeenLastCalledWith(expect.objectContaining({ optimization_policy: policy }));
    expect(wrapper.text()).toContain(text);
    expect(wrapper.text()).toContain("全量有效训练行");
    expect(api.warning).toHaveBeenCalledTimes(warns ? 1 : 0);
    expect(api.success).toHaveBeenCalledTimes(warns ? 0 : 1);
    wrapper.unmount();
  });
});
