<template>
  <div class="version-lineage-picker" :data-selected-version-id="selectedVersionId ?? ''">
    <el-popover
      v-model:visible="popoverVisible"
      placement="bottom-start"
      :fallback-placements="['top-start']"
      :teleported="true"
      :offset="12"
      :popper-options="lineagePopperOptions"
      width="min(620px, calc(100vw - 48px))"
      :disabled="!datasetName || loading || !versions.length"
      trigger="click"
    >
      <template #reference>
        <button
          type="button"
          class="lineage-trigger"
          data-test="lineage-trigger"
          :disabled="!datasetName || loading || !versions.length"
        >
          <span>
            <strong>{{ selectedVersion ? versionDisplayName(selectedVersion) : triggerCopy }}</strong>
            <small v-if="selectedVersion">查看版本血缘</small>
          </span>
          <el-icon><ArrowDown /></el-icon>
        </button>
      </template>

      <div class="lineage-panel">
        <div class="lineage-panel-header">
          <div>
            <span class="lineage-panel-label lineage-panel-label-sans">版本血缘</span>
            <strong>{{ datasetName || "当前数据集" }}</strong>
          </div>
          <span class="lineage-rule">{{ contextLabel }}</span>
        </div>

        <div class="lineage-legend" aria-label="版本状态说明">
          <span><i class="legend-dot eligible"></i>{{ eligibleLabel }}</span>
          <span><i class="legend-dot unavailable"></i>当前阶段不可用</span>
        </div>

        <div class="lineage-tree" role="tree" aria-label="数据版本血缘">
          <div
            v-for="row in lineageRows"
            :key="row.node.id"
            class="lineage-row-wrap"
            :style="{ '--lineage-depth': row.depth }"
          >
            <span v-if="row.depth > 0" class="lineage-connector" aria-hidden="true"></span>
            <div
              class="lineage-node"
              :class="{
                selected: row.node.id === selectedVersionId,
                disabled: !isEligible(row.node),
              }"
              data-test="lineage-node"
              :data-version-id="row.node.id"
              :data-parent-id="row.node.parent_version_id ?? ''"
              role="treeitem"
              :aria-level="row.depth + 1"
              :aria-disabled="!isEligible(row.node)"
              :aria-selected="row.node.id === selectedVersionId"
              :tabindex="isEligible(row.node) ? 0 : -1"
              @click="selectVersion(row.node)"
              @keydown.enter.prevent="selectVersion(row.node)"
              @keydown.space.prevent="selectVersion(row.node)"
            >
              <span class="lineage-node-dot" aria-hidden="true"></span>
              <div class="lineage-node-copy">
                <div class="lineage-node-title">
                  <strong>{{ versionDisplayName(row.node) }}</strong>
                  <span v-if="row.node.id === selectedVersionId" class="selected-badge">{{ selectedBadgeLabel }}</span>
                </div>
                <div class="lineage-node-meta">
                  <span>{{ formatVersionDate(row.node.created_at) }}</span>
                  <span class="font-mono">{{ shortVersionId(row.node.id) }}</span>
                  <span>{{ row.node.row_count }} rows · {{ row.node.column_count }} cols</span>
                </div>
                <small v-if="!isEligible(row.node)">{{ disabledReason(row.node) }}</small>
              </div>
              <span class="lineage-status" :class="{ eligible: isEligible(row.node) }">
                {{ isEligible(row.node) ? eligibleLabel : "当前阶段不可用" }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </el-popover>

    <div v-if="showEmptyState" class="lineage-empty" data-test="no-eligible-source">
      <strong>{{ emptyStateText }}</strong>
      <span v-if="emptyStateHint">{{ emptyStateHint }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ArrowDown } from "@element-plus/icons-vue";
import type { Options as PopperOptions } from "element-plus";
import type { DatasetVersionNode } from "../../types/api";
import {
  formatVersionDate,
  shortVersionId,
  versionDisplayName,
} from "../../utils/versionOperation";

interface LineageRow {
  node: DatasetVersionNode;
  depth: number;
}

const lineagePopperOptions = {
  modifiers: [
    {
      name: "preventOverflow",
      enabled: true,
      options: {
        boundary: "clippingParents",
        rootBoundary: "viewport",
        padding: 12,
        mainAxis: true,
        altAxis: false,
        tether: true,
      },
    },
  ],
} satisfies Partial<PopperOptions>;

const props = withDefaults(defineProps<{
  datasetName: string;
  versions: DatasetVersionNode[];
  selectedVersionId: string | null;
  contextLabel: string;
  eligibleLabel: string;
  isEligible: (version: DatasetVersionNode) => boolean;
  disabledReason: (version: DatasetVersionNode) => string;
  emptyStateText: string;
  emptyStateHint?: string;
  placeholder?: string;
  loading?: boolean;
  selectedBadgeLabel?: string;
}>(), {
  emptyStateHint: "",
  placeholder: "选择分析源版本",
  loading: false,
  selectedBadgeLabel: "当前分析源",
});

const emit = defineEmits<{
  select: [versionId: string];
  "update:selectedVersionId": [versionId: string];
}>();

const popoverVisible = ref(false);
const selectedVersion = computed(
  () => props.versions.find((version) => version.id === props.selectedVersionId) ?? null
);
const eligibleVersions = computed(() => props.versions.filter(props.isEligible));
const showEmptyState = computed(
  () => !!props.datasetName && !props.loading && eligibleVersions.value.length === 0
);
const triggerCopy = computed(() => {
  if (props.loading) return "正在读取版本血缘";
  if (!props.datasetName) return "请先选择数据集";
  if (!eligibleVersions.value.length) return props.emptyStateText;
  return props.placeholder;
});

const lineageRows = computed<LineageRow[]>(() => {
  const nodeIds = new Set(props.versions.map((node) => node.id));
  const childrenByParent = new Map<string | null, DatasetVersionNode[]>();

  for (const node of props.versions) {
    const parentId = node.parent_version_id && nodeIds.has(node.parent_version_id)
      ? node.parent_version_id
      : null;
    const siblings = childrenByParent.get(parentId) ?? [];
    siblings.push(node);
    childrenByParent.set(parentId, siblings);
  }

  for (const siblings of childrenByParent.values()) {
    siblings.sort((left, right) => {
      const timeDiff = Date.parse(left.created_at) - Date.parse(right.created_at);
      return Number.isFinite(timeDiff) && timeDiff !== 0 ? timeDiff : left.id.localeCompare(right.id);
    });
  }

  const rows: LineageRow[] = [];
  const visited = new Set<string>();
  const visit = (node: DatasetVersionNode, depth: number) => {
    if (visited.has(node.id)) return;
    visited.add(node.id);
    rows.push({ node, depth });
    for (const child of childrenByParent.get(node.id) ?? []) visit(child, depth + 1);
  };

  for (const root of childrenByParent.get(null) ?? []) visit(root, 0);
  for (const node of props.versions) visit(node, 0);
  return rows;
});

const selectVersion = (version: DatasetVersionNode) => {
  if (!props.isEligible(version)) return;
  emit("update:selectedVersionId", version.id);
  emit("select", version.id);
  popoverVisible.value = false;
};
</script>

<style scoped>
.version-lineage-picker {
  width: 100%;
}

.lineage-trigger {
  width: 100%;
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 7px 12px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: #ffffff;
  color: var(--text-primary);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.lineage-trigger:hover:not(:disabled),
.lineage-trigger:focus-visible {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(110, 155, 105, 0.12);
  outline: none;
}

.lineage-trigger:disabled {
  color: var(--text-faint);
  background: var(--bg-subtle);
  cursor: not-allowed;
}

.lineage-trigger > span {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.lineage-trigger strong,
.lineage-trigger small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lineage-trigger strong {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
}

.lineage-trigger small {
  font-size: 11px;
  color: var(--text-muted);
}

.lineage-panel {
  width: 100%;
  max-height: min(520px, calc(50vh - 64px));
  max-height: min(520px, calc(50dvh - 64px));
  overflow-y: auto;
  overscroll-behavior: contain;
  color: var(--text-primary);
}

.lineage-panel-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.lineage-panel-header > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.lineage-panel-header strong {
  font-size: 14px;
}

.lineage-panel-label {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
  color: var(--color-primary);
}

.lineage-panel-label-sans {
  font-family: var(--font-sans);
}

.lineage-rule {
  font-size: 11px;
  color: var(--text-muted);
}

.lineage-legend {
  display: flex;
  gap: 18px;
  padding: 12px 0 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.lineage-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-dot,
.lineage-node-dot {
  display: inline-block;
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #929f94;
}

.legend-dot.eligible,
.lineage-node:not(.disabled) .lineage-node-dot {
  background: var(--color-primary);
}

.lineage-node.selected .lineage-node-dot {
  box-shadow: 0 0 0 3px rgba(110, 155, 105, 0.16);
}

.lineage-tree {
  padding: 4px 0;
}

.lineage-row-wrap {
  --depth-offset: calc(var(--lineage-depth) * 28px);
  position: relative;
  margin-left: var(--depth-offset);
  margin-top: 7px;
}

.lineage-connector {
  position: absolute;
  left: -16px;
  top: -12px;
  width: 16px;
  height: 34px;
  border-left: 1.5px solid #a8b3a9;
  border-bottom: 1.5px solid #a8b3a9;
  border-bottom-left-radius: 6px;
}

.lineage-node {
  position: relative;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 70px;
  padding: 11px 12px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
  transition: border-color 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}

.lineage-node:hover:not(.disabled),
.lineage-node:focus-visible {
  border-color: var(--color-primary);
  box-shadow: 0 3px 10px rgba(38, 55, 37, 0.08);
  transform: translateY(-1px);
  outline: none;
}

.lineage-node.selected {
  border-color: var(--color-primary);
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.lineage-node.disabled {
  background: #f8f9f7;
  color: var(--text-muted);
  cursor: not-allowed;
}

.lineage-node-copy {
  min-width: 0;
}

.lineage-node-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.lineage-node-title strong {
  overflow: hidden;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selected-badge,
.lineage-status {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
}

.selected-badge {
  color: #466f43;
  background: #edf5eb;
}

.lineage-status {
  color: var(--text-muted);
  background: #ecefec;
}

.lineage-status.eligible {
  color: #466f43;
  background: #edf5eb;
}

.lineage-node-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 12px;
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-faint);
}

.lineage-node-copy > small {
  display: block;
  margin-top: 5px;
  font-size: 10px;
  color: var(--text-muted);
}

.lineage-empty {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-subtle);
}

.lineage-empty strong {
  font-size: 12px;
}

.lineage-empty span {
  font-size: 11px;
  color: var(--text-muted);
}

@media (max-width: 680px) {
  .lineage-panel-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .lineage-node {
    grid-template-columns: 10px minmax(0, 1fr);
  }

  .lineage-status {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
