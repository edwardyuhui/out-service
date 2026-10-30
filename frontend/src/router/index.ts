import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from "vue-router";
import WorkspaceLayout from "../layouts/WorkspaceLayout.vue";
import { hasEnteredLanding } from "./landingEntry";

const routes: RouteRecordRaw[] = [
  // ── Public: Landing (Marketing / Showcase) ───────────────
  {
    path: "/",
    name: "Landing",
    component: () => import("../views/LandingView.vue"),
    meta: { landingGatePublic: true },
  },

  // ── App Shell: All workspace routes ──────────────────────
  {
    path: "/",
    component: WorkspaceLayout,
    children: [
      // Home (Prompt-first)
      {
        path: "/home",
        name: "Home",
        component: () => import("../views/HomeView.vue"),
        meta: { title: "主页" },
      },

      // Agent Workspace (core)
      {
        path: "/workspace",
        name: "Workspace",
        component: () => import("../views/WorkspaceView.vue"),
        meta: { title: "Agent Workspace" },
      },
      {
        path: "/workspace/:executionId",
        name: "WorkspaceExecution",
        component: () => import("../views/WorkspaceView.vue"),
        meta: { title: "Agent Workspace" },
      },

      // Legacy /copilot → kept for E2E test compatibility
      {
        path: "/copilot",
        name: "Copilot",
        component: () => import("../views/WorkspaceView.vue"),
        meta: { title: "Agent Workspace" },
      },

      // Run History
      {
        path: "/runs",
        name: "Runs",
        component: () => import("../views/RunsView.vue"),
        meta: { title: "历史任务" },
      },

      // Assets (aggregated)
      {
        path: "/assets",
        name: "Assets",
        component: () => import("../views/AssetsView.vue"),
        meta: { title: "功能中心" },
      },
      {
        path: "/assets/preprocessing",
        name: "AssetPreprocessing",
        component: () => import("../views/AssetCategoryView.vue"),
        props: { category: "preprocessing" },
        meta: { title: "预处理与优选" },
      },
      {
        path: "/assets/modeling",
        name: "AssetModeling",
        component: () => import("../views/AssetCategoryView.vue"),
        props: { category: "modeling" },
        meta: { title: "建模与寻优" },
      },
      {
        path: "/assets/delivery",
        name: "AssetDelivery",
        component: () => import("../views/AssetCategoryView.vue"),
        props: { category: "delivery" },
        meta: { title: "分析与交付" },
      },

      // Data Management
      {
        path: "/simulation",
        name: "Simulation",
        component: () => import("../views/SimulationView.vue"),
        meta: { title: "仿真生成器" },
      },
      {
        path: "/datasets",
        name: "Datasets",
        component: () => import("../views/DatasetsView.vue"),
        meta: { title: "数据资产" },
      },
      {
        path: "/datasets/:id",
        name: "DatasetDetail",
        component: () => import("../views/DatasetDetailView.vue"),
        meta: { title: "数据集详情" },
      },

      // Preprocessing (paths kept for E2E)
      {
        path: "/preprocessing/cleaning",
        name: "Cleaning",
        component: () => import("../views/CleaningView.vue"),
        meta: { title: "时间规整与清洗" },
      },
      {
        path: "/preprocessing/segmentation",
        name: "Segmentation",
        component: () => import("../views/SegmentationView.vue"),
        meta: { title: "动态响应区间优选" },
      },
      {
        path: "/preprocessing/delay",
        name: "Delay",
        component: () => import("../views/DelayView.vue"),
        meta: { title: "多变量时滞分析" },
      },
      {
        path: "/preprocessing/collinearity",
        name: "Collinearity",
        component: () => import("../views/CollinearityView.vue"),
        meta: { title: "共线性与变量筛选" },
      },

      // Modeling
      {
        path: "/modeling/arx",
        name: "ARXModeling",
        component: () => import("../views/ARXModelingView.vue"),
        meta: { title: "ARX 系统辨识" },
      },
      {
        path: "/modeling/optimization",
        name: "OptunaOptimization",
        component: () => import("../views/OptunaView.vue"),
        meta: { title: "Optuna 闭环寻优" },
      },

      // Benchmark (path kept for E2E)
      {
        path: "/benchmark",
        name: "Benchmark",
        component: () => import("../views/BenchmarkView.vue"),
        meta: { title: "一键自评测基准" },
      },

      // Deliverables (legacy path kept + new)
      {
        path: "/deliverables",
        name: "Deliverables",
        component: () => import("../views/DeliverablesView.vue"),
        meta: { title: "报告与交付中心" },
      },

      // Settings
      {
        path: "/settings",
        name: "Settings",
        component: () => import("../views/SettingsView.vue"),
        meta: { title: "系统设置" },
      },

      // Legacy /dashboard → redirect home
      {
        path: "/dashboard",
        redirect: "/home",
      },
    ],
  },

  // ── Error Pages ───────────────────────────────────────────
  {
    path: "/403",
    name: "403",
    component: () => import("../views/error/403View.vue"),
    meta: { landingGatePublic: true },
  },
  {
    path: "/404",
    name: "404",
    component: () => import("../views/error/404View.vue"),
    meta: { landingGatePublic: true },
  },
  {
    path: "/500",
    name: "500",
    component: () => import("../views/error/500View.vue"),
    meta: { landingGatePublic: true },
  },
  {
    path: "/:pathMatch(.*)*",
    redirect: "/404",
    meta: { landingGatePublic: true },
  },
];

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({ history, routes });

  router.beforeEach((to) => {
    document.title = to.meta.title
      ? `${to.meta.title} — IndusOpt 工模智优`
      : "IndusOpt 工模智优";

    // Landing gate: if not yet visited landing, redirect there first
    // Public routes (landing, error pages) bypass this gate.
    if (to.meta.landingGatePublic === true || hasEnteredLanding()) return true;
    return { name: "Landing", query: { next: to.fullPath }, replace: true };
  });

  return router;
}

const router = createAppRouter();
export default router;
