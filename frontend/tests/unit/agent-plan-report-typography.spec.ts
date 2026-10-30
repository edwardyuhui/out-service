import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AgentPlan from "../../src/components/workspace/AgentPlan.vue";
import ToolExecution from "../../src/components/workspace/ToolExecution.vue";
import type { CopilotExecutionStepSnapshot, ExecutionPlanStep } from "../../src/types/api";

const step = (stepId: string, tool: string): ExecutionPlanStep => ({
  step_id: stepId,
  tool,
  depends_on: [],
  parameters: {},
  requires_confirmation: false,
  status: "pending",
});

const stepRun = (stepId: string, tool: string): CopilotExecutionStepSnapshot => ({
  step_id: stepId,
  sequence: 1,
  tool,
  status: "completed",
  requires_confirmation: false,
  confirmation_status: "NOT_REQUIRED",
  attempt_count: 1,
  source_version_id: null,
  result_version_id: null,
  input_payload: {},
  result_payload: {},
  processing_run_ids: [],
  error_code: null,
  error_message: null,
  started_at: null,
  finished_at: null,
});

describe("Agent business typography", () => {
  it("uses Sans for raw tool keys and localized execution steps", () => {
    const wrapper = mount(AgentPlan, {
      props: {
        steps: [
          step("step-segment", "detect_dynamic_segments"),
          step("step-fit", "fit_arx"),
          step("step-optimize", "optimize_pipeline"),
          step("step-evaluate", "evaluate_model"),
          step("step-report", "generate_report"),
        ],
        stepRuns: [],
        currentStepId: null,
      },
    });
    const labels = wrapper.findAll(".plan-step__tool");

    expect(labels.map(label => label.text())).toEqual([
      "动态区间优选",
      "系统辨识",
      "Optuna 闭环寻优 (Optimize)",
      "模型测试集评价 (Evaluate)",
      "报告交付",
    ]);
    for (const label of labels) expect(label.classes()).not.toContain("font-mono");
    expect(labels[4]!.classes()).toContain("plan-step__tool--report");

    const source = readFileSync(resolve(process.cwd(), "src/components/workspace/AgentPlan.vue"), "utf8");
    const businessRule = source.match(/\.plan-count,\s*\.plan-step__tool,\s*\.plan-step__duration\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(businessRule).toContain("font-family: var(--font-sans)");
    expect(businessRule).toContain("letter-spacing: normal");
  });

  it("normalizes the real execution-stream report label by stable tool key", () => {
    const report = mount(ToolExecution, {
      props: {
        stepRun: stepRun("step-report", "generate_report"),
        planStep: step("step-report", "generate_report"),
      },
    });
    const reportLabel = report.get(".te-tool");

    expect(reportLabel.text()).toBe("报告交付");
    expect(reportLabel.text()).not.toContain("Report");
    expect(reportLabel.classes()).toContain("te-tool--report");
    expect(reportLabel.classes()).not.toContain("font-mono");

    const businessSteps = [
      ["step-segment", "detect_dynamic_segments", "动态区间优选"],
      ["step-fit", "fit_arx", "系统辨识"],
      ["step-optimize", "optimize_pipeline", "Optuna 寻优 (Optimize)"],
      ["step-evaluate", "evaluate_model", "模型评价 (Evaluate)"],
    ] as const;
    for (const [stepId, tool, expected] of businessSteps) {
      const business = mount(ToolExecution, {
        props: {
          stepRun: stepRun(stepId, tool),
          planStep: step(stepId, tool),
        },
      });
      expect(business.get(".te-tool").text()).toBe(expected);
      expect(business.get(".te-tool").classes()).not.toContain("font-mono");
    }

    const clean = mount(ToolExecution, {
      props: {
        stepRun: stepRun("step-clean", "clean"),
        planStep: step("step-clean", "clean"),
      },
    });
    expect(clean.get(".te-tool").text()).toBe("数据清洗 (Clean)");
    expect(clean.get(".te-tool").classes()).not.toContain("font-mono");

    const source = readFileSync(resolve(process.cwd(), "src/components/workspace/ToolExecution.vue"), "utf8");
    expect(source).toContain("generate_report: '报告交付'");
    expect(source).not.toContain("generate_report: '报告交付 (Report)'");
    const businessRule = source.match(/\.te-tool,\s*\.te-duration,\s*\.te-metric__value\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(businessRule).toContain("font-family: var(--font-sans)");
    expect(businessRule).toContain("letter-spacing: normal");
  });

  it("renders the optimize step composite score as a decimal instead of FIT percent", () => {
    const optimized = stepRun("step-optimize", "optimize_pipeline");
    optimized.result_payload = {
      best_value: 0.394,
      objective_semantics: {
        name: "composite_identification_score",
        version: "v1",
        direction: "maximize",
      },
    };
    const wrapper = mount(ToolExecution, {
      props: {
        stepRun: optimized,
        planStep: step("step-optimize", "optimize_pipeline"),
      },
    });

    expect(wrapper.get(".te-metrics").text()).toContain("综合辨识得分");
    expect(wrapper.get(".te-metrics").text()).toContain("0.394");
    expect(wrapper.get(".te-metrics").text()).not.toContain("BEST FIT");
    expect(wrapper.get(".te-metrics").text()).not.toContain("39.4%");

    const legacy = stepRun("step-optimize-legacy", "optimize_pipeline");
    legacy.result_payload = { best_value: 0.394 };
    const legacyWrapper = mount(ToolExecution, {
      props: {
        stepRun: legacy,
        planStep: step("step-optimize-legacy", "optimize_pipeline"),
      },
    });
    expect(legacyWrapper.get(".te-metrics").text()).toContain("优化目标值");
    expect(legacyWrapper.get(".te-metrics").text()).toContain("0.394");
    expect(legacyWrapper.get(".te-metrics").text()).not.toContain("FIT");
  });
});
