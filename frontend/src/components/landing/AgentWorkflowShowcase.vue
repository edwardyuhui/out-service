<template>
  <div class="agent-showcase" aria-label="Agent 执行路径">
    <!-- Two-Column Terminal / Copilot Studio Layout -->
    <div class="copilot-grid">
      <!-- Left: Agent Dialog & Execution Stream -->
      <div class="copilot-stream">
        <div class="stream-header">
          <div class="stream-title">
            <span class="pulse-indicator"></span>
            <span class="font-mono text-bold">INDUS-COPILOT · AGENT ENGINE</span>
          </div>
          <span class="stream-mode font-mono">AUTONOMOUS ORCHESTRATION</span>
        </div>

        <div class="intent-bubble">
          <div class="bubble-sender font-mono">
            <svg class="sender-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
            <span>ENGINEERING INTENT</span>
          </div>
          <p class="bubble-prompt font-mono">
            "完成 ARX 模型辨识，使用 Optuna 对模型进行优化，并评价优化后的模型。"
          </p>
        </div>

        <!-- Step List Stream -->
        <div class="stream-steps" role="tablist">
          <button
            v-for="(step, index) in steps"
            :key="step.name"
            class="stream-step-row"
            :class="{ active: activeIndex === index, 'is-gate': step.control === 'Human Approval' || step.control === 'User Trigger' }"
            type="button"
            role="tab"
            :aria-selected="activeIndex === index"
            @click="activeIndex = index"
            @pointerenter="activeIndex = index"
          >
            <div class="step-badge-index font-mono">0{{ index + 1 }}</div>
            <div class="step-main-info">
              <div class="step-name-row">
                <span class="step-name">{{ step.name }}</span>
                <span class="step-control-tag font-mono" :class="'ctrl-' + step.control.toLowerCase().replace(/\s+/g, '-')">
                  {{ step.control }}
                </span>
              </div>
              <span class="step-type-text font-mono">{{ step.type }}</span>
            </div>
            <div class="step-select-chevron">›</div>
          </button>
        </div>
      </div>

      <!-- Right: Real-time Node Inspector & Safety Boundary -->
      <div class="copilot-inspector" aria-live="polite">
        <div class="inspector-top">
          <div class="ins-tag font-mono">{{ activeStep.type }} · STAGE 0{{ activeIndex + 1 }}</div>
          <h4 class="ins-title">{{ activeStep.name }}</h4>
        </div>

        <div class="ins-content">
          <div class="ins-section">
            <div class="ins-label font-mono">TASK EXECUTION</div>
            <p class="ins-desc">{{ activeStep.detail }}</p>
          </div>

          <div class="ins-meta-grid">
            <div class="meta-box">
              <span class="meta-box-label font-mono">CONTROL GATE</span>
              <span class="meta-box-val font-mono">{{ activeStep.control }}</span>
            </div>
            <div class="meta-box">
              <span class="meta-box-label font-mono">INTERACTION LEVEL</span>
              <span class="meta-box-val font-mono">{{ activeStep.control === 'Human Approval' ? 'HITL (人在回路)' : 'Autonomous (自动)' }}</span>
            </div>
          </div>

          <div class="ins-boundary-card">
            <div class="boundary-header font-mono">
              <svg class="boundary-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
              </svg>
              <span>DETERMINISTIC BOUNDARY</span>
            </div>
            <div class="boundary-value font-mono">{{ activeStep.boundary }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

interface AgentStep {
  name: string;
  control: string;
  type: string;
  detail: string;
  boundary: string;
}

const steps: AgentStep[] = [
  {
    name: "Profile",
    control: "Inspect",
    type: "DATA CONTEXT",
    detail: "读取数据画像与多通道采样统计量，为后续模型阶数决策建立不可变上下文。",
    boundary: "Read-only analysis (只读不修改)",
  },
  {
    name: "Dynamic Segment",
    control: "Select",
    type: "SIGNAL WINDOW",
    detail: "基于质量约束 D-最优算法，自动定位表达过程动态特性的高信噪比过渡带。",
    boundary: "Traceable source segment (可溯源段)",
  },
  {
    name: "Fit ARX",
    control: "Human Approval",
    type: "MODEL STRUCTURE",
    detail: "工程师确认拟合参数与时滞阶数后执行系统辨识，并保存可重放的模型资产。",
    boundary: "Confirmation required (必须人工确认)",
  },
  {
    name: "Optimize",
    control: "Human Approval",
    type: "VALIDATION SEARCH",
    detail: "在验证集边界内运行 Optuna 贝叶斯搜索，生成新的正式全局寻优模型。",
    boundary: "No Test tuning (严禁测试集调优)",
  },
  {
    name: "Evaluate",
    control: "User Trigger",
    type: "HELD-OUT TEST",
    detail: "用户显式触发已保存模型的最终评测，读取 held-out Test 独立数据集生成真实结果。",
    boundary: "No refit (不可重新拟合)",
  },
];

const activeIndex = ref(2);
const activeStep = computed(() => steps[activeIndex.value]);
</script>

<style scoped>
.agent-showcase {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.05);
}

.copilot-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  min-height: 440px;
}

/* Left: Dialog & Stream */
.copilot-stream {
  padding: 24px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stream-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.stream-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #0f172a;
}

.pulse-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 6px #2563eb;
}

.stream-mode {
  font-size: 9px;
  color: #64748b;
  letter-spacing: 0.05em;
}

/* Intent Bubble */
.intent-bubble {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}

.bubble-sender {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
}

.sender-svg {
  width: 12px;
  height: 12px;
}

.bubble-prompt {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  line-height: 1.5;
}

/* Step List */
.stream-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stream-step-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  transition: all 0.18s ease;
}

.stream-step-row:hover {
  border-color: #93c5fd;
  transform: translateX(3px);
}

.stream-step-row.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}

.stream-step-row.is-gate {
  border-left: 3px solid #d97706;
}

.step-badge-index {
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
}

.step-main-info {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.step-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.step-control-tag {
  font-size: 9px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #475569;
}

.ctrl-human-approval,
.ctrl-user-trigger {
  background: #fef3c7;
  color: #92400e;
}

.step-type-text {
  font-size: 9px;
  color: #94a3b8;
  font-weight: 600;
}

.step-select-chevron {
  font-size: 16px;
  color: #cbd5e1;
  font-weight: bold;
}

.stream-step-row.active .step-select-chevron {
  color: #2563eb;
}

/* Right: Inspector */
.copilot-inspector {
  padding: 28px 24px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 20px;
}

.inspector-top {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.ins-tag {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
  letter-spacing: 0.05em;
}

.ins-title {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
}

.ins-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ins-label {
  font-size: 9px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}

.ins-desc {
  margin: 0;
  font-size: 13px;
  color: #334155;
  line-height: 1.65;
}

.ins-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.meta-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-box-label {
  font-size: 9px;
  color: #94a3b8;
  font-weight: 700;
}

.meta-box-val {
  font-size: 11px;
  font-weight: 700;
  color: #0f172a;
}

.ins-boundary-card {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 6px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.boundary-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 700;
  color: #15803d;
}

.boundary-svg {
  width: 12px;
  height: 12px;
}

.boundary-value {
  font-size: 12px;
  font-weight: 700;
  color: #047857;
}

.font-mono {
  font-family: var(--font-mono);
}

.text-bold {
  font-weight: 700;
}

@media (max-width: 860px) {
  .copilot-grid {
    grid-template-columns: 1fr;
  }
  .copilot-stream {
    border-right: none;
    border-bottom: 1px solid #e2e8f0;
  }
}
</style>
