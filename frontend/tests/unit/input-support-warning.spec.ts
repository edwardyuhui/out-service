import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import InputSupportWarning from "../../src/components/InputSupportWarning.vue";

const render = (support?: unknown) => mount(InputSupportWarning, {
  props: { support }, global: { stubs: { ElAlert: { props: ["title"], template: "<p>{{ title }}</p>" } } },
});
describe("input support evidence", () => {
  it("names unsupported controls and asks for actual excitation data", () => {
    const text = render({ status: "unsupported", unsupported_constant_inputs: ["heater"] }).text();
    expect(text).toContain("heater");
    expect(text).toContain("真实运行数据");
  });
  it("distinguishes extrapolation from missing or historical evidence", () => {
    expect(render({ status: "extrapolation" }).text()).toContain("外推");
    expect(render({ status: "unavailable" }).text()).toContain("无法确认");
    expect(render().text()).toBe("");
    expect(render({ status: "within_observed_input_ranges" }).text()).toBe("");
  });
});
