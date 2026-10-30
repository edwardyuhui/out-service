import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { createPinia } from "pinia";
import RunsView from "../../src/views/RunsView.vue";
import { listDatasets } from "../../src/api/datasets";
import type { DatasetItem } from "../../src/types/api";

vi.mock("../../src/api/datasets", () => ({ listDatasets: vi.fn() }));
const mockedListDatasets = vi.mocked(listDatasets);

const ElSelectStub = defineComponent({
  name: "ElSelect",
  props: ["modelValue"],
  emits: ["update:modelValue"],
  template: "<div><slot /></div>",
});

const execution = (
  executionId: string,
  datasetId: string,
  goal: string,
  status: string,
  createdAt: string
) => ({
  execution_id: executionId,
  dataset_id: datasetId,
  workflow_status: status,
  created_at: createdAt,
  plan: { goal, steps: [{ step_id: "step-1" }] },
  artifacts: {},
});

const dataset = (id: string, name: string): DatasetItem => ({
  id,
  name,
  version_id: id + "-version",
  file_size_bytes: 128,
  row_count: 10,
  col_count: 3,
  created_at: "2026-09-09T10:00:00Z",
  time_column: "timestamp",
  input_columns: ["u"],
  output_column: "y",
});

beforeEach(() => {
  localStorage.clear();
  mockedListDatasets.mockReset();
});

describe("RunsView final polish", () => {
  it("keeps metadata content, filtering, sorting, and detail navigation while using Sans", async () => {
    localStorage.setItem("indusopt.recent_executions", JSON.stringify([
      execution("execution-new-123456", "dataset-new", "最新分析数据", "SUCCEEDED", "2026-09-09T10:00:00Z"),
      execution("execution-old-123456", "dataset-old", "较早失败任务", "FAILED", "2026-09-08T10:00:00Z"),
    ]));
    mockedListDatasets.mockResolvedValue({
      items: [
        dataset("dataset-new", "最新生产数据"),
        dataset("dataset-old", "历史验证数据"),
      ],
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
    });
    await router.push("/runs");
    await router.isReady();
    const wrapper = mount(RunsView, {
      global: {
        plugins: [router, createPinia()],
        stubs: {
          PageHeader: { props: ["title", "description"], template: "<header><h1>{{ title }}</h1><p>{{ description }}</p><slot name='actions' /></header>" },
          AppEmptyState: { template: "<div data-test='empty-state' />" },
          ElSelect: ElSelectStub,
          ElOption: true,
        },
      },
    });
    await flushPromises();

    const metadata = wrapper.findAll(".run-row__meta");
    expect(metadata).toHaveLength(2);
    expect(metadata[0]!.classes()).not.toContain("font-mono");
    expect(metadata[0]!.text()).toContain("数据集：最新生产数据");
    expect(metadata[0]!.text()).not.toContain("execution-new");
    expect(metadata[0]!.text()).toContain("1 个阶段");
    expect(mockedListDatasets).toHaveBeenCalledTimes(1);

    const source = readFileSync(resolve(process.cwd(), "src/views/RunsView.vue"), "utf8");
    const metadataRule = source.match(/\.run-row__meta\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(metadataRule).toContain("font-family: var(--font-sans)");
    expect(metadataRule).toContain("letter-spacing: normal");
    const datasetRule = source.match(/\.run-dataset\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(datasetRule).toContain("text-overflow: ellipsis");
    expect(datasetRule).toContain("white-space: nowrap");

    await wrapper.get(".runs-search-input").setValue("历史验证数据");
    expect(wrapper.findAll(".run-row")).toHaveLength(1);
    expect(wrapper.get(".run-row__goal").text()).toBe("较早失败任务");

    await wrapper.get(".runs-search-input").setValue("execution-new-123456");
    expect(wrapper.findAll(".run-row")).toHaveLength(1);
    expect(wrapper.get(".run-row__goal").text()).toBe("最新分析数据");

    await wrapper.get(".runs-search-input").setValue("较早失败");
    expect(wrapper.findAll(".run-row")).toHaveLength(1);
    expect(wrapper.get(".run-row__goal").text()).toBe("较早失败任务");

    await wrapper.get(".runs-search-input").setValue("");
    const selects = wrapper.findAllComponents(ElSelectStub);
    selects[0]!.vm.$emit("update:modelValue", "FAILED");
    await nextTick();
    expect(wrapper.findAll(".run-row")).toHaveLength(1);
    expect(wrapper.get(".run-row__goal").text()).toBe("较早失败任务");

    selects[0]!.vm.$emit("update:modelValue", "");
    selects[1]!.vm.$emit("update:modelValue", "asc");
    await nextTick();
    expect(wrapper.findAll(".run-row__goal").map((node) => node.text())).toEqual([
      "较早失败任务",
      "最新分析数据",
    ]);

    await wrapper.findAll(".run-row")[0]!.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/workspace/execution-old-123456");
  });

  it("uses a non-ID fallback when the dataset name cannot be resolved", async () => {
    localStorage.setItem("indusopt.recent_executions", JSON.stringify([
      execution("execution-missing", "dataset-missing-uuid", "未知来源任务", "SUCCEEDED", "2026-09-09T10:00:00Z"),
    ]));
    mockedListDatasets.mockResolvedValue({ items: [] });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
    });
    await router.push("/runs");
    await router.isReady();

    const wrapper = mount(RunsView, {
      global: {
        plugins: [router, createPinia()],
        stubs: {
          PageHeader: true,
          AppEmptyState: true,
          ElSelect: ElSelectStub,
          ElOption: true,
        },
      },
    });
    await flushPromises();

    expect(wrapper.get(".run-dataset").text()).toBe("数据集：未知数据集");
    expect(wrapper.get(".run-dataset").attributes("title")).toBe("未知数据集");
    expect(wrapper.text()).not.toContain("dataset-missing-uuid");
    expect(wrapper.text()).not.toContain("execution-missing");
  });
});
