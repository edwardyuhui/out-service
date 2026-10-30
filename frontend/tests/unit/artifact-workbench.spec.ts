import { defineComponent, nextTick } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactWorkbench from "../../src/components/artifact/ArtifactWorkbench.vue";
import { ApiError } from "../../src/api/client";
import type { ChartOption } from "../../src/components/ChartContainer.vue";
import type { CopilotExecutionSnapshot } from "../../src/types/api";
import { mergeSelectedSampleIndices } from "../../src/utils/segmentationArtifact";

const deliveryApi = vi.hoisted(() => ({ exportDataset: vi.fn() }));
const messageApi = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock("../../src/api/delivery", () => deliveryApi);
vi.mock("element-plus", () => ({
  ElMessage: messageApi,
  ElButton: {
    name: "ElButton",
    inheritAttrs: false,
    props: ["tag", "type"],
    template: `
      <component
        :is="tag || 'button'"
        v-bind="$attrs"
        class="el-button"
        :class="'el-button--' + (type || 'default')"
      ><slot /></component>
    `,
  },
}));

const ChartContainerStub = defineComponent({
  name: "ChartContainer",
  props: {
    options: { type: Object, required: true },
    height: { type: String, default: undefined },
  },
  template: '<div data-test="profile-chart" :data-height="height" />',
});

const executionWith = (
  tool: string,
  resultPayload: Record<string, unknown>
): CopilotExecutionSnapshot => ({
  execution_id: "execution-1",
  copilot_run_id: null,
  dataset_id: "dataset-1",
  initial_version_id: "version-0",
  current_version_id: "version-0",
  planner_source: "deterministic",
  workflow_status: "SUCCEEDED",
  current_step_id: null,
  pending_confirmation_step_id: null,
  plan: {
    goal: "test artifact rendering",
    dataset_id: "dataset-1",
    steps: [{
      step_id: "step-1",
      tool,
      depends_on: [],
      parameters: {},
      requires_confirmation: false,
      status: "completed",
    }],
    stop_conditions: [],
    assumptions: [],
  },
  artifacts: {},
  error_code: null,
  error_message: null,
  created_at: "2026-09-09T00:00:00Z",
  updated_at: "2026-09-09T00:00:01Z",
  finished_at: "2026-09-09T00:00:01Z",
  step_runs: [{
    step_id: "step-1",
    sequence: 1,
    tool,
    status: "completed",
    requires_confirmation: false,
    confirmation_status: "NOT_REQUIRED",
    attempt_count: 1,
    source_version_id: "version-0",
    result_version_id: null,
    input_payload: {},
    result_payload: resultPayload,
    processing_run_ids: [],
    error_code: null,
    error_message: null,
    started_at: "2026-09-09T00:00:00Z",
    finished_at: "2026-09-09T00:00:01Z",
  }],
});

const mountWorkbench = async (execution: CopilotExecutionSnapshot) => {
  const wrapper = mount(ArtifactWorkbench, {
    props: { execution },
    global: { stubs: { ChartContainer: ChartContainerStub } },
  });
  await nextTick();
  return wrapper;
};

beforeEach(() => {
  vi.clearAllMocks();
});

const reportExecution = (): CopilotExecutionSnapshot => {
  const reportId = "44444444-4444-4444-4444-444444444444";
  const execution = executionWith("generate_report", {
    report_id: reportId,
    execution_id: "execution-1",
    dataset_id: "dataset-1",
    title: "生产分析报告",
    markdown: "# 关键结论\n\n- 清洗与异常检测均已完成。",
    fully_resolved: true,
    unresolved: [],
    bindings: [],
    artifact_uri: `reports/${reportId}.md`,
    narration_source: "template",
    llm_provider: "none",
    llm_model: "none",
  });
  const steps = [
    ["profile", "profile_dataset", { summary: "画像完成", result: { n_samples: 1200 } }],
    ["anomaly", "detect_anomalies", { summary: "异常检测完成", result: { anomaly_count: 6, anomaly_ratio: 0.005 } }],
    ["clean", "clean_data", {
      summary: {
        rows_before: 1200,
        rows_after: 1198,
        changes: {
          unique_changed_cells: 7,
          missing_value_fills: 4,
          outlier_replacements: 3,
          duplicate_timestamps_processed: 0,
          resampling_empty_rows_created: 0,
          smoothing_changes: 0,
        },
      },
      total_cleaned_points: 7,
    }],
    ["report", "generate_report", execution.step_runs[0].result_payload],
  ] as const;
  execution.plan.steps = steps.map(([stepId, tool]) => ({
    step_id: stepId,
    tool,
    depends_on: [],
    parameters: {},
    requires_confirmation: false,
    status: "completed",
  }));
  execution.step_runs = steps.map(([stepId, tool, payload], index) => ({
    ...execution.step_runs[0],
    step_id: stepId,
    sequence: index + 1,
    tool,
    result_payload: payload,
  }));
  return execution;
};

describe("ArtifactWorkbench profile_dataset rendering", () => {
  it("renders the persisted profile envelope as summary, cards, chart, details, and collapsed raw data", async () => {
    const wrapper = await mountWorkbench(executionWith("profile_dataset", {
      summary: "数据画像完成：1200 个样本，2 个输入变量。",
      result: {
        n_samples: 1200,
        fingerprint: {
          fields: [
            "log_sample_count",
            "input_count",
            "missing_ratio",
            "anomaly_ratio",
            "snr_db_scaled",
            "dynamic_ratio",
            "output_autocorrelation",
            "input_autocorrelation",
            "collinearity_scaled",
            "future_metric",
          ],
          values: {
            log_sample_count: 0.5132,
            input_count: 0.25,
            missing_ratio: 0.02,
            anomaly_ratio: 0.2242,
            snr_db_scaled: 0.72,
            dynamic_ratio: 0.42,
            output_autocorrelation: 0.81,
            input_autocorrelation: 0.68,
            collinearity_scaled: 0.36,
            future_metric: "raw-value",
          },
        },
      },
    }));

    expect(wrapper.get('[data-test="profile-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="profile-summary"]').text()).toBe(
      "数据画像完成：1200 个样本，2 个输入变量。"
    );
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("1,200");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("2.00%");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("画像离群比例22.42%");
    expect(wrapper.get('[data-test="profile-overview"]').text()).not.toContain("异常率");
    expect(wrapper.get('[data-test="profile-overview"]').text()).not.toContain("0.2242");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("42.00%");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("样本规模指纹");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("不代表原始样本数");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("指标明细");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("说明");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("画像离群比例");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("与正式 Hampel 异常检测结果不是同一指标");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).not.toContain("仅解释后端已定义的指纹语义");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("future_metric");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("raw-value");
    expect(wrapper.get('[data-test="profile-chart"]').attributes("data-height")).toBe("180px");
    expect(wrapper.find('[data-test="profile-raw-data"]').exists()).toBe(false);
    expect(wrapper.find(".aw-json").exists()).toBe(false);

    const chart = wrapper.getComponent(ChartContainerStub);
    const options = chart.props("options") as ChartOption;
    expect(options.xAxis).toMatchObject({ type: "value", min: 0, max: 100 });
    expect(options.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "bar", data: [2, 22.42] }),
    ]));

    await wrapper.get(".profile-raw__toggle").trigger("click");
    expect(wrapper.get('[data-test="profile-raw-data"]').text()).toContain('"fingerprint"');
    expect(wrapper.get(".profile-raw__toggle").text()).toBe("收起原始数据");
  });

  it("handles malformed and missing profile fields without crashing or inventing values", async () => {
    const wrapper = await mountWorkbench(executionWith("profile_dataset", {
      result: {
        fingerprint: {
          fields: ["missing_ratio", "unknown_without_value"],
          values: { missing_ratio: "not-a-number" },
        },
      },
    }));

    expect(wrapper.get('[data-test="profile-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="profile-quality-chart"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="profile-overview"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("not-a-number");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("unknown_without_value");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("不可用");
    expect(wrapper.find('[data-test="profile-raw-data"]').exists()).toBe(false);
  });

  it("keeps unknown generic artifacts on the existing JSON renderer", async () => {
    const wrapper = await mountWorkbench(executionWith("unknown_future_tool", {
      summary: "特征筛选完成",
      result: { selected_count: 2 },
    }));

    expect(wrapper.find('[data-test="profile-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="cleaning-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.get(".aw-section__label").text()).toBe("工件详细数据 (Payload Details)");
    expect(wrapper.get(".aw-json").text()).toContain('"selected_count": 2');
  });

  it("routes the saved collinearity result to switchable heatmaps and a VIF chart", async () => {
    const wrapper = await mountWorkbench(executionWith("analyze_collinearity", {
      task: { id: "internal-task-id" },
      variables: ["fuel_flow", "exhaust_fan_speed", "raw_material_flow"],
      matrix: [[1, 0.21, null], [0.21, 1, 0.18], [null, 0.18, 1]],
      spearman_matrix: [[1, 0.31, null], [0.31, 1, 0.11], [null, 0.11, 1]],
      vif_scores: { fuel_flow: 1.2, exhaust_fan_speed: null, raw_material_flow: 1.4 },
      condition_number: null,
      recommendations: [
        { variable: "fuel_flow", action: "keep", reason: "相关性低" },
        { variable: "exhaust_fan_speed", action: "review", reason: "VIF 无法计算" },
        { variable: "raw_material_flow", action: "keep", reason: "相关性低" },
      ],
    }));

    expect(wrapper.get(".aw-tab.is-active").text()).toBe("共线性分析");
    expect(wrapper.get('[data-test="collinearity-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("本次未建议剔除输入变量");
    expect(wrapper.text()).toContain("N/A");
    expect(wrapper.text()).toContain("exhaust_fan_speed");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("internal-task-id");

    const charts = wrapper.findAllComponents(ChartContainerStub);
    expect(charts).toHaveLength(2);
    const pearson = charts[0].props("options") as ChartOption;
    const pearsonSeries = pearson.series as { type: string; data: unknown[] }[];
    expect(pearsonSeries[0].type).toBe("heatmap");
    expect(pearsonSeries[0].data).toContainEqual([1, 0, 0.21]);
    expect(pearsonSeries[0].data).not.toContainEqual([2, 0, 0]);
    expect(pearsonSeries[1].data).toContainEqual([2, 0]);
    const vif = charts[1].props("options") as ChartOption;
    expect((vif.series as { data: unknown[] }[])[0].data).toEqual([1.2, null, 1.4]);

    await wrapper.get('[data-test="correlation-mode-spearman"]').trigger("click");
    const spearman = charts[0].props("options") as ChartOption;
    expect((spearman.series as { data: unknown[] }[])[0].data).toContainEqual([1, 0, 0.31]);
  });

  it("shows accurate empty states for incomplete saved collinearity fields", async () => {
    const wrapper = await mountWorkbench(executionWith("analyze_collinearity", {
      task: { id: "internal-task-id" },
      variables: ["u1", "u2"],
      recommendations: [],
    }));

    expect(wrapper.findAllComponents(ChartContainerStub)).toHaveLength(0);
    expect(wrapper.text()).toContain("无可用数据");
    expect(wrapper.text()).toContain("当前结果未提供变量建议");
    expect(wrapper.text()).not.toContain("本次未建议剔除输入变量");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
  });

  it("keeps completed collinearity and feature steps visible when historical payloads are empty", async () => {
    const collinearity = await mountWorkbench(executionWith("analyze_collinearity", {}));
    expect(collinearity.get(".aw-tab.is-active").text()).toBe("共线性分析");
    expect(collinearity.get('[data-test="collinearity-artifact-renderer"]').text()).toContain("无可用数据");
    collinearity.unmount();

    const feature = await mountWorkbench(executionWith("select_variables", {}));
    expect(feature.get(".aw-tab.is-active").text()).toBe("特征筛选");
    expect(feature.get('[data-test="feature-selection-empty"]').text()).toContain("未保存完整的变量决策");
  });

  it("reopens a saved keep-all feature result with the original decision and no new version", async () => {
    const execution = executionWith("select_variables", {
      data_changed: false,
      summary: {
        dropped_columns: [],
        kept_input_columns: ["fuel_flow", "exhaust_fan_speed", "raw_material_flow"],
        reason: "正式共线性分析未建议剔除输入变量，保留全部输入且未创建新数据版本。",
      },
    });
    execution.step_runs[0].source_version_id = "source-version-id";
    const wrapper = await mountWorkbench(execution);

    expect(wrapper.get('[data-test="feature-selection-counts"]').text()).toMatch(/保留\s*3/);
    expect(wrapper.get('[data-test="feature-selection-counts"]').text()).toMatch(/剔除\s*0/);
    expect(wrapper.get('[data-test="feature-selection-version-status"]').text()).toContain("数据未变");
    expect(wrapper.get('[data-test="feature-selection-version-status"]').text()).toContain("未生成新版本");
    expect(wrapper.get('[data-test="feature-selection-reason"]').text()).toContain("正式共线性分析未建议剔除输入变量");
    expect(wrapper.get('[data-test="feature-selection-kept"]').text()).toContain("raw_material_flow");
    expect(wrapper.find(".aw-json").exists()).toBe(false);

    wrapper.unmount();
    const reopened = await mountWorkbench(execution);
    expect(reopened.get('[data-test="feature-selection-counts"]').text()).toMatch(/保留\s*3/);
    expect(reopened.get('[data-test="feature-selection-version-status"]').text()).toContain("未生成新版本");
  });

  it("shows actual dropped inputs and saved source/result versions", async () => {
    const execution = executionWith("select_variables", {
      source_version_id: "source-version-id",
      result_version_id: "result-version-id",
      summary: {
        dropped_columns: ["u2"],
        kept_input_columns: ["u1", "u3"],
        rows_before: 600,
        rows_after: 600,
      },
    });
    execution.step_runs[0].source_version_id = "source-version-id";
    execution.step_runs[0].result_version_id = "result-version-id";
    const wrapper = await mountWorkbench(execution);

    expect(wrapper.get('[data-test="feature-selection-counts"]').text()).toMatch(/保留\s*2/);
    expect(wrapper.get('[data-test="feature-selection-counts"]').text()).toMatch(/剔除\s*1/);
    expect(wrapper.get('[data-test="feature-selection-dropped"]').text()).toContain("u2");
    expect(wrapper.get('[data-test="feature-selection-kept"]').text()).toContain("u1");
    expect(wrapper.get('[data-test="feature-selection-kept"]').text()).toContain("u3");
    expect(wrapper.get('[data-test="feature-selection-version-status"]').text()).toContain("已生成新版本");
    expect(wrapper.get('[data-test="feature-selection-version-status"]').text()).toContain("来源版本");
    expect(wrapper.get('[data-test="feature-selection-version-status"]').text()).toContain("结果版本");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
  });

  it("routes ARX artifacts to the dedicated business renderer", async () => {
    const wrapper = await mountWorkbench(executionWith("arx_fit", {
      model_id: "11111111-1111-1111-1111-111111111111",
      processing_run_id: "22222222-2222-2222-2222-222222222222",
      version_id: "33333333-3333-3333-3333-333333333333",
      estimator: "ols",
      model_structure: {
        model_type: "ARX",
        input_columns: ["u1", "u2", "u3"],
        output_column: "y",
        na: 2,
        nb: { u1: 2, u2: 3, u3: 1 },
        delays: { u1: 0, u2: 4, u3: 1 },
        estimator: "ols",
        ridge_alpha: null,
        parameter_count: 8,
      },
      validation: {
        free_run_fit: 84.237,
        free_run_rmse: 0.30000000000004,
        one_step_fit: 92.415,
        fit_gap: 8.178,
        residual_whiteness_ratio: 0.81234,
        stable: true,
        steady_state_gains: { u1: 1.24, u2: -0.42 },
      },
      metrics: { aic: -126.789, bic: -112.456 },
      coefficients: { a1: -1.2, a2: 0.35, b_u1_0: 0.42 },
      prior_violations: [],
    }));

    const renderer = wrapper.get('[data-test="arx-model-artifact-renderer"]');
    expect(wrapper.find('[data-test="profile-artifact-renderer"]').exists()).toBe(false);
    expect(renderer.text()).toContain("ARX 模型结果");
    expect(renderer.text()).not.toContain("Model identification");
    expect(renderer.text()).toContain("使用验证集评估模型选择效果");
    expect(renderer.get('[data-test="arx-model-summary"]').text()).toContain("估计方法OLS");
    expect(renderer.get('[data-test="arx-model-summary"]').text()).toContain("输入通道3");
    expect(renderer.get('[data-test="arx-model-summary"]').text()).toContain("参数数量8");
    expect(renderer.get('[data-test="arx-model-summary"]').text()).toContain("稳定性稳定");

    const structure = renderer.get('[data-test="arx-model-structure"]');
    expect(structure.text()).toContain("u1");
    expect(structure.text()).toContain("nb = 2");
    expect(structure.text()).toContain("delay = 4");
    expect(structure.text()).toContain("na = 2");
    expect(structure.text()).toContain("输出y");
    const channelRows = renderer.findAll('[data-test="arx-channel-table"] tbody tr');
    expect(channelRows[0]?.text()).toContain("u1");
    expect(channelRows[0]?.text()).toContain("1.24");
    expect(channelRows[1]?.text()).toContain("u2");
    expect(channelRows[1]?.text()).toContain("-0.42");
    expect(channelRows[2]?.text()).toContain("u3");
    expect(channelRows[2]?.text()).toContain("—");

    const validation = renderer.get('[data-test="arx-validation"]').text();
    expect(validation).toContain("验证集 · 模型选择依据");
    expect(validation).not.toContain("Validation · 模型选择依据");
    expect(validation).toContain("Free-run FIT84.24%");
    expect(validation).toContain("Free-run RMSE0.3");
    expect(validation).toContain("One-step FIT92.42%");
    expect(validation).toContain("Fit Gap8.18 pp");
    expect(validation).toContain("Residual Whiteness0.8123");
    expect(validation).not.toContain("AIC");
    expect(validation).not.toContain("BIC");

    const coefficientOptions = renderer
      .get('[data-test="arx-coefficients"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(coefficientOptions.yAxis).toEqual(expect.objectContaining({
      data: ["a1", "a2", "b_u1_0"],
    }));
    expect(coefficientOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [-1.2, 0.35, 0.42] }),
    ]);

    const primaryText = [
      renderer.get(".arx-model__header").text(),
      renderer.get('[data-test="arx-model-summary"]').text(),
      structure.text(),
      validation,
      renderer.get('[data-test="arx-coefficients"]').text(),
    ].join(" ");
    expect(primaryText).not.toContain("11111111-1111-1111-1111-111111111111");
    const technical = renderer.get('[data-test="arx-model-technical-details"]');
    expect(technical.attributes("open")).toBeUndefined();
    expect(technical.text()).toContain("11111111-1111-1111-1111-111111111111");
    expect(technical.text()).toContain("AIC -126.789");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
  });

  it("gracefully degrades historical ARX artifacts without guessing structure", async () => {
    const wrapper = await mountWorkbench(executionWith("fit_arx", {
      model_id: "11111111-1111-1111-1111-111111111111",
      estimator: "ridge",
      coefficients: { a1: -0.9 },
    }));

    expect(wrapper.get('[data-test="arx-model-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="arx-model-structure-empty"]').text()).toContain(
      "该历史任务未记录完整模型结构"
    );
    expect(wrapper.find('[data-test="arx-channel-table"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("delay =");
  });
});

describe("ArtifactWorkbench model evaluation rendering", () => {
  const evaluationPayload = () => ({
    model_id: "44444444-4444-4444-4444-444444444444",
    source_version_id: "55555555-5555-5555-5555-555555555555",
    processing_run_id: "66666666-6666-6666-6666-666666666666",
    evaluation_scope: "test",
    model_structure: {
      model_type: "ARX",
      input_columns: ["u1", "u2"],
      output_column: "y",
      na: 2,
      nb: { u1: 2, u2: 2 },
      delays: { u1: 0, u2: 0 },
      estimator: "ols",
      ridge_alpha: null,
      parameter_count: 6,
    },
    model_health: { stable: true, max_pole_modulus: 0.743210000000004 },
    test: {
      free_run: { fit: 84.567, r2: 0.81234, rmse: 0.30000000000004, mae: 0.24567, nrmse: 0.12345 },
      one_step: { fit: 92.345, r2: 0.92345, rmse: 0.18000000000003, mae: 0.14567, nrmse: 0.07345 },
      n_samples: 4,
    },
    series: {
      sample_indices: [960, 961, 962, 963],
      timestamps: [],
      y_true: [1, 2, 1.5, 2.2],
      free_run_prediction: [0.8, 1.7, 1.3, 2],
      one_step_prediction: [0.95, 2.05, 1.48, 2.18],
      one_step_residual: [0.05, -0.05, 0.02, 0.02],
      free_run_residual: [0.2, 0.3, 0.2, 0.2],
    },
    residual_diagnostics: {
      partition: "test",
      residual_type: "one_step",
      residual_whiteness_ratio: 0.81234,
      acf_values: [1, 0.24, -0.11],
      confidence_interval: 0.12,
    },
    validation: { residual_whiteness_ratio: 0.11111 },
  });

  it("defaults to Free-run and switches both metrics and prediction series", async () => {
    const wrapper = await mountWorkbench(executionWith("evaluate_model", evaluationPayload()));
    const renderer = wrapper.get('[data-test="model-evaluation-artifact-renderer"]');

    expect(renderer.text()).toContain("最终测试集评价");
    expect(renderer.text()).not.toContain("Final evaluation");
    expect(renderer.get('[data-test="evaluation-scope-badge"]').text()).toBe("Held-out Test");
    expect(renderer.get('[data-test="evaluation-leakage-note"]').text()).toContain(
      "未参与模型训练、参数选择或闭环寻优"
    );
    expect(renderer.get('[data-test="prediction-mode-free-run"]').classes()).toContain("is-active");
    expect(renderer.get('[data-test="prediction-mode-free-run"]').text()).toBe("Free-run");
    expect(renderer.get('[data-test="prediction-mode-one-step"]').text()).toBe("One-step");
    const metrics = renderer.get('[data-test="evaluation-metrics"]');
    expect(metrics.attributes("data-mode")).toBe("free_run");
    expect(metrics.text()).toContain("FIT84.57%");
    expect(metrics.text()).toContain("R²0.8123");
    expect(metrics.text()).toContain("RMSE0.3");
    expect(metrics.text()).not.toContain("0.30000000000004");

    const predictionChart = renderer
      .get('[data-test="evaluation-prediction-section"]')
      .getComponent(ChartContainerStub);
    let predictionOptions = predictionChart.props("options") as ChartOption;
    expect(predictionOptions.legend).toEqual(expect.objectContaining({
      data: ["真实值", "自由运行预测"],
    }));
    expect(predictionOptions.xAxis).toEqual(expect.objectContaining({
      data: [960, 961, 962, 963],
    }));
    expect(predictionOptions.series).toEqual([
      expect.objectContaining({ name: "真实值", data: [1, 2, 1.5, 2.2] }),
      expect.objectContaining({ name: "自由运行预测", data: [0.8, 1.7, 1.3, 2] }),
    ]);
    expect(predictionOptions.dataZoom).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "inside", filterMode: "none" }),
      expect.objectContaining({ type: "slider", filterMode: "none" }),
    ]));

    await renderer.get('[data-test="prediction-mode-one-step"]').trigger("click");
    await nextTick();
    expect(metrics.attributes("data-mode")).toBe("one_step");
    expect(metrics.text()).toContain("FIT92.34%");
    expect(metrics.text()).toContain("R²0.9235");
    predictionOptions = predictionChart.props("options") as ChartOption;
    expect(predictionOptions.series).toEqual([
      expect.objectContaining({ name: "真实值", data: [1, 2, 1.5, 2.2] }),
      expect.objectContaining({ name: "单步预测", data: [0.95, 2.05, 1.48, 2.18] }),
    ]);
  });

  it("keeps residuals fixed to Test one-step data and reads Test diagnostics", async () => {
    const wrapper = await mountWorkbench(executionWith("evaluate_model", evaluationPayload()));
    const renderer = wrapper.get('[data-test="model-evaluation-artifact-renderer"]');
    const residualChart = renderer
      .get('[data-test="evaluation-residual-section"]')
      .getComponent(ChartContainerStub);
    const before = residualChart.props("options") as ChartOption;
    expect(before.series).toEqual([
      expect.objectContaining({
        name: "一步预测残差",
        data: [0.05, -0.05, 0.02, 0.02],
        markLine: expect.objectContaining({ data: [{ yAxis: 0 }] }),
      }),
    ]);

    await renderer.get('[data-test="prediction-mode-one-step"]').trigger("click");
    await nextTick();
    expect((residualChart.props("options") as ChartOption).series).toEqual(before.series);
    const diagnostics = renderer.get('[data-test="evaluation-diagnostics"]').text();
    expect(diagnostics).toContain("残差白度0.8123");
    expect(diagnostics).not.toContain("0.1111");
    expect(diagnostics).toContain("模型稳定性稳定");
    expect(diagnostics).toContain("最大极点模0.7432");
    expect(diagnostics).toContain("测试样本数4");
  });

  it("renders Test one-step ACF and keeps complete UUIDs in closed technical details", async () => {
    const wrapper = await mountWorkbench(executionWith("evaluate_model", evaluationPayload()));
    const renderer = wrapper.get('[data-test="model-evaluation-artifact-renderer"]');
    const acfSection = renderer.get('[data-test="evaluation-acf-section"]');
    expect(acfSection.text()).toContain("Test one-step residual");
    expect(acfSection.text()).toContain("ACF");
    const acfOptions = acfSection.getComponent(ChartContainerStub).props("options") as ChartOption;
    expect(acfOptions.xAxis).toEqual(expect.objectContaining({ data: [0, 1, 2] }));
    expect(acfOptions.series).toEqual([
      expect.objectContaining({
        type: "bar",
        data: [1, 0.24, -0.11],
        markLine: expect.objectContaining({
          data: [{ yAxis: 0.12 }, { yAxis: -0.12 }],
        }),
      }),
    ]);

    const primaryText = [
      renderer.get(".evaluation-header").text(),
      renderer.get('[data-test="evaluation-metrics"]').text(),
      renderer.get('[data-test="evaluation-prediction-section"]').text(),
      renderer.get('[data-test="evaluation-residual-section"]').text(),
      renderer.get('[data-test="evaluation-diagnostics"]').text(),
      acfSection.text(),
    ].join(" ");
    expect(primaryText).not.toContain("44444444-4444-4444-4444-444444444444");
    const technical = renderer.get('[data-test="model-evaluation-technical-details"]');
    expect(technical.attributes("open")).toBeUndefined();
    expect(technical.text()).toContain("44444444-4444-4444-4444-444444444444");
    expect(technical.text()).toContain("55555555-5555-5555-5555-555555555555");
  });

  it("keeps historical metric-only evaluations usable without fake charts", async () => {
    const wrapper = await mountWorkbench(executionWith("evaluate_model", {
      model_id: "44444444-4444-4444-4444-444444444444",
      test: {
        free_run: { fit: 70.5, r2: 0.61, rmse: 0.8, mae: 0.6, nrmse: 0.4 },
        one_step: { fit: 81.2, r2: 0.77, rmse: 0.5, mae: 0.4, nrmse: 0.25 },
      },
    }));

    expect(wrapper.get('[data-test="evaluation-metrics"]').text()).toContain("FIT70.50%");
    expect(wrapper.get('[data-test="evaluation-prediction-empty"]').text()).toContain(
      "该历史评价未保存测试序列"
    );
    expect(wrapper.get('[data-test="evaluation-residual-empty"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="evaluation-diagnostics-empty"]').text()).toContain(
      "该历史评价未保存残差诊断数据"
    );
    expect(wrapper.find('[data-test="evaluation-prediction-chart"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="evaluation-acf-chart"]').exists()).toBe(false);
  });
});

describe("ArtifactWorkbench segmentation rendering", () => {
  const segmentationPayload = () => ({
    source_version_id: "11111111-1111-1111-1111-111111111111",
    processing_run_id: "22222222-2222-2222-2222-222222222222",
    timestamps: Array.from(
      { length: 12 },
      (_, index) => `2026-09-09T00:00:${String(index).padStart(2, "0")}Z`
    ),
    series: { u1: Array.from({ length: 12 }, (_, index) => index) },
    segments: [
      {
        segment_id: "seg_01",
        start_index: 1,
        end_index: 3,
        start_time: "2026-09-09T00:00:01Z",
        end_time: "2026-09-09T00:00:03Z",
        rank: 1,
        n_rows: 3,
        information_gain_bits: 1.6,
        dynamic_score: 1.6,
        snr_db: 12.4,
      },
      {
        segment_id: "seg_02",
        start_index: 8,
        end_index: 9,
        start_time: "2026-09-09T00:00:08Z",
        end_time: "2026-09-09T00:00:09Z",
        rank: 2,
        n_rows: 2,
        information_gain_bits: 0.8,
        dynamic_score: 0.8,
        snr_db: 10.2,
      },
    ],
    selection: {
      candidate_count: 7,
      gated_count: 4,
      selected_count: 2,
      selected_rows: 5,
      coverage_ratio: 5 / 12,
    },
    selected_indices: [1, 2, 3, 8, 9],
  });

  it("renders real selection facts, coverage, and information-gain ranking", async () => {
    const wrapper = await mountWorkbench(
      executionWith("detect_dynamic_segments", segmentationPayload())
    );

    expect(wrapper.get('[data-test="segmentation-artifact-renderer"]').exists()).toBe(true);
    const overview = wrapper.get('[data-test="segmentation-overview"]').text();
    expect(overview).toContain("入选样本数5");
    expect(overview).toContain("入选区间数2");
    expect(overview).toContain("全量可建模样本覆盖率41.67%");
    expect(overview).toContain("候选窗口数7");
    expect(wrapper.get('[data-test="segmentation-summary"]').text()).toContain(
      "在训练分区中筛选出 2 个有效动态区间，共覆盖 5 个去重建模样本"
    );
    expect(wrapper.get('[data-test="segmentation-coverage-legend"]').text()).toContain(
      "整体样本轴"
    );
    expect(wrapper.get('[data-test="segmentation-coverage-legend"]').text()).toContain(
      "入选建模区间"
    );
    expect(wrapper.get('[data-test="segmentation-ranking-title"]').text()).toBe(
      "入选区间信息增益"
    );
    expect(wrapper.find('[data-test="segmentation-ranking-limit-note"]').exists()).toBe(false);

    const coverageOptions = wrapper
      .get('[data-test="segmentation-coverage-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    const coverageSeries = (coverageOptions.series as Array<Record<string, unknown>>)[0];
    const markArea = coverageSeries.markArea as { data: unknown[] };
    expect(markArea.data).toHaveLength(2);

    const rankingOptions = wrapper
      .get('[data-test="segmentation-ranking-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(rankingOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [1.6, 0.8] }),
    ]);
    expect(wrapper.find('[data-test="segmentation-raw-data"]').exists()).toBe(false);
    expect(wrapper.find(".font-mono").exists()).toBe(false);
  });

  it("labels and explains the compact Top 8 ranking when more segments are selected", async () => {
    const payload = segmentationPayload();
    payload.segments = Array.from({ length: 10 }, (_, index) => ({
      segment_id: `seg_${String(index + 1).padStart(2, "0")}`,
      start_index: index,
      end_index: index,
      start_time: payload.timestamps[index],
      end_time: payload.timestamps[index],
      rank: index + 1,
      n_rows: 1,
      information_gain_bits: 10 - index,
      dynamic_score: 10 - index,
      snr_db: 12 - index / 10,
    }));
    payload.selection.selected_count = 10;
    payload.selection.selected_rows = 10;
    payload.selection.coverage_ratio = 10 / 12;
    payload.selected_indices = Array.from({ length: 10 }, (_, index) => index);

    const wrapper = await mountWorkbench(
      executionWith("detect_dynamic_segments", payload)
    );

    expect(wrapper.get('[data-test="segmentation-ranking-title"]').text()).toBe(
      "入选区间信息增益 Top 8"
    );
    expect(wrapper.get('[data-test="segmentation-ranking-limit-note"]').text()).toBe(
      "共入选 10 个区间，当前展示信息增益最高的前 8 个。"
    );

    const rankingOptions = wrapper
      .get('[data-test="segmentation-ranking-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(rankingOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [10, 9, 8, 7, 6, 5, 4, 3] }),
    ]);
  });

  it("deterministically merges persisted selected sample indices into intervals", async () => {
    expect(mergeSelectedSampleIndices([1, 2, 3, 8, 9])).toEqual([
      { startIndex: 1, endIndex: 3, count: 3 },
      { startIndex: 8, endIndex: 9, count: 2 },
    ]);

    const wrapper = await mountWorkbench(executionWith("detect_dynamic_segments", {
      timestamps: Array.from({ length: 12 }, (_, index) => String(index)),
      selected_sample_indices: [1, 2, 3, 8, 9],
    }));
    expect(wrapper.get('[data-test="segmentation-overview"]').text()).toContain("入选样本数5");
    expect(wrapper.get('[data-test="segmentation-coverage-chart"]').exists()).toBe(true);
  });

  it("keeps raw JSON collapsed inside technical details", async () => {
    const wrapper = await mountWorkbench(
      executionWith("detect_dynamic_segments", segmentationPayload())
    );

    const technical = wrapper.get('[data-test="segmentation-technical-details"]');
    expect(technical.get("button").attributes("aria-expanded")).toBe("false");
    expect(wrapper.find('[data-test="segmentation-raw-data"]').exists()).toBe(false);

    await technical.get("button").trigger("click");
    expect(wrapper.get('[data-test="segmentation-raw-data"]').text()).toContain(
      '"selected_indices"'
    );
    expect(wrapper.get('[data-test="segmentation-raw-data"]').classes()).toContain("font-mono");
  });

  it("shows a business empty state when no visual selection evidence exists", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_dynamic_segments", {
      selected_indices: [],
      segments: [],
    }));

    expect(wrapper.get('[data-test="segmentation-empty"]').text()).toContain(
      "当前结果未包含可视化区间数据"
    );
    expect(wrapper.find('[data-test="segmentation-coverage-chart"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="segmentation-ranking-chart"]').exists()).toBe(false);
  });
});

describe("ArtifactWorkbench anomaly rendering", () => {
  it("renders the formal anomaly envelope without a default JSON wall or invented position evidence", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      summary: "检出疑似异常点 6 个（占比 0.30%），噪声水平估计 0.02417。",
      result: {
        anomaly_count: 3,
        anomaly_ratio: 0.0025,
        future_metric: "raw-value",
      },
    }));

    expect(wrapper.get('[data-test="anomaly-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="anomaly-summary"]').text()).toContain("噪声水平估计 0.02417");
    expect(wrapper.get('[data-test="anomaly-overview"]').text()).toContain("异常点数量3");
    expect(wrapper.get('[data-test="anomaly-overview"]').text()).toContain("异常比例0.25%");
    expect(wrapper.get('[data-test="anomaly-overview"]').text()).not.toContain("画像离群比例");
    expect(wrapper.get('[data-test="anomaly-metrics"]').text()).toContain("疑似异常样本数量");
    expect(wrapper.get('[data-test="anomaly-other-metrics"]').text()).toContain("future_metric");
    expect(wrapper.get('[data-test="anomaly-other-metrics"]').text()).toContain("raw-value");
    const ratioChart = wrapper.get('[data-test="anomaly-ratio-chart"]');
    const chart = ratioChart.getComponent(ChartContainerStub);
    expect(chart.attributes("data-height")).toBe("112px");
    const options = chart.props("options") as ChartOption;
    expect(options.xAxis).toMatchObject({ type: "value", min: 0, max: 100, interval: 20 });
    expect(options.yAxis).toMatchObject({ type: "category", data: ["异常比例"] });
    expect(options.series).toEqual([
      expect.objectContaining({ type: "bar", data: [0.25] }),
    ]);
    expect(options.series).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ barMinHeight: expect.any(Number) }),
    ]));
    const tooltip = options.tooltip as { formatter?: (params: unknown) => string };
    expect(tooltip.formatter?.({ value: 0.25 })).toContain("异常比例：0.25%");
    expect(tooltip.formatter?.({ value: 0.25 })).toContain("异常样本：3 / 1,200 个样本");
    expect(wrapper.find('[data-test="anomaly-ratio-track"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-position-chart"]').exists()).toBe(false);
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-raw-data"]').exists()).toBe(false);

    await wrapper.get(".anomaly-raw__toggle").trigger("click");
    expect(wrapper.get('[data-test="anomaly-raw-data"]').text()).toContain('"anomaly_count": 3');
  });

  it("uses the compact zero state for standalone anomaly results without drawing an empty chart", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      result: { anomaly_count: 0, anomaly_ratio: 0 },
    }));

    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("本次未检出疑似异常点");
    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("0.00%");
    expect(wrapper.find('[data-test="anomaly-ratio-chart"]').exists()).toBe(false);
  });

  it("keeps a larger anomaly ratio on the same true zero-to-one-hundred bar scale", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      result: {
        anomaly_count: 20,
        anomaly_ratio: 0.2,
        total: 100,
        n_samples: 99,
        sample_count: 98,
      },
    }));

    const options = wrapper
      .get('[data-test="anomaly-ratio-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(options.xAxis).toMatchObject({ min: 0, max: 100 });
    expect(options.series).toEqual([
      expect.objectContaining({ type: "bar", data: [20] }),
    ]);
    const tooltip = options.tooltip as { formatter?: (params: unknown) => string };
    expect(tooltip.formatter?.({ value: 20 })).toContain("异常比例：20.00%");
    expect(tooltip.formatter?.({ value: 20 })).toContain("异常样本：20 / 100 个样本");
  });

  it("does not chart an invalid ratio and safely handles an empty historical envelope", async () => {
    const invalid = await mountWorkbench(executionWith("detect_anomalies", {
      result: { anomaly_count: "unknown", anomaly_ratio: 1.2 },
    }));
    expect(invalid.find('[data-test="anomaly-ratio-chart"]').exists()).toBe(false);
    expect(invalid.get('[data-test="anomaly-metrics"]').text()).toContain("unknown");
    expect(invalid.get('[data-test="anomaly-metrics"]').text()).toContain("1.2");

    const empty = await mountWorkbench(executionWith("detect_anomalies", {
      summary: null,
      result: null,
    }));
    expect(empty.get('[data-test="anomaly-empty"]').text()).toBe("暂无可结构化展示的异常检测结果");
    expect(empty.find('[data-test="anomaly-raw-data"]').exists()).toBe(false);
  });
});

const cleaningPayload = (overrides: Record<string, unknown> = {}) => ({
  source_version_id: "11111111-1111-1111-1111-111111111111",
  effective_version_id: "22222222-2222-2222-2222-222222222222",
  derived_version_id: "22222222-2222-2222-2222-222222222222",
  created_new_version: true,
  no_op: false,
  converged: false,
  reused_existing_version: false,
  processing_run_id: "33333333-3333-3333-3333-333333333333",
  summary: {
    rows_before: 2000,
    rows_after: 1992,
    changes: {
      count_unit: "cell",
      unique_changed_cells: 7,
      missing_value_fills: 3,
      outlier_replacements: 2,
      smoothing_changes: 1,
      duplicate_timestamps_processed: 1,
      resampling_empty_rows_created: 0,
      overlapping_changed_cells: 1,
      category_counts_may_overlap: true,
      source_missing_cells: 4,
      aligned_missing_cells_before_interpolation: 5,
      future_scalar: 9,
      future_object: { ignored: true },
    },
  },
  ...overrides,
});

describe("ArtifactWorkbench cleaning rendering", () => {
  it("renders Normal Changed as impact facts without promoting version UUIDs", async () => {
    const wrapper = await mountWorkbench(executionWith("clean_data", cleaningPayload()));

    expect(wrapper.get('[data-test="cleaning-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="cleaning-summary"]').text()).toBe(
      "本次清洗已生成新的数据版本，并对数据内容进行了实际修正。"
    );
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("已生成新版本");
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("结果有变化");
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("正常清洗");
    expect(wrapper.find('[data-test="cleaning-version-flow"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("源版本");
    expect(wrapper.text()).not.toContain("有效版本");
    expect(wrapper.text()).not.toContain("11111111…");
    expect(wrapper.text()).not.toContain("22222222…");

    const impact = wrapper.get('[data-test="cleaning-impact-overview"]').text();
    expect(impact).toContain("修改单元格7");
    expect(impact).toContain("缺失填补3");
    expect(impact).toContain("异常替换2");
    expect(impact).toContain("重采样空行0");

    const actionSection = wrapper.get('[data-test="cleaning-action-distribution"]');
    const actionOptions = actionSection.getComponent(ChartContainerStub).props("options") as ChartOption;
    expect(actionOptions.yAxis).toMatchObject({
      type: "category",
      data: ["缺失填补", "异常替换", "重复时间戳处理", "平滑修改"],
    });
    expect(actionOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [3, 2, 1, 1] }),
    ]);
    expect(actionOptions.series).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "pie" }),
      expect.objectContaining({ stack: expect.anything() }),
    ]));
    expect(wrapper.get('[data-test="cleaning-overlap-note"]').text()).toContain("不表示占比构成");

    const rowOptions = wrapper
      .get('[data-test="cleaning-row-count-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(rowOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [2000, 1992] }),
    ]);
    expect(wrapper.find('[data-test="cleaning-missing-count-chart"]').exists()).toBe(false);

    const metrics = wrapper.get('[data-test="cleaning-metrics"]').text();
    expect(metrics).toContain("本次 Cleaning 中发生实际修改的唯一单元格数量");
    expect(metrics).toContain("通过已配置异常处理策略实际替换的单元格数量");
    expect(metrics).not.toContain("Hampel");
    expect(wrapper.get('[data-test="cleaning-other-metrics"]').text()).toContain("future_scalar9");
    expect(wrapper.get('[data-test="cleaning-other-metrics"]').text()).not.toContain("future_object");
    expect(wrapper.get('[data-test="cleaning-provenance"]').text()).toContain("33333333…");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.find('[data-test="cleaning-raw-data"]').exists()).toBe(false);

    await wrapper.get(".cleaning-raw__toggle").trigger("click");
    expect(wrapper.get('[data-test="cleaning-raw-data"]').text()).toContain('"created_new_version": true');
  });

  it.each([
    {
      name: "Converged",
      payload: cleaningPayload({
        effective_version_id: "11111111-1111-1111-1111-111111111111",
        derived_version_id: null,
        created_new_version: false,
        no_op: true,
        converged: true,
        reused_existing_version: false,
      }),
      summary: "清洗结果已收敛，本次未生成新的数据版本。",
      statuses: ["未生成新版本", "数据状态不变", "已收敛"],
    },
    {
      name: "Reuse",
      payload: {
        summary: "正式清洗服务已复用现有不可变版本。",
        result: cleaningPayload({
          derived_version_id: null,
          created_new_version: false,
          no_op: false,
          converged: false,
          reused_existing_version: true,
        }),
      },
      summary: "正式清洗服务已复用现有不可变版本。",
      statuses: ["复用既有版本", "结果有变化", "幂等复用"],
    },
  ])("keeps $name semantics distinct", async ({ payload, summary, statuses }) => {
    const wrapper = await mountWorkbench(executionWith("clean_data", payload));

    expect(wrapper.get('[data-test="cleaning-summary"]').text()).toBe(summary);
    statuses.forEach((status) => {
      expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain(status);
    });
    expect(wrapper.find('[data-test="cleaning-version-flow"]').exists()).toBe(false);
  });

  it("keeps first-clean zero-change certification distinct", async () => {
    const wrapper = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      no_op: true,
      converged: true,
      summary: { changes: { unique_changed_cells: 0 } },
    })));

    expect(wrapper.get('[data-test="cleaning-summary"]').text()).toBe(
      "本次清洗完成零变化认证，并生成了新的数据版本。"
    );
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("零变化认证");
  });

  it("does not invent missing metrics, zeros, or before-after charts", async () => {
    const withoutChanges = await mountWorkbench(executionWith("clean_data", cleaningPayload({ summary: undefined })));
    expect(withoutChanges.find('[data-test="cleaning-impact-overview"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-action-distribution"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-row-count-chart"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-missing-count-chart"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-metrics"]').exists()).toBe(false);
    expect(withoutChanges.text()).not.toContain("修改单元格0");
    expect(withoutChanges.find('[data-test="cleaning-version-flow"]').exists()).toBe(false);
    expect(withoutChanges.get('[data-test="cleaning-provenance"]').exists()).toBe(true);

    const empty = await mountWorkbench(executionWith("clean_data", { summary: null, result: null }));
    expect(empty.get('[data-test="cleaning-empty"]').text()).toBe("暂无可结构化展示的数据清洗结果");
    expect(empty.find('[data-test="cleaning-raw-data"]').exists()).toBe(false);
  });

  it("shows an empty action message for explicit zeros and charts missing data only from a complete pair", async () => {
    const allZero = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: {
        changes: {
          missing_value_fills: 0,
          outlier_replacements: 0,
          duplicate_timestamps_processed: 0,
          resampling_empty_rows_created: 0,
          smoothing_changes: 0,
        },
      },
    })));
    expect(allZero.get('[data-test="cleaning-action-empty"]').text()).toBe(
      "本次未记录具体清洗动作计数。"
    );
    expect(allZero.find('[data-test="cleaning-action-chart"]').exists()).toBe(false);

    const complete = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: {
        missing: { before: 106, after: 0 },
        changes: { source_missing_cells: 106, missing_value_fills: 106 },
      },
    })));
    const missingOptions = complete
      .get('[data-test="cleaning-missing-count-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(missingOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [106, 0] }),
    ]);

    const incomplete = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: { changes: { source_missing_cells: 106, missing_value_fills: 106 } },
    })));
    expect(incomplete.find('[data-test="cleaning-missing-count-chart"]').exists()).toBe(false);
  });

  it("uses one sample-size status for equal standalone row counts while preserving content changes", async () => {
    const wrapper = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: {
        rows_before: 1200,
        rows_after: 1200,
        changes: {
          unique_changed_cells: 9,
          outlier_replacements: 9,
          category_counts_may_overlap: true,
        },
      },
    })));

    expect(wrapper.get('[data-test="cleaning-row-count-unchanged"]').text()).toContain("样本规模保持不变");
    expect(wrapper.get('[data-test="cleaning-row-count-unchanged"]').text()).toContain("1,200 → 1,200");
    expect(wrapper.find('[data-test="cleaning-row-count-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="cleaning-impact-overview"]').text()).toContain("修改单元格9");
    expect(wrapper.get('[data-test="cleaning-action-chart"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain("清洗无变化");
  });
});

describe("ArtifactWorkbench lag compensation rendering", () => {
  it("plots applied lags including zero and downloads the step result rather than the final version", async () => {
    const execution = executionWith("apply_lag_compensation", {
      summary: { lag_map: { u1: 4, u2: 8, u3: 7, u4: 0 } },
      result_version_id: "lag-version",
    });
    execution.current_version_id = "later-feature-version";
    const wrapper = await mountWorkbench(execution);
    const chart = wrapper.getComponent(ChartContainerStub).props("options") as any;
    expect(chart.yAxis.data).toEqual(["u1", "u2", "u3", "u4"]);
    expect(chart.series[0].data).toEqual([4, 8, 7, 0]);
    expect(chart.series[0].label.formatter({ value: 0 })).toBe("0 · 未平移");
    expect(wrapper.get('[data-test="download-lag-csv"]').attributes("href"))
      .toBe("/api/v1/datasets/dataset-1/download?version_id=lag-version");
    expect(wrapper.get('[data-test="download-lag-csv"]').classes()).toContain("el-button--primary");
  });

  it("does not invent zero lags or a download for incomplete historical records", async () => {
    const wrapper = await mountWorkbench(executionWith("apply_lag_compensation", {
      summary: { lag_map: { u1: null, u2: "8", u3: -1, u4: 1.5 } },
    }));
    expect(wrapper.find('[data-test="lag-compensation-chart"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="lag-chart-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="download-lag-csv"]').exists()).toBe(false);
    expect(wrapper.html()).not.toContain("version_id=undefined");
  });

  it("renders confirmed zero-lag no-op semantics without inventing a version or download", async () => {
    const wrapper = await mountWorkbench(executionWith("apply_lag_compensation", {
      disposition: "CONFIRMED_NO_OP",
      final_lag_map: { u1: 0, u2: 0, u3: 0 },
      parameter_sources: {
        u1: "delay_recommendation",
        u2: "delay_recommendation",
        u3: "delay_recommendation",
      },
      user_confirmed: true,
      source_version_id: "version-0",
      effective_version_id: "version-0",
    }));

    expect(wrapper.get('[data-test="lag-no-op-result"]').text()).toContain("已确认无需额外时滞补偿");
    expect(wrapper.get('[data-test="lag-no-op-description"]').text()).toContain("未执行数据平移或边界裁剪");
    const lagRows = wrapper.get('[data-test="lag-no-op-lags"]').findAll(".aw-kv");
    expect(lagRows.map(row => row.text())).toEqual([
      "u10 个采样点",
      "u20 个采样点",
      "u30 个采样点",
    ]);
    expect(wrapper.get('[data-test="lag-no-op-version-status"]').text()).toContain("数据版本保持不变");
    expect(wrapper.get('[data-test="lag-no-op-version-status"]').text()).toContain("下载当前数据集");
    expect(wrapper.text()).not.toContain("补偿前样本数");
    expect(wrapper.text()).not.toContain("补偿后样本数");
    expect(wrapper.text()).not.toContain("已生成补偿后数据版本");
    expect(wrapper.text()).not.toContain("下载补偿后 CSV");
    expect(wrapper.html()).not.toContain("version_id=undefined");
  });

  it("preserves the existing renderer for legacy artifacts without disposition", async () => {
    const wrapper = await mountWorkbench(executionWith("apply_lag_compensation", {
      summary: {
        rows_before: 1200,
        rows_after: 1192,
        removed_boundary_rows: 8,
        lag_map: { u1: 3, u2: 8, u3: 5 },
      },
      result_version_id: "version-1",
    }));

    expect(wrapper.text()).toContain("补偿前样本数1200");
    expect(wrapper.text()).toContain("补偿后样本数1192");
    expect(wrapper.text()).toContain("裁剪边界行数8");
    expect(wrapper.text()).toContain("u13 采样点");
    expect(wrapper.get('[data-test="lag-result-version"]').text()).toBe("version-1");
    expect(wrapper.get('a[href="/api/v1/datasets/dataset-1/download?version_id=version-1"]').text()).toBe("下载补偿后 CSV");
    expect(wrapper.find('[data-test="lag-no-op-result"]').exists()).toBe(false);
  });

  it("preserves the existing renderer for explicit APPLY_VERSION artifacts", async () => {
    const wrapper = await mountWorkbench(executionWith("apply_lag_compensation", {
      disposition: "APPLY_VERSION",
      summary: {
        rows_before: 800,
        rows_after: 796,
        removed_boundary_rows: 4,
        lag_map: { u1: 4 },
      },
      result_version_id: "version-2",
    }));

    expect(wrapper.text()).toContain("补偿前样本数800");
    expect(wrapper.text()).toContain("补偿后样本数796");
    expect(wrapper.text()).toContain("裁剪边界行数4");
    expect(wrapper.text()).toContain("u14 采样点");
    expect(wrapper.get('[data-test="lag-result-version"]').text()).toBe("version-2");
    expect(wrapper.text()).toContain("下载补偿后 CSV");
    expect(wrapper.find('[data-test="lag-no-op-result"]').exists()).toBe(false);
  });
});

describe("ArtifactWorkbench optimization artifact", () => {
  it("groups best parameters and presents composite objective semantics for non-specialists", async () => {
    const wrapper = await mountWorkbench(executionWith("optimize_pipeline", {
      objective_semantics: {
        name: "composite_identification_score",
        version: "v1",
        direction: "maximize",
      },
      best_value: 0.394,
      n_trials: 20,
      best_params: {
        window_size: 180,
        max_segments: 6,
        max_anomaly_ratio: 0.04,
        max_missing_ratio: 0.30000000000000004,
        min_input_activity_ratio: 0.1,
        nk: 0,
        na: 2,
        nb: 2,
        estimator: "ridge",
        ridge_alpha: 0.1,
        future_parameter: 7.500000000000001,
      },
    }));

    expect(wrapper.text()).toContain("综合辨识得分（Composite Identification Score）");
    expect(wrapper.text()).toContain("0.394");
    expect(wrapper.text()).not.toContain("最优目标 FIT");
    expect(wrapper.text()).not.toContain("39.4%");
    expect(wrapper.get('[data-test="optimization-objective-note"]').text()).toContain("验证集自由运行拟合能力");

    const parameters = wrapper.get('[data-test="optimization-parameters"]');
    expect(parameters.text()).toContain("最优策略参数");
    expect(parameters.get('[data-test="optimization-group-data-selection"]').text()).toContain("数据优选参数");
    expect(parameters.get('[data-test="optimization-group-arx-model"]').text()).toContain("ARX 模型参数");
    expect(parameters.get('[data-test="optimization-group-other"]').text()).toContain("其他参数");

    const windowSize = parameters.get('[data-test="optimization-param-window_size"]');
    expect(windowSize.text()).toContain("滑动窗口长度（window_size）");
    expect(windowSize.text()).toContain("控制动态区段分析时每个候选窗口包含的采样点数。");
    expect(windowSize.text()).toContain("180 个采样点");
    expect(parameters.get('[data-test="optimization-param-max_segments"]').text()).toContain("6 个区段");
    expect(parameters.get('[data-test="optimization-param-max_anomaly_ratio"]').text()).toContain("4%");
    expect(parameters.get('[data-test="optimization-param-max_missing_ratio"]').text()).toContain("30%");
    expect(parameters.get('[data-test="optimization-param-min_input_activity_ratio"]').text()).toContain("10%");
    expect(parameters.get('[data-test="optimization-param-nk"]').text()).toContain("0 阶");
    expect(parameters.get('[data-test="optimization-param-na"]').text()).toContain("2 阶");
    expect(parameters.get('[data-test="optimization-param-nb"]').text()).toContain("2 阶");
    expect(parameters.get('[data-test="optimization-param-estimator"]').text()).toContain("岭回归（Ridge）");
    expect(parameters.get('[data-test="optimization-param-ridge_alpha"]').text()).toContain("0.1");
    expect(parameters.get('[data-test="optimization-param-future_parameter"]').text()).toContain("future_parameter");
    expect(parameters.get('[data-test="optimization-param-future_parameter"]').text()).toContain("7.5");
    expect(parameters.text()).not.toContain("0.30000000000000004");
  });

  it("formats OLS and safely falls back when legacy objective semantics are absent", async () => {
    const wrapper = await mountWorkbench(executionWith("optimize_pipeline", {
      best_value: 0.394,
      best_params: { estimator: "ols" },
    }));

    expect(wrapper.text()).toContain("优化目标值");
    expect(wrapper.text()).toContain("0.394");
    expect(wrapper.text()).toContain("普通最小二乘（OLS）");
    expect(wrapper.text()).not.toContain("综合辨识得分（Composite Identification Score）");
    expect(wrapper.text()).not.toContain("FIT");
    expect(wrapper.find('[data-test="optimization-objective-note"]').exists()).toBe(false);
  });
});

describe("ArtifactWorkbench report and delivery actions", () => {
  it("uses the dedicated report renderer and restores real sibling results from a persisted snapshot", async () => {
    const wrapper = await mountWorkbench(reportExecution());

    expect(wrapper.get('[data-test="report-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("样本数1,200");
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("异常点6");
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("异常比例0.50%");
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("修改单元格7");
    expect(wrapper.get('[data-test="report-profile-section"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="report-anomaly-section"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="report-cleaning-section"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="report-markdown"]').text()).toContain("清洗与异常检测均已完成");
    expect(wrapper.get('[data-test="report-evidence"]').text()).toContain("样本数量");
    expect(wrapper.get('[data-test="report-evidence"]').text()).toContain("来源：本次数据画像");
    expect(wrapper.get('[data-test="report-evidence"]').text()).not.toContain("run type");
  });

  it("uses compact zero states and keeps technical identifiers out of the primary report UI", async () => {
    const execution = reportExecution();
    execution.current_version_id = "11111111-1111-1111-1111-111111111111";
    execution.step_runs[0].result_payload = {
      summary: "画像完成",
      result: {
        n_samples: 1500,
        fingerprint: { values: { missing_ratio: 0, anomaly_ratio: 0 } },
      },
    };
    execution.step_runs[1].result_payload = {
      summary: "异常检测完成",
      result: { anomaly_count: 0, anomaly_ratio: 0 },
    };
    execution.step_runs[2].result_payload = {
      total_cleaned_points: 0,
      processing_run_id: "22222222-2222-2222-2222-222222222222",
      task: {
        progress: {
          message: "正式清洗服务已生成不可变版本 11111111-1111-1111-1111-111111111111。",
        },
      },
      summary: {
        rows_before: 1500,
        rows_after: 1500,
        changes: {
          unique_changed_cells: 0,
          missing_value_fills: 0,
          outlier_replacements: 0,
          duplicate_timestamps_processed: 0,
          resampling_empty_rows_created: 0,
          smoothing_changes: 0,
        },
      },
    };
    execution.step_runs[2].processing_run_ids = ["22222222-2222-2222-2222-222222222222"];
    const report = execution.step_runs[3].result_payload;
    report.execution_id = execution.execution_id;
    report.title = "IndusOpt 数据质量分析与清洗报告";
    report.markdown = "## 一、分析概述\n\n本次仅执行数据质量分析与清洗。";

    const wrapper = await mountWorkbench(execution);

    expect(wrapper.get(".report-status").text()).toBe("本次任务证据已解析");
    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("本次未检出疑似异常点");
    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("0.00%");
    expect(wrapper.find('[data-test="anomaly-ratio-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="profile-quality-chart"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="cleaning-action-empty"]').text()).toContain("本次清洗未修改数据");
    expect(wrapper.find('[data-test="cleaning-action-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="cleaning-row-count-unchanged"]').text()).toContain("1,500 → 1,500");
    expect(wrapper.find('[data-test="cleaning-row-count-chart"]').exists()).toBe(false);

    const primaryText = [
      wrapper.get(".report-header").text(),
      wrapper.get('[data-test="report-core-metrics"]').text(),
      wrapper.get('[data-test="report-stages"]').text(),
      wrapper.get('[data-test="report-evidence"]').text(),
      wrapper.get('[data-test="report-markdown"]').text(),
    ].join(" ");
    expect(primaryText).not.toContain("11111111-1111-1111-1111-111111111111");
    expect(primaryText).not.toContain("22222222-2222-2222-2222-222222222222");
    expect(primaryText).not.toContain("derived version id");
    expect(primaryText).not.toContain("constant value segment count");
    expect(primaryText).not.toContain("profile_dataset");
    expect(primaryText).not.toContain("detect_anomalies");
    expect(primaryText).not.toContain("clean_data");
    expect(primaryText).not.toContain("ARX");

    const technical = wrapper.get('[data-test="report-technical-details"]');
    expect(technical.attributes("open")).toBeUndefined();
    expect(technical.text()).toContain(execution.execution_id);
    expect(technical.text()).toContain("11111111-1111-1111-1111-111111111111");
    expect(technical.text()).toContain("22222222-2222-2222-2222-222222222222");
  });

  it("renders non-zero cleaning actions and changed row counts as comparison charts", async () => {
    const wrapper = await mountWorkbench(reportExecution());

    const actionOptions = wrapper
      .get('[data-test="cleaning-action-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(actionOptions.yAxis).toEqual(expect.objectContaining({ type: "category" }));
    expect(actionOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [4, 3] }),
    ]);
    expect(wrapper.get('[data-test="cleaning-row-count-chart"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="cleaning-row-count-unchanged"]').exists()).toBe(false);
  });

  it("does not invent absent metrics and keeps raw JSON and UUIDs in closed technical details", async () => {
    const reportId = "44444444-4444-4444-4444-444444444444";
    const wrapper = await mountWorkbench(executionWith("generate_report", {
      report_id: reportId,
      title: "无指标报告",
      markdown: "结论仅来自现有证据。",
      fully_resolved: true,
      unresolved: [],
      bindings: [],
    }));

    expect(wrapper.find('[data-test="report-core-metrics"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("N/A");
    expect(wrapper.text()).not.toContain("综合评分");
    const technical = wrapper.get('[data-test="report-technical-details"]');
    expect(technical.attributes("open")).toBeUndefined();
    expect(technical.get('[data-test="report-raw-json"]').text()).toContain(reportId);
    expect(wrapper.get(".report-header").text()).not.toContain(reportId);
    expect(wrapper.get('[data-test="report-markdown"]').text()).not.toContain(reportId);
  });

  it("binds current-dataset download to the execution dataset and current version", async () => {
    const execution = executionWith("profile_dataset", { result: { n_samples: 10 } });
    execution.dataset_id = "dataset-current";
    execution.current_version_id = "version-current";
    const wrapper = await mountWorkbench(execution);

    expect(wrapper.get('[data-test="download-current-dataset"]').attributes("href")).toBe(
      "/api/v1/datasets/dataset-current/download?version_id=version-current"
    );
  });

  it("shows the formal no-selection message without falling back to a full dataset download", async () => {
    deliveryApi.exportDataset.mockRejectedValueOnce(
      new ApiError("EXPORT_NO_SELECTION", "no selection", "request-1")
    );
    const wrapper = await mountWorkbench(executionWith("profile_dataset", { result: { n_samples: 10 } }));

    await wrapper.get('[data-test="export-optimised-dataset"]').trigger("click");
    await flushPromises();

    expect(deliveryApi.exportDataset).toHaveBeenCalledWith({
      dataset_id: "dataset-1",
      version_id: "version-0",
    });
    expect(wrapper.get('[data-test="export-notice"]').text()).toBe(
      "尚未完成样本优选，无法导出优选数据集。"
    );
    expect(messageApi.error).toHaveBeenCalledWith("尚未完成样本优选，无法导出优选数据集。");
    expect(wrapper.get('[data-test="download-current-dataset"]').text()).toBe("下载当前数据集");
  });

  it("shows real export metrics and persisted artifact download routes after success", async () => {
    deliveryApi.exportDataset.mockResolvedValueOnce({
      export_id: "export-1",
      dataset_id: "dataset-1",
      version_id: "version-0",
      task: {},
      csv_uri: "exports/export-1.csv",
      manifest_uri: "exports/export-1.manifest.json",
      exported_rows: 25,
      source_rows: 100,
      coverage_ratio: 0.25,
      columns: ["timestamp", "u", "y"],
    });
    const wrapper = await mountWorkbench(executionWith("profile_dataset", { result: { n_samples: 100 } }));

    await wrapper.get('[data-test="export-optimised-dataset"]').trigger("click");
    await flushPromises();

    const notice = wrapper.get('[data-test="export-notice"]');
    expect(notice.text()).toContain("优选数据集导出完成");
    expect(notice.text()).toContain("导出 25 / 100 行，覆盖率 25.00%");
    const csv = notice.get('a[href="/api/v1/delivery/exports/export-1/csv"]');
    const manifest = notice.get('a[href="/api/v1/delivery/exports/export-1/manifest"]');
    expect(csv.text()).toBe("下载优选 CSV");
    expect(manifest.text()).toBe("下载 Manifest");
    expect(csv.classes()).toEqual(expect.arrayContaining([
      "el-button",
      "artifact-download-button",
      "artifact-download-button--primary",
    ]));
    expect(manifest.classes()).toEqual(expect.arrayContaining([
      "el-button",
      "artifact-download-button",
      "artifact-download-button--secondary",
    ]));
  });

  it("renders export artifact downloads as equal formal Element Plus actions", async () => {
    const wrapper = await mountWorkbench(executionWith("export_dataset", {
      export_id: "export-2",
      exported_rows: 48,
      source_rows: 120,
      coverage_ratio: 0.4,
    }));

    const renderer = wrapper.get('[data-test="export-artifact-renderer"]');
    const actions = renderer.get('[data-test="export-download-actions"]');
    const csv = actions.get('[data-test="download-optimised-csv"]');
    const manifest = actions.get('[data-test="download-export-manifest"]');

    expect(csv.element.tagName).toBe("A");
    expect(manifest.element.tagName).toBe("A");
    expect(csv.attributes("href")).toBe("/api/v1/delivery/exports/export-2/csv");
    expect(manifest.attributes("href")).toBe(
      "/api/v1/delivery/exports/export-2/manifest"
    );
    expect(csv.classes()).toContain("el-button--primary");
    expect(manifest.classes()).toContain("el-button--default");
    expect(csv.classes()).toContain("artifact-download-button");
    expect(manifest.classes()).toContain("artifact-download-button");
  });
});
