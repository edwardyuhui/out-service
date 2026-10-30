import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../src/api/client", () => ({
  default: { get, post },
}));

import {
  chatWithCopilot,
  confirmCopilotStep,
  executePipelineOptimization,
  executeModelEvaluation,
  getCopilotExecution,
  validateArxStructure,
  validateFeatureSelection,
  validateLagOverrides,
} from "../../src/api/copilot";

describe("Copilot API", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue({});
    post.mockResolvedValue({});
  });

  it("allows enough time for a real LLM to generate and validate a plan", async () => {
    const request = {
      message: "生成高质量建模数据计划",
      active_version_id: null,
    };

    await chatWithCopilot(request);

    expect(post).toHaveBeenCalledWith("/copilot/chat", request, { timeout: 120_000 });
  });

  it("loads an execution snapshot by its exact execution_id", async () => {
    const executionId = "22222222-2222-4222-8222-222222222222";

    await getCopilotExecution(executionId);

    expect(get).toHaveBeenCalledWith(`/copilot/executions/${executionId}`);
  });
  it("executes model evaluation with only execution_id", async () => {
    const executionId = "22222222-2222-4222-8222-222222222222";

    await executeModelEvaluation(executionId);

    expect(post).toHaveBeenCalledWith("/copilot/evaluate-model/execute", {
      execution_id: executionId,
    });
  });
  it("executes pipeline optimization with only execution_id and its dedicated timeout", async () => {
    const executionId = "22222222-2222-4222-8222-222222222222";

    await executePipelineOptimization(executionId);

    expect(post).toHaveBeenCalledWith(
      "/copilot/optimize-pipeline/execute",
      { execution_id: executionId },
      { timeout: 600_000 }
    );
  });

  it("sends persistent execution and step identifiers when confirming a step", async () => {
    const request = {
      copilot_run_id: "11111111-1111-4111-8111-111111111111",
      confirmation_id: "s2",
      execution_id: "22222222-2222-4222-8222-222222222222",
      step_id: "s2",
      approved: true,
    };

    await confirmCopilotStep(request);

    expect(post).toHaveBeenCalledWith("/copilot/confirm", request);
  });

  it("validates controlled ARX structure overrides without confirming a model", async () => {
    const request = {
      execution_id: "22222222-2222-4222-8222-222222222222",
      step_id: "s2",
      manual_overrides: { na: 3, nb: { u1: 4 } },
    };

    await validateArxStructure(request);

    expect(post).toHaveBeenCalledWith("/copilot/arx-structure/validate", request);
  });
  it("validates controlled Feature Selection without using the confirm endpoint", async () => {
    const request = {
      execution_id: "22222222-2222-4222-8222-222222222222",
      step_id: "s2",
      drop_columns: ["u2"],
    };

    await validateFeatureSelection(request);

    expect(post).toHaveBeenCalledWith("/copilot/feature-selection/validate", request);
  });
  it("validates controlled Lag overrides without using the confirm endpoint", async () => {
    const request = {
      execution_id: "22222222-2222-4222-8222-222222222222",
      step_id: "s2",
      manual_overrides: [{ variable: "u1", value: 4 }],
    };

    await validateLagOverrides(request);

    expect(post).toHaveBeenCalledWith("/copilot/lag-overrides/validate", request);
  });
});