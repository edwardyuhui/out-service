<template>
  <section class="industrial-card version-compare-workbench" aria-labelledby="version-compare-title">
    <header class="workbench-header">
      <div>
        <span class="workbench-eyebrow">VERSION COMPARE</span>
        <h3 id="version-compare-title">清洗版本对比</h3>
        <p>比较两个 Cleaning 阶段版本的数据变化与血缘关系。</p>
      </div>
    </header>

    <div class="selector-grid">
      <div class="selector-field">
        <label>Baseline Version</label>
        <VersionLineagePicker
          data-test="compare-baseline-picker"
          :dataset-name="dataset?.name ?? ''"
          :versions="versions"
          :selected-version-id="baselineVersionId"
          :loading="false"
          context-label="仅原始或清洗规整版本可用于对比"
          eligible-label="可用于版本对比"
          empty-state-text="暂无可用于对比的数据版本。"
          empty-state-hint="请先上传、生成或清洗数据。"
          placeholder="选择比较基线"
          selected-badge-label="比较基线"
          :is-eligible="isCompareEligible"
          :disabled-reason="compareDisabledReason"
          @select="selectBaseline"
        />
      </div>

      <div class="selector-field">
        <label>Compare Version</label>
        <VersionLineagePicker
          data-test="compare-target-picker"
          :dataset-name="dataset?.name ?? ''"
          :versions="versions"
          :selected-version-id="compareVersionId"
          :loading="false"
          context-label="仅原始或清洗规整版本可用于对比"
          eligible-label="可用于版本对比"
          empty-state-text="暂无可用于对比的数据版本。"
          empty-state-hint="请先上传、生成或清洗数据。"
          placeholder="选择对照版本"
          selected-badge-label="对照版本"
          :is-eligible="isCompareEligible"
          :disabled-reason="compareDisabledReason"
          @select="selectCompare"
        />
      </div>
    </div>

    <div class="execution-row">
      <div class="channel-field">
        <label for="version-compare-channel">观察通道</label>
        <el-select
          id="version-compare-channel"
          v-model="selectedChannel"
          data-test="version-compare-channel"
          placeholder="选择共同数值通道"
          :loading="channelLoading"
          :disabled="channelLoading || !channelOptions.length"
        >
          <el-option
            v-for="option in channelOptions"
            :key="option.name"
            :label="channelLabel(option)"
            :value="option.name"
          />
        </el-select>
        <small v-if="channelLoading" class="loading-copy">正在读取共同数值通道…</small>
      </div>

      <el-button
        data-test="version-compare-submit"
        type="primary"
        :loading="compareLoading"
        :disabled="!canCompare"
        @click="executeCompare"
      >开始比较</el-button>
    </div>

    <el-alert
      v-if="channelError"
      class="inline-alert"
      type="error"
      :title="channelError"
      :closable="false"
      show-icon
    >
      <el-button size="small" plain @click="loadChannels">重新读取通道</el-button>
    </el-alert>
    <el-alert
      v-else-if="pairReady && !channelLoading && channelOptions.length === 0"
      class="inline-alert"
      type="info"
      title="两个版本没有可共同比较的数值通道。"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="dedupedChannelWarnings.length"
      class="inline-alert"
      type="warning"
      :title="dedupedChannelWarnings.join('；')"
      :closable="false"
      show-icon
    />

    <el-alert
      v-if="compareError"
      class="result-alert"
      type="error"
      :title="compareError"
      :closable="false"
      show-icon
    />
    <div v-if="compareLoading" class="compare-loading" data-test="compare-loading">
      正在比较完整版本数据…
    </div>

    <div v-else-if="result" class="compare-result" data-test="version-compare-result">
      <div class="summary-header">
        <div>
          <span class="summary-scope">SELECTED CHANNEL</span>
          <h4>数据差异 · 当前通道 {{ result.channel.name }}</h4>
          <p>{{ directionCopy }}</p>
          <p class="relation-explanation">{{ relationExplanation }}</p>
        </div>
        <div class="summary-badges">
          <el-tag effect="plain">{{ relationCopy }}</el-tag>
        </div>
      </div>

      <el-alert
        v-if="result.relation === 'SAME_VERSION' && hasZeroDifference"
        class="result-alert"
        type="info"
        title="同一版本，无数据差异。"
        :closable="false"
        show-icon
      />

      <div class="metric-grid">
        <div class="metric-card changed"><span>值变化</span><strong>{{ result.generic_diff_summary.changed_values }}</strong></div>
        <div class="metric-card added"><span>新增点</span><strong>{{ result.generic_diff_summary.added_points }}</strong></div>
        <div class="metric-card removed"><span>移除点</span><strong>{{ result.generic_diff_summary.removed_points }}</strong></div>
        <div class="metric-card ambiguous"><span>对齐歧义组</span><strong>{{ result.generic_diff_summary.ambiguous_timestamp_groups }}</strong></div>
      </div>

      <div class="summary-secondary">
        <span>Baseline {{ result.generic_diff_summary.baseline_point_count }} points</span>
        <span>Compare {{ result.generic_diff_summary.compare_point_count }} points</span>
        <span v-if="result.generic_diff_summary.baseline_duplicate_occurrences > 0">
          Baseline 重复 occurrence {{ result.generic_diff_summary.baseline_duplicate_occurrences }}
        </span>
        <span v-if="result.generic_diff_summary.compare_duplicate_occurrences > 0">
          Compare 重复 occurrence {{ result.generic_diff_summary.compare_duplicate_occurrences }}
        </span>
      </div>

      <el-alert
        v-if="result.projection.applied"
        class="result-alert"
        type="info"
        title="图形已抽样显示，差异统计基于完整数据。"
        :closable="false"
        show-icon
      />
      <el-alert
        v-if="result.difference_points_truncated"
        class="result-alert"
        type="info"
        title="差异统计完整，图中仅显示部分差异点。"
        :closable="false"
        show-icon
      />
      <el-alert
        v-if="dedupedResultWarnings.length"
        class="result-alert"
        type="warning"
        :title="dedupedResultWarnings.join('；')"
        :closable="false"
        show-icon
      />

      <div class="chart-header">
        <div><strong>Overlay</strong><span>Baseline 与 Compare 共享真实时间轴</span></div>
        <el-button data-test="version-compare-reset-zoom" size="small" plain @click="resetZoom">重置视图</el-button>
      </div>
      <div class="version-compare-chart-stage">
        <ChartContainer
          ref="chartRef"
          :options="overlayChartOptions"
          height="420px"
          @chart-click="handleChartClick"
          @chart-viewport-change="handleChartViewportChange"
        />
        <div
          v-if="selectedDifference"
          ref="differenceDetailHostRef"
          class="difference-detail-host"
          :class="{ 'is-anchor-hidden': !differenceDetailPosition }"
          :style="differenceDetailCardStyle"
          :aria-hidden="!differenceDetailPosition"
          data-test="difference-detail-host"
        >
          <CleaningVersionDifferenceDetailCard
            :difference="selectedDifference.difference"
            @close="clearSelectedDifference"
          />
        </div>
      </div>
      <p v-if="result.generic_diff_summary.ambiguous_timestamp_groups > 0" class="ambiguity-note">
        重复时间戳歧义按 timestamp group 表达，未建立 occurrence 间的推测配对。
      </p>

      <div
        class="evidence-grid"
        :class="{ 'status-only': !result.direct_derivation_summary }"
        data-test="version-compare-evidence-grid"
      >
        <article
          v-if="result.direct_derivation_summary"
          class="evidence-card direct-evidence-card"
          data-test="direct-cleaning-evidence"
        >
          <header>
            <div>
              <span class="evidence-eyebrow">ALL NUMERIC COLUMNS</span>
              <h4>直接清洗证据 · 全部数值通道</h4>
            </div>
            <el-tag effect="plain">{{ evidenceSourceLabel }}</el-tag>
          </header>

          <div v-if="primaryEvidenceEntries.length" class="evidence-metrics">
            <div v-for="entry in primaryEvidenceEntries" :key="entry.key" :data-evidence-key="entry.key">
              <span>{{ entry.label }}</span><strong>{{ entry.displayValue }}</strong>
            </div>
          </div>
          <dl v-if="auxiliaryEvidenceEntries.length" class="evidence-auxiliary">
            <div v-for="entry in auxiliaryEvidenceEntries" :key="entry.key" :data-evidence-key="entry.key">
              <dt>{{ entry.label }}</dt><dd>{{ entry.displayValue }}</dd>
            </div>
          </dl>
          <el-alert
            v-if="result.direct_derivation_summary.evidence_source === 'legacy_total_only'"
            type="warning"
            title="历史版本未记录完整分类明细。"
            :closable="false"
            show-icon
          />
          <details v-if="otherAuditEntries.length" class="other-audit-fields" data-test="other-audit-fields">
            <summary>其他审计字段</summary>
            <dl>
              <div v-for="entry in otherAuditEntries" :key="entry.key">
                <dt>{{ entry.key }}</dt><dd>{{ entry.displayValue }}</dd>
              </div>
            </dl>
          </details>
        </article>

        <article class="evidence-card version-status-card" data-test="version-status-card">
          <header>
            <div>
              <span class="evidence-eyebrow">ARTIFACT + CONVERGENCE</span>
              <h4>版本状态</h4>
            </div>
            <el-tag v-if="result.artifacts_identical" type="success" effect="light">数据内容一致</el-tag>
          </header>
          <p
            v-if="result.artifacts_identical && !result.convergence_evidence.baseline && !result.convergence_evidence.compare"
            class="identity-explanation"
          >数据内容一致不等同于存在正式清洗收敛证据。</p>
          <div class="convergence-grid">
            <section
              v-for="side in convergenceSides"
              :key="side.key"
              class="convergence-side"
              :data-test="`convergence-${side.key}`"
            >
              <span>{{ side.label }}</span>
              <strong>{{ side.versionName }}</strong>
              <p :class="{ confirmed: !!side.evidence }">
                {{ side.evidence ? '存在正式清洗收敛证据' : '无正式收敛运行证据' }}
              </p>
              <dl v-if="side.evidence">
                <div><dt>发生时间</dt><dd>{{ formatTooltipTimestamp(side.evidence.occurred_at) }}</dd></div>
                <div><dt>ProcessingRun</dt><dd>{{ shortUuid(side.evidence.processing_run_id) }}</dd></div>
                <div><dt>唯一修改单元格</dt><dd>{{ side.evidence.unique_changed_cells }}</dd></div>
              </dl>
            </section>
          </div>
        </article>
      </div>
    </div>

    <div v-else-if="!compareError" class="workbench-empty">
      <strong>选择两个版本与观察通道后开始比较</strong>
      <span>切换选择不会自动下载完整版本差异。</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import type { CustomSeriesRenderItem } from "echarts";
import ChartContainer, { type ChartOption, type ChartViewportChange } from "../ChartContainer.vue";
import CleaningVersionDifferenceDetailCard from "./CleaningVersionDifferenceDetailCard.vue";
import VersionLineagePicker from "../versioning/VersionLineagePicker.vue";
import { getCleaningVersionCompare, getCleaningVersionCompareChannels } from "../../api/datasets";
import { ApiError } from "../../api/client";
import type {
  CleaningVersionDirection,
  CleaningVersionCompareChannelOption,
  CleaningVersionCompareData,
  CleaningVersionRelation,
  ConvergenceEvidence,
  DatasetItem,
  DatasetVersionNode,
  DirectDerivationChanges,
  VersionComparePoint,
  VersionDifferencePoint,
  VersionDifferenceKind,
} from "../../types/api";

defineOptions({ name: "CleaningVersionCompareWorkbench" });

const props = defineProps<{
  dataset: DatasetItem | null;
  versions: DatasetVersionNode[];
  currentVersionId: string | null;
}>();

type ChartAction = {
  type: string;
  start?: number;
  end?: number;
  seriesId?: string;
  dataIndex?: number;
};
type CoordinateFinder = {
  gridIndex?: number;
  xAxisIndex?: number;
  yAxisIndex?: number;
};
type ChartExpose = {
  dispatchAction: (action: ChartAction) => void;
  convertToPixel: (finder: CoordinateFinder, value: unknown) => number | number[] | null;
  containPixel: (finder: CoordinateFinder, value: number[]) => boolean;
  getSize: () => { width: number; height: number };
};
type DifferenceHoverEmphasis = {
  itemStyle: {
    color: string;
    borderColor: string;
    borderWidth: number;
    shadowBlur: number;
    shadowColor: string;
  };
};
type MarkerDatum = {
  value: [string, number];
  differencePoint: true;
  differenceIndex: number;
  differenceKind: Exclude<VersionDifferenceKind, "AMBIGUOUS_ALIGNMENT">;
  anchorKind: "data-point";
  anchorValue: [string, number];
  visualSeriesId: string;
  visualDataIndex: number;
  emphasis: DifferenceHoverEmphasis;
};
type AmbiguousAnnotationDatum = {
  name: "对齐歧义";
  xAxis: string;
};
type AmbiguityHitStripDatum = {
  value: [string];
  timestamp: string;
  differencePoint: true;
  differenceIndex: number;
  differenceKind: "AMBIGUOUS_ALIGNMENT";
  visualDataIndex: number;
};
type AmbiguousSelectedDatum = {
  differencePoint: true;
  differenceIndex: number;
  differenceKind: "AMBIGUOUS_ALIGNMENT";
  anchorKind: "timestamp";
  anchorValue: string;
  visualSeriesId: string;
  visualDataIndex: number;
};
type DifferenceEventDatum = MarkerDatum | AmbiguousSelectedDatum;
type SelectedDifference = DifferenceEventDatum & {
  difference: VersionDifferencePoint;
};
type ChartClickEvent = {
  componentType?: string;
  seriesType?: string;
  seriesName?: string;
  seriesIndex?: number;
  seriesId?: string;
  dataIndex?: number;
  data?: unknown;
};
type DifferenceDetailPosition = {
  left: number;
  top: number;
  horizontal: "left" | "right";
  vertical: "above" | "below";
};
type VisibleTimeWindow = {
  startEpochMs: number;
  endEpochMs: number;
};
type EvidenceEntry = {
  key: string;
  label: string;
  displayValue: string;
};

const ELIGIBLE_OPERATIONS = new Set(["simulation_generate", "raw_upload", "preprocessing.clean"]);
const BASELINE_COLOR = "#A8665E";
const COMPARE_COLOR = "#557562";
const CHANGED_COLOR = "#B5965D";
const AMBIGUOUS_COLOR = "#8E7B55";
const DIFFERENCE_HOVER_COLORS = {
  VALUE_CHANGED: CHANGED_COLOR,
  POINT_ADDED: COMPARE_COLOR,
  POINT_REMOVED: BASELINE_COLOR,
} satisfies Record<MarkerDatum["differenceKind"], string>;
const AMBIGUITY_HIT_SERIES_NAME = "version-ambiguity-hit-strip";
const DIFFERENCE_SERIES_IDS = {
  changed: "version-difference-changed",
  added: "version-difference-added",
  removed: "version-difference-removed",
  hitArea: "version-difference-hit-area",
  ambiguous: "version-difference-ambiguous-annotation",
  ambiguityHitStrip: AMBIGUITY_HIT_SERIES_NAME,
} as const;
const ORDINARY_DIFFERENCE_SERIES_IDS = new Set<string>([
  DIFFERENCE_SERIES_IDS.changed,
  DIFFERENCE_SERIES_IDS.added,
  DIFFERENCE_SERIES_IDS.removed,
]);
const DIFFERENCE_CARD_GAP = 16;
const DIFFERENCE_CARD_INSET = 8;
const DIFFERENCE_CARD_FALLBACK_WIDTH = 292;
const DIFFERENCE_CARD_FALLBACK_HEIGHT = 320;
const AMBIGUOUS_ANCHOR_TOP = 72;
const AMBIGUITY_HIT_STRIP_WIDTH = 14;
const AMBIGUITY_HIT_STRIP_Z = 21;
const FULL_DATA_ZOOM_EPSILON = 0.000001;

const baselineVersionId = ref<string | null>(null);
const compareVersionId = ref<string | null>(null);
const channelOptions = ref<CleaningVersionCompareChannelOption[]>([]);
const selectedChannel = ref<string | null>(null);
const channelWarnings = ref<string[]>([]);
const channelLoading = ref(false);
const channelError = ref("");
const compareLoading = ref(false);
const compareError = ref("");
const result = shallowRef<CleaningVersionCompareData | null>(null);
const chartRef = ref<ChartExpose | null>(null);
const selectedDifference = ref<SelectedDifference | null>(null);
const differenceDetailPosition = ref<DifferenceDetailPosition | null>(null);
const differenceDetailHostRef = ref<HTMLElement | null>(null);
const visibleTimeWindow = ref<VisibleTimeWindow | null>(null);
let channelRequestId = 0;
let compareRequestId = 0;
let differencePositionRequestId = 0;

const isCompareEligible = (version: DatasetVersionNode) => ELIGIBLE_OPERATIONS.has(version.tool);
const compareDisabledReason = () => "已进入后续处理阶段，不属于 Cleaning 版本对比范围";
const pairReady = computed(() => !!props.dataset && !!baselineVersionId.value && !!compareVersionId.value);
const canCompare = computed(() => pairReady.value && !!selectedChannel.value && !channelLoading.value && !compareLoading.value);
const dedupeWarnings = (warnings: string[]) => {
  const seen = new Set<string>();
  return warnings.filter((warning) => {
    if (seen.has(warning)) return false;
    seen.add(warning);
    return true;
  });
};
const dedupedChannelWarnings = computed(() => dedupeWarnings(channelWarnings.value));
const dedupedResultWarnings = computed(() => {
  const channelWarningSet = new Set(dedupedChannelWarnings.value);
  return dedupeWarnings(result.value?.warnings ?? []).filter((warning) => !channelWarningSet.has(warning));
});

const nearestEligibleAncestor = (current: DatasetVersionNode, byId: Map<string, DatasetVersionNode>) => {
  const visited = new Set<string>();
  let parentId = current.parent_version_id;
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) return null;
    if (isCompareEligible(parent)) return parent;
    parentId = parent.parent_version_id;
  }
  return null;
};

const descendantDistance = (ancestorId: string, candidate: DatasetVersionNode, byId: Map<string, DatasetVersionNode>) => {
  const visited = new Set<string>();
  let current: DatasetVersionNode | undefined = candidate;
  let distance = 0;
  while (current.parent_version_id && !visited.has(current.id)) {
    visited.add(current.id);
    distance += 1;
    if (current.parent_version_id === ancestorId) return distance;
    current = byId.get(current.parent_version_id);
    if (!current) return null;
  }
  return null;
};

const applyDefaultPair = () => {
  const eligible = props.versions.filter(isCompareEligible);
  const current = eligible.find((version) => version.id === props.currentVersionId);
  if (!current) {
    baselineVersionId.value = null;
    compareVersionId.value = null;
    return;
  }
  if (eligible.length === 1) {
    baselineVersionId.value = current.id;
    compareVersionId.value = current.id;
    return;
  }
  const byId = new Map(props.versions.map((version) => [version.id, version]));
  const ancestor = nearestEligibleAncestor(current, byId);
  if (ancestor) {
    baselineVersionId.value = ancestor.id;
    compareVersionId.value = current.id;
    return;
  }
  baselineVersionId.value = current.id;
  const descendants = eligible
    .filter((version) => version.id !== current.id)
    .map((version) => ({ version, distance: descendantDistance(current.id, version, byId) }))
    .filter((entry): entry is { version: DatasetVersionNode; distance: number } => entry.distance !== null);
  const nearestDistance = Math.min(...descendants.map((entry) => entry.distance));
  const nearest = descendants.filter((entry) => entry.distance === nearestDistance);
  compareVersionId.value = nearest.length === 1 ? nearest[0].version.id : null;
};

const invalidateResult = () => {
  clearSelectedDifference();
  visibleTimeWindow.value = null;
  ++compareRequestId;
  compareLoading.value = false;
  compareError.value = "";
  result.value = null;
};

const currentPairMatches = (datasetId: string, baselineId: string, compareId: string) =>
  props.dataset?.id === datasetId && baselineVersionId.value === baselineId && compareVersionId.value === compareId;

const errorCopy = (prefix: string, error: unknown) => {
  if (error instanceof ApiError) return `${prefix} [${error.code}]：${error.message}`;
  return `${prefix}：${error instanceof Error ? error.message : "未知错误"}`;
};

const loadChannels = async () => {
  const requestId = ++channelRequestId;
  const preferredChannel = selectedChannel.value;
  channelOptions.value = [];
  selectedChannel.value = null;
  channelWarnings.value = [];
  channelError.value = "";
  invalidateResult();
  const datasetId = props.dataset?.id;
  const baselineId = baselineVersionId.value;
  const compareId = compareVersionId.value;
  if (!datasetId || !baselineId || !compareId) {
    channelLoading.value = false;
    return;
  }
  channelLoading.value = true;
  try {
    const response = await getCleaningVersionCompareChannels(datasetId, {
      baseline_version_id: baselineId,
      compare_version_id: compareId,
    });
    if (requestId !== channelRequestId || !currentPairMatches(datasetId, baselineId, compareId)) return;
    channelOptions.value = response.channels;
    channelWarnings.value = response.warnings;
    selectedChannel.value = response.channels.some((option) => option.name === preferredChannel)
      ? preferredChannel
      : response.channels[0]?.name ?? null;
  } catch (error) {
    if (requestId !== channelRequestId || !currentPairMatches(datasetId, baselineId, compareId)) return;
    channelError.value = errorCopy("共同通道加载失败", error);
  } finally {
    if (requestId === channelRequestId) channelLoading.value = false;
  }
};

const selectBaseline = (versionId: string) => {
  clearSelectedDifference();
  baselineVersionId.value = versionId;
};
const selectCompare = (versionId: string) => {
  clearSelectedDifference();
  compareVersionId.value = versionId;
};

const executeCompare = async () => {
  if (!canCompare.value) return;
  const datasetId = props.dataset!.id;
  const baselineId = baselineVersionId.value!;
  const compareId = compareVersionId.value!;
  const channel = selectedChannel.value!;
  const requestId = ++compareRequestId;
  clearSelectedDifference();
  visibleTimeWindow.value = null;
  result.value = null;
  compareError.value = "";
  compareLoading.value = true;
  try {
    const response = await getCleaningVersionCompare(datasetId, {
      baseline_version_id: baselineId,
      compare_version_id: compareId,
      channel,
      max_points: 10_000,
    });
    if (requestId !== compareRequestId || !currentPairMatches(datasetId, baselineId, compareId) || selectedChannel.value !== channel) return;
    visibleTimeWindow.value = null;
    result.value = response;
  } catch (error) {
    if (requestId !== compareRequestId || !currentPairMatches(datasetId, baselineId, compareId) || selectedChannel.value !== channel) return;
    compareError.value = errorCopy("版本比较失败", error);
  } finally {
    if (requestId === compareRequestId) compareLoading.value = false;
  }
};

const channelLabel = (option: CleaningVersionCompareChannelOption) => option.unit ? `${option.name} (${option.unit})` : option.name;
const RELATION_COPY: Record<CleaningVersionRelation, string> = {
  DIRECT_PARENT: "直接派生",
  ANCESTOR_DESCENDANT: "跨级祖先比较",
  SIBLING: "同源分支",
  SAME_VERSION: "同一版本",
  UNRELATED_WITHIN_DATASET: "同数据集独立分支",
};
const DIRECTION_COPY: Record<CleaningVersionDirection, string> = {
  BASELINE_TO_COMPARE: "Baseline → Compare",
  COMPARE_TO_BASELINE: "Compare → Baseline",
  NONE: "无派生方向",
};
const relationCopy = computed(() => result.value ? RELATION_COPY[result.value.relation] : "");
const directionCopy = computed(() => result.value ? DIRECTION_COPY[result.value.direction] : "");
const relationExplanation = computed(() => {
  const response = result.value;
  if (!response) return "";
  if (response.relation === "DIRECT_PARENT") {
    const operation = response.direct_derivation_summary ? "直接清洗" : "直接处理";
    return response.direction === "COMPARE_TO_BASELINE"
      ? `Baseline 由 Compare 经一次${operation}产生。`
      : `Compare 由 Baseline 经一次${operation}产生。`;
  }
  if (response.relation === "ANCESTOR_DESCENDANT") {
    return response.direction === "COMPARE_TO_BASELINE"
      ? "Baseline 是 Compare 的后代版本，中间包含一个或多个处理步骤。"
      : "Compare 是 Baseline 的后代版本，中间包含一个或多个处理步骤。";
  }
  if (response.relation === "SIBLING") return "两个版本来自同一父版本，不存在直接派生关系。";
  if (response.relation === "SAME_VERSION") return "Baseline 与 Compare 指向同一个不可变版本。";
  return "两个版本属于同一数据集，但当前血缘中不存在直接祖先或同父关系。";
});
const hasZeroDifference = computed(() => {
  const summary = result.value?.generic_diff_summary;
  return !!summary && summary.changed_values === 0 && summary.added_points === 0
    && summary.removed_points === 0 && summary.ambiguous_timestamp_groups === 0;
});

const lineData = (points: VersionComparePoint[]) => points.map((point) => [point.timestamp, point.value] as [string, number | null]);

const formatAxisTimestamp = (value: string | number) => {
  let timestamp = String(value);
  if (typeof value === "number") {
    const parsed = new Date(value);
    if (Number.isFinite(parsed.getTime())) timestamp = parsed.toISOString();
  }
  const match = timestamp.match(/[T ](\d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp;
};
const formatTooltipTimestamp = (timestamp: string) => {
  const match = timestamp.replace("T", " ").match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp.replace("T", " ");
};
const formatValue = (value: unknown) => {
  if (value === null || typeof value !== "number" || !Number.isFinite(value)) return "缺失";
  return value.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 4 });
};
const shortUuid = (value: string) => value.length > 8 ? `${value.slice(0, 8)}…` : value;

const EVIDENCE_SOURCE_LABELS = {
  persisted: "持久化审计证据",
  replayed: "只读重放恢复",
  legacy_total_only: "历史总数记录",
} as const;
type EvidenceFieldConfig = {
  key: string;
  label: string;
  type: "number" | "boolean" | "string";
};
const PRIMARY_EVIDENCE_FIELDS: EvidenceFieldConfig[] = [
  { key: "unique_changed_cells", label: "唯一修改单元格", type: "number" },
  { key: "missing_value_fills", label: "缺失填补", type: "number" },
  { key: "outlier_replacements", label: "异常值替换", type: "number" },
  { key: "smoothing_changes", label: "平滑调整", type: "number" },
  { key: "duplicate_timestamps_processed", label: "重复时间戳处理", type: "number" },
  { key: "resampling_empty_rows_created", label: "重采样新增空行", type: "number" },
];
const AUXILIARY_EVIDENCE_FIELDS: EvidenceFieldConfig[] = [
  { key: "overlapping_changed_cells", label: "重叠修改单元格", type: "number" },
  { key: "category_counts_may_overlap", label: "分类计数可能重叠", type: "boolean" },
  { key: "source_missing_cells", label: "源数据缺失单元格", type: "number" },
  { key: "aligned_missing_cells_before_interpolation", label: "插值前对齐缺失单元格", type: "number" },
  { key: "breakdown_status", label: "分类明细状态", type: "string" },
  { key: "count_unit", label: "计数单位", type: "string" },
];
const KNOWN_EVIDENCE_KEYS = new Set([
  ...PRIMARY_EVIDENCE_FIELDS.map((field) => field.key),
  ...AUXILIARY_EVIDENCE_FIELDS.map((field) => field.key),
]);
const hasOwn = (value: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(value, key);
const isValidKnownEvidenceValue = (value: unknown, type: EvidenceFieldConfig["type"]) => {
  if (value === null) return true;
  if (type === "number") return typeof value === "number" && Number.isFinite(value);
  return typeof value === type;
};
const formatKnownEvidenceValue = (value: unknown) => {
  if (value === null) return "未记录";
  if (typeof value === "number") return formatValue(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
};
const buildEvidenceEntries = (
  changes: DirectDerivationChanges,
  fields: EvidenceFieldConfig[],
  legacyTotalOnly: boolean
) => fields.flatMap((field): EvidenceEntry[] => {
  if (legacyTotalOnly && field.key !== "unique_changed_cells") return [];
  if (!hasOwn(changes, field.key)) return [];
  const value = changes[field.key];
  if (!isValidKnownEvidenceValue(value, field.type)) return [];
  return [{ key: field.key, label: field.label, displayValue: formatKnownEvidenceValue(value) }];
});
const evidenceSourceLabel = computed(() => {
  const source = result.value?.direct_derivation_summary?.evidence_source;
  return source ? EVIDENCE_SOURCE_LABELS[source] : "";
});
const primaryEvidenceEntries = computed(() => {
  const evidence = result.value?.direct_derivation_summary;
  return evidence
    ? buildEvidenceEntries(evidence.changes, PRIMARY_EVIDENCE_FIELDS, evidence.evidence_source === "legacy_total_only")
    : [];
});
const auxiliaryEvidenceEntries = computed(() => {
  const evidence = result.value?.direct_derivation_summary;
  return evidence && evidence.evidence_source !== "legacy_total_only"
    ? buildEvidenceEntries(evidence.changes, AUXILIARY_EVIDENCE_FIELDS, false)
    : [];
});
const otherAuditEntries = computed(() => {
  const evidence = result.value?.direct_derivation_summary;
  if (!evidence || evidence.evidence_source === "legacy_total_only") return [];
  return Object.entries(evidence.changes).flatMap(([key, value]): EvidenceEntry[] => {
    if (KNOWN_EVIDENCE_KEYS.has(key)) return [];
    const isScalar = value === null
      || typeof value === "string"
      || typeof value === "boolean"
      || (typeof value === "number" && Number.isFinite(value));
    if (!isScalar) return [];
    return [{ key, label: key, displayValue: value === null ? "null" : String(value) }];
  });
});
const convergenceSides = computed(() => {
  const response = result.value;
  if (!response) return [];
  return [
    { key: "baseline", label: "Baseline", versionName: response.baseline.name, evidence: response.convergence_evidence.baseline },
    { key: "compare", label: "Compare", versionName: response.compare.name, evidence: response.convergence_evidence.compare },
  ] satisfies Array<{
    key: "baseline" | "compare";
    label: string;
    versionName: string;
    evidence: ConvergenceEvidence | null;
  }>;
});

const appendMarker = (
  target: MarkerDatum[],
  differenceIndex: number,
  differenceKind: MarkerDatum["differenceKind"],
  visualSeriesId: string,
  timestamp: string,
  value: number
) => {
  const anchorValue: [string, number] = [timestamp, value];
  const hoverColor = DIFFERENCE_HOVER_COLORS[differenceKind];
  target.push({
    value: anchorValue,
    differencePoint: true,
    differenceIndex,
    differenceKind,
    anchorKind: "data-point",
    anchorValue,
    visualSeriesId,
    visualDataIndex: target.length,
    emphasis: {
      itemStyle: {
        color: `${hoverColor}24`,
        borderColor: hoverColor,
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: `${hoverColor}66`,
      },
    },
  });
};
const appendOccurrenceMarkers = (
  target: MarkerDatum[],
  difference: VersionDifferencePoint,
  differenceIndex: number,
  side: "baseline" | "compare",
  differenceKind: MarkerDatum["differenceKind"],
  visualSeriesId: string
) => {
  const directValue = side === "baseline" ? difference.baseline_value : difference.compare_value;
  if (directValue !== null) {
    appendMarker(target, differenceIndex, differenceKind, visualSeriesId, difference.timestamp, directValue);
    return;
  }
  const occurrences = side === "baseline" ? difference.baseline_occurrences : difference.compare_occurrences;
  for (const occurrence of occurrences) {
    if (occurrence.value === null) continue;
    appendMarker(target, differenceIndex, differenceKind, visualSeriesId, occurrence.timestamp, occurrence.value);
  }
};

const isDifferenceEventDatum = (value: unknown): value is DifferenceEventDatum => {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  if (
    candidate.differencePoint !== true
    || !Number.isInteger(candidate.differenceIndex)
    || typeof candidate.differenceKind !== "string"
    || typeof candidate.anchorKind !== "string"
    || typeof candidate.visualSeriesId !== "string"
    || !Number.isInteger(candidate.visualDataIndex)
  ) return false;
  if (candidate.anchorKind === "timestamp") {
    return candidate.differenceKind === "AMBIGUOUS_ALIGNMENT" && typeof candidate.anchorValue === "string";
  }
  return candidate.anchorKind === "data-point"
    && candidate.differenceKind !== "AMBIGUOUS_ALIGNMENT"
    && Array.isArray(candidate.anchorValue)
    && candidate.anchorValue.length === 2
    && typeof candidate.anchorValue[0] === "string"
    && typeof candidate.anchorValue[1] === "number"
    && Number.isFinite(candidate.anchorValue[1]);
};
const isAmbiguityHitStripDatum = (value: unknown): value is AmbiguityHitStripDatum => {
  if (!value || typeof value !== "object") return false;
  return "differencePoint" in value
    && value.differencePoint === true
    && "differenceIndex" in value
    && Number.isInteger(value.differenceIndex)
    && value.differenceIndex >= 0
    && "differenceKind" in value
    && value.differenceKind === "AMBIGUOUS_ALIGNMENT"
    && "timestamp" in value
    && typeof value.timestamp === "string"
    && "visualDataIndex" in value
    && Number.isInteger(value.visualDataIndex)
    && value.visualDataIndex >= 0;
};
const dispatchDifferenceState = (type: "highlight" | "downplay", selected: SelectedDifference) => {
  if (!ORDINARY_DIFFERENCE_SERIES_IDS.has(selected.visualSeriesId)) return;
  chartRef.value?.dispatchAction({
    type,
    seriesId: selected.visualSeriesId,
    dataIndex: selected.visualDataIndex,
  });
};
const clearSelectedDifference = () => {
  const previous = selectedDifference.value;
  if (previous) dispatchDifferenceState("downplay", previous);
  ++differencePositionRequestId;
  selectedDifference.value = null;
  differenceDetailPosition.value = null;
};
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
const placeDifferenceDetailCard = (
  point: number[],
  chartSize: { width: number; height: number },
  cardSize: { width: number; height: number }
): DifferenceDetailPosition => {
  const horizontal: DifferenceDetailPosition["horizontal"] = point[0] < chartSize.width / 2 ? "right" : "left";
  const preferredLeft = horizontal === "right"
    ? point[0] + DIFFERENCE_CARD_GAP
    : point[0] - cardSize.width - DIFFERENCE_CARD_GAP;
  const aboveTop = point[1] - cardSize.height - DIFFERENCE_CARD_GAP;
  const vertical: DifferenceDetailPosition["vertical"] = aboveTop >= DIFFERENCE_CARD_INSET ? "above" : "below";
  const preferredTop = vertical === "above" ? aboveTop : point[1] + DIFFERENCE_CARD_GAP;
  return {
    left: clamp(preferredLeft, DIFFERENCE_CARD_INSET, chartSize.width - cardSize.width - DIFFERENCE_CARD_INSET),
    top: clamp(preferredTop, DIFFERENCE_CARD_INSET, chartSize.height - cardSize.height - DIFFERENCE_CARD_INSET),
    horizontal,
    vertical,
  };
};
const differenceDetailCardStyle = computed(() => {
  const position = differenceDetailPosition.value;
  return position ? { left: `${position.left}px`, top: `${position.top}px` } : { left: "0", top: "0" };
});
const toEpochMilliseconds = (value: number | string | Date | undefined) => {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (value instanceof Date) {
    const epoch = value.getTime();
    return Number.isFinite(epoch) ? epoch : null;
  }
  if (typeof value === "string") {
    const epoch = Date.parse(value);
    return Number.isFinite(epoch) ? epoch : null;
  }
  return null;
};
const updateVisibleTimeWindow = (change: Extract<ChartViewportChange, { reason: "datazoom" }>) => {
  for (const range of change.ranges) {
    if (!range.xAxisIndices.includes(0)) continue;
    const isFullRange = typeof range.start === "number"
      && typeof range.end === "number"
      && Math.abs(range.start) <= FULL_DATA_ZOOM_EPSILON
      && Math.abs(100 - range.end) <= FULL_DATA_ZOOM_EPSILON;
    if (isFullRange) {
      visibleTimeWindow.value = null;
      return;
    }
    const startEpochMs = toEpochMilliseconds(range.startValue);
    const endEpochMs = toEpochMilliseconds(range.endValue);
    if (startEpochMs === null || endEpochMs === null) continue;
    visibleTimeWindow.value = {
      startEpochMs: Math.min(startEpochMs, endEpochMs),
      endEpochMs: Math.max(startEpochMs, endEpochMs),
    };
    return;
  }
};
const isTimestampVisible = (timestamp: string) => {
  const window = visibleTimeWindow.value;
  if (!window) return true;
  const timestampEpochMs = Date.parse(timestamp);
  return Number.isFinite(timestampEpochMs)
    && timestampEpochMs >= window.startEpochMs
    && timestampEpochMs <= window.endEpochMs;
};
const updateDifferenceDetailPosition = async () => {
  const requestId = ++differencePositionRequestId;
  const selected = selectedDifference.value;
  if (!selected) {
    differenceDetailPosition.value = null;
    return;
  }
  await nextTick();
  if (requestId !== differencePositionRequestId || selected !== selectedDifference.value) return;
  const chart = chartRef.value;
  const card = differenceDetailHostRef.value;
  if (!chart || !card) {
    differenceDetailPosition.value = null;
    return;
  }
  const chartSize = chart.getSize();
  if (chartSize.width <= 0 || chartSize.height <= 0) {
    differenceDetailPosition.value = null;
    return;
  }
  let point: number[] | null = null;
  if (selected.anchorKind === "data-point") {
    const converted = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, selected.anchorValue);
    if (Array.isArray(converted) && converted.length >= 2 && converted.every(Number.isFinite)) point = converted;
    if (!point || !chart.containPixel({ gridIndex: 0 }, point)) {
      differenceDetailPosition.value = null;
      return;
    }
  } else {
    if (!isTimestampVisible(selected.anchorValue)) {
      differenceDetailPosition.value = null;
      return;
    }
    const converted = chart.convertToPixel({ xAxisIndex: 0 }, selected.anchorValue);
    const x = typeof converted === "number" ? converted : Array.isArray(converted) ? converted[0] : null;
    if (typeof x === "number" && Number.isFinite(x)) {
      point = [x, Math.min(AMBIGUOUS_ANCHOR_TOP, chartSize.height / 2)];
    }
  }
  if (!point) {
    differenceDetailPosition.value = null;
    return;
  }
  const cardRect = card.getBoundingClientRect();
  differenceDetailPosition.value = placeDifferenceDetailCard(point, chartSize, {
    width: cardRect.width || DIFFERENCE_CARD_FALLBACK_WIDTH,
    height: cardRect.height || DIFFERENCE_CARD_FALLBACK_HEIGHT,
  });
};
const handleChartViewportChange = (change: ChartViewportChange) => {
  if (change.reason === "datazoom") updateVisibleTimeWindow(change);
  void updateDifferenceDetailPosition();
};
const selectDifference = (datum: DifferenceEventDatum, difference: VersionDifferencePoint) => {
  const previous = selectedDifference.value;
  if (previous) dispatchDifferenceState("downplay", previous);
  const next: SelectedDifference = { ...datum, difference };
  differenceDetailPosition.value = null;
  selectedDifference.value = next;
  dispatchDifferenceState("highlight", next);
  void updateDifferenceDetailPosition();
};
const handleChartClick = (params: unknown) => {
  const event = params as ChartClickEvent;
  if (
    event.componentType === "series"
    && event.seriesType === "custom"
    && event.seriesName === AMBIGUITY_HIT_SERIES_NAME
  ) {
    if (!isAmbiguityHitStripDatum(event.data)) return;
    const differencePoints = result.value?.difference_points;
    if (!differencePoints || event.data.differenceIndex >= differencePoints.length) return;
    const difference = differencePoints[event.data.differenceIndex];
    if (!difference || difference.difference_kind !== "AMBIGUOUS_ALIGNMENT") return;
    selectDifference({
      differencePoint: true,
      differenceIndex: event.data.differenceIndex,
      differenceKind: "AMBIGUOUS_ALIGNMENT",
      anchorKind: "timestamp",
      anchorValue: event.data.timestamp,
      visualSeriesId: DIFFERENCE_SERIES_IDS.ambiguityHitStrip,
      visualDataIndex: event.data.visualDataIndex,
    }, difference);
    return;
  }
  if (!isDifferenceEventDatum(event.data)) return;
  const difference = result.value?.difference_points[event.data.differenceIndex];
  if (!difference || difference.difference_kind !== event.data.differenceKind) return;
  selectDifference(event.data, difference);
};

const renderAmbiguityHitStrip: CustomSeriesRenderItem = (params, api) => {
  const coordSys = params.coordSys;
  if (
    coordSys.type !== "cartesian2d"
    || !("y" in coordSys)
    || typeof coordSys.y !== "number"
    || !("height" in coordSys)
    || typeof coordSys.height !== "number"
  ) return null;

  // UI-only coordinate helper for x pixel conversion; not a business y value.
  const uiOnlyCoordinateY = 0;
  const x = api.coord([api.value(0), uiOnlyCoordinateY])[0];
  if (typeof x !== "number" || !Number.isFinite(x)) return null;

  return {
    type: "rect",
    shape: {
      x: x - AMBIGUITY_HIT_STRIP_WIDTH / 2,
      y: coordSys.y,
      width: AMBIGUITY_HIT_STRIP_WIDTH,
      height: coordSys.height,
    },
    style: { fill: "rgba(142, 123, 85, 0.001)" },
    emphasis: {
      style: {
        fill: "rgba(142, 123, 85, 0.1)",
        shadowBlur: 4,
        shadowColor: "rgba(142, 123, 85, 0.24)",
      },
    },
  };
};

const overlayChartOptions = computed<ChartOption>(() => {
  const response = result.value;
  if (!response) return {};
  const changed: MarkerDatum[] = [];
  const added: MarkerDatum[] = [];
  const removed: MarkerDatum[] = [];
  const ambiguousAnnotations: AmbiguousAnnotationDatum[] = [];
  const ambiguityHitStrips: AmbiguityHitStripDatum[] = [];
  response.difference_points.forEach((difference, differenceIndex) => {
    if (difference.difference_kind === "VALUE_CHANGED") {
      const anchor = difference.compare_value ?? difference.baseline_value;
      if (anchor !== null) appendMarker(
        changed,
        differenceIndex,
        "VALUE_CHANGED",
        DIFFERENCE_SERIES_IDS.changed,
        difference.timestamp,
        anchor
      );
    } else if (difference.difference_kind === "POINT_ADDED") {
      appendOccurrenceMarkers(added, difference, differenceIndex, "compare", "POINT_ADDED", DIFFERENCE_SERIES_IDS.added);
    } else if (difference.difference_kind === "POINT_REMOVED") {
      appendOccurrenceMarkers(removed, difference, differenceIndex, "baseline", "POINT_REMOVED", DIFFERENCE_SERIES_IDS.removed);
    } else {
      ambiguousAnnotations.push({
        name: "对齐歧义",
        xAxis: difference.timestamp,
      });
      ambiguityHitStrips.push({
        value: [difference.timestamp],
        timestamp: difference.timestamp,
        differencePoint: true,
        differenceIndex,
        differenceKind: "AMBIGUOUS_ALIGNMENT",
        visualDataIndex: ambiguityHitStrips.length,
      });
    }
  });
  const hitAreaData = [...changed, ...added, ...removed];
  return {
    animation: false,
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(248, 248, 244, 0.97)",
      borderColor: "#C5CEC6",
      textStyle: { color: "#34443A", fontSize: 12 },
      formatter: (params: unknown) => {
        const entries = Array.isArray(params) ? params : [params];
        const validEntries = entries.filter((entry): entry is { seriesName?: string; value?: unknown } => !!entry && typeof entry === "object");
        const firstValue = validEntries[0]?.value;
        const timestamp = Array.isArray(firstValue) && typeof firstValue[0] === "string" ? firstValue[0] : "";
        return [
          timestamp ? `时间：${formatTooltipTimestamp(timestamp)}` : "",
          ...validEntries.map((entry) => {
            const value = Array.isArray(entry.value) ? entry.value[1] : null;
            return `${entry.seriesName ?? "数据"}：${formatValue(value)}`;
          }),
        ].filter(Boolean).join("<br/>");
      },
    },
    legend: { data: ["Baseline", "Compare"], top: 2, left: "center", itemGap: 22, textStyle: { color: "#536158", fontSize: 11 } },
    grid: { left: "3%", right: "4%", bottom: 72, top: "16%", containLabel: true },
    dataZoom: [
      { id: "version-compare-inside-zoom", type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false, moveOnMouseMove: true },
      { id: "version-compare-slider-zoom", type: "slider", xAxisIndex: 0, filterMode: "none", height: 18, bottom: 8, showDetail: false, brushSelect: false, backgroundColor: "#F2F5F1", borderColor: "#CDD5CE", fillerColor: "rgba(85, 117, 98, 0.18)" },
    ],
    xAxis: { type: "time", axisLabel: { formatter: formatAxisTimestamp, hideOverlap: true } },
    yAxis: { type: "value", scale: true },
    series: [
      {
        id: "version-compare-baseline",
        name: "Baseline",
        type: "line",
        showSymbol: false,
        connectNulls: false,
        lineStyle: { type: "dashed", width: 1.8, opacity: 0.72, color: BASELINE_COLOR },
        itemStyle: { color: BASELINE_COLOR },
        data: lineData(response.baseline_series.points),
        z: 2,
      },
      {
        id: "version-compare-target",
        name: "Compare",
        type: "line",
        showSymbol: false,
        connectNulls: false,
        lineStyle: { type: "solid", width: 2.6, color: COMPARE_COLOR },
        itemStyle: { color: COMPARE_COLOR },
        data: lineData(response.compare_series.points),
        markLine: {
          silent: true,
          symbol: ["none", "diamond"],
          symbolSize: [0, 11],
          label: { show: true, formatter: "对齐歧义", position: "insideEndTop", color: AMBIGUOUS_COLOR, fontSize: 10 },
          lineStyle: { color: AMBIGUOUS_COLOR, type: "dashed", width: 1.4, opacity: 0.8 },
          data: ambiguousAnnotations,
        },
        z: 3,
      },
      { id: DIFFERENCE_SERIES_IDS.changed, name: "值变化", type: "scatter", silent: true, symbol: "emptyCircle", symbolSize: 9, itemStyle: { color: CHANGED_COLOR, borderColor: CHANGED_COLOR, borderWidth: 2 }, data: changed, z: 7 },
      { id: DIFFERENCE_SERIES_IDS.added, name: "新增点", type: "scatter", silent: true, symbol: "triangle", symbolSize: 10, itemStyle: { color: COMPARE_COLOR }, data: added, z: 7 },
      { id: DIFFERENCE_SERIES_IDS.removed, name: "移除点", type: "scatter", silent: true, symbol: "triangle", symbolRotate: 180, symbolSize: 10, itemStyle: { color: BASELINE_COLOR }, data: removed, z: 7 },
      {
        id: DIFFERENCE_SERIES_IDS.hitArea,
        type: "scatter",
        silent: false,
        symbol: "circle",
        symbolSize: 20,
        cursor: "pointer",
        legendHoverLink: false,
        tooltip: { show: false },
        itemStyle: { color: "rgba(0, 0, 0, 0.001)" },
        emphasis: { scale: 1.1, focus: "none" },
        data: hitAreaData,
        z: 20,
      },
      {
        id: DIFFERENCE_SERIES_IDS.ambiguityHitStrip,
        name: AMBIGUITY_HIT_SERIES_NAME,
        type: "custom",
        coordinateSystem: "cartesian2d",
        xAxisIndex: 0,
        yAxisIndex: 0,
        dimensions: ["timestamp"],
        encode: { x: 0 },
        silent: false,
        cursor: "pointer",
        legendHoverLink: false,
        tooltip: { show: false },
        renderItem: renderAmbiguityHitStrip,
        data: ambiguityHitStrips,
        clip: true,
        z: AMBIGUITY_HIT_STRIP_Z,
      },
    ],
  };
});

const resetZoom = () => {
  chartRef.value?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  void updateDifferenceDetailPosition();
};

watch([() => props.dataset?.id, () => props.currentVersionId, () => props.versions], () => {
  clearSelectedDifference();
  applyDefaultPair();
}, { immediate: true });
watch([() => props.dataset?.id, baselineVersionId, compareVersionId], () => { void loadChannels(); }, { immediate: true });
watch(selectedChannel, (channel, previous) => { if (channel !== previous) invalidateResult(); });
onBeforeUnmount(() => { ++differencePositionRequestId; });
</script>

<style scoped>
.version-compare-workbench { padding: 20px; background: #fff; }
.workbench-header, .summary-header, .chart-header, .execution-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.workbench-header h3, .workbench-header p, .summary-header h4, .summary-header p { margin: 0; }
.workbench-header h3 { margin-top: 4px; font-size: 17px; }
.workbench-header p, .summary-header p, .chart-header span, .loading-copy, .workbench-empty span, .ambiguity-note { color: var(--text-muted); font-size: 11px; }
.workbench-header p { margin-top: 4px; font-size: 12px; }
.workbench-eyebrow, .summary-scope { color: var(--color-primary); font-size: 9px; font-weight: 700; letter-spacing: .1em; }
.selector-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 18px; }
.selector-field, .channel-field { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.selector-field > label, .channel-field > label { color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.execution-row { align-items: flex-end; margin-top: 16px; }
.channel-field { width: min(360px, 100%); }
.channel-field :deep(.el-select) { width: 100%; }
.inline-alert, .result-alert, .compare-loading { margin-top: 14px; }
.compare-loading { padding: 24px; border: 1px dashed var(--border-default); border-radius: 8px; color: var(--text-muted); font-size: 12px; text-align: center; }
.compare-result { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--border-light); }
.summary-header { align-items: flex-start; }
.summary-header h4 { margin-top: 3px; font-size: 15px; }
.summary-header p { margin-top: 4px; }
.summary-header .relation-explanation { max-width: 720px; margin-top: 7px; color: var(--text-secondary); }
.summary-badges { display: flex; gap: 8px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.metric-card { display: flex; flex-direction: column; gap: 5px; padding: 12px 14px; border: 1px solid var(--border-light); border-radius: 8px; background: #fafbf8; }
.metric-card span { color: var(--text-muted); font-size: 10px; }
.metric-card strong { color: var(--text-primary); font-family: var(--font-sans); font-size: 21px; }
.metric-card.changed { border-top: 2px solid #B5965D; }
.metric-card.added { border-top: 2px solid #557562; }
.metric-card.removed { border-top: 2px solid #A8665E; }
.metric-card.ambiguous { border-top: 2px solid #8E7B55; }
.summary-secondary { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 10px; color: var(--text-muted); font-size: 10px; }
.chart-header { margin: 18px 0 8px; }
.chart-header > div { display: flex; flex-direction: column; gap: 2px; }
.chart-header strong { font-size: 13px; }
.ambiguity-note { margin: 6px 0 0; }
.version-compare-chart-stage { position: relative; }
.difference-detail-host { position: absolute; z-index: 12; }
.difference-detail-host.is-anchor-hidden { visibility: hidden; pointer-events: none; }
.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }
.evidence-grid.status-only { grid-template-columns: 1fr; }
.evidence-card { min-width: 0; padding: 16px; border: 1px solid var(--border-light); border-radius: 9px; background: #fafbf8; }
.evidence-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.evidence-card h4 { margin: 3px 0 0; font-size: 14px; }
.evidence-eyebrow { color: var(--color-primary); font-family: var(--font-sans); font-size: 9px; font-weight: 700; letter-spacing: normal; }
.evidence-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }
.evidence-metrics > div { display: flex; flex-direction: column; gap: 4px; padding: 9px 10px; border: 1px solid #e1e6df; border-radius: 6px; background: #fff; }
.evidence-metrics span, .evidence-auxiliary dt, .other-audit-fields dt { color: var(--text-muted); font-size: 10px; }
.evidence-metrics strong { font-family: var(--font-sans); font-size: 16px; }
.evidence-auxiliary, .other-audit-fields dl { display: grid; gap: 6px; margin: 12px 0 0; }
.evidence-auxiliary > div, .other-audit-fields dl > div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; }
.evidence-auxiliary dd, .other-audit-fields dd { overflow-wrap: anywhere; margin: 0; font-family: var(--font-sans); font-size: 10px; }
.direct-evidence-card :deep(.el-alert) { margin-top: 12px; }
.other-audit-fields { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-light); }
.other-audit-fields summary { color: var(--text-secondary); font-size: 11px; cursor: pointer; }
.identity-explanation { margin: 12px 0 0; padding: 8px 10px; border-left: 3px solid #8e9b90; background: #f0f3ef; color: var(--text-secondary); font-size: 10px; }
.convergence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.convergence-side { min-width: 0; padding: 11px; border: 1px solid #e1e6df; border-radius: 7px; background: #fff; }
.convergence-side > span { color: var(--text-muted); font-size: 9px; font-weight: 700; text-transform: uppercase; }
.convergence-side > strong { display: block; overflow: hidden; margin-top: 3px; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.convergence-side > p { margin: 9px 0 0; color: var(--text-muted); font-size: 10px; }
.convergence-side > p.confirmed { color: #466f43; font-weight: 650; }
.convergence-side dl { display: grid; gap: 5px; margin: 10px 0 0; padding-top: 9px; border-top: 1px solid #e5e9e4; }
.convergence-side dl > div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.convergence-side dt { color: var(--text-muted); font-size: 9px; }
.convergence-side dd { overflow-wrap: anywhere; margin: 0; font-family: var(--font-sans); font-size: 9px; }
.workbench-empty { display: flex; flex-direction: column; align-items: center; gap: 5px; margin-top: 20px; padding: 34px 20px; border: 1px dashed var(--border-default); border-radius: 8px; background: var(--bg-subtle); }
.workbench-empty strong { font-size: 13px; }
@media (max-width: 900px) {
  .selector-grid, .metric-grid, .evidence-grid, .convergence-grid { grid-template-columns: 1fr; }
  .execution-row, .workbench-header, .summary-header { align-items: stretch; flex-direction: column; }
  .summary-badges { align-self: flex-start; }
}
</style>
