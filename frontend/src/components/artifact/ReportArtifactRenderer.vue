<template>
  <section class="report-artifact" data-test="report-artifact-renderer">
    <header class="report-header">
      <div>
        <span class="report-eyebrow">分析报告</span>
        <h3>{{ reportTitle }}</h3>
      </div>
      <span class="report-status" :class="{ warning: !fullyResolved }">
        {{ resolutionLabel }}
      </span>
    </header>

    <section v-if="coreMetrics.length" class="report-section" data-test="report-core-metrics">
      <h4>核心指标</h4>
      <div class="report-metrics">
        <article v-for="metric in coreMetrics" :key="metric.label">
          <span>{{ metric.label }}</span>
          <strong class="tabular-nums">{{ metric.value }}</strong>
        </article>
      </div>
    </section>

    <section class="report-section" data-test="report-stages">
      <h4>执行阶段成果</h4>
      <div class="report-stages">
        <article v-for="stage in reportStages" :key="stage.stepId">
          <span class="stage-dot" :class="stage.statusClass" aria-hidden="true" />
          <div>
            <strong>{{ stage.label }}</strong>
            <p v-if="stage.summary">{{ stage.summary }}</p>
          </div>
          <span class="stage-meta">{{ stage.statusLabel }}<template v-if="stage.duration"> · {{ stage.duration }}</template></span>
        </article>
      </div>
    </section>

    <details v-if="profilePayload" class="report-detail" data-test="report-profile-section">
      <summary>数据画像</summary>
      <ProfileArtifactRenderer :payload="profilePayload" compact />
    </details>

    <details v-if="anomalyPayload" class="report-detail" data-test="report-anomaly-section">
      <summary>异常检测</summary>
      <AnomalyArtifactRenderer :payload="anomalyPayload" compact />
    </details>

    <details v-if="cleaningPayload" class="report-detail" data-test="report-cleaning-section">
      <summary>清洗影响</summary>
      <CleaningArtifactRenderer :payload="cleaningPayload" compact />
    </details>

    <section v-if="markdownBlocks.length" class="report-section report-body" data-test="report-markdown">
      <h4>关键结论与报告正文</h4>
      <template v-for="(block, index) in markdownBlocks" :key="index">
        <h5 v-if="block.type === 'heading'">{{ block.text }}</h5>
        <ul v-else-if="block.type === 'list'">
          <li v-for="item in block.items" :key="item">{{ item }}</li>
        </ul>
        <p v-else>{{ block.text }}</p>
      </template>
    </section>

    <section v-if="businessEvidence.length" class="report-section" data-test="report-evidence">
      <h4>证据与来源</h4>
      <div class="evidence-list">
        <article v-for="evidence in businessEvidence" :key="evidence.key">
          <div>
            <strong>{{ evidence.stage }}</strong>
            <span>{{ evidence.metric }}</span>
          </div>
          <span class="evidence-value">{{ evidence.value }}</span>
          <span class="evidence-state">来源：{{ evidence.source }}</span>
        </article>
      </div>
    </section>

    <details class="report-technical" data-test="report-technical-details">
      <summary>技术详情</summary>
      <dl>
        <template v-for="item in technicalItems" :key="item.label">
          <dt>{{ item.label }}</dt>
          <dd class="font-mono">{{ item.value }}</dd>
        </template>
      </dl>
      <pre class="report-raw font-mono" data-test="report-raw-json">{{ rawPayload }}</pre>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { CopilotExecutionSnapshot, CopilotExecutionStepSnapshot } from "../../types/api";
import AnomalyArtifactRenderer from "./AnomalyArtifactRenderer.vue";
import CleaningArtifactRenderer from "./CleaningArtifactRenderer.vue";
import ProfileArtifactRenderer from "./ProfileArtifactRenderer.vue";

type MarkdownBlock =
  | { type: "heading" | "paragraph"; text: string; items?: never }
  | { type: "list"; text?: never; items: string[] };

const props = defineProps<{
  payload: Record<string, unknown>;
  execution: CopilotExecutionSnapshot;
}>();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const finiteNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const nonEmptyString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;
const unwrap = (payload: Record<string, unknown>): Record<string, unknown> =>
  isRecord(payload.result) ? payload.result : payload;

const stepFor = (tool: string): CopilotExecutionStepSnapshot | undefined =>
  props.execution.step_runs.find((step) => step.tool === tool);

const payloadFor = (tool: string): Record<string, unknown> | null => {
  const payload = stepFor(tool)?.result_payload;
  return isRecord(payload) && Object.keys(payload).length ? payload : null;
};

const profilePayload = computed(() => payloadFor("profile_dataset"));
const anomalyPayload = computed(() => payloadFor("detect_anomalies"));
const cleaningPayload = computed(() => payloadFor("clean_data"));
const reportTitle = computed(() => nonEmptyString(props.payload.title) ?? "分析报告");
const fullyResolved = computed(() => props.payload.fully_resolved === true);
const unresolvedCount = computed(() => Array.isArray(props.payload.unresolved) ? props.payload.unresolved.length : 0);
const executionScoped = computed(() =>
  nonEmptyString(props.payload.execution_id) === props.execution.execution_id
);
const resolutionLabel = computed(() => {
  if (!fullyResolved.value) return `${unresolvedCount.value} 项引用未解析`;
  return executionScoped.value ? "本次任务证据已解析" : "报告引用已解析";
});

const coreMetrics = computed(() => {
  const metrics: Array<{ label: string; value: string }> = [];
  const profile = profilePayload.value ? unwrap(profilePayload.value) : {};
  const anomaly = anomalyPayload.value ? unwrap(anomalyPayload.value) : {};
  const cleaning = cleaningPayload.value ? unwrap(cleaningPayload.value) : {};
  const cleaningSummary = isRecord(cleaning.summary) ? cleaning.summary : {};
  const sampleCount = finiteNumber(profile.n_samples);
  const anomalyCount = finiteNumber(anomaly.anomaly_count);
  const anomalyRatio = finiteNumber(anomaly.anomaly_ratio);
  const changed = finiteNumber(cleaning.total_cleaned_points);
  const rowsBefore = finiteNumber(cleaningSummary.rows_before);
  const rowsAfter = finiteNumber(cleaningSummary.rows_after);
  if (sampleCount !== null) metrics.push({ label: "样本数", value: Math.round(sampleCount).toLocaleString("zh-CN") });
  if (anomalyCount !== null) metrics.push({ label: "异常点", value: Math.round(anomalyCount).toLocaleString("zh-CN") });
  if (anomalyRatio !== null && anomalyRatio >= 0 && anomalyRatio <= 1) metrics.push({ label: "异常比例", value: `${(anomalyRatio * 100).toFixed(2)}%` });
  if (changed !== null) metrics.push({ label: "修改单元格", value: Math.round(changed).toLocaleString("zh-CN") });
  if (rowsBefore !== null) metrics.push({ label: "清洗前样本", value: Math.round(rowsBefore).toLocaleString("zh-CN") });
  if (rowsAfter !== null) metrics.push({ label: "清洗后样本", value: Math.round(rowsAfter).toLocaleString("zh-CN") });
  return metrics;
});

const stageLabels: Record<string, string> = {
  profile_dataset: "数据画像",
  align_and_resample: "时间对齐与重采样",
  detect_anomalies: "异常检测",
  clean_data: "数据清洗",
  detect_dynamic_segments: "动态区间与数据优选",
  estimate_delays: "时滞估计",
  apply_lag_compensation: "时滞补偿",
  analyze_collinearity: "共线性诊断",
  select_variables: "变量优选",
  fit_arx: "动态模型辨识",
  evaluate_model: "模型评价",
  optimize_pipeline: "闭环寻优",
  generate_report: "分析报告",
  export_dataset: "数据导出",
};

const UUID_PATTERN = /\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/gi;
const withoutTechnicalIds = (value: string): string => value.replace(UUID_PATTERN, "技术标识已隐藏");

const stageSummary = (step: CopilotExecutionStepSnapshot): string => {
  const payload = step.result_payload;
  const explicit = nonEmptyString(payload.summary);
  if (explicit) return withoutTechnicalIds(explicit);
  const result = unwrap(payload);
  const task = isRecord(result.task) ? result.task : {};
  const progress = isRecord(task.progress) ? task.progress : {};
  return withoutTechnicalIds(nonEmptyString(progress.message) ?? "");
};

const stageDuration = (step: CopilotExecutionStepSnapshot): string => {
  if (!step.started_at || !step.finished_at) return "";
  const milliseconds = new Date(step.finished_at).getTime() - new Date(step.started_at).getTime();
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "";
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
};

const statusLabel = (status: string): string => ({
  SUCCEEDED: "已完成",
  completed: "已完成",
  FAILED: "失败",
  failed: "失败",
  RUNNING: "执行中",
  running: "执行中",
  WAITING_CONFIRMATION: "待确认",
  waiting_confirmation: "待确认",
}[status] ?? status);

const reportStages = computed(() => props.execution.step_runs.flatMap((step) => {
  const label = stageLabels[step.tool];
  return label ? [{
    stepId: step.step_id,
    label,
    statusLabel: statusLabel(step.status),
    statusClass: step.status.toLowerCase(),
    summary: stageSummary(step),
    duration: stageDuration(step),
  }] : [];
}));

const markdownBlocks = computed<MarkdownBlock[]>(() => {
  const markdown = nonEmptyString(props.payload.markdown);
  if (!markdown) return [];
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ type: "paragraph", text: paragraph.join(" ") });
    if (list.length) blocks.push({ type: "list", items: [...list] });
    paragraph = [];
    list = [];
  };
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flush();
    } else if (/^#{1,6}\s+/.test(line)) {
      flush();
      blocks.push({ type: "heading", text: line.replace(/^#{1,6}\s+/, "") });
    } else if (/^[-*]\s+/.test(line)) {
      if (paragraph.length) flush();
      list.push(line.replace(/^[-*]\s+/, ""));
    } else {
      if (list.length) flush();
      paragraph.push(line);
    }
  }
  flush();
  return blocks;
});

type BusinessEvidence = {
  key: string;
  stage: string;
  metric: string;
  value: string;
  source: string;
};

const countText = (value: number): string => Math.round(value).toLocaleString("zh-CN");
const ratioText = (value: number): string => `${(value * 100).toFixed(2)}%`;
const businessEvidence = computed<BusinessEvidence[]>(() => {
  const evidence: BusinessEvidence[] = [];
  const profile = profilePayload.value ? unwrap(profilePayload.value) : {};
  const profileFingerprint = isRecord(profile.fingerprint) ? profile.fingerprint : {};
  const profileValues = isRecord(profileFingerprint.values) ? profileFingerprint.values : {};
  const anomaly = anomalyPayload.value ? unwrap(anomalyPayload.value) : {};
  const cleaning = cleaningPayload.value ? unwrap(cleaningPayload.value) : {};
  const cleaningSummary = isRecord(cleaning.summary) ? cleaning.summary : {};
  const changes = isRecord(cleaningSummary.changes) ? cleaningSummary.changes : {};
  const pushCount = (
    key: string, stage: string, metric: string, value: unknown, source: string
  ) => {
    const numeric = finiteNumber(value);
    if (numeric !== null) evidence.push({ key, stage, metric, value: countText(numeric), source });
  };
  const pushRatio = (
    key: string, stage: string, metric: string, value: unknown, source: string
  ) => {
    const numeric = finiteNumber(value);
    if (numeric !== null && numeric >= 0 && numeric <= 1) {
      evidence.push({ key, stage, metric, value: ratioText(numeric), source });
    }
  };
  pushCount("profile-samples", "数据画像", "样本数量", profile.n_samples, "本次数据画像");
  pushRatio("profile-missing", "数据画像", "缺失比例", profileValues.missing_ratio, "本次数据画像");
  pushRatio("profile-anomaly", "数据画像", "画像离群比例", profileValues.anomaly_ratio, "本次数据画像");
  pushCount("anomaly-count", "异常检测", "疑似异常点数量", anomaly.anomaly_count, "本次异常检测");
  pushRatio("anomaly-ratio", "异常检测", "疑似异常比例", anomaly.anomaly_ratio, "本次异常检测");
  pushCount(
    "clean-changed",
    "数据清洗",
    "修改单元格",
    changes.unique_changed_cells ?? cleaning.total_cleaned_points,
    "本次数据清洗"
  );
  pushCount("clean-rows-before", "数据清洗", "清洗前样本", cleaningSummary.rows_before, "本次数据清洗");
  pushCount("clean-rows-after", "数据清洗", "清洗后样本", cleaningSummary.rows_after, "本次数据清洗");
  return evidence;
});

const processingRunIds = computed(() => [...new Set(
  props.execution.step_runs.flatMap((step) => step.processing_run_ids)
)]);

const technicalItems = computed(() => [
  ["Report ID", props.payload.report_id],
  ["Dataset ID", props.payload.dataset_id],
  ["Execution ID", props.payload.execution_id ?? props.execution.execution_id],
  ["Version ID", props.execution.current_version_id],
  ["ProcessingRun IDs", processingRunIds.value.join(", ")],
  ["Artifact", props.payload.artifact_uri],
  ["Narration", props.payload.narration_source],
  ["Provider", props.payload.llm_provider],
  ["Model", props.payload.llm_model],
].flatMap(([label, value]) => {
  const text = nonEmptyString(value);
  return text ? [{ label: String(label), value: text }] : [];
}));

const rawPayload = computed(() => JSON.stringify(props.payload, null, 2));
</script>

<style scoped>
.report-artifact { display: flex; flex-direction: column; gap: 18px; min-width: 0; color: var(--text-primary); }
.report-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.report-eyebrow { color: var(--text-tertiary); font-size: 11px; }
.report-header h3 { margin: 4px 0 0; font-size: 18px; line-height: 1.35; }
.report-status { flex-shrink: 0; padding: 5px 9px; border-radius: 999px; background: #EDF5EA; color: #426340; font-size: 11px; white-space: nowrap; }
.report-status.warning { background: #FFF4DD; color: #8A621F; }
.report-section { padding-top: 16px; border-top: 1px solid var(--border-subtle); }
.report-section h4 { margin: 0 0 10px; font-size: 13px; }
.report-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.report-metrics article { padding: 11px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: var(--surface-2); }
.report-metrics span { display: block; color: var(--text-tertiary); font-size: 10px; }
.report-metrics strong { display: block; margin-top: 4px; font-size: 17px; }
.report-stages { display: flex; flex-direction: column; gap: 8px; }
.report-stages article { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: start; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); }
.stage-dot { width: 7px; height: 7px; margin-top: 5px; border-radius: 50%; background: var(--text-muted); }
.stage-dot.succeeded, .stage-dot.completed { background: var(--success); }
.stage-dot.failed { background: var(--danger); }
.report-stages strong { font-size: 12px; }
.report-stages p { margin: 3px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.5; }
.stage-meta { color: var(--text-muted); font-size: 10px; white-space: nowrap; }
.report-detail, .report-technical { border: 1px solid var(--border-default); border-radius: 8px; background: #fff; }
.report-detail > summary, .report-technical > summary { padding: 11px 12px; color: var(--text-primary); font-size: 12px; font-weight: 600; cursor: pointer; }
.report-detail > :not(summary), .report-technical > :not(summary) { margin: 0 12px 14px; }
.report-body h5 { margin: 16px 0 6px; font-size: 13px; }
.report-body p, .report-body li { color: var(--text-secondary); font-size: 12px; line-height: 1.75; }
.report-body p { margin: 0 0 10px; white-space: pre-wrap; }
.evidence-list article { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); }
.evidence-list strong, .evidence-list span { display: block; font-size: 11px; }
.evidence-list div span { margin-top: 2px; color: var(--text-tertiary); }
.evidence-value { color: var(--text-secondary); text-align: right; }
.evidence-state { color: var(--success); }
.report-technical dl { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 6px 10px; font-size: 10px; }
.report-technical dt { color: var(--text-tertiary); }
.report-technical dd { margin: 0; overflow-wrap: anywhere; color: var(--text-secondary); }
.report-raw { max-height: 260px; overflow: auto; padding: 10px; border-radius: 6px; background: #F7F8F5; color: var(--text-secondary); font-size: 10px; white-space: pre; }
@media (max-width: 620px) {
  .report-header { flex-direction: column; }
  .report-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .evidence-list article { grid-template-columns: minmax(0, 1fr) auto; }
  .evidence-state { display: none; }
}
</style>
