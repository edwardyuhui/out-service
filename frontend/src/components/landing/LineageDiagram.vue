<template>
  <div class="lineage-shell" aria-label="数据集示例版本血缘">
    <!-- Header Caption -->
    <div class="lineage-header">
      <div class="header-titles">
        <span class="caption-tag font-mono">Example Lineage</span>
        <h3 class="caption-title">不可变多级数据版本血缘树 (DAG)</h3>
      </div>
      <p class="caption-text">
        示例路径用于说明不可变派生与来源追踪，不代表每个数据集必须经历全部步骤。
      </p>
    </div>

    <!-- Git-Style Tree & Schema Inspector Grid -->
    <div class="lineage-grid">
      <!-- Left: Visual DAG Commit Pipeline -->
      <div class="dag-tree-column">
        <div class="dag-tree" role="tablist">
          <div
            v-for="(version, index) in versions"
            :key="version.id"
            class="tree-node-wrapper"
          >
            <!-- Branch Line -->
            <div
              v-if="index > 0"
              class="branch-connector"
              :class="{ 'branch-active': index <= activeIndex }"
            ></div>

            <!-- Version Node -->
            <button
              class="tree-node-btn"
              :class="{ active: activeIndex === index, related: index <= activeIndex }"
              type="button"
              role="tab"
              :aria-selected="activeIndex === index"
              @click="activeIndex = index"
              @pointerenter="activeIndex = index"
            >
              <div class="node-bullet font-mono">
                <span class="bullet-inner"></span>
                <span>{{ version.id }}</span>
              </div>

              <div class="node-meta">
                <div class="node-name-line">
                  <strong class="node-name">{{ version.name }}</strong>
                  <span class="node-op font-mono">{{ version.operation }}</span>
                </div>
                <span class="node-lineage font-mono">{{ version.lineage }}</span>
              </div>
            </button>
          </div>

          <!-- Model Ready Terminal Node -->
          <div class="branch-connector branch-dashed branch-active"></div>
          <div class="tree-node-terminal">
            <div class="terminal-bullet font-mono">
              <svg class="terminal-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </div>
            <div class="terminal-meta">
              <span class="model-ready-tag font-mono">MODEL INPUT</span>
              <strong class="terminal-name">可建模数据版本</strong>
              <span class="terminal-sub font-mono">Ready for System Identification</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Detailed Version Inspector Panel -->
      <div class="inspector-column" aria-live="polite">
        <div class="inspector-card">
          <div class="ins-card-header">
            <div class="ins-id-group">
              <span class="ins-version-pill font-mono">{{ activeVersion.id }}</span>
              <span class="ins-op-tag font-mono">{{ activeVersion.operation }}</span>
            </div>
            <strong class="ins-version-name">{{ activeVersion.name }}</strong>
          </div>

          <div class="ins-body">
            <div class="ins-row">
              <span class="ins-row-label font-mono">ENGINEERING OPERATION</span>
              <p class="ins-desc">{{ activeVersion.detail }}</p>
            </div>

            <div class="ins-code-box">
              <span class="ins-row-label font-mono">PROVENANCE METADATA POINTER</span>
              <div class="code-banner font-mono">
                <code>{{ activeVersion.lineage }}</code>
                <span class="code-badge">HASH-ANCHORED</span>
              </div>
            </div>

            <div class="ins-properties-grid">
              <div class="prop-card font-mono">
                <span class="p-name">IMMUTABLE SNAPSHOT</span>
                <span class="p-val text-emerald">TRUE (不可就地覆盖)</span>
              </div>
              <div class="prop-card font-mono">
                <span class="p-name">LINEAGE POINTER</span>
                <span class="p-val text-blue">CHAIN RECORDED</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

interface DatasetVersion {
  id: string;
  name: string;
  operation: string;
  detail: string;
  lineage: string;
}

const versions: DatasetVersion[] = [
  {
    id: "V0",
    name: "Original",
    operation: "SOURCE",
    detail: "保留原始多通道传感器采样数据资产，后续处理不会覆盖这一版本，支持全周期对账。",
    lineage: "source_version: original",
  },
  {
    id: "V1",
    name: "Cleaning",
    operation: "CLEANING",
    detail: "经过异常值剔除与三次样条插值后形成规整基准版本，记录其直接来源为 V0。",
    lineage: "derived_from: V0",
  },
  {
    id: "V2",
    name: "Lag Compensation",
    operation: "LAG COMPENSATION",
    detail: "确认通道时滞后生成不可变时移对齐版本，保留完整的时滞阶数与物理因果证据。",
    lineage: "derived_from: V1",
  },
  {
    id: "V3",
    name: "Feature Selection",
    operation: "FEATURE SELECTION",
    detail: "通过 VIF 共线性降维后生成最终特征子集版本，模型严格绑定该不可变资产。",
    lineage: "derived_from: V2",
  },
];

const activeIndex = ref(1);
const activeVersion = computed(() => versions[activeIndex.value]);
</script>

<style scoped>
.lineage-shell {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.05);
}

.lineage-header {
  padding: 24px 28px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.caption-tag {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
  letter-spacing: 0.08em;
}

.caption-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.caption-text {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  max-width: 500px;
  line-height: 1.5;
}

/* Grid Layout */
.lineage-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 420px;
}

/* Left: DAG Tree Column */
.dag-tree-column {
  padding: 28px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
}

.dag-tree {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.tree-node-wrapper {
  display: flex;
  flex-direction: column;
}

.branch-connector {
  width: 2px;
  height: 18px;
  background: #e2e8f0;
  margin-left: 20px;
  transition: background-color 0.2s ease;
}

.branch-active {
  background: #2563eb;
}

.branch-dashed {
  background: transparent;
  border-left: 2px dashed #059669;
}

.tree-node-btn {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: all 0.18s ease;
}

.tree-node-btn:hover {
  border-color: #93c5fd;
  transform: translateX(4px);
}

.tree-node-btn.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.1);
  transform: translateX(4px);
}

.node-bullet {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
  background: #ffffff;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #cbd5e1;
  flex-shrink: 0;
}

.bullet-inner {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2563eb;
}

.node-meta {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.node-name-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.node-op {
  font-size: 9px;
  font-weight: 600;
  color: #64748b;
  background: #f1f5f9;
  padding: 1px 5px;
  border-radius: 3px;
}

.node-lineage {
  font-size: 10px;
  color: #64748b;
}

/* Terminal Node */
.tree-node-terminal {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  background: #f0fdf4;
  border: 1.5px dashed #059669;
  border-radius: 8px;
}

.terminal-bullet {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #059669;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.terminal-svg {
  width: 14px;
  height: 14px;
}

.terminal-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.model-ready-tag {
  font-size: 9px;
  font-weight: 800;
  color: #059669;
  letter-spacing: 0.05em;
}

.terminal-name {
  font-size: 13px;
  font-weight: 800;
  color: #065f46;
}

.terminal-sub {
  font-size: 9px;
  color: #059669;
}

/* Right: Inspector Column */
.inspector-column {
  padding: 28px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.inspector-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 24px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.ins-card-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.ins-id-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ins-version-pill {
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid #bfdbfe;
}

.ins-op-tag {
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
}

.ins-version-name {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.ins-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ins-row-label {
  display: block;
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

.code-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
}

.code-banner code {
  font-size: 11px;
  font-weight: 700;
  color: #2563eb;
}

.code-badge {
  font-size: 9px;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid #a7f3d0;
}

.ins-properties-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.prop-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.p-name {
  font-size: 9px;
  color: #94a3b8;
  font-weight: 700;
}

.p-val {
  font-size: 10px;
  font-weight: 700;
}

.text-emerald { color: #059669; }
.text-blue { color: #2563eb; }

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 860px) {
  .lineage-grid {
    grid-template-columns: 1fr;
  }
  .dag-tree-column {
    border-right: none;
    border-bottom: 1px solid #e2e8f0;
  }
}
</style>
