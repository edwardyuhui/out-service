import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { nextTick } from "vue";
import AssetCategoryView from "../../src/views/AssetCategoryView.vue";
import AssetsView from "../../src/views/AssetsView.vue";
import CommandPalette from "../../src/components/CommandPalette.vue";
import PrimaryNav from "../../src/components/shell/PrimaryNav.vue";
import { createAppRouter } from "../../src/router";

const PageHeaderStub = {
  props: ["eyebrow", "title", "description"],
  template: `<header>
    <span v-if="eyebrow" class="page-eyebrow-stub">{{ eyebrow }}</span>
    <h1>{{ title }}</h1>
    <p>{{ description }}</p>
    <slot name="actions" />
  </header>`,
};

const RouterLinkStub = {
  props: ["to"],
  template: `<a :data-to="to"><slot /></a>`,
};

const navigationStubs = {
  PageHeader: PageHeaderStub,
  RouterLink: RouterLinkStub,
};

const assetTitles = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll(".asset-card__title").map((node) => node.text());

const moduleLinks = (category: "preprocessing" | "modeling" | "delivery") => {
  const wrapper = mount(AssetCategoryView, {
    props: { category },
    global: { stubs: navigationStubs },
  });

  return wrapper.findAll(".module-card").map((node) => ({
    title: node.get("h2").text(),
    path: node.attributes("data-to"),
  }));
};

afterEach(() => {
  document.body.innerHTML = "";
});

describe("Function Center information architecture", () => {
  it("keeps secondary module hover and focus feedback aligned with first-level cards", () => {
    const primarySource = readFileSync(resolve(process.cwd(), "src/views/AssetsView.vue"), "utf8");
    const secondarySource = readFileSync(resolve(process.cwd(), "src/views/AssetCategoryView.vue"), "utf8");
    const sharedFeedbackDeclarations = [
      "background: #F7F9F5;",
      "border-color: #D6DDD2;",
      "transform: translateY(-1px);",
      "box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);",
      "background: #E8F0E5;",
      "color: #426340;",
      "transform: translateX(2px);",
      "outline: 2px solid var(--border-focus, #82A978);",
      "outline-offset: 2px;",
    ];

    for (const declaration of sharedFeedbackDeclarations) {
      expect(primarySource).toContain(declaration);
      expect(secondarySource).toContain(declaration);
    }
    expect(secondarySource).toContain(
      "transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;"
    );
    expect(secondarySource).toContain(
      "transition: background-color 180ms ease, color 180ms ease;"
    );
    expect(secondarySource).toContain(
      "transition: transform 180ms ease, color 180ms ease;"
    );
    expect(secondarySource).not.toMatch(/\.module-card(?:\.router-link-(?:exact-)?active|\.selected|\.active)\s*\{/);
  });

  it("uses the formal Function Center heading, introduction, and no technical eyebrow", () => {
    const wrapper = mount(AssetsView, { global: { stubs: navigationStubs } });

    expect(wrapper.get("h1").text()).toBe("功能中心");
    expect(wrapper.get("header p").text()).toBe(
      "集中访问从数据准备、预处理、系统辨识到分析交付的工业时序建模能力。"
    );
    expect(wrapper.find(".page-eyebrow-stub").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("资产中心");
    expect(wrapper.text()).not.toContain("DATA & MODEL / ASSETS");
  });

  it("renders exactly the six formal first-level entries", () => {
    const wrapper = mount(AssetsView, { global: { stubs: navigationStubs } });

    expect(assetTitles(wrapper)).toEqual([
      "数据集与版本",
      "预处理与优选",
      "建模与寻优",
      "仿真测试集生成",
      "分析与交付",
      "系统环境设置",
    ]);
    expect(wrapper.findAll(".asset-card")).toHaveLength(6);
    expect(assetTitles(wrapper)).not.toEqual(
      expect.arrayContaining(["ARX 辨识模型", "闭环参数寻优", "消融评测基准", "报告与交付中心"])
    );
    expect(assetTitles(wrapper)).not.toContain("仿真工况数据集");
  });

  it("navigates from the preprocessing first-level card to its category route", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
    });
    await router.push("/assets");
    const wrapper = mount(AssetsView, {
      global: { plugins: [router], stubs: { PageHeader: PageHeaderStub } },
    });
    const card = wrapper.findAll(".asset-card").find((node) => node.text().includes("预处理与优选"));

    await card!.trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/assets/preprocessing");
  });

  it("maps preprocessing to the four existing formal module routes", () => {
    expect(moduleLinks("preprocessing")).toEqual([
      { title: "时间规整与清洗", path: "/preprocessing/cleaning" },
      { title: "质量约束 D-最优优选", path: "/preprocessing/segmentation" },
      { title: "多变量时滞对齐", path: "/preprocessing/delay" },
      { title: "VIF 共线性与筛选", path: "/preprocessing/collinearity" },
    ]);
  });

  it("maps modeling to ARX and Optuna", () => {
    expect(moduleLinks("modeling")).toEqual([
      { title: "ARX 系统辨识", path: "/modeling/arx" },
      { title: "Optuna 闭环寻优", path: "/modeling/optimization" },
    ]);
  });

  it("maps analysis and delivery to Benchmark and Deliverables without Settings", () => {
    expect(moduleLinks("delivery")).toEqual([
      { title: "消融对账评测", path: "/benchmark" },
      { title: "工程报告与数据交付", path: "/deliverables" },
    ]);
  });

  it("keeps Settings as a direct independent first-level route", () => {
    const wrapper = mount(AssetsView, { global: { stubs: navigationStubs } });
    const settingsCard = wrapper.findAll(".asset-card").find((node) => node.text().includes("系统环境设置"));

    expect(settingsCard?.attributes("data-to")).toBe("/settings");
  });

  it.each([
    ["preprocessing", "预处理与优选"],
    ["modeling", "建模与寻优"],
    ["delivery", "分析与交付"],
  ] as const)("renders a Chinese breadcrumb for the %s category", (category, title) => {
    const wrapper = mount(AssetCategoryView, {
      props: { category },
      global: { stubs: navigationStubs },
    });
    const breadcrumb = wrapper.get(".category-breadcrumb");

    expect(breadcrumb.text()).toContain(`功能中心/${title}`);
    expect(breadcrumb.get("a").attributes("data-to")).toBe("/assets");
    expect(wrapper.find(".page-eyebrow-stub").exists()).toBe(false);
    expect(wrapper.text()).not.toMatch(/ASSETS \/ (PREPROCESSING|MODELING|DELIVERY)/);
  });
});

describe("Primary navigation", () => {
  it("shows Function Center and no longer exposes the old name", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
    });
    await router.push("/home");
    const wrapper = mount(PrimaryNav, {
      global: {
        plugins: [createPinia(), router],
        stubs: {
          "el-tooltip": { template: "<div><slot /></div>" },
        },
      },
    });

    expect(wrapper.text()).toContain("功能中心");
    expect(wrapper.text()).not.toContain("资产中心");
    expect(wrapper.get(".brand-name").text()).toBe("IndusOpt");
    expect(wrapper.get(".brand-logo__image").attributes("src")).toContain("indusopt-mark.png");
    expect(wrapper.get(".brand-logo__image").attributes("alt")).toBe("");
    expect(wrapper.get(".brand-logo").find("svg").exists()).toBe(false);
    expect(wrapper.find(".brand-badge").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("A14");
  });
});

describe("Asset routes", () => {
  it("adds the three category routes and preserves every atomic feature route", () => {
    const paths = new Map(createAppRouter(createMemoryHistory()).getRoutes().map((route) => [route.path, route.name]));

    expect(paths.get("/assets/preprocessing")).toBe("AssetPreprocessing");
    expect(paths.get("/assets/modeling")).toBe("AssetModeling");
    expect(paths.get("/assets/delivery")).toBe("AssetDelivery");

    expect(paths.get("/preprocessing/cleaning")).toBe("Cleaning");
    expect(paths.get("/preprocessing/segmentation")).toBe("Segmentation");
    expect(paths.get("/preprocessing/delay")).toBe("Delay");
    expect(paths.get("/preprocessing/collinearity")).toBe("Collinearity");
    expect(paths.get("/modeling/arx")).toBe("ARXModeling");
    expect(paths.get("/modeling/optimization")).toBe("OptunaOptimization");
    expect(paths.get("/benchmark")).toBe("Benchmark");
    expect(paths.get("/deliverables")).toBe("Deliverables");
    expect(paths.get("/settings")).toBe("Settings");

    const assetsRoute = createAppRouter(createMemoryHistory()).getRoutes()
      .find((route) => route.path === "/assets");
    expect(assetsRoute?.meta.title).toBe("功能中心");
  });
});

describe("Command Palette hierarchy", () => {
  it("places Settings in its own group and gives Chinese group titles Sans semantics", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
    });
    await router.push("/");
    const wrapper = mount(CommandPalette, {
      global: {
        plugins: [router],
        stubs: { "el-icon": { template: "<span><slot /></span>" } },
      },
    });

    (wrapper.vm as unknown as { open: () => void }).open();
    await nextTick();

    const groupTitles = Array.from(document.body.querySelectorAll<HTMLElement>(".cmd-group-title"));
    expect(groupTitles.map((title) => title.textContent)).toEqual([
      "常用导航",
      "预处理与优选",
      "建模与寻优",
      "分析与交付",
      "系统环境设置",
    ]);
    expect(groupTitles.every((title) => !title.classList.contains("font-mono"))).toBe(true);

    const settingsItem = Array.from(document.body.querySelectorAll<HTMLElement>(".cmd-item-title"))
      .find((item) => item.textContent?.includes("系统环境设置"));
    expect(settingsItem?.closest(".cmd-group")?.querySelector(".cmd-group-title")?.textContent).toBe("系统环境设置");

    const commandTitles = Array.from(document.body.querySelectorAll<HTMLElement>(".cmd-item-title"))
      .map((item) => item.textContent ?? "");
    expect(commandTitles).toContain("功能中心");
    expect(commandTitles.some((title) => title.includes("资产中心"))).toBe(false);

    wrapper.unmount();
  });
});

describe("Chinese structural typography", () => {
  it("uses the shared Sans rule for industrial card titles including Benchmark configuration", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/assets/main.css"), "utf8");
    const titleRules = Array.from(styles.matchAll(/\.industrial-card-title\s*\{([^}]+)\}/g))
      .map((match) => match[1])
      .join("\n");
    const benchmarkTemplate = readFileSync(resolve(process.cwd(), "src/views/BenchmarkView.vue"), "utf8");

    expect(titleRules).toContain("font-family: var(--font-sans)");
    expect(titleRules).toContain("letter-spacing: normal");
    expect(titleRules).toContain("text-transform: none");
    expect(benchmarkTemplate).toContain('<div class="industrial-card-title">');
    expect(benchmarkTemplate).not.toContain('class="industrial-card-title font-mono"');
  });

  it("keeps the Home hierarchy Chinese-first without changing Suggested Workflows", () => {
    const source = readFileSync(resolve(process.cwd(), "src/views/HomeView.vue"), "utf8");
    const recentRule = source.match(/\.home-section-label--recent\s*\{([^}]+)\}/)?.[1] ?? "";

    expect(source).not.toContain("A14 · INDUSTRIAL AI AGENT WORKSPACE");
    expect(source).not.toContain("RECENT TASKS");
    expect(source).toContain('<span class="home-section-label home-section-label--recent">最近任务</span>');
    expect(recentRule).toContain("font-family: var(--font-sans)");
    expect(recentRule).toContain("letter-spacing: normal");
    expect(source).toContain("SUGGESTED WORKFLOWS");
    expect(source).toContain("· 推荐场景");
  });

  it("uses the shared PageHeader hierarchy for Task History without an eyebrow", () => {
    const runsSource = readFileSync(resolve(process.cwd(), "src/views/RunsView.vue"), "utf8");
    const assetsSource = readFileSync(resolve(process.cwd(), "src/views/AssetsView.vue"), "utf8");

    expect(runsSource).toContain("<PageHeader");
    expect(assetsSource).toContain("<PageHeader");
    expect(runsSource).toContain('title="任务历史"');
    expect(runsSource).toContain('description="查看 Agent 的执行阶段、审批和产物记录"');
    expect(runsSource).not.toContain("AGENT / HISTORY");
  });

  it("uses concise Sans panel headers while preserving technical body typography", () => {
    const planSource = readFileSync(resolve(process.cwd(), "src/components/workspace/AgentPlan.vue"), "utf8");
    const artifactSource = readFileSync(resolve(process.cwd(), "src/components/artifact/ArtifactWorkbench.vue"), "utf8");
    const streamSource = readFileSync(resolve(process.cwd(), "src/components/workspace/AgentStream.vue"), "utf8");
    const workspaceSource = readFileSync(resolve(process.cwd(), "src/views/WorkspaceView.vue"), "utf8");
    const planHeaderRule = planSource.match(/\.plan-header__label\s*\{([^}]+)\}/)?.[1] ?? "";
    const artifactHeaderRule = artifactSource.match(/\.aw-header__title\s*\{([^}]+)\}/)?.[1] ?? "";

    expect(planSource).toContain('<span class="plan-header__label">执行计划</span>');
    expect(planSource).not.toContain("AGENT PLAN");
    expect(planHeaderRule).toContain("font-family: var(--font-sans)");
    expect(planHeaderRule).toContain("letter-spacing: normal");
    expect(planSource).toContain('class="plan-step__tool"');
    expect(planSource).toContain(".plan-step__tool,");

    expect(artifactSource).toContain('<span class="aw-header__title">成果展示区</span>');
    expect(streamSource).toContain("可在右侧成果展示区查看和下载结果");
    expect(workspaceSource).toContain("<span>成果展示区</span>");
    expect(workspaceSource).toContain("收起成果展示区");
    expect(workspaceSource).toContain("展开成果展示区");
    expect(`${artifactSource}${streamSource}${workspaceSource}`).not.toContain("成果工作区");
    expect(artifactSource).not.toContain("WORKSPACE ARTIFACTS");
    expect(artifactHeaderRule).toContain("font-family: var(--font-sans)");
    expect(artifactHeaderRule).toContain("letter-spacing: normal");
    expect(artifactSource).toContain("aw-json font-mono");
    expect(artifactSource).toContain("<MetricStrip");
  });
});
