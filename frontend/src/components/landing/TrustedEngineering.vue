<template>
  <div class="trust-layout" aria-label="核心可信工程底座">
    <!-- Left Hero Bento Card: Data Trust & Lineage DAG -->
    <article class="trust-module trust-module-data" tabindex="0">
      <div class="module-top">
        <div class="module-tag-row">
          <span class="module-number font-mono">01</span>
          <span class="module-badge font-mono">IMMUTABLE LINEAGE · Example Lineage</span>
        </div>
        <h3 class="module-title">数据可信 · 全生命周期不可变血缘</h3>
        <p class="module-desc">
          版本血缘贯穿清洗与预处理，让每次数据变换都有来源、有依据。原始多变量时序入库后固化为基准版本 V0，
          后续每次清洗对齐与 D-最优优选均派生全新的不可变数据实体，杜绝就地覆盖与脏数据污染。
        </p>
      </div>

      <!-- Rich Interactive Lineage DAG Component -->
      <div class="lineage-dag-box" aria-label="数据版本血缘示意">
        <div class="dag-nodes-flow">
          <div class="dag-step-node">
            <div class="dag-node-header">
              <span class="dag-version font-mono">V0</span>
              <span class="dag-tag font-mono">Original</span>
            </div>
            <div class="dag-node-name">原始工业时序</div>
            <div class="dag-node-info">多通道传感器原始采样 (4000点)</div>
          </div>

          <div class="dag-edge">
            <span class="edge-line"></span>
            <span class="edge-label font-mono">IQR清洗 / 样条插值</span>
            <span class="edge-arrow">›</span>
          </div>

          <div class="dag-step-node">
            <div class="dag-node-header">
              <span class="dag-version font-mono">V1</span>
              <span class="dag-tag font-mono">Cleaning</span>
            </div>
            <div class="dag-node-name">规整基准数据集</div>
            <div class="dag-node-info">等间隔对齐 · 异常值剔除修复</div>
          </div>

          <div class="dag-edge">
            <span class="edge-line"></span>
            <span class="edge-label font-mono">D-最优高动态优选</span>
            <span class="edge-arrow">›</span>
          </div>

          <div class="dag-step-node dag-node-active">
            <div class="dag-node-header">
              <span class="dag-version font-mono">V2</span>
              <span class="dag-tag font-mono">Derived</span>
            </div>
            <div class="dag-node-name">优选建模特征集</div>
            <div class="dag-node-info">14.3% 预算 · 满秩动态窗口</div>
          </div>
        </div>

        <div class="lineage-properties font-mono">
          <div class="prop-item"><span class="prop-dot"></span>时间单调性 100% 校验</div>
          <div class="prop-item"><span class="prop-dot"></span>不可变哈希指纹锚定</div>
          <div class="prop-item"><span class="prop-dot"></span>父子派生指针完整回溯</div>
        </div>
      </div>
    </article>

    <!-- Right Top Bento Card: Model Trust & White-Box Simulation -->
    <article class="trust-module trust-module-model" tabindex="0">
      <div class="module-top">
        <div class="module-tag-row">
          <span class="module-number font-mono">02</span>
          <span class="module-badge font-mono">WHITE-BOX SIMULATION</span>
        </div>
        <h3 class="module-title">模型可信 · 白盒机理与自由仿真验证</h3>
        <p class="module-desc">
          模型结构、保存资产与评价结果共同形成可重放的系统辨识证据。
          拒绝“黑盒拟合”，提供清晰的差分方程多项式与单位圆极点分布，通过纯自由仿真（无测量反馈）对账。
        </p>
      </div>

      <!-- Waveform Simulation Visual -->
      <div class="model-visual-box" aria-label="测量值与模型响应示意">
        <div class="svg-wrapper">
          <svg viewBox="0 0 400 90" class="model-svg" role="img" aria-label="测量响应与模型响应曲线">
            <!-- Grid -->
            <line x1="0" y1="45" x2="400" y2="45" stroke="#f1f5f9" stroke-width="1" stroke-dasharray="3,3" />
            <!-- Measured Line (Solid Deep Blue) -->
            <polyline
              class="measured"
              points="0,68 30,65 60,52 90,26 120,18 150,30 180,50 210,58 240,46 270,30 300,35 330,50 360,56 400,48"
            />
            <!-- Predicted Model Line (Dashed Emerald) -->
            <polyline
              class="predicted"
              points="0,70 30,62 60,49 90,28 120,20 150,32 180,48 210,55 240,48 270,32 300,38 330,48 360,54 400,50"
            />
          </svg>
        </div>
        <div class="model-legend-bar">
          <div class="legend-unit font-mono">
            <span class="leg-dash dash-measured"></span>
            <span>Measured 实测真实响应</span>
          </div>
          <div class="legend-unit font-mono">
            <span class="leg-dash dash-predicted"></span>
            <span>Model 自由仿真拟合输出</span>
          </div>
          <div class="model-status-chip font-mono">
            <span>A(q) 极点渐近稳定</span>
          </div>
        </div>
      </div>
    </article>

    <!-- Right Bottom Bento Card: Decision Process Trust & Human Gate -->
    <article class="trust-module trust-module-decision" tabindex="0">
      <div class="module-top">
        <div class="module-tag-row">
          <span class="module-number font-mono">03</span>
          <span class="module-badge font-mono">HUMAN-IN-THE-LOOP</span>
        </div>
        <h3 class="module-title">决策过程可信 · 人在回路与确定性安全门控</h3>
        <p class="module-desc">
          Agent 编排、人工确认、Optuna 与 held-out evaluation 共同约束执行路径。
          关键时滞与特征筛选必须由 Human Approval 确认，最终由 User Trigger 触发 Held-out Evaluation 独立验证。
        </p>
      </div>

      <!-- Decision Process Stepper Visual -->
      <div class="decision-stepper-box" aria-label="决策过程步骤示意">
        <div class="dec-step-item">
          <div class="dec-circle font-mono">01</div>
          <div class="dec-texts">
            <span class="dec-main font-mono">Plan</span>
            <span class="dec-sub">Agent 编排规划</span>
          </div>
        </div>

        <div class="dec-arrow-sep">›</div>

        <div class="dec-step-item dec-step-highlight">
          <div class="dec-circle font-mono">02</div>
          <div class="dec-texts">
            <span class="dec-main font-mono">Approval</span>
            <span class="dec-sub text-primary">Human Approval 门控</span>
          </div>
        </div>

        <div class="dec-arrow-sep">›</div>

        <div class="dec-step-item">
          <div class="dec-circle font-mono">03</div>
          <div class="dec-texts">
            <span class="dec-main font-mono">Optimize</span>
            <span class="dec-sub">Optuna 闭环寻优</span>
          </div>
        </div>

        <div class="dec-arrow-sep">›</div>

        <div class="dec-step-item">
          <div class="dec-circle font-mono">04</div>
          <div class="dec-texts">
            <span class="dec-main font-mono">Evaluate</span>
            <span class="dec-sub">User Trigger 评价</span>
          </div>
        </div>
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
// TrustedEngineering component
</script>

<style scoped>
.trust-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  grid-template-rows: repeat(2, minmax(240px, auto));
  gap: 20px;
  min-height: 540px;
}

/* Bento Modules */
.trust-module {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 16px;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
  transition: all 0.22s ease;
}

.trust-module:hover {
  border-color: #93c5fd;
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
}

.trust-module-data {
  grid-row: 1 / 3;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.trust-module-model {
  background: #ffffff;
}

.trust-module-decision {
  background: #ffffff;
}

/* Module Header Typography */
.module-top {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.module-tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.module-number {
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid #bfdbfe;
}

.module-badge {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.05em;
}

.module-title {
  margin: 0;
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.3;
}

.module-desc {
  margin: 0;
  font-size: 13px;
  color: #475569;
  line-height: 1.65;
}

/* Left Card: Lineage DAG Box */
.lineage-dag-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.02);
}

.dag-nodes-flow {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dag-step-node {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: all 0.2s ease;
}

.dag-node-active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}

.dag-node-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dag-version {
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
  background: #ffffff;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid #cbd5e1;
}

.dag-tag {
  font-size: 9px;
  color: #94a3b8;
  font-weight: 700;
}

.dag-node-name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.dag-node-info {
  font-size: 11px;
  color: #64748b;
}

.dag-edge {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #94a3b8;
  padding: 0 10px;
}

.edge-line {
  flex: 1;
  height: 1px;
  background: #e2e8f0;
}

.edge-label {
  font-size: 9px;
  color: #64748b;
  background: #ffffff;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid #e2e8f0;
}

.edge-arrow {
  color: #2563eb;
  font-size: 12px;
  font-weight: bold;
}

.lineage-properties {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 10px;
  color: #64748b;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.prop-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.prop-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #059669;
}

/* Right Top: Model Visual */
.model-visual-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.svg-wrapper {
  width: 100%;
  height: 64px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 4px;
}

.model-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.measured {
  fill: none;
  stroke: #2563eb;
  stroke-width: 2.2;
  stroke-linecap: round;
}

.predicted {
  fill: none;
  stroke: #059669;
  stroke-width: 2.2;
  stroke-dasharray: 4,3;
  stroke-linecap: round;
}

.model-legend-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
}

.legend-unit {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #475569;
}

.leg-dash {
  width: 14px;
  height: 3px;
  border-radius: 2px;
}

.dash-measured { background: #2563eb; }
.dash-predicted { background: #059669; }

.model-status-chip {
  font-size: 10px;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid #a7f3d0;
}

/* Right Bottom: Decision Stepper */
.decision-stepper-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.dec-step-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dec-circle {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
}

.dec-step-highlight .dec-circle {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

.dec-texts {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.dec-main {
  font-size: 11px;
  font-weight: 700;
  color: #0f172a;
}

.dec-sub {
  font-size: 9px;
  color: #64748b;
  white-space: nowrap;
}

.dec-arrow-sep {
  color: #cbd5e1;
  font-size: 16px;
  font-weight: bold;
}

.text-primary {
  color: #2563eb;
  font-weight: 700;
}

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 1024px) {
  .trust-layout {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
  .trust-module-data {
    grid-row: auto;
  }
}
</style>
