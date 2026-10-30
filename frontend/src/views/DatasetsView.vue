<template>
  <div class="page-container datasets-view">
    <PageHeader
      eyebrow="PREPARE DATA / DATASETS"
      title="数据资产"
      description="上传工业 CSV、配置变量角色，并追踪每一次处理产生的数据版本"
    />

    <!-- Upload Card -->
    <div class="industrial-card section-block">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><Upload /></el-icon> 上传工业 CSV
        </div>
      </div>
      <el-upload
        class="upload-area"
        drag
        action="#"
        :http-request="customUpload"
        :show-file-list="false"
      >
        <el-icon class="el-icon--upload"><upload-filled /></el-icon>
        <div class="el-upload__text">
          拖拽 CSV 文件到此处或 <em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持最大 100 MB；自动识别 UTF-8、GBK、GB2312 编码及逗号、分号、制表符分隔
          </div>
        </template>
      </el-upload>
    </div>

    <!-- Datasets Table -->
    <div class="industrial-card section-block dataset-table-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><List /></el-icon> 已登记数据集
        </div>
        <div class="dataset-table-toolbar">
          <el-button size="small" @click="resetColumnWidths">恢复默认列宽</el-button>
          <el-button type="primary" size="small" :icon="Refresh" @click="fetchDatasets">刷新列表</el-button>
        </div>
      </div>

      <div class="dataset-table-wrap">
        <el-table
          ref="datasetTableRef"
          :data="datasetList"
          border
          stripe
          style="width: 100%"
          v-loading="loading"
          @header-dragend="handleColumnResize"
        >
          <template #empty>
            <AppEmptyState
              inline
              icon="dataset"
              title="暂无已登记数据集"
              description="在上方区域上传工业 CSV 文件即可建立数据集与初始基线版本。"
            />
          </template>
          <el-table-column
            prop="name"
            column-key="dataset_name"
            label="数据集名称"
            :width="columnWidths.dataset_name"
            :min-width="COLUMN_WIDTHS.dataset_name.min"
            resizable
            show-overflow-tooltip
          />
          <el-table-column
            prop="version_id"
            column-key="active_version"
            label="当前版本"
            :width="columnWidths.active_version"
            :min-width="COLUMN_WIDTHS.active_version.min"
            resizable
          >
            <template #default="{ row }">
              <el-tooltip :content="row.version_id || row.latest_version_id" placement="top">
                <span class="version-summary">{{ shortIdentifier(row.version_id || row.latest_version_id) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column
            prop="row_count"
            column-key="row_count"
            label="样本行数"
            :width="columnWidths.row_count"
            :min-width="COLUMN_WIDTHS.row_count.min"
            resizable
          />
          <el-table-column
            column-key="column_count"
            label="列规模"
            :width="columnWidths.column_count"
            :min-width="COLUMN_WIDTHS.column_count.min"
            resizable
          >
            <template #default="{ row }">
              {{ row.col_count || row.column_count }} 列
            </template>
          </el-table-column>
          <el-table-column
            prop="time_column"
            column-key="time_column"
            label="时间列"
            :width="columnWidths.time_column"
            :min-width="COLUMN_WIDTHS.time_column.min"
            resizable
          >
            <template #default="{ row }">
              <el-tag v-if="row.time_column" size="small" effect="plain">{{ row.time_column }}</el-tag>
              <el-tag v-else type="info" size="small" effect="plain">未指定</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            column-key="variable_config"
            label="变量配置"
            :width="columnWidths.variable_config"
            :min-width="COLUMN_WIDTHS.variable_config.min"
            resizable
          >
            <template #default="{ row }">
              <div class="variable-config-cell">
                <el-tag v-if="row.output_column" type="success" size="small" effect="plain">
                  输出: {{ row.output_column }}
                </el-tag>
                <el-tag v-if="row.input_columns?.length" type="info" size="small" effect="plain">
                  输入: {{ row.input_columns.join(', ') }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column
            column-key="actions"
            label="操作"
            :width="250"
            fixed="right"
            :resizable="false"
          >
            <template #default="{ row }">
              <div class="dataset-actions-cell">
                <el-button type="primary" link size="small" @click="handleSelectDataset(row)">查看详情</el-button>
                <el-button type="default" link size="small" @click="openConfigDialog(row)">列配置</el-button>
                <el-button type="danger" link size="small" @click="handleDelete(row.id)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- Column Config Dialog -->
    <el-dialog v-model="configDialogVisible" title="配置数据集列角色" width="500px">
      <el-form class="parameter-form-grid parameter-form-grid--single">
        <el-form-item label="时间戳列">
          <el-input v-model="configForm.time_column" placeholder="例如: timestamp" />
        </el-form-item>
        <el-form-item label="输入变量">
          <el-input v-model="configForm.input_columns_str" placeholder="多个以逗号分隔, 如: u1,u2" />
        </el-form-item>
        <el-form-item label="目标输出">
          <el-input v-model="configForm.output_column" placeholder="例如: y" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="configLoading" @click="saveConfig">保存配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from "vue";
import { Upload, List, UploadFilled, Refresh } from "@element-plus/icons-vue";
import PageHeader from "../components/common/PageHeader.vue";
import AppEmptyState from "../components/common/AppEmptyState.vue";
import { useDatasetStore } from "../stores/datasetStore";
import { getDatasets, deleteDataset, uploadDataset, configureDataset } from "../api/datasets";
import type { DatasetItem } from "../types/api";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import type { TableColumnCtx, TableInstance } from "element-plus";

type DatasetColumnKey =
  | "dataset_name"
  | "active_version"
  | "row_count"
  | "column_count"
  | "time_column"
  | "variable_config";

type DatasetColumnWidths = Record<DatasetColumnKey, number>;

const COLUMN_WIDTH_STORAGE_KEY = "indusopt.dataset-table.column-widths.v1";
const COLUMN_WIDTHS: Record<DatasetColumnKey, { default: number; min: number; max: number }> = {
  dataset_name: { default: 250, min: 180, max: 520 },
  active_version: { default: 150, min: 110, max: 260 },
  row_count: { default: 120, min: 95, max: 220 },
  column_count: { default: 105, min: 85, max: 180 },
  time_column: { default: 140, min: 100, max: 280 },
  variable_config: { default: 280, min: 180, max: 560 },
};
const DATASET_COLUMN_KEYS = Object.keys(COLUMN_WIDTHS) as DatasetColumnKey[];

const defaultColumnWidths = (): DatasetColumnWidths =>
  Object.fromEntries(
    DATASET_COLUMN_KEYS.map((key) => [key, COLUMN_WIDTHS[key].default]),
  ) as DatasetColumnWidths;

const loadColumnWidths = (): DatasetColumnWidths => {
  const widths = defaultColumnWidths();
  if (typeof window === "undefined") return widths;
  try {
    const raw = window.localStorage.getItem(COLUMN_WIDTH_STORAGE_KEY);
    if (!raw) return widths;
    const stored = JSON.parse(raw);
    if (!stored || typeof stored !== "object" || Array.isArray(stored)) return widths;
    for (const key of DATASET_COLUMN_KEYS) {
      const value = (stored as Record<string, unknown>)[key];
      const limits = COLUMN_WIDTHS[key];
      if (
        typeof value === "number"
        && Number.isFinite(value)
        && value >= limits.min
        && value <= limits.max
      ) {
        widths[key] = Math.round(value);
      }
    }
  } catch {
    return widths;
  }
  return widths;
};

const datasetStore = useDatasetStore();
const router = useRouter();

const loading = ref(false);
const datasetList = ref<DatasetItem[]>([]);
const datasetTableRef = ref<TableInstance>();
const columnWidths = reactive<DatasetColumnWidths>(loadColumnWidths());

const configDialogVisible = ref(false);
const configLoading = ref(false);
const currentDataset = ref<DatasetItem | null>(null);
const configForm = reactive({
  time_column: "timestamp",
  input_columns_str: "u1,u2",
  output_column: "y",
});

const shortIdentifier = (value?: string) => value ? `${value.slice(0, 8)}…` : "尚未生成";

const isDatasetColumnKey = (value: string | undefined): value is DatasetColumnKey =>
  Boolean(value && Object.prototype.hasOwnProperty.call(COLUMN_WIDTHS, value));

const persistColumnWidths = () => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      COLUMN_WIDTH_STORAGE_KEY,
      JSON.stringify(Object.fromEntries(DATASET_COLUMN_KEYS.map((key) => [key, columnWidths[key]]))),
    );
  } catch {
    // Column resizing remains usable when browser storage is unavailable.
  }
};

const handleColumnResize = (
  newWidth: number,
  _oldWidth: number,
  column: TableColumnCtx<Record<PropertyKey, unknown>>,
) => {
  if (!isDatasetColumnKey(column.columnKey)) return;
  const limits = COLUMN_WIDTHS[column.columnKey];
  const width = Math.min(limits.max, Math.max(limits.min, Math.round(newWidth)));
  column.width = width;
  column.realWidth = width;
  columnWidths[column.columnKey] = width;
  persistColumnWidths();
  nextTick(() => datasetTableRef.value?.doLayout());
};

const resetColumnWidths = () => {
  Object.assign(columnWidths, defaultColumnWidths());
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(COLUMN_WIDTH_STORAGE_KEY);
    } catch {
      // The in-memory reset still succeeds when browser storage is unavailable.
    }
  }
  nextTick(() => datasetTableRef.value?.doLayout());
};

const fetchDatasets = async () => {
  loading.value = true;
  try {
    const res = await getDatasets();
    datasetList.value = res.items || [];
    datasetStore.setDatasetsList(datasetList.value);
  } catch (err: any) {
    ElMessage.error(`获取数据集列表失败 [${err.code || 'ERR'}]: ${err.message}`);
  } finally {
    loading.value = false;
  }
};

const customUpload = async (options: any) => {
  try {
    const res = await uploadDataset(options.file, options.file.name);
    if (res.deduplicated) {
      ElMessage.info(`系统匹配到已存在的相同哈希文件，快速关联数据集: ${res.dataset.name}`);
    } else {
      ElMessage.success(`数据集 ${res.dataset.name} 真实上传并解析成功！`);
    }
    fetchDatasets();
  } catch (err: any) {
    ElMessage.error(`上传失败 [${err.code || 'ERR'}]: ${err.message}`);
  }
};

const handleSelectDataset = (row: DatasetItem) => {
  datasetStore.setActiveDataset(row);
  router.push(`/datasets/${row.id}`);
};

const openConfigDialog = (row: DatasetItem) => {
  currentDataset.value = row;
  configForm.time_column = row.time_column || "timestamp";
  configForm.input_columns_str = (row.input_columns || ["u1", "u2"]).join(",");
  configForm.output_column = row.output_column || "y";
  configDialogVisible.value = true;
};

const saveConfig = async () => {
  if (!currentDataset.value) return;
  configLoading.value = true;
  try {
    const inputCols = configForm.input_columns_str.split(",").map((s) => s.trim()).filter(Boolean);
    await configureDataset(currentDataset.value.id, {
      time_column: configForm.time_column,
      input_columns: inputCols,
      output_column: configForm.output_column,
    });
    ElMessage.success("列角色配置保存成功！");
    configDialogVisible.value = false;
    fetchDatasets();
  } catch (err: any) {
    ElMessage.error(`配置保存失败 [${err.code || 'ERR'}]: ${err.message}`);
  } finally {
    configLoading.value = false;
  }
};

const handleDelete = async (id: string) => {
  try {
    await deleteDataset(id);
    ElMessage.success("数据集删除成功");
    fetchDatasets();
  } catch (err: any) {
    ElMessage.error(`删除失败 [${err.code || 'ERR'}]: ${err.message}`);
  }
};

onMounted(() => {
  fetchDatasets();
});
</script>

<style scoped>
.datasets-view {
  padding: var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12);
  min-height: 100%;
}

.page-header {
  margin-bottom: 20px;
}

.subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.upload-area {
  width: 100%;
}

.dataset-table-card,
.dataset-table-wrap {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.dataset-table-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.variable-config-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.dataset-actions-cell {
  white-space: nowrap;
}

.datasets-view .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.version-summary {
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: help;
}
</style>
