import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import AppHeader from "../../src/components/AppHeader.vue";
import DashboardView from "../../src/views/DashboardView.vue";
import SettingsView from "../../src/views/SettingsView.vue";
import { useSystemStore } from "../../src/stores/systemStore";
import { getDashboardLeaderboard } from "../../src/api/dashboard";
import { getDatasets } from "../../src/api/datasets";
import { getHealthLive, getHealthReady, getSystemInfo } from "../../src/api/health";
import {
  getAgentLlmConfig,
  resetAgentLlmConfig,
  testAgentLlmConnection,
  updateAgentLlmConfig,
} from "../../src/api/agentSettings";
import { ElMessage, ElMessageBox } from "element-plus";

vi.mock("../../src/api/dashboard", () => ({ getDashboardLeaderboard: vi.fn() }));
vi.mock("../../src/api/datasets", () => ({ getDatasets: vi.fn() }));
vi.mock("../../src/api/health", () => ({
  getHealthLive: vi.fn(),
  getHealthReady: vi.fn(),
  getSystemInfo: vi.fn(),
}));
vi.mock("../../src/api/agentSettings", () => ({
  getAgentLlmConfig: vi.fn(),
  resetAgentLlmConfig: vi.fn(),
  testAgentLlmConnection: vi.fn(),
  updateAgentLlmConfig: vi.fn(),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("element-plus", () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}));

const mockedGetDashboardLeaderboard = vi.mocked(getDashboardLeaderboard);
const mockedGetDatasets = vi.mocked(getDatasets);
const mockedGetHealthLive = vi.mocked(getHealthLive);
const mockedGetHealthReady = vi.mocked(getHealthReady);
const mockedGetSystemInfo = vi.mocked(getSystemInfo);
const mockedGetAgentLlmConfig = vi.mocked(getAgentLlmConfig);
const mockedResetAgentLlmConfig = vi.mocked(resetAgentLlmConfig);
const mockedTestAgentLlmConnection = vi.mocked(testAgentLlmConnection);
const mockedUpdateAgentLlmConfig = vi.mocked(updateAgentLlmConfig);

const componentStubs = {
  "el-tooltip": { template: "<div><slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-button": { template: "<button @click=\"$emit('click')\"><slot /></button>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  "el-empty": { props: ["description"], template: "<div>{{ description }}</div>" },
  "el-table": { template: "<div><slot /></div>" },
  "el-table-column": { template: "<div><slot /></div>" },
  "el-descriptions": { template: "<div><slot /></div>" },
  "el-descriptions-item": { template: "<div><slot /></div>" },
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { template: "<div><slot /></div>" },
  "el-select": {
    name: "ElSelect",
    props: ["modelValue"],
    emits: ["update:modelValue", "change"],
    template: "<select><slot /></select>",
  },
  "el-option": true,
  "el-input": {
    name: "ElInput",
    props: ["modelValue", "type"],
    emits: ["update:modelValue"],
    template: "<input :type=\"type || 'text'\" :value=\"modelValue\" />",
  },
  "el-input-number": {
    name: "ElInputNumber",
    props: ["modelValue"],
    emits: ["update:modelValue"],
    template: "<input type=\"number\" :value=\"modelValue\" />",
  },
  "el-checkbox": {
    name: "ElCheckbox",
    props: ["modelValue"],
    emits: ["update:modelValue"],
    template: "<label><input type=\"checkbox\" /><slot /></label>",
  },
  "el-collapse": { template: "<div><slot /></div>" },
  "el-collapse-item": { props: ["title"], template: "<section>{{ title }}<slot /></section>" },
  DataAnalysis: true,
  ChatDotSquare: true,
  Lightning: true,
  Trophy: true,
  Connection: true,
  Refresh: true,
  Key: true,
  Check: true,
};

const mountWithPinia = (component: typeof AppHeader | typeof DashboardView | typeof SettingsView) => {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(component, { global: { plugins: [pinia], stubs: componentStubs } });
};
const leaderboard = { items: [] };
const datasets = { items: [], page: { current_page: 1, page_size: 1, total_items: 2, total_pages: 2 } };
const defaultAgentConfig = {
  source: "environment" as const,
  persistence: "process_memory" as const,
  enabled: false,
  provider: "none",
  base_url: "",
  model: "",
  has_api_key: false,
  timeout_seconds: 60,
  updated_at: null,
};
const runtimeAgentConfig = {
  ...defaultAgentConfig,
  source: "runtime" as const,
  enabled: true,
  provider: "deepseek",
  base_url: "https://example.invalid/v1",
  model: "planner-model",
  has_api_key: true,
  updated_at: "2026-08-24T00:00:00Z",
};

describe("system status components", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    mockedGetSystemInfo.mockResolvedValue({
      name: "IndusOpt API",
      version: "0.4.0",
      api_version: "v1",
      environment: "test",
      docs_url: "/docs",
      openapi_url: "/openapi.json",
    });
    mockedGetAgentLlmConfig.mockResolvedValue(defaultAgentConfig);
    mockedUpdateAgentLlmConfig.mockResolvedValue(runtimeAgentConfig);
    mockedResetAgentLlmConfig.mockResolvedValue(defaultAgentConfig);
    mockedTestAgentLlmConnection.mockResolvedValue({
      connected: true,
      provider: "deepseek",
      model: "planner-model",
      latency_ms: 12,
      message: "模型服务连接成功。",
    });
    vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm");
  });

  it.each([
    ["connecting", "正在检测"],
    ["ready", "系统就绪"],
    ["offline", "服务离线"],
  ] as const)("renders %s as %s in the header", async (status, expected) => {
    const wrapper = mountWithPinia(AppHeader);
    useSystemStore().status = status;
    await nextTick();
    expect(wrapper.text()).toContain("IndusOpt 工模智优");
    expect(wrapper.get(".status-text").text()).toBe(expected);
  });

  it("shows Dashboard failure instead of normal zero-data KPIs and supports a manual retry", async () => {
    mockedGetDatasets.mockRejectedValueOnce(new Error("Bad Gateway"));
    mockedGetDashboardLeaderboard.mockRejectedValueOnce(new Error("Bad Gateway"));
    const wrapper = mountWithPinia(DashboardView);
    await flushPromises();

    expect(wrapper.text()).toContain("工作台数据加载失败");
    expect(wrapper.text()).toContain("暂不可用");
    expect(wrapper.text()).not.toContain("0 个");

    mockedGetDatasets.mockResolvedValue(datasets);
    mockedGetDashboardLeaderboard.mockResolvedValue(leaderboard);
    const retryButton = wrapper.findAll("button").find((button) => button.text() === "重新加载");
    expect(retryButton).toBeDefined();
    await retryButton!.trigger("click");
    await flushPromises();

    expect(wrapper.text()).not.toContain("工作台数据加载失败");
    expect(wrapper.text()).toContain("2 个");
  });

  it("retries a failed Dashboard request once when health recovers", async () => {
    mockedGetDatasets.mockRejectedValueOnce(new Error("Bad Gateway")).mockResolvedValue(datasets);
    mockedGetDashboardLeaderboard.mockRejectedValueOnce(new Error("Bad Gateway")).mockResolvedValue(leaderboard);
    const wrapper = mountWithPinia(DashboardView);
    const systemStore = useSystemStore();
    systemStore.status = "offline";
    await flushPromises();

    systemStore.status = "ready";
    await flushPromises();

    expect(mockedGetDashboardLeaderboard).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("2 个");
  });

  it("reports a real offline result in Settings without a mock success", async () => {
    mockedGetHealthLive.mockRejectedValue(new Error("connection refused"));
    const wrapper = mountWithPinia(SettingsView);

    await wrapper.get("button").trigger("click");
    await flushPromises();

    expect(useSystemStore().status).toBe("offline");
    expect(ElMessage.error).toHaveBeenCalledWith("服务离线：无法连接后端，或数据库、任务队列尚未就绪");
    expect(ElMessage.success).not.toHaveBeenCalled();
  });

  it("loads the real Agent configuration without rendering a secret", async () => {
    mockedGetAgentLlmConfig.mockResolvedValue(runtimeAgentConfig);
    const wrapper = mountWithPinia(SettingsView);
    await flushPromises();

    expect(mockedGetAgentLlmConfig).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("运行时配置已生效");
    expect(wrapper.text()).toContain("已配置（不回显）");
    expect(wrapper.text()).not.toContain("sk-demo-key-indusopt-2026");
    expect(wrapper.find('input[type="password"]').exists()).toBe(true);
    expect(wrapper.find<HTMLInputElement>('input[type="password"]').element.value).toBe("");
  });

  it("fills the current official DeepSeek endpoint and default model", async () => {
    const wrapper = mountWithPinia(SettingsView);
    await flushPromises();

    const provider = wrapper.findComponent({ name: "ElSelect" });
    await provider.vm.$emit("update:modelValue", "deepseek");
    await provider.vm.$emit("change", "deepseek");
    await nextTick();

    const inputs = wrapper.findAllComponents({ name: "ElInput" });
    expect(inputs[0]!.props("modelValue")).toBe("deepseek-flash");
    expect(inputs[1]!.props("modelValue")).toBe("https://api.deepseek.com");
  });

  it("saves a new runtime configuration and immediately clears the input key", async () => {
    const wrapper = mountWithPinia(SettingsView);
    await flushPromises();

    const provider = wrapper.findComponent({ name: "ElSelect" });
    await provider.vm.$emit("update:modelValue", "deepseek");
    await provider.vm.$emit("change", "deepseek");
    const inputs = wrapper.findAllComponents({ name: "ElInput" });
    await inputs[0]!.vm.$emit("update:modelValue", "planner-model");
    await inputs[1]!.vm.$emit("update:modelValue", "https://example.invalid/v1");
    await inputs[2]!.vm.$emit("update:modelValue", "temporary-secret");

    const save = wrapper.findAll("button").find((button) => button.text().includes("保存并立即生效"));
    expect(save).toBeDefined();
    await save!.trigger("click");
    await flushPromises();

    expect(mockedUpdateAgentLlmConfig).toHaveBeenCalledWith({
      provider: "deepseek",
      base_url: "https://example.invalid/v1",
      model: "planner-model",
      api_key: "temporary-secret",
      clear_api_key: false,
      timeout_seconds: 60,
    });
    expect(wrapper.find<HTMLInputElement>('input[type="password"]').element.value).toBe("");
    expect(wrapper.text()).not.toContain("temporary-secret");
    expect(ElMessage.success).toHaveBeenCalledWith("Agent 模型配置已生效");
  });
});
