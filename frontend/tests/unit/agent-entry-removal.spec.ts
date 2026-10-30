import { describe, expect, it } from "vitest";
import { mount, shallowMount } from "@vue/test-utils";
import { createPinia } from "pinia";
import AppHeader from "../../src/components/AppHeader.vue";
import DefaultLayout from "../../src/layouts/DefaultLayout.vue";

const headerStubs = {
  "el-tooltip": { template: "<div><slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-tag": { template: "<span><slot /></span>" },
  DataAnalysis: true,
};

describe("single Agent entry", () => {
  it("does not render the global Open Agent action", () => {
    const wrapper = mount(AppHeader, {
      global: { plugins: [createPinia()], stubs: headerStubs },
    });

    expect(wrapper.text()).not.toContain("打开 Agent");
    expect(wrapper.find(".copilot-btn").exists()).toBe(false);
  });

  it("does not mount a second CopilotView or Agent drawer in DefaultLayout", () => {
    const wrapper = shallowMount(DefaultLayout, {
      global: {
        stubs: {
          AppHeader: true,
          AppSidebar: true,
          "router-view": true,
        },
      },
    });

    expect(wrapper.find("el-drawer-stub").exists()).toBe(false);
    expect(wrapper.findComponent({ name: "CopilotView" }).exists()).toBe(false);
  });
});