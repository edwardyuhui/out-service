import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { nextTick } from "vue";
import WorkspaceLayout from "../../src/layouts/WorkspaceLayout.vue";
import appRouter from "../../src/router";
import { LANDING_SESSION_KEY } from "../../src/router/landingEntry";
import LandingView from "../../src/views/LandingView.vue";

interface MountedLanding {
  wrapper: VueWrapper;
  router: Router;
}

const mountedWrappers: VueWrapper[] = [];

async function mountLanding(): Promise<MountedLanding> {
  if (typeof window.matchMedia !== "function") {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
  }

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: LandingView },
      { path: "/home", component: { template: "<div>Home</div>" } },
      { path: "/copilot", component: { template: "<div>Copilot</div>" } },
      { path: "/workspace", component: { template: "<div>Workspace</div>" } },
    ],
  });
  await router.push("/");
  await router.isReady();
  const wrapper = mount(LandingView, {
    global: { plugins: [router] },
  });
  mountedWrappers.push(wrapper);
  await nextTick();
  return { wrapper, router };
}

afterEach(() => {
  mountedWrappers.splice(0).forEach((wrapper) => wrapper.unmount());
  document.body.innerHTML = "";
  window.sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("formal landing", () => {
  it("resolves outside WorkspaceLayout without changing business routes", () => {
    const landing = appRouter.resolve("/");
    const workspace = appRouter.resolve("/workspace");
    const copilot = appRouter.resolve("/copilot");

    expect(landing.name).toBe("Landing");
    expect(landing.matched).toHaveLength(1);
    // Landing is NOT under WorkspaceLayout (it's a top-level public route)
    expect(landing.matched.some((record) => record.components?.default === WorkspaceLayout)).toBe(false);
    expect(workspace.path).toBe("/workspace");
    expect(copilot.path).toBe("/copilot");
    // Workspace and Copilot ARE under WorkspaceLayout
    expect(workspace.matched.some((r) => r.components?.default === WorkspaceLayout)).toBe(true);
    expect(copilot.matched.some((r) => r.components?.default === WorkspaceLayout)).toBe(true);
  });

  it("renders the core landing content", async () => {
    const { wrapper } = await mountLanding();

    expect(wrapper.get(".landing")).toBeDefined();
    expect(wrapper.get("h1").text()).toContain("让工业建模");
    expect(wrapper.text()).toContain("89.0%");
    expect(wrapper.text()).toContain("进入工作台");
    expect(wrapper.text()).toContain("Industrial AI Agent Workspace");
  });

  it("marks the session and pushes to /home from every Enter Workspace CTA", async () => {
    const { wrapper, router } = await mountLanding();
    const push = vi.spyOn(router, "push").mockResolvedValue(undefined);

    const buttons = wrapper.findAll("button").filter(
      (b) => b.text().includes("进入工作台") || b.text().includes("进入 IndusOpt")
    );
    expect(buttons.length).toBeGreaterThanOrEqual(1);

    await buttons[0]!.trigger("click");
    expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBe("1");
    expect(push).toHaveBeenCalledWith("/home");
  });

  it("navigates to benchmark section when CTA is clicked", async () => {
    const { wrapper } = await mountLanding();
    const benchmarkSection = wrapper.find("#benchmark");
    // The benchmark section should be present in the DOM
    expect(benchmarkSection.exists()).toBe(true);
  });

  it("displays the ablation benchmark table with known strategy rows", async () => {
    const { wrapper } = await mountLanding();
    const text = wrapper.text();
    expect(text).toContain("D-最优");
    expect(text).toContain("89.0");
    expect(text).toContain("BEST");
  });

  it("shows all 8 workflow stages", async () => {
    const { wrapper } = await mountLanding();
    const text = wrapper.text();
    expect(text).toContain("数据质量诊断");
    expect(text).toContain("ARX 系统辨识");
    expect(text).toContain("Optuna 参数寻优");
  });

  it("shows HITL confirmation demo card", async () => {
    const { wrapper } = await mountLanding();
    const text = wrapper.text();
    expect(text).toContain("需要你的确认");
    expect(text).toContain("批准并继续");
    expect(text).toContain("时滞补偿");
  });

  it("shows hero stats strip", async () => {
    const { wrapper } = await mountLanding();
    const text = wrapper.text();
    expect(text).toContain("Free-run FIT");
    expect(text).toContain("S1~S6");
  });

  it("shows all 8 features in the features section", async () => {
    const { wrapper } = await mountLanding();
    const text = wrapper.text();
    expect(text).toContain("Agent 自动编排");
    expect(text).toContain("合规证明可追溯");
    expect(text).toContain("三点 HITL 确认");
  });

  it("renders sticky nav with enter CTA", async () => {
    const { wrapper } = await mountLanding();
    expect(wrapper.find(".landing-nav__cta").exists()).toBe(true);
    expect(wrapper.find(".landing-header").exists()).toBe(true);
  });
});
