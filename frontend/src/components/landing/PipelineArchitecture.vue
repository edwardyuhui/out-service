<template>
  <div class="pipeline-architecture" aria-label="IndusOpt 工业算法工程闭环">
    <!-- 6 Stage Flow Stepper -->
    <div class="pipeline-stepper">
      <button
        v-for="(stage, idx) in stages"
        :key="stage.id"
        class="stepper-node"
        :class="{ active: activeStageId === stage.id }"
        type="button"
        @click="activeStageId = stage.id"
      >
        <div class="node-top-bar">
          <span class="node-index font-mono">0{{ idx + 1 }}</span>
          <span class="node-cat">{{ stage.category }}</span>
        </div>
        <div class="node-title">{{ stage.title }}</div>
        <div class="node-summary">{{ stage.summary }}</div>
      </button>
    </div>

    <!-- Active Stage Detail Panel -->
    <div class="stage-detail-panel" aria-live="polite">
      <div class="detail-header">
        <div class="detail-title-group">
          <span class="detail-badge font-mono">{{ activeStage.category }} · STAGE 0{{ activeStageIndex + 1 }}</span>
          <h3 class="detail-title">{{ activeStage.title }}</h3>
        </div>
        <div class="detail-endpoint font-mono">{{ activeStage.endpoint }}</div>
      </div>

      <div class="detail-grid">
        <!-- Left: Purpose and Feature List -->
        <div class="detail-col-main">
          <div class="col-section-title font-mono">ENGINEERING MECHANISM</div>
          <p class="detail-desc">{{ activeStage.mechanism }}</p>
          <div class="feature-bullets">
            <div v-for="(b, i) in activeStage.bullets" :key="i" class="bullet-item">
              <svg class="bullet-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              <span class="bullet-text">{{ b }}</span>
            </div>
          </div>
        </div>

        <!-- Right: Algorithm, Guardrail, Artifact -->
        <div class="detail-col-side">
          <div class="side-card">
            <div class="side-card-label font-mono">
              <svg class="label-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
                <rect x="9" y="9" width="6" height="6"></rect>
                <line x1="9" y1="1" x2="9" y2="4"></line>
                <line x1="15" y1="1" x2="15" y2="4"></line>
                <line x1="9" y1="20" x2="9" y2="23"></line>
                <line x1="15" y1="20" x2="15" y2="23"></line>
              </svg>
              <span>ALGORITHM CORE</span>
            </div>
            <div class="side-card-val">{{ activeStage.algoDesc }}</div>
          </div>

          <div class="side-card guardrail-card">
            <div class="side-card-label font-mono text-emerald">
              <svg class="label-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                <polyline points="9 12 11 14 15 10"></polyline>
              </svg>
              <span>SAFETY GUARDRAIL</span>
            </div>
            <div class="side-card-val">{{ activeStage.guardrail }}</div>
          </div>

          <div class="side-card artifact-card">
            <div class="side-card-label font-mono text-blue">
              <svg class="label-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                <line x1="12" y1="22.08" x2="12" y2="12"></line>
              </svg>
              <span>IMMUTABLE ARTIFACT</span>
            </div>
            <div class="side-card-val font-mono">{{ activeStage.artifact }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

interface Stage {
  id: string;
  category: string;
  title: string;
  summary: string;
  endpoint: string;
  mechanism: string;
  algoDesc: string;
  bullets: string[];
  guardrail: string;
  artifact: string;
}

const stages: Stage[] = [
  {
    id: "data",
    category: "数据接入",
    title: "多源 CSV 规整清洗",
    summary: "时间戳解析与等间隔插值",
    endpoint: "POST /api/v1/preprocessing/clean",
    mechanism: "通过时间序列重采样、三次样条插值与 3σ 异常点清洗，输出基准规整数据版本，保留原始数据不可变性与完整血缘。",
    algoDesc: "IQR 四分位滤波与纳秒级时间戳单调性对齐",
    bullets: [
      "自动检测并解析多编码格式（UTF-8, GBK, Latin-1）",
      "时序等间隔重采样与多通道采样频率对齐",
      "生成不可变派生数据集版本 (V0 ➔ V1)",
    ],
    guardrail: "严格校验时间单调性；缺失率超过 20% 时触发质量预警并标记为不可辨识异常。",
    artifact: "CleanedDatasetProfile (V1) + Lineage DAG",
  },
  {
    id: "segment",
    category: "动态优选",
    title: "质量约束 D-最优优选",
    summary: "协方差极大化消除稳态冗余",
    endpoint: "POST /api/v1/preprocessing/segment",
    mechanism: "结合滑动窗口信噪比门控与多变量信息矩阵行列式极大化算法，以 14.3% 数据量完整捕获全量系统动态特性。",
    algoDesc: "反向最优实验设计与 CELF 延迟贪心搜索 (J = log det(XᵀX))",
    bullets: [
      "动态信噪比质量门控先行拦截低频稳态数据段",
      "贪心 D-最优算法迭代选取信息矩阵行列式增益最大的窗口",
      "数学证明彻底解决异构激励下的设计矩阵秩亏问题",
    ],
    guardrail: "内建预算门控：当预算/窗长 ≤ 2.3 时提示失效边界，阻断病态辨识。",
    artifact: "SelectedWindowSegments (14.3% 预算)",
  },
  {
    id: "delay",
    category: "时滞分析",
    title: "预白化互相关时滞补偿",
    summary: "多通道纯时滞估计与移位对齐",
    endpoint: "POST /api/v1/preprocessing/delay",
    mechanism: "采用自适应 AR 预白化自回归消除输入序列自相关假象，在互相关峰值处精准估计各输入通道到输出的物理滞后。",
    algoDesc: "自适应 AR(p) 预白化残差互相关 (CCF Peak Detection)",
    bullets: [
      "自适应 AR(p) 滤波器预白化输入时序，消除虚假相关",
      "互相关最大值法搜索各通道最优滞后阶数",
      "多输入通道独立时滞移位与数据矩阵对齐",
    ],
    guardrail: "时滞上限 nk ≤ 20 步；校验物理方向单调性，过滤反向因果异常。",
    artifact: "Lag Matrix (nk=1..5) + Time-Aligned Dataset",
  },
  {
    id: "collinearity",
    category: "特征降维",
    title: "VIF 共线性检测与筛选",
    summary: "方差膨胀因子诊断与强相关剔除",
    endpoint: "POST /api/v1/preprocessing/collinearity",
    mechanism: "计算多变量方差膨胀因子（VIF）并结合主成分分析，剔除高共线性冗余测点，防止多变量回归产生过拟合。",
    algoDesc: "OLS 辅助回归方差膨胀因子计算 (VIF = 1 / (1 - R²))",
    bullets: [
      "逐列计算多变量回归决定系数与膨胀因子",
      "迭代剔除最大 VIF 变量直至全部满足安全阈值",
      "白名单保护关键操作变量，确保物理意义完整",
    ],
    guardrail: "VIF 默认安全阈值 ≤ 10；至少保留一个关键输入变量与输出关联。",
    artifact: "Reduced Feature Vector + Collinearity Report",
  },
  {
    id: "arx",
    category: "系统辨识",
    title: "ARX 辨识与自由仿真评测",
    summary: "QR 分解最小二乘与滚动自由仿真",
    endpoint: "POST /api/v1/modeling/arx/fit",
    mechanism: "基于最小二乘 Householder QR 分解辨识多输入单输出 ARX 模型参数，并进行全局闭环滚动自由仿真与残差白噪声检验。",
    algoDesc: "数值稳定 Householder QR 分解与极点渐近稳定性判定",
    bullets: [
      "基于正交变换的高精度数值最小二乘参数求解",
      "纯模型自主预测（无测量值反馈）自由仿真验证",
      "残差自相关与正态性检验，验证模型无偏性",
    ],
    guardrail: "多项式 A(q) 所有极点必须位于单位圆内，严格保障渐近稳定性。",
    artifact: "Saved Model (ARX-Best) + Verification JSON",
  },
  {
    id: "optuna",
    category: "闭环寻优",
    title: "Optuna 闭环自适应寻优",
    summary: "贝叶斯 TPE 搜索预处理与模型超参",
    endpoint: "POST /api/v1/optimization/optuna/start",
    mechanism: "利用树状 Parzen 估计器（TPE）在预处理窗长、时滞阶数与模型结构空间中联合自动寻优，两阶段算力摊薄加速 24 倍。",
    algoDesc: "Tree-structured Parzen Estimator (TPE) 贝叶斯搜索",
    bullets: [
      "预处理与建模超参跨阶段联合优化",
      "基于验证集自由仿真拟合度作为优化目标函数",
      "早停机制自动终止无效试验，大幅节省工业算力",
    ],
    guardrail: "设置单次 Trial 超时保护与最大试验次数限制，避免死循环。",
    artifact: "Optuna Study Artifact + Parameter Sensitivity Map",
  },
];

const activeStageId = ref("segment");

const activeStageIndex = computed(() =>
  stages.findIndex((s) => s.id === activeStageId.value)
);

const activeStage = computed(
  () => stages[activeStageIndex.value] ?? stages[0]
);
</script>

<style scoped>
.pipeline-architecture {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 6 Stage Flow Stepper */
.pipeline-stepper {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
}

.stepper-node {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stepper-node:hover {
  border-color: #93c5fd;
  background: #f8fafc;
  transform: translateY(-2px);
}

.stepper-node.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.1);
  transform: translateY(-2px);
}

.node-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.node-index {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
}

.node-cat {
  font-size: 10px;
  color: #94a3b8;
  font-weight: 600;
}

.node-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.3;
}

.node-summary {
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
}

/* Detail Panel */
.stage-detail-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 24px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.05);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.detail-title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-badge {
  font-size: 11px;
  font-weight: 700;
  color: #2563eb;
  letter-spacing: 0.05em;
}

.detail-title {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
}

.detail-endpoint {
  font-size: 12px;
  padding: 6px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  color: #475569;
}

/* Grid in Detail Panel */
.detail-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 28px;
}

.col-section-title {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}

.detail-desc {
  font-size: 14px;
  color: #334155;
  line-height: 1.7;
  margin-bottom: 16px;
}

.feature-bullets {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bullet-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: #1e293b;
}

.bullet-svg {
  width: 15px;
  height: 15px;
  color: #059669;
  flex-shrink: 0;
  margin-top: 2px;
}

.bullet-text {
  line-height: 1.5;
}

/* Right Side Cards */
.detail-col-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.side-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.side-card-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.05em;
}

.label-svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.side-card-val {
  font-size: 13px;
  color: #0f172a;
  line-height: 1.5;
}

.guardrail-card {
  border-color: #a7f3d0;
  background: #f0fdf4;
}

.text-emerald {
  color: #059669;
}

.artifact-card {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.text-blue {
  color: #2563eb;
}

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 1024px) {
  .pipeline-stepper {
    grid-template-columns: repeat(3, 1fr);
  }
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .pipeline-stepper {
    grid-template-columns: 1fr;
  }
}
</style>
