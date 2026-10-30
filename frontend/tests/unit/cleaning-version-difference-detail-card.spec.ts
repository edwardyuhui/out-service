import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import CleaningVersionDifferenceDetailCard from "../../src/components/cleaning/CleaningVersionDifferenceDetailCard.vue";
import type { VersionDifferencePoint } from "../../src/types/api";

const difference = (overrides: Partial<VersionDifferencePoint>): VersionDifferencePoint => ({
  timestamp: "2026-01-01T00:00:00Z",
  difference_kind: "VALUE_CHANGED",
  baseline_value: 1,
  compare_value: 1.5,
  absolute_delta: 0.5,
  baseline_occurrences: [],
  compare_occurrences: [],
  ...overrides,
});

describe("CleaningVersionDifferenceDetailCard", () => {
  it("renders VALUE_CHANGED using the Backend delta and never derives a missing delta", async () => {
    const wrapper = mount(CleaningVersionDifferenceDetailCard, {
      props: { difference: difference({}) },
    });

    expect(wrapper.text()).toContain("值变化");
    expect(wrapper.get("[data-test='difference-baseline-value']").text()).toBe("1");
    expect(wrapper.get("[data-test='difference-compare-value']").text()).toBe("1.5");
    expect(wrapper.get("[data-test='difference-absolute-delta']").text()).toBe("0.5");

    await wrapper.setProps({ difference: difference({ absolute_delta: null }) });
    expect(wrapper.get("[data-test='difference-absolute-delta']").text()).toBe("未提供");
    expect(wrapper.text()).not.toContain("0.5");
  });

  it("renders POINT_ADDED and POINT_REMOVED with explicit non-existence semantics", async () => {
    const wrapper = mount(CleaningVersionDifferenceDetailCard, {
      props: {
        difference: difference({
          difference_kind: "POINT_ADDED",
          baseline_value: null,
          compare_value: 3,
          absolute_delta: null,
        }),
      },
    });

    expect(wrapper.text()).toContain("新增点");
    expect(wrapper.get("[data-test='difference-baseline-value']").text()).toBe("不存在");
    expect(wrapper.get("[data-test='difference-compare-value']").text()).toBe("3");
    expect(wrapper.find("[data-test='difference-absolute-delta']").exists()).toBe(false);

    await wrapper.setProps({
      difference: difference({
        difference_kind: "POINT_REMOVED",
        baseline_value: 4,
        compare_value: null,
        absolute_delta: null,
      }),
    });
    expect(wrapper.text()).toContain("移除点");
    expect(wrapper.get("[data-test='difference-baseline-value']").text()).toBe("4");
    expect(wrapper.get("[data-test='difference-compare-value']").text()).toBe("不存在");
    expect(wrapper.find("[data-test='difference-absolute-delta']").exists()).toBe(false);
  });

  it("renders AMBIGUOUS occurrence groups without pairing or delta", () => {
    const wrapper = mount(CleaningVersionDifferenceDetailCard, {
      props: {
        difference: difference({
          difference_kind: "AMBIGUOUS_ALIGNMENT",
          baseline_value: null,
          compare_value: null,
          absolute_delta: null,
          baseline_occurrences: [
            { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 0, value: 4 },
            { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 1, value: 5 },
          ],
          compare_occurrences: [
            { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 0, value: 4.5 },
          ],
        }),
      },
    });

    expect(wrapper.text()).toContain("对齐歧义");
    expect(wrapper.text()).toContain("Baseline occurrences (2)");
    expect(wrapper.text()).toContain("Compare occurrences (1)");
    expect(wrapper.text()).toContain("#0");
    expect(wrapper.text()).toContain("#1");
    expect(wrapper.text()).toContain("系统未推测 occurrence 配对");
    expect(wrapper.text()).not.toContain("Absolute delta");
    expect(wrapper.text()).not.toContain("→");
  });

  it("emits close from the explicit close control", async () => {
    const wrapper = mount(CleaningVersionDifferenceDetailCard, {
      props: { difference: difference({}) },
    });
    await wrapper.get("[data-test='difference-detail-close']").trigger("click");
    expect(wrapper.emitted("close")).toEqual([[]]);
  });
});
