import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { shallowMount } from "@vue/test-utils";
import DefaultLayout from "../../src/layouts/DefaultLayout.vue";

describe("default layout boundary rebound", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("moves the page slightly and settles when scrolling beyond the top", async () => {
    vi.useFakeTimers();
    const wrapper = shallowMount(DefaultLayout, {
      global: {
        stubs: {
          AppHeader: true,
          AppSidebar: true,
          CopilotView: true,
          "router-view": true,
          "el-drawer": true,
        },
      },
    });

    const scroller = wrapper.get("[data-main-scroller]");
    Object.defineProperties(scroller.element, {
      scrollTop: { configurable: true, value: 0, writable: true },
      clientHeight: { configurable: true, value: 600 },
      scrollHeight: { configurable: true, value: 1200 },
    });

    await scroller.trigger("wheel", { deltaY: -100 });
    await nextTick();
    expect(wrapper.get("[data-scroll-stage]").attributes("style")).toContain(
      "translate3d(0, 12px, 0)"
    );

    vi.advanceTimersByTime(55);
    await nextTick();
    expect(wrapper.get("[data-scroll-stage]").attributes("style")).toContain(
      "translate3d(0, 0px, 0)"
    );
    expect(wrapper.get("[data-scroll-stage]").classes()).toContain("is-rebounding");
  });
});
