import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import DatasetDetailView from "../../src/views/DatasetDetailView.vue";
import { getDatasetDetail, getDatasetProfile, getDatasetVersions } from "../../src/api/datasets";
import type { DatasetProfile } from "../../src/types/api";

vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetProfile: vi.fn(),
  getDatasetVersions: vi.fn(),
}));
vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "dataset-id" } }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("element-plus", () => ({ ElMessage: { error: vi.fn() } }));

const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetProfile = vi.mocked(getDatasetProfile);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);

const stubs = {
  "el-tabs": { template: "<div><slot /></div>" },
  "el-tab-pane": { template: "<section><slot /></section>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-table": { template: "<table><slot /></table>" },
  "el-table-column": { props: ["label"], template: "<div>{{ label }}<slot /></div>" },
  "el-row": { template: "<div><slot /></div>" },
  "el-col": { template: "<div><slot /></div>" },
  "el-divider": { template: "<hr />" },
  "el-empty": { props: ["description"], template: "<div>{{ description }}</div>" },
  "el-button": { template: "<button><slot /></button>" },
  "el-collapse": { template: "<div><slot /></div>" },
  "el-collapse-item": { template: "<section><slot name=\"title\" /><slot /></section>" },
  "el-timeline": { template: "<div><slot /></div>" },
  "el-timeline-item": { template: "<div><slot /></div>" },
  "el-card": { template: "<div><slot /></div>" },
  StateView: true,
  DataLine: true,
  Share: true,
  ArrowRight: true,
};

const detail = {
  id: "dataset-id",
  name: "S4",
  source: "simulation",
  status: "ready",
  row_count: 120,
  column_count: 2,
  version_id: "version-id",
  preview: { rows: [], columns: [] },
};

const profile = (segments: Array<{ column: string; start_index: number; end_index: number; length: number }>) =>
  ({
    dataset_id: "dataset-id",
    version_id: "version-id",
    total_rows: 120,
    total_cols: 2,
    missing_rate: 0,
    missing_rates: { control: 0 },
    anomaly_counts: { control: 0 },
    interval_histogram: [],
    quality_score: 100,
    recommendations: [],
    frozen_segments: [],
    candidate_frozen_segments: segments,
    freeze_detection_summary: {
      candidate_count: segments.length,
      affected_column_count: new Set(segments.map((segment) => segment.column)).size,
      longest_segment: segments[0] ?? null,
    },
  }) as unknown as DatasetProfile;

async function mountView(currentProfile: DatasetProfile, currentDetail = detail) {
  mockedGetDatasetDetail.mockResolvedValue(currentDetail as never);
  mockedGetDatasetProfile.mockResolvedValue(currentProfile);
  mockedGetDatasetVersions.mockResolvedValue({ nodes: [], edges: [] } as never);
  const wrapper = mount(DatasetDetailView, { global: { plugins: [createPinia()], stubs } });
  await flushPromises();
  return wrapper;
}

describe("DatasetDetailView candidate frozen segments", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a Chinese summary and bounded structured details instead of raw JSON", async () => {
    const wrapper = await mountView(profile([
      { column: "control", start_index: 50, end_index: 99, length: 50 },
      { column: "pressure", start_index: 3, end_index: 31, length: 29 },
    ]));

    expect(wrapper.text()).toContain("候选异常冻结：共 2 段，涉及 2 个变量；最长区段为 control，第50–99行，共50点。");
    expect(wrapper.text()).toContain("变量");
    expect(wrapper.text()).toContain("开始位置");
    expect(wrapper.text()).toContain("结束位置");
    expect(wrapper.text()).toContain("持续点数");
    expect(wrapper.text()).not.toContain("start_index");
    expect(wrapper.text()).not.toContain("[{\"column\"");
  });

  it("renders the no-candidate empty state", async () => {
    const wrapper = await mountView(profile([]));

    expect(wrapper.text()).toContain("未检测到异常冻结段");
  });

  it("renders persisted simulation truth and preserves sigma zero", async () => {
    const wrapper = await mountView(profile([]), {
      ...detail,
      simulation: {
        root_version_id: "root-version",
        original_row_count: 1200,
        physical_columns: ["u1", "u2", "y"],
        time_column: "timestamp",
        scenario: "S4",
        system_type: "MISO ARX",
        true_na: 2,
        true_nb: [2, 2],
        true_delays: [3, 8],
        true_delays_by_input: { u1: 3, u2: 8 },
        noise_level: 0,
        provenance: {},
      },
    });

    expect(wrapper.text()).toContain("仿真真值概览");
    expect(wrapper.text()).toContain("原始样本量1200");
    expect(wrapper.text()).toContain("系统类型MISO ARX");
    expect(wrapper.text()).toContain("噪声水平 σ0");
  });

  it("uses missing semantics and hides simulation truth for uploaded datasets", async () => {
    const historical = await mountView(profile([]), { ...detail, simulation: null });
    expect(historical.text()).toContain("历史真值未记录");

    const uploaded = await mountView(profile([]), {
      ...detail,
      source: "upload",
      simulation: null,
    });
    expect(uploaded.text()).not.toContain("仿真真值概览");
  });
});
