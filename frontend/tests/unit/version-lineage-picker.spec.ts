import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import VersionLineagePicker from "../../src/components/versioning/VersionLineagePicker.vue";
import type { DatasetVersionNode } from "../../src/types/api";

const raw: DatasetVersionNode = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "V0 · 仿真原始数据",
  tool: "simulation_generate",
  parent_version_id: null,
  created_at: "2026-09-03T10:00:00Z",
  row_count: 2000,
  column_count: 6,
  artifact_path: "raw.csv",
};

const clean: DatasetVersionNode = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "V1 · 清洗规整",
  tool: "preprocessing.clean",
  parent_version_id: raw.id,
  created_at: "2026-09-03T10:10:00Z",
  row_count: 1998,
  column_count: 6,
  artifact_path: "clean.csv",
};

const lag: DatasetVersionNode = {
  id: "33333333-3333-4333-8333-333333333333",
  name: "V2 · 时滞补偿",
  tool: "preprocessing.lag_compensation",
  parent_version_id: clean.id,
  created_at: "2026-09-03T10:20:00Z",
  row_count: 1989,
  column_count: 6,
  artifact_path: "lag.csv",
};

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  props: {
    placement: String,
    fallbackPlacements: Array,
    teleported: Boolean,
    offset: Number,
    popperOptions: Object,
  },
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

const mountPicker = (
  versions: DatasetVersionNode[],
  selectedVersionId: string | null = clean.id
) => mount(VersionLineagePicker, {
  props: {
    datasetName: "accept_collinearity_phase2",
    versions,
    selectedVersionId,
    contextLabel: "清洗规整版本可用于 Stage 03",
    eligibleLabel: "可用于 D-最优",
    emptyStateText: "暂无可用清洗规整版本。",
    emptyStateHint: "请先完成时间清洗。",
    isEligible: (version: DatasetVersionNode) => version.tool === "preprocessing.clean",
    disabledReason: (version: DatasetVersionNode) =>
      version.tool === "simulation_generate" ? "需先完成清洗规整" : "已进入后续阶段",
  },
  global: {
    stubs: {
      "el-popover": ElPopoverStub,
      "el-icon": { template: "<span><slot /></span>" },
      ArrowDown: true,
    },
  },
});

describe("VersionLineagePicker", () => {
  it("declares a viewport-safe Popover positioning contract", () => {
    const wrapper = mountPicker([raw, clean, lag]);
    const popover = wrapper.getComponent(ElPopoverStub);

    expect(popover.props("placement")).toBe("bottom-start");
    expect(popover.props("fallbackPlacements")).toEqual(["top-start"]);
    expect(popover.props("teleported")).toBe(true);
    expect(popover.props("offset")).toBe(12);

    const popperOptions = popover.props("popperOptions") as {
      modifiers: Array<{
        name: string;
        enabled: boolean;
        options: Record<string, unknown>;
      }>;
    };
    const preventOverflow = popperOptions.modifiers.find(
      (modifier) => modifier.name === "preventOverflow"
    );

    expect(preventOverflow).toEqual({
      name: "preventOverflow",
      enabled: true,
      options: {
        boundary: "clippingParents",
        rootBoundary: "viewport",
        padding: 12,
        mainAxis: true,
        altAxis: false,
        tether: true,
      },
    });
  });

  it("renders the Chinese panel title with the explicit Sans typography contract", () => {
    const wrapper = mountPicker([raw, clean, lag]);
    const title = wrapper.get(".lineage-panel-label");

    expect(title.text()).toBe("版本血缘");
    expect(title.classes()).toContain("lineage-panel-label-sans");
    expect(title.classes()).not.toContain("font-mono");
  });

  it("keeps the default selected badge and supports an additive custom label", async () => {
    const defaultPicker = mountPicker([raw, clean, lag]);
    expect(defaultPicker.get(`[data-version-id='${clean.id}']`).text()).toContain("当前分析源");

    const customPicker = mountPicker([raw, clean, lag]);
    await customPicker.setProps({ selectedBadgeLabel: "比较基线" });
    expect(customPicker.get(`[data-version-id='${clean.id}']`).text()).toContain("比较基线");
    expect(customPicker.get(`[data-version-id='${clean.id}']`).text()).not.toContain("当前分析源");
  });

  it("builds the displayed chain from parent_version_id and renders selected, eligibility, and metadata", () => {
    const wrapper = mountPicker([lag, raw, clean]);
    const nodes = wrapper.findAll("[data-test='lineage-node']");

    expect(nodes.map((node) => node.attributes("data-version-id"))).toEqual([
      raw.id,
      clean.id,
      lag.id,
    ]);
    expect(nodes[1]?.attributes("data-parent-id")).toBe(raw.id);
    expect(nodes[2]?.attributes("data-parent-id")).toBe(clean.id);
    expect(nodes[1]?.classes()).toContain("selected");
    expect(nodes[1]?.text()).toContain("当前分析源");
    expect(nodes[1]?.text()).toContain("可用于 D-最优");
    expect(nodes[0]?.attributes("aria-disabled")).toBe("true");
    expect(nodes[2]?.attributes("aria-disabled")).toBe("true");
    expect(nodes[1]?.text()).toContain("22222222…2222");
    expect(nodes[1]?.text()).toContain("1998 rows");
    expect(nodes[1]?.text()).toContain("6 cols");
  });

  it("preserves branches, ignores disabled mouse and keyboard actions, and emits eligible selection", async () => {
    const cleanBranch = {
      ...clean,
      id: "44444444-4444-4444-8444-444444444444",
      name: "V1B · 清洗规整",
      parent_version_id: raw.id,
    };
    const unknown = {
      ...lag,
      id: "55555555-5555-4555-8555-555555555555",
      name: "",
      tool: "custom.transform",
      parent_version_id: cleanBranch.id,
    };
    const wrapper = mountPicker([unknown, cleanBranch, raw, clean], null);

    expect(wrapper.get(`[data-version-id='${cleanBranch.id}']`).attributes("data-parent-id")).toBe(raw.id);
    expect(wrapper.get(`[data-version-id='${unknown.id}']`).text()).toContain("custom.transform");

    const rawNode = wrapper.get(`[data-version-id='${raw.id}']`);
    await rawNode.trigger("click");
    await rawNode.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("select")).toBeUndefined();

    const eligibleNode = wrapper.get(`[data-version-id='${cleanBranch.id}']`);
    await eligibleNode.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("select")).toEqual([[cleanBranch.id]]);
    expect(wrapper.emitted("update:selectedVersionId")).toEqual([[cleanBranch.id]]);
  });

  it("shows the supplied empty state when no version is eligible", () => {
    const wrapper = mountPicker([raw, lag], null);
    const empty = wrapper.get("[data-test='no-eligible-source']");

    expect(empty.text()).toContain("暂无可用清洗规整版本");
    expect(empty.text()).toContain("请先完成时间清洗");
  });
});
