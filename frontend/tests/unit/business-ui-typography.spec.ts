import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ApprovalCard from "../../src/components/workspace/ApprovalCard.vue";
import type { CopilotExecutionStepSnapshot, ExecutionPlanStep } from "../../src/types/api";

const lagStep: ExecutionPlanStep = {
  step_id: "step-delay",
  tool: "delay_analyze",
  depends_on: [],
  parameters: {},
  requires_confirmation: true,
  status: "waiting_confirmation",
};

const lagRun: CopilotExecutionStepSnapshot = {
  step_id: "step-delay",
  sequence: 1,
  tool: "delay_analyze",
  status: "waiting_confirmation",
  requires_confirmation: true,
  confirmation_status: "PENDING",
  attempt_count: 1,
  source_version_id: "source-version-id",
  result_version_id: null,
  input_payload: { recommended_lag_map: { u1: 0, u2: 0, u3: 1 } },
  result_payload: {},
  processing_run_ids: [],
  error_code: null,
  error_message: null,
  started_at: null,
  finished_at: null,
};

describe("business UI typography contract", () => {
  it("renders lag variables and recommendations as ordinary Sans UI", () => {
    const wrapper = mount(ApprovalCard, {
      props: {
        stepRun: lagRun,
        planStep: lagStep,
        executionId: "execution-id",
        copilotRunId: "copilot-run-id",
      },
    });

    const rows = wrapper.findAll(".ac-lag-row").slice(1);
    expect(rows.map(row => row.text())).toEqual([
      "u10",
      "u20",
      "u31",
    ]);
    for (const row of rows) expect(row.find(".font-mono").exists()).toBe(false);

    const source = readFileSync(resolve(process.cwd(), "src/components/workspace/ApprovalCard.vue"), "utf8");
    const lagRule = source.match(/\.ac-lag-row\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(lagRule).toContain("font-family: var(--font-sans)");
    expect(lagRule).toContain("letter-spacing: normal");
  });

  it("keeps delay result values and sampling units in Sans", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/artifact/ArtifactWorkbench.vue"), "utf8");
    expect(source).toContain('<span class="aw-kv__key">{{ key }}</span>');
    expect(source).toContain('<span class="aw-kv__val">{{ val }} 采样点</span>');
    expect(source).not.toContain('class="aw-kv__val font-mono">{{ val }} 采样点');
  });

  it("uses Sans for model parameters and Mono for raw technical evidence", () => {
    const workbench = readFileSync(resolve(process.cwd(), "src/components/artifact/ArtifactWorkbench.vue"), "utf8");
    const report = readFileSync(resolve(process.cwd(), "src/components/artifact/ReportArtifactRenderer.vue"), "utf8");
    const mainCss = readFileSync(resolve(process.cwd(), "src/assets/main.css"), "utf8");

    expect(workbench).toContain('class="aw-json font-mono"');
    expect(workbench).toContain('<span class="aw-kv__val">{{ parameter.value }}</span>');
    expect(workbench).not.toContain('class="aw-kv__val font-mono"');
    expect(report).toContain('class="report-raw font-mono"');
    expect(report).toContain('<dd class="font-mono">{{ item.value }}</dd>');
    expect(mainCss).toMatch(/\.font-mono\s*\{\s*font-family: var\(--font-mono\);/);
    expect(mainCss).toMatch(/\.tabular-nums\s*\{[^}]*font-family: var\(--font-sans\);/s);
  });
});
