import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ApprovalCard from "../../src/components/workspace/ApprovalCard.vue";
import type { CopilotExecutionStepSnapshot, CopilotConfirmRequest } from "../../src/types/api";

function featureStep(recommendedDropColumns: string[]): CopilotExecutionStepSnapshot {
  return {
    step_id: "step-feature",
    sequence: 1,
    tool: "select_variables",
    status: "WAITING_CONFIRMATION",
    requires_confirmation: true,
    confirmation_status: "PENDING",
    attempt_count: 1,
    source_version_id: null,
    result_version_id: null,
    input_payload: { recommended_drop_columns: recommendedDropColumns },
    result_payload: {},
    processing_run_ids: [],
    error_code: null,
    error_message: null,
    started_at: null,
    finished_at: null,
  };
}

describe("feature selection confirmation", () => {
  it("explains an empty recommendation and submits keep-all", async () => {
    const wrapper = mount(ApprovalCard, {
      props: {
        stepRun: featureStep([]),
        executionId: "execution-id",
        copilotRunId: "copilot-run-id",
      },
    });

    expect(wrapper.text()).toContain("分析未建议剔除输入变量，本次将保留全部输入");
    expect(wrapper.text()).not.toContain("建议移除以下列");
    expect(wrapper.findAll(".ac-feature-item")).toHaveLength(0);

    await wrapper.find('[data-test="approve-step-feature"]').trigger("click");
    const request = wrapper.emitted("confirm")?.[0]?.[0] as CopilotConfirmRequest;
    expect(request.feature_drop_columns).toEqual([]);
  });

  it("keeps suggested columns selectable", async () => {
    const wrapper = mount(ApprovalCard, {
      props: {
        stepRun: featureStep(["u2"]),
        executionId: "execution-id",
        copilotRunId: "copilot-run-id",
      },
    });

    expect(wrapper.text()).toContain("建议移除以下列");
    expect(wrapper.findAll(".ac-feature-item")).toHaveLength(1);
    await wrapper.find('[data-test="approve-step-feature"]').trigger("click");
    const request = wrapper.emitted("confirm")?.[0]?.[0] as CopilotConfirmRequest;
    expect(request.feature_drop_columns).toEqual(["u2"]);
  });
});
