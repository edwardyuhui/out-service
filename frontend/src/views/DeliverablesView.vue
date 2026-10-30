<template>
  <div class="page-container deliverables-view">
    <PageHeader
      eyebrow="DELIVERABLES & REPORTS / EXPORT"
      title="报告生成与数据交付"
      description="报告中的每一个数值都由可信运行记录解析而来；大模型只负责组织语言与工程洞察，不编造任何数字"
    />

    <div class="deliverables-layout">
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Document /></el-icon> 交付参数
          </div>
        </div>

        <el-form class="parameter-form-grid" label-position="top">
          <el-form-item label="数据集名称">
            <el-select v-model="selectedDatasetId" clearable filterable placeholder="请选择数据集" :loading="datasetsLoading" @change="handleDatasetChange">
              <el-option v-for="item in datasets" :key="item.id" :label="datasetOptionLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="数据版本">
            <VersionLineagePicker
              :dataset-name="selectedDataset?.name || ''"
              :versions="versions"
              :selected-version-id="selectedVersionId"
              context-label="报告与交付版本"
              eligible-label="可选择"
              :is-eligible="versionEligible"
              :disabled-reason="versionDisabledReason"
              empty-state-text="该数据集没有合法版本"
              placeholder="选择数据版本"
              :loading="contextLoading"
              selected-badge-label="当前选择"
              @select="handleVersionChange"
            />
          </el-form-item>
          <el-form-item label="Optuna Study">
            <el-select v-model="selectedStudyId" clearable placeholder="报告可不关联；Best 导出必须选择" :loading="studiesLoading" :disabled="!selectedVersionId" @change="clearGeneratedOutputs">
              <el-option v-for="study in studies" :key="study.study_id" :label="studyOptionLabel(study)" :value="study.study_id" />
            </el-select>
            <p class="form-hint">默认选择按完成时间排序的最近一次合法成功 Study；列表不使用排行榜顺序。</p>
          </el-form-item>
          <el-form-item label="本版本变量">
            <div class="variable-summary">
              <span>输入</span>
              <el-tag v-for="column in selectedInputColumns" :key="column" size="small">{{ column }}</el-tag>
              <span>输出</span>
              <el-tag v-if="selectedOutputColumn" size="small" type="success">{{ selectedOutputColumn }}</el-tag>
              <em v-else>未配置</em>
            </div>
          </el-form-item>
          <el-form-item class="parameter-form-actions">
            <el-button
              type="primary"
              :loading="reporting"
              :disabled="!canGenerateReport"
              icon="Document"
              @click="handleReport"
            >
              生成 HTML 图文报告
            </el-button>
            <el-button
              type="success"
              :loading="exporting"
              :disabled="!canExportBest"
              icon="Download"
              @click="handleExport"
            >
              导出 Optuna Best 数据集
            </el-button>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="selectedVersionId && !studiesLoading && studies.length === 0"
          type="warning"
          :closable="false"
          show-icon
          class="alert-gap"
          title="当前版本没有通过严格 Best 校验的成功 Study；仍可生成不关联 Study 的部分报告。"
        />

        <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
          <template #title>{{ errorMessage }}</template>
        </el-alert>
      </div>

      <div class="industrial-card" v-if="exportResult">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Download /></el-icon> Optuna Best 优选数据集
          </div>
          <el-tag type="success">
            {{ exportResult.exported_rows }} / {{ exportResult.source_rows }} 行
          </el-tag>
        </div>
        <el-descriptions border :column="2" size="small">
          <el-descriptions-item label="采样占比">
            {{ (exportResult.coverage_ratio * 100).toFixed(2) }}%
          </el-descriptions-item>
          <el-descriptions-item label="导出列">
            <span class="code-inline">{{ exportResult.columns.join(", ") }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <ExportDownloadActions
          class="download-actions"
          :csv-url="`/api/v1/delivery/exports/${exportResult.export_id}/csv`"
          :manifest-url="`/api/v1/delivery/exports/${exportResult.export_id}/manifest`"
        />
      </div>

      <template v-if="report">
        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Finished /></el-icon> 数值溯源
            </div>
            <el-tag :type="report.fully_resolved ? 'success' : 'warning'">
              {{ report.bindings.length }} 个数值已绑定运行记录
              {{ report.fully_resolved ? "" : `，${report.unresolved.length} 个未解析` }}
            </el-tag>
          </div>
          <el-alert type="info" :closable="false" class="alert-gap">
            <template #title>
              报告草稿中禁止出现任何未绑定的数字字面量；校验不通过将拒绝渲染并要求重新生成。
              下表列出了报告里每个数字的来源运行记录与字段路径。
            </template>
          </el-alert>
          <el-table :data="report.bindings" stripe height="300" style="width: 100%">
            <el-table-column label="占位符" width="330">
              <template #default="{ row }">
                <span class="code-inline">{{ row.placeholder }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="run_id" label="来源运行" width="120" />
            <el-table-column prop="path" label="字段路径" />
            <el-table-column label="解析值" width="180">
              <template #default="{ row }">
                <span class="fit-val">{{ row.value }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Printer /></el-icon> {{ report.title }}
            </div>
            <div class="report-actions">
              <el-tag type="info">真实图表 {{ report.charts.length }} 幅</el-tag>
              <el-button :icon="FullScreen" @click="openFullscreenReport">全屏查看</el-button>
              <el-button icon="Download" @click="downloadHtml">下载 HTML</el-button>
              <el-button icon="Printer" @click="printHtml">打印 / 保存 PDF</el-button>
            </div>
          </div>
          <iframe
            ref="reportFrame"
            class="report-frame"
            title="HTML 图文报告预览"
            sandbox="allow-same-origin allow-modals"
            :srcdoc="report.html"
          />
          <p class="artifact-path" v-if="report.html_artifact_uri">
            HTML 产物：<span class="code-inline">{{ report.html_artifact_uri }}</span>
          </p>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { Document, Download, Finished, FullScreen, Printer } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import PageHeader from "../components/common/PageHeader.vue";
import VersionLineagePicker from "../components/versioning/VersionLineagePicker.vue";
import ExportDownloadActions from "../components/artifact/ExportDownloadActions.vue";
import { getDatasetDetail, getDatasetVersions } from "../api/datasets";
import { exportDataset, generateReport, getDeliveryStudies } from "../api/delivery";
import { ApiError } from "../api/client";
import { useDatasetStore } from "../stores/datasetStore";
import type { DatasetItem, DatasetVersionNode, DeliveryStudyOption, ExportDatasetResponse, ReportResponse } from "../types/api";

const route = useRoute();
const datasetStore = useDatasetStore();
const selectedDatasetId = ref<string | null>(null);
const selectedVersionId = ref<string | null>(null);
const versions = ref<DatasetVersionNode[]>([]);
const studies = ref<DeliveryStudyOption[]>([]);
const selectedStudyId = ref<string | null>(null);
const reporting = ref(false);
const exporting = ref(false);
const datasetsLoading = ref(false);
const contextLoading = ref(false);
const studiesLoading = ref(false);
const errorMessage = ref("");
const report = ref<ReportResponse | null>(null);
const exportResult = ref<ExportDatasetResponse | null>(null);
const reportFrame = ref<HTMLIFrameElement | null>(null);
let contextGeneration = 0;
let studyGeneration = 0;

const datasets = computed(() => datasetStore.datasetsList);
const selectedDataset = computed(() => datasets.value.find((item) => item.id === selectedDatasetId.value) ?? null);
const selectedVersion = computed(() => versions.value.find((item) => item.id === selectedVersionId.value) ?? null);
const selectedStudy = computed(() => studies.value.find((item) => item.study_id === selectedStudyId.value) ?? null);
const selectedInputColumns = computed(() => selectedStudy.value?.input_columns ?? selectedVersion.value?.input_columns ?? []);
const selectedOutputColumn = computed(() => selectedStudy.value?.output_column ?? selectedVersion.value?.output_column ?? null);
const canGenerateReport = computed(() => Boolean(selectedDatasetId.value && selectedVersionId.value) && !contextLoading.value);
const canExportBest = computed(() => Boolean(selectedDatasetId.value && selectedVersionId.value && selectedStudyId.value) && !contextLoading.value && !studiesLoading.value);

const clearGeneratedOutputs = () => {
  report.value = null;
  exportResult.value = null;
  errorMessage.value = "";
  reporting.value = false;
  exporting.value = false;
};

const resetContext = () => {
  selectedVersionId.value = null;
  versions.value = [];
  studies.value = [];
  selectedStudyId.value = null;
  clearGeneratedOutputs();
};

const errorText = (error: unknown) => error instanceof ApiError ? error.message : String(error);
const formatDate = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
};
const datasetOptionLabel = (item: DatasetItem) => {
  const duplicated = datasets.value.filter((candidate) => candidate.name === item.name).length > 1;
  const source = item.source === "simulation" ? "仿真" : "上传";
  const qualifier = duplicated ? ` · ${formatDate(item.created_at)} · ${item.id.slice(0, 8)}` : "";
  return `${item.name} · ${source}${qualifier}`;
};
const studyOptionLabel = (study: DeliveryStudyOption) => `${formatDate(study.finished_at)} · Best Trial ${study.best_trial_number} · ${study.best_value.toFixed(4)}`;
const versionEligible = () => true;
const versionDisabledReason = () => "";

const loadStudies = async (datasetId: string, versionId: string, generation: number) => {
  const request = ++studyGeneration;
  studiesLoading.value = true;
  studies.value = [];
  selectedStudyId.value = null;
  try {
    const response = await getDeliveryStudies(datasetId, versionId);
    if (generation !== contextGeneration || request !== studyGeneration) return;
    if (response.dataset_id !== datasetId || response.version_id !== versionId) throw new Error("Study 列表与当前数据集版本不一致");
    studies.value = response.items;
    selectedStudyId.value = response.items[0]?.study_id ?? null;
  } catch (error) {
    if (generation !== contextGeneration || request !== studyGeneration) return;
    errorMessage.value = errorText(error);
  } finally {
    if (generation === contextGeneration && request === studyGeneration) studiesLoading.value = false;
  }
};

const handleDatasetChange = async (value: string | null) => {
  const generation = ++contextGeneration;
  studyGeneration += 1;
  resetContext();
  if (!value) return;
  selectedDatasetId.value = value;
  contextLoading.value = true;
  try {
    const [detail, lineage] = await Promise.all([getDatasetDetail(value), getDatasetVersions(value)]);
    if (generation !== contextGeneration) return;
    if (detail.id !== value || lineage.dataset_id !== value) throw new Error("数据集详情或版本响应作用域不一致");
    const activeVersionId = lineage.active_version_id;
    if (!activeVersionId || !lineage.nodes.some((node) => node.id === activeVersionId)) {
      throw new Error("数据集当前版本异常：active_version_id 不在合法版本列表中");
    }
    datasetStore.setActiveDataset(detail);
    versions.value = lineage.nodes;
    selectedVersionId.value = activeVersionId;
    await loadStudies(value, activeVersionId, generation);
  } catch (error) {
    if (generation !== contextGeneration) return;
    resetContext();
    selectedDatasetId.value = value;
    errorMessage.value = errorText(error);
  } finally {
    if (generation === contextGeneration) contextLoading.value = false;
  }
};

const handleVersionChange = (versionId: string) => {
  if (!selectedDatasetId.value || versionId === selectedVersionId.value) return;
  const generation = ++contextGeneration;
  studyGeneration += 1;
  selectedVersionId.value = versionId;
  studies.value = [];
  selectedStudyId.value = null;
  clearGeneratedOutputs();
  void loadStudies(selectedDatasetId.value, versionId, generation);
};

const handleReport = async () => {
  if (!selectedDatasetId.value || !selectedVersionId.value) return;
  const generation = contextGeneration;
  errorMessage.value = "";
  reporting.value = true;
  try {
    const result = await generateReport({ dataset_id: selectedDatasetId.value, version_id: selectedVersionId.value, study_id: selectedStudyId.value });
    if (generation !== contextGeneration) return;
    report.value = result;
    ElMessage.success(`HTML 报告已生成，包含 ${result.charts.length} 幅真实图表`);
  } catch (error) {
    if (generation !== contextGeneration) return;
    report.value = null;
    errorMessage.value = errorText(error);
  } finally {
    if (generation === contextGeneration) reporting.value = false;
  }
};

const handleExport = async () => {
  if (!selectedDatasetId.value || !selectedVersionId.value || !selectedStudyId.value) return;
  const generation = contextGeneration;
  errorMessage.value = "";
  exporting.value = true;
  try {
    const result = await exportDataset({ dataset_id: selectedDatasetId.value, version_id: selectedVersionId.value, study_id: selectedStudyId.value, mode: "optimization_best" });
    if (generation !== contextGeneration) return;
    exportResult.value = result;
    ElMessage.success(`已严格导出 Best Trial 的 ${result.exported_rows} 行训练数据`);
  } catch (error) {
    if (generation !== contextGeneration) return;
    exportResult.value = null;
    errorMessage.value = errorText(error);
  } finally {
    if (generation === contextGeneration) exporting.value = false;
  }
};

const downloadHtml = () => {
  if (!report.value) return;
  const url = URL.createObjectURL(new Blob([report.value.html], { type: "text/html;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `indusopt-report-${report.value.report_id}.html`;
  anchor.click();
  URL.revokeObjectURL(url);
};

const openFullscreenReport = () => {
  const html = report.value?.html;
  if (!html) {
    ElMessage.warning("请先生成有效的 HTML 报告");
    return;
  }

  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const reportWindow = window.open(url, "_blank");
  if (!reportWindow) {
    URL.revokeObjectURL(url);
    ElMessage.error("浏览器阻止了新标签页，请允许此站点打开弹出窗口后重试");
    return;
  }

  reportWindow.opener = null;
  reportWindow.addEventListener("load", () => URL.revokeObjectURL(url), { once: true });
};

const printHtml = () => {
  const target = reportFrame.value?.contentWindow;
  if (!target) return ElMessage.error("报告预览尚未准备完成");
  target.focus();
  target.print();
};

onMounted(async () => {
  datasetsLoading.value = true;
  await datasetStore.ensureDatasetNamesLoaded();
  datasetsLoading.value = false;
  const requested = typeof route.query.dataset_id === "string" ? route.query.dataset_id : null;
  const contextual = requested || datasetStore.activeDataset?.id || null;
  if (contextual && datasets.value.some((item) => item.id === contextual)) {
    selectedDatasetId.value = contextual;
    await handleDatasetChange(contextual);
  }
});
</script>

<style scoped>
.deliverables-view {
  min-height: 100%;
}

.deliverables-layout {
  display: flex;
  flex-direction: column;
  gap: var(--section-gap-md);
}

.alert-gap {
  margin: 12px 0;
}

.parameter-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}

.parameter-form-actions {
  grid-column: 1 / -1;
}

.parameter-form-actions :deep(.el-form-item__content) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.form-hint {
  width: 100%;
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.variable-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  min-height: 32px;
}

.variable-summary > span {
  color: var(--text-secondary);
  font-size: 12px;
}

.variable-summary em {
  color: var(--text-muted);
  font-style: normal;
}

.download-actions {
  max-width: 430px;
  margin-top: 16px;
}

.report-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.report-frame {
  width: 100%;
  min-height: 760px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: #fff;
}

.report-content {
  line-height: 1.8;
  color: var(--text-primary);
}

.report-content h4 {
  margin: 16px 0 6px;
  color: var(--text-primary);
}

.fit-val {
  font-weight: 600;
  color: var(--accent);
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.artifact-path {
  margin-top: 14px;
  font-size: 12px;
  color: var(--text-secondary);
}

@media (max-width: 800px) {
  .parameter-form-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .parameter-form-actions {
    grid-column: auto;
  }

  .report-frame {
    min-height: 620px;
  }
}
</style>
