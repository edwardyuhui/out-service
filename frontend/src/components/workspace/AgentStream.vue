<template>
  <div class="agent-stream" ref="streamRef">
    <!-- User Request Bubble -->
    <div class="stream-section">
      <div class="stream-user-request">
        <div class="stream-user-request__avatar">U</div>
        <div class="stream-user-request__body">
          <div class="stream-user-request__text">{{ execution.plan?.goal || '用户请求' }}</div>
        </div>
      </div>
    </div>

    <!-- Compliance Proof (compact) -->
    <div v-if="execution.artifacts?.compliance" class="stream-compliance">
      <span
        class="compliance-badge"
        :class="execution.artifacts.compliance.passed ? 'ok' : 'fail'"
      >
        {{ execution.artifacts.compliance.passed ? '✓ 合规证明通过' : '✗ 合规校验未通过' }}
      </span>
      <span class="compliance-id font-mono" :title="execution.artifacts?.compliance?.proof_id">
        {{ (execution.artifacts?.compliance?.proof_id ?? '').slice(0, 8) }}
      </span>
    </div>

    <!-- Plan Overview / Execution Timeline -->
    <AgentPlan
      v-if="execution.plan?.steps?.length"
      :steps="execution.plan.steps"
      :step-runs="execution.step_runs"
      :current-step-id="execution.current_step_id"
      @step-click="$emit('artifact-select', $event)"
    />

    <!-- Step Events Stream -->
    <div class="stream-events">
      <template v-for="stepRun in execution.step_runs" :key="stepRun.step_id">
        <!-- Tool Execution Event -->
        <ToolExecution
          :step-run="stepRun"
          :plan-step="getPlanStep(stepRun.step_id)"
          @click="$emit('artifact-select', stepRun.step_id)"
        />

        <!-- Approval Card (if waiting) -->
        <ApprovalCard
          v-if="needsApproval(stepRun.step_id)"
          :step-run="stepRun"
          :plan-step="getPlanStep(stepRun.step_id)"
          :execution-id="execution.execution_id"
          :copilot-run-id="execution.copilot_run_id"
          :submitting="isConfirming"
          @confirm="$emit('confirm', $event)"
        />
      </template>

      <!-- Currently running step indicator -->
      <div v-if="isRunning" class="stream-running" data-test="stream-running">
        <div class="stream-running__indicator">
          <span class="agent-working-dot" />
        </div>
        <div class="stream-running__text">
          <span class="stream-running__tool">{{ currentToolName }}</span>
          <span class="stream-running__desc">Agent 正在执行…</span>
        </div>
      </div>

      <!-- Manual execute triggers -->
      <div
        v-if="canExecuteEvaluation"
        class="stream-action-card"
        data-test="stream-evaluate-action"
      >
        <div class="stream-action-card__body">
          <div class="stream-action-card__title">模型评价</div>
          <div class="stream-action-card__desc">ARX 建模完成，点击在测试集上执行模型评价</div>
        </div>
        <button
          type="button"
          class="stream-action-card__btn"
          @click="$emit('execute-evaluation')"
        >
          执行评价
        </button>
      </div>

      <div
        v-if="canExecuteOptimization"
        class="stream-action-card"
        data-test="stream-optimize-action"
      >
        <div class="stream-action-card__body">
          <div class="stream-action-card__title">管道优化</div>
          <div class="stream-action-card__desc">点击启动 Optuna 闭环寻优（预计 2~10 分钟）</div>
        </div>
        <button
          type="button"
          class="stream-action-card__btn"
          @click="$emit('execute-optimization')"
        >
          启动优化
        </button>
      </div>
    </div>

    <div v-if="execution.workflow_status === 'SUCCEEDED'" class="stream-conclusion" data-test="execution-completed">
      <div class="stream-conclusion__label">任务已完成</div>
      <div>所有步骤执行成功，可在右侧成果展示区查看和下载结果。</div>
    </div>
    <div v-else-if="execution.workflow_status === 'FAILED'" class="stream-notice warning" role="alert">
      {{ execution.error_message || '任务执行失败，请查看失败步骤。' }}
    </div>

    <!-- Conclusion -->
    <div v-if="execution.artifacts?.conclusion" class="stream-conclusion">
      <div class="stream-conclusion__label">CONCLUSION · 执行结论</div>
      <div class="stream-conclusion__text">{{ execution.artifacts.conclusion }}</div>
      <div v-if="execution.artifacts?.assumptions?.length" class="stream-conclusion__assumptions">
        <div class="stream-conclusion__assumptions-label">ASSUMPTIONS · 建模假设</div>
        <ul>
          <li v-for="(a, i) in execution.artifacts.assumptions" :key="i">{{ a }}</li>
        </ul>
      </div>
    </div>

    <!-- Hydrating / resume notice (for E2E data-test compat) -->
    <div v-if="isHydrating" class="stream-notice info" data-test="hydrating-execution">
      正在从后端恢复 Agent Execution…
    </div>
    <div v-if="resumeNotice" class="stream-notice warning" data-test="resume-notice">
      {{ resumeNotice }}
    </div>
    <div v-if="execution.execution_id" class="stream-meta font-mono" style="display:none">
      <span data-test="execution-id">{{ execution.execution_id }}</span>
      <span data-test="workflow-status">{{ execution.workflow_status }}</span>
      <span data-test="current-version-id">{{ execution.current_version_id }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import AgentPlan from './AgentPlan.vue';
import ToolExecution from './ToolExecution.vue';
import ApprovalCard from './ApprovalCard.vue';
import type { CopilotExecutionSnapshot, ExecutionPlanStep, CopilotConfirmRequest } from '../../types/api';

const props = defineProps<{
  execution: CopilotExecutionSnapshot;
  isSending: boolean;
  isConfirming?: boolean;
}>();

const emit = defineEmits<{
  confirm: [req: CopilotConfirmRequest];
  'execute-evaluation': [];
  'execute-optimization': [];
  'artifact-select': [stepId: string];
}>();

const streamRef = ref<HTMLElement | null>(null);
const isHydrating = ref(false);
const resumeNotice = ref('');

const isRunning = computed(() =>
  props.execution.workflow_status === 'RUNNING' ||
  props.execution.workflow_status === 'WAITING_ASYNC_TASK'
);

const currentToolName = computed(() => {
  const step = props.execution.step_runs.find(
    s => s.step_id === props.execution.current_step_id
  );
  return step?.tool ?? '';
});

function getPlanStep(stepId: string): ExecutionPlanStep | undefined {
  return props.execution.plan?.steps?.find(s => s.step_id === stepId);
}

function needsApproval(stepId: string): boolean {
  if (props.execution.pending_confirmation_step_id !== stepId) return false;
  const run = props.execution.step_runs.find(s => s.step_id === stepId);
  return run?.confirmation_status === 'PENDING';
}

const canExecuteEvaluation = computed(() => {
  const pending = props.execution.plan?.steps?.find(
    s => s.tool === 'evaluate_model' && props.execution.step_runs.find(r => r.step_id === s.step_id)?.status === 'PENDING'
  );
  return !!pending && props.execution.current_step_id === pending.step_id && props.execution.workflow_status === 'PLANNED';
});

const canExecuteOptimization = computed(() => {
  const pending = props.execution.plan?.steps?.find(
    s => s.tool === 'optimize_pipeline' && props.execution.step_runs.find(r => r.step_id === s.step_id)?.status === 'PENDING'
  );
  return !!pending && props.execution.current_step_id === pending.step_id && props.execution.workflow_status === 'PLANNED';
});

// Auto-scroll to bottom when new events arrive
watch(() => props.execution.step_runs.length, async () => {
  await nextTick();
  if (streamRef.value) {
    streamRef.value.scrollTop = streamRef.value.scrollHeight;
  }
});
</script>

<style scoped>
.agent-stream {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  scroll-behavior: smooth;
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
}

/* User Request */
.stream-user-request {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-user-request__avatar {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: #EDF4E9;
  border: 1px solid #D6E5D1;
  color: #426340;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stream-user-request__text {
  font-size: 14px;
  color: #171717;
  line-height: 1.55;
}

/* Compliance Badge */
.stream-compliance {
  display: flex;
  align-items: center;
  gap: 8px;
}

.compliance-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 9999px;
  font-weight: 500;
}

.compliance-badge.ok {
  color: var(--success);
  background: var(--success-soft);
  border: 1px solid var(--color-success-border);
}

.compliance-badge.fail {
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid var(--color-error-border);
}

.compliance-id {
  font-size: 11px;
  color: #8E8E93;
}

/* Events stream */
.stream-events {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Running indicator */
.stream-running {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-left: 2.5px solid var(--accent);
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-running__indicator {
  flex-shrink: 0;
}

.stream-running__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stream-running__tool {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.stream-running__desc {
  font-size: 12px;
  color: #8E8E93;
}

/* Action cards (manual trigger) */
.stream-action-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-action-card__title {
  font-size: 13px;
  font-weight: 600;
  color: #171717;
  margin-bottom: 2px;
}

.stream-action-card__desc {
  font-size: 12px;
  color: #666666;
}

.stream-action-card__btn {
  flex-shrink: 0;
  padding: 6px 14px;
  background: #426340;
  border: none;
  border-radius: 6px;
  color: #FFFFFF;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.stream-action-card__btn:hover {
  background: #345032;
}

/* Conclusion */
.stream-conclusion {
  padding: 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  border-left: 3px solid var(--success);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-conclusion__label {
  font-size: 11px;
  color: var(--success);
  letter-spacing: normal;
  font-family: var(--font-sans);
  margin-bottom: 8px;
  font-weight: 600;
}

.stream-conclusion__text {
  font-size: 13px;
  color: #171717;
  line-height: 1.6;
}

.stream-conclusion__assumptions {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ECECED;
}

.stream-conclusion__assumptions-label {
  font-size: 11px;
  color: #8E8E93;
  letter-spacing: normal;
  font-family: var(--font-sans);
  margin-bottom: 8px;
  font-weight: 600;
}

.stream-conclusion__assumptions ul {
  padding-left: 16px;
}

.stream-conclusion__assumptions li {
  font-size: 12px;
  color: #666666;
  line-height: 1.6;
}

/* Notice banners */
.stream-notice {
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
}

.stream-notice.info {
  background: var(--info-soft);
  border: 1px solid var(--color-info-border);
  color: var(--info);
}

.stream-notice.warning {
  background: var(--warning-soft);
  border: 1px solid var(--color-warning-border);
  color: var(--warning);
}
</style>
