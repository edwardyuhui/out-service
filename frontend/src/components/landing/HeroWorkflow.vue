<template>
  <div
    ref="zone"
    class="hero-workflow"
    :class="{ 'has-pointer': pointerInside }"
    aria-label="可组合工业建模工作流"
    @pointerenter="pointerInside = true"
    @pointerleave="resetPointer"
    @pointermove="handlePointerMove"
  >
    <!-- Top Minimalist Track Bar -->
    <div class="workflow-topbar">
      <div class="track-title-group">
        <span class="track-tag font-mono">PIPELINE</span>
        <span class="track-title">8 阶段闭环建模拓扑</span>
      </div>
      <div class="track-hint font-mono">
        <span>点击或悬停节点探索</span>
      </div>
    </div>

    <!-- Clean Linear Flow Track -->
    <div class="workflow-track-wrapper">
      <div class="workflow-track">
        <div class="track-line" aria-hidden="true">
          <div
            class="track-progress"
            :style="{ width: ((activeIndex + 0.5) / steps.length) * 100 + '%' }"
          ></div>
        </div>

        <button
          v-for="(step, index) in steps"
          :key="step.name"
          :ref="(element) => setNodeRef(element, index)"
          class="workflow-node"
          :class="{
            active: activeIndex === index,
            passed: activeIndex > index,
          }"
          type="button"
          @focus="activeIndex = index"
          @pointerenter="activeIndex = index"
          @click="activeIndex = index"
        >
          <!-- Minimalist Circle Icon -->
          <div class="node-bubble">
            <span class="bubble-num font-mono">{{ String(index + 1).padStart(2, "0") }}</span>
          </div>

          <div class="node-label">
            <span class="node-name">{{ step.name }}</span>
            <span class="node-cname">{{ step.cname }}</span>
          </div>
        </button>
      </div>
    </div>

    <!-- Unified Minimalist Detail Card -->
    <div class="workflow-detail-panel" aria-live="polite">
      <div class="detail-left">
        <div class="detail-header">
          <span class="detail-badge font-mono">{{ activeStep.label }}</span>
          <span class="detail-step-index font-mono">STAGE {{ String(activeIndex + 1).padStart(2, "0") }}</span>
        </div>
        <h3 class="detail-title">{{ activeStep.name }} · {{ activeStep.cname }}</h3>
        <p class="detail-desc">{{ activeStep.detail }}</p>
      </div>

      <div class="detail-right">
        <div class="meta-row">
          <span class="meta-label font-mono">CORE ALGORITHM</span>
          <span class="meta-value">{{ activeStep.algorithm }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label font-mono">GUARDRAIL</span>
          <span class="meta-value">{{ activeStep.guardrail }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label font-mono">ARTIFACT</span>
          <span class="meta-value font-mono text-primary">{{ activeStep.artifact }}</span>
        </div>
      </div>
    </div>

    <!-- Footer Note -->
    <div class="workflow-footer">
      <span class="footer-dot"></span>
      <p class="workflow-note">按工程目标组合步骤，并非每个任务固定执行全部流程。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

interface WorkflowStep {
  name: string;
  cname: string;
  label: string;
  detail: string;
  algorithm: string;
  guardrail: string;
  artifact: string;
}

const steps: WorkflowStep[] = [
  {
    name: "Raw Data",
    cname: "数据接入",
    label: "01 DATA INGESTION",
    detail: "多通道时序数据清洗接入，解析时间戳、阀位开度与传感器温度等原始量纲。",
    algorithm: "纳秒级单调性检查与时间戳规整",
    guardrail: "空值率安全门控 (<50%)",
    artifact: "Dataset Version V0 (Raw)",
  },
  {
    name: "Cleaning",
    cname: "清洗插值",
    label: "02 QUALITY ASSURANCE",
    detail: "消除传感器跳变噪声、三次样条插值填补微小缺失，并统一多通道采样频率。",
    algorithm: "IQR 四分位滤波与三次样条重采样",
    guardrail: "连续缺失段长度 ≤ 12 步",
    artifact: "Dataset Version V1 (Cleaned)",
  },
  {
    name: "Segmentation",
    cname: "D-最优优选",
    label: "03 D-OPTIMAL SELECTION",
    detail: "基于反向最优实验设计，从漫长稳态中精准截取高信息量过渡带，保障矩阵满秩。",
    algorithm: "信息矩阵行列式极大化 (CELF Lazy Greedy)",
    guardrail: "预算窗长比 ≥ 2.3 · 满秩门控",
    artifact: "Active_Segments (14.3% 预算)",
  },
  {
    name: "Delay",
    cname: "时滞测定",
    label: "04 LAG ESTIMATION",
    detail: "通过 AR 预白化消除输入自相关虚假峰值，精准测定阀位到温度的真实物理纯时滞。",
    algorithm: "预白化互相关时滞测定 (CCF Peak)",
    guardrail: "物理单调性与时滞上限约束",
    artifact: "Lag Matrix (nk=1..5)",
  },
  {
    name: "Feature",
    cname: "共线性降维",
    label: "05 COLLINEARITY REDUCTION",
    detail: "计算方差膨胀因子（VIF），剔除高共线性的冗余测点，避免多变量过拟合。",
    algorithm: "VIF 方差膨胀因子与主成分降维",
    guardrail: "VIF 阈值 ≤ 10 · 关键输入保护",
    artifact: "Reduced Feature Vector",
  },
  {
    name: "ARX",
    cname: "系统辨识",
    label: "06 SYSTEM IDENTIFICATION",
    detail: "基于最小二乘 Householder QR 分解辨识 ARX 参数，并进行全局自由仿真稳定性验证。",
    algorithm: "Householder QR 分解与自由仿真",
    guardrail: "系统极点位于单位圆内 (渐近稳定)",
    artifact: "Saved Model (ARX-Best)",
  },
  {
    name: "Optimize",
    cname: "闭环寻优",
    label: "07 CLOSED-LOOP SEARCH",
    detail: "利用 TPE 贝叶斯搜索算法在模型阶数与时滞空间自动寻优，两阶段算力摊薄加速 24 倍。",
    algorithm: "TPE 树状 Parzen 估计超参搜索",
    guardrail: "Early Stopping 20 Trials 早停",
    artifact: "Optuna Study Artifact",
  },
  {
    name: "Evaluate",
    cname: "独立测试",
    label: "08 HELD-OUT EVALUATION",
    detail: "在完全隔离的时间外测试集上验证模型自由仿真精度，生成全数值可溯源交付物。",
    algorithm: "自由仿真残差范数评估",
    guardrail: "测试集时间维度严格隔离",
    artifact: "Verification Report & PDF",
  },
];

const defaultStep: WorkflowStep = steps[2]; // Default to Segmentation

const zone = ref<HTMLElement | null>(null);
const nodeRefs: HTMLElement[] = [];
const activeIndex = ref(2);
const pointerInside = ref(false);
let animationFrame: number | null = null;
let pendingPointer: PointerEvent | null = null;

const activeStep = computed(() => steps[activeIndex.value] ?? defaultStep);

function setNodeRef(element: unknown, index: number) {
  if (element instanceof HTMLElement) {
    nodeRefs[index] = element;
  }
}

function applyPointerPosition(event: PointerEvent) {
  if (!zone.value) return;
  const bounds = zone.value.getBoundingClientRect();
  const x = event.clientX - bounds.left;
  const y = event.clientY - bounds.top;
  zone.value.style.setProperty("--pointer-x", `${x}px`);
  zone.value.style.setProperty("--pointer-y", `${y}px`);

  let nearestIndex = -1;
  let nearestDistance = Number.POSITIVE_INFINITY;
  nodeRefs.forEach((node, index) => {
    const rect = node.getBoundingClientRect();
    const nodeX = rect.left + rect.width / 2;
    const nodeY = rect.top + rect.height / 2;
    const distance = Math.hypot(event.clientX - nodeX, event.clientY - nodeY);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  if (nearestIndex !== -1) {
    activeIndex.value = nearestIndex;
  }
}

function handlePointerMove(event: PointerEvent) {
  if (event.pointerType === "touch") return;
  pendingPointer = event;
  if (animationFrame !== null) return;
  animationFrame = window.requestAnimationFrame(() => {
    if (pendingPointer) applyPointerPosition(pendingPointer);
    animationFrame = null;
  });
}

function resetPointer() {
  pointerInside.value = false;
  pendingPointer = null;
}

onBeforeUnmount(() => {
  if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
});
</script>

<style scoped>
.hero-workflow {
  --pointer-x: 50%;
  --pointer-y: 50%;
  position: relative;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  color: #1e293b;
  font-size: 13px;
}

/* Minimalist Topbar */
.workflow-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.track-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.track-tag {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid #bfdbfe;
}

.track-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.track-hint {
  font-size: 11px;
  color: #94a3b8;
}

/* Linear Flow Track */
.workflow-track-wrapper {
  padding: 24px 20px 20px;
  background: #ffffff;
  overflow-x: auto;
}

.workflow-track {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  min-width: 580px;
}

/* Continuous connection line */
.track-line {
  position: absolute;
  top: 14px;
  left: 20px;
  right: 20px;
  height: 2px;
  background: #e2e8f0;
  z-index: 0;
}

.track-progress {
  height: 100%;
  background: #2563eb;
  transition: width 0.3s ease;
}

.workflow-node {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 0 4px;
  transition: all 0.2s ease;
}

.node-bubble {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #ffffff;
  border: 2px solid #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.bubble-num {
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
}

.workflow-node:hover .node-bubble {
  border-color: #2563eb;
  transform: scale(1.1);
}

.workflow-node.passed .node-bubble {
  border-color: #93c5fd;
  background: #eff6ff;
}

.workflow-node.active .node-bubble {
  border-color: #2563eb;
  background: #2563eb;
  transform: scale(1.15);
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.15);
}

.workflow-node.active .bubble-num {
  color: #ffffff;
}

.node-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}

.node-name {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}

.node-cname {
  font-size: 10px;
  color: #94a3b8;
  white-space: nowrap;
}

.workflow-node:hover .node-name,
.workflow-node.active .node-name {
  color: #0f172a;
  font-weight: 700;
}

.workflow-node.active .node-cname {
  color: #2563eb;
}

/* Unified Detail Panel (Clean Split-View) */
.workflow-detail-panel {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 24px;
  padding: 18px 24px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
}

.detail-left {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.detail-badge {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid #bfdbfe;
}

.detail-step-index {
  font-size: 10px;
  color: #94a3b8;
  font-weight: 600;
}

.detail-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.detail-desc {
  margin: 0;
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
}

.detail-right {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  padding-left: 20px;
  border-left: 1px solid #e2e8f0;
}

.meta-row {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.meta-label {
  font-size: 9px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.05em;
}

.meta-value {
  font-size: 12px;
  color: #1e293b;
  font-weight: 500;
}

.text-primary {
  color: #2563eb;
  font-weight: 600;
}

/* Footer Note */
.workflow-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  font-size: 11px;
  color: #64748b;
}

.footer-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #2563eb;
}

.workflow-note {
  margin: 0;
}

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 800px) {
  .workflow-detail-panel {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .detail-right {
    padding-left: 0;
    border-left: none;
    border-top: 1px solid #e2e8f0;
    padding-top: 12px;
  }
}
</style>
