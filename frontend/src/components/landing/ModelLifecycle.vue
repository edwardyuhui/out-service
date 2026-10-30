<template>
  <div class="lifecycle-shell" aria-label="模型与寻优工程生命周期">
    <!-- Top 5-Phase Blueprint Stepper -->
    <div class="blueprint-track" role="list">
      <div
        v-for="(stage, index) in stages"
        :key="stage.name"
        class="blueprint-card"
        role="listitem"
      >
        <div class="card-head">
          <span class="stage-code font-mono">{{ stage.code }}</span>
          <span class="stage-index font-mono">0{{ index + 1 }}</span>
        </div>
        <h4 class="stage-title">{{ stage.name }}</h4>
        <p class="stage-desc">{{ stage.detail }}</p>
        <div class="stage-footer font-mono">
          <span class="foot-dot"></span>
          <span class="stage-boundary">{{ stage.boundary }}</span>
        </div>
      </div>
    </div>

    <!-- Bottom Distinct Proof Banner -->
    <div class="lifecycle-proof-banner">
      <div class="proof-unit">
        <div class="proof-icon-box">
          <svg class="proof-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
          </svg>
        </div>
        <div class="proof-copy">
          <span class="proof-tag font-mono">MODEL ASSET</span>
          <strong class="proof-strong">结构、参数与 source version 共同保存</strong>
        </div>
      </div>

      <div class="proof-unit">
        <div class="proof-icon-box icon-emerald">
          <svg class="proof-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
        </div>
        <div class="proof-copy">
          <span class="proof-tag font-mono text-emerald">EVALUATION</span>
          <strong class="proof-strong">同一保存模型进入 held-out Test</strong>
        </div>
      </div>

      <div class="proof-statement">
        <span class="statement-dot"></span>
        <p class="statement-text">页面只呈现正式工程边界，不展示虚构性能数值。</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const stages = [
  { code: "STRUCTURE", name: "ARX", detail: "定义输入输出动态结构与多项式", boundary: "System identification" },
  { code: "VALIDATE", name: "Validation", detail: "在验证集上比较候选结构与拟合精度", boundary: "Selection boundary" },
  { code: "SEARCH", name: "Optuna Search", detail: "在验证范围内执行超参贝叶斯寻优", boundary: "No Test tuning" },
  { code: "FREEZE", name: "Saved Model", detail: "固化模型资产与真实不可变血缘", boundary: "Replayable artifact" },
  { code: "EVALUATE", name: "Held-out Evaluation", detail: "对保存模型完成最终独立评价", boundary: "One-step + free-run" },
];
</script>

<style scoped>
.lifecycle-shell {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.05);
  display: flex;
  flex-direction: column;
}

/* 5 Connected Blueprint Cards */
.blueprint-track {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  padding: 24px;
  background: #f8fafc;
}

.blueprint-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.blueprint-card:hover {
  border-color: #2563eb;
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stage-code {
  font-size: 9px;
  font-weight: 800;
  color: #2563eb;
  letter-spacing: 0.05em;
}

.stage-index {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
}

.stage-title {
  margin: 4px 0 2px;
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
}

.stage-desc {
  margin: 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  flex-grow: 1;
}

.stage-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #f1f5f9;
  font-size: 9px;
  color: #475569;
}

.foot-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #059669;
}

/* Proof Banner */
.lifecycle-proof-banner {
  padding: 18px 24px;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  display: grid;
  grid-template-columns: 1.1fr 1.1fr 1fr;
  align-items: center;
  gap: 20px;
}

.proof-unit {
  display: flex;
  align-items: center;
  gap: 12px;
}

.proof-icon-box {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.icon-emerald {
  background: #ecfdf5;
  color: #059669;
}

.proof-svg {
  width: 16px;
  height: 16px;
}

.proof-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.proof-tag {
  font-size: 9px;
  font-weight: 700;
  color: #2563eb;
  letter-spacing: 0.08em;
}

.proof-strong {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.4;
}

.proof-statement {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-self: end;
}

.statement-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #94a3b8;
}

.statement-text {
  margin: 0;
  font-size: 11px;
  color: #64748b;
}

.text-emerald { color: #059669; }
.font-mono { font-family: var(--font-mono); }

@media (max-width: 1024px) {
  .blueprint-track {
    grid-template-columns: repeat(2, 1fr);
  }
  .lifecycle-proof-banner {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .proof-statement {
    justify-self: start;
  }
}

@media (max-width: 640px) {
  .blueprint-track {
    grid-template-columns: 1fr;
  }
}
</style>
