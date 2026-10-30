<template>
  <div class="page-container simulation-view">
    <PageHeader
      eyebrow="GROUND TRUTH / SIMULATION"
      title="仿真测试集生成器"
      description="构造带有精确物理真值的工业时序 S1–S6 测试场景，用于验证时滞与 ARX 辨识算法"
    />

    <div class="simulation-layout">
      <!-- Parameters Form Card -->
      <div class="industrial-card form-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Setting /></el-icon> 仿真场景与参数配置
          </div>
        </div>

        <el-form :model="form" class="parameter-form-grid">
          <el-form-item label="仿真场景" class="form-span-full">
            <el-radio-group v-model="form.scenario" size="default" @change="handleScenarioChange">
              <el-radio-button label="S1">S1 基础单输入 (基线可信度)</el-radio-button>
              <el-radio-button label="S2">S2 多输入不同滞后</el-radio-button>
              <el-radio-button label="S3">S3 长稳态短动态</el-radio-button>
              <el-radio-button label="S4">S4 强噪声与异常污染</el-radio-button>
              <el-radio-button label="S5">S5 高共线性输入</el-radio-button>
              <el-radio-button label="S6">S6 异构激励压力测试</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="数据集名称" class="form-span-2">
            <el-input v-model="form.dataset_name" placeholder="请输入数据集标识名" @input="handleDatasetNameInput" />
          </el-form-item>

          <el-form-item label="采样步数 N">
            <el-input-number v-model="form.num_samples" :min="500" :max="50000" :step="500" />
          </el-form-item>

          <el-form-item label="输入变量数量">
            <div class="input-count-field">
              <el-select
                v-model="form.input_count"
                clearable
                :disabled="isFixedInputScenario"
                :placeholder="inputCountPlaceholder"
                data-test="input-count"
              >
                <el-option
                  v-for="count in supportedInputCounts"
                  :key="count"
                  :label="`${count} 个输入变量`"
                  :value="count"
                />
              </el-select>
              <span class="input-count-help">
                {{ isFixedInputScenario ? "S1 固定为 1 个输入变量" : "可选；留空时使用系统默认值（2 个输入变量）" }}
              </span>
            </div>
          </el-form-item>

          <el-form-item label="噪声水平 σ" class="form-span-2">
            <el-slider v-model="form.noise_level" :min="0" :max="1" :step="0.05" show-input />
          </el-form-item>

          <el-form-item label="随机种子 Seed">
            <el-input-number
              v-model="form.seed"
              :min="0"
              :max="2147483647"
              :step="1"
              data-test="simulation-seed"
            />
          </el-form-item>

          <el-form-item class="parameter-form-actions">
            <el-button type="primary" :loading="loading" icon="VideoPlay" @click="handleGenerate">
              生成仿真数据集并解析真值
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- Result & Ground Truth Card -->
      <div class="industrial-card result-card" v-if="result">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Check /></el-icon> 仿真结果与真值
          </div>
          <el-tag type="success">可复现实验基线集</el-tag>
        </div>

        <el-descriptions :column="2" border>
          <el-descriptions-item label="数据集 ID">
            <span class="code-inline">{{ result.dataset_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="初始版本">
            <span class="code-inline">{{ result.version_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="样本行数">{{ result.num_rows }} 行</el-descriptions-item>
          <el-descriptions-item label="物理字段">{{ result.columns.join(", ") }}</el-descriptions-item>
          <el-descriptions-item label="系统类型">{{ result.ground_truth.system_type }}</el-descriptions-item>
          <el-descriptions-item label="真值阶数">na={{ result.ground_truth.true_na }}, nb=[{{ result.ground_truth.true_nb.join(",") }}]</el-descriptions-item>
          <el-descriptions-item label="真实滞后 d_true">d_true = [{{ result.ground_truth.true_delays.join(", ") }}] 步</el-descriptions-item>
          <el-descriptions-item label="噪声水平 σ">{{ result.ground_truth.noise_level }}</el-descriptions-item>
        </el-descriptions>

        <!-- Ground Truth Parameters Details -->
        <div class="gt-params-box">
          <h4>系统方程真值参数</h4>
          <p class="code-inline">
            y(t) = -a₁ y(t-1) - a₂ y(t-2) + ∑ b_{i,j} u_i(t - d_i - j) + e(t)
          </p>
          <pre class="params-pre">{{ JSON.stringify(result.ground_truth.true_parameters, null, 2) }}</pre>
        </div>

        <div style="margin-top: 16px; display: flex; gap: 12px; flex-wrap: wrap">
          <el-button type="success" icon="Download" @click="handleDownloadCSV">
            下载仿真 CSV 文件
          </el-button>
          <el-button type="primary" icon="Cpu" @click="handleGoToARX">
            前往 ARX 系统辨识校验基线 ->
          </el-button>
          <el-button type="info" text icon="View" @click="$router.push(`/datasets/${result.dataset_id}`)">
            查看质量诊断
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive } from "vue";
import { Setting, Check, Download, Cpu, View } from "@element-plus/icons-vue";
import PageHeader from "../components/common/PageHeader.vue";
import { generateSimulationDataset } from "../api/simulation";
import type { SimulationGenerateRequest, SimulationGenerateResponse } from "../types/api";
import { useDatasetStore } from "../stores/datasetStore";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

const datasetStore = useDatasetStore();
const router = useRouter();
const loading = ref(false);
const result = ref<SimulationGenerateResponse | null>(null);

type SimulationScenario = SimulationGenerateRequest["scenario"];

const SCENARIO_DEFAULT_DATASET_NAMES: Record<SimulationScenario, string> = {
  S1: "S1_Single_Input_Baseline",
  S2: "S2_Multi_Input_Delay",
  S3: "S3_Long_Steady_State",
  S4: "S4_Noise_And_Anomaly",
  S5: "S5_High_Collinearity",
  S6: "S6_Heterogeneous_Excitation",
};

const initialScenario: SimulationScenario = "S1";
const isDatasetNameDirty = ref(false);
const supportedInputCounts = [2, 3, 4] as const;

const form = reactive<SimulationGenerateRequest>({
  scenario: initialScenario,
  dataset_name: SCENARIO_DEFAULT_DATASET_NAMES[initialScenario],
  num_samples: 1500,
  noise_level: 0,
  seed: 42,
});

const isFixedInputScenario = computed(() => form.scenario === "S1");
const inputCountPlaceholder = computed(() =>
  isFixedInputScenario.value ? "该场景固定为 1" : "使用系统默认值"
);

const isSimulationScenario = (value: unknown): value is SimulationScenario =>
  typeof value === "string" && Object.prototype.hasOwnProperty.call(SCENARIO_DEFAULT_DATASET_NAMES, value);

const handleScenarioChange = (value: unknown) => {
  if (!isSimulationScenario(value)) return;
  form.scenario = value;
  if (value === "S1") {
    form.input_count = undefined;
  }
  if (!isDatasetNameDirty.value) {
    form.dataset_name = SCENARIO_DEFAULT_DATASET_NAMES[value];
  }
};

const handleDatasetNameInput = () => {
  isDatasetNameDirty.value = true;
};

const handleGenerate = async () => {
  const selectedInputCount = form.input_count;
  if (
    !isFixedInputScenario.value &&
    selectedInputCount != null &&
    !supportedInputCounts.some((count) => count === selectedInputCount)
  ) {
    ElMessage.error("输入变量数量必须为 2、3 或 4");
    return;
  }

  const { input_count: _inputCount, ...basePayload } = form;
  const payload: SimulationGenerateRequest = {
    ...basePayload,
    ...(!isFixedInputScenario.value && selectedInputCount != null
      ? { input_count: selectedInputCount }
      : {}),
  };

  loading.value = true;
  try {
    const res = await generateSimulationDataset(payload);
    result.value = res;
    datasetStore.setActiveDataset({
      id: res.dataset_id,
      name: res.dataset_name,
      version_id: res.version_id,
      file_size_bytes: 0,
      row_count: res.num_rows,
      col_count: res.num_cols,
      created_at: new Date().toISOString(),
      time_column: "timestamp",
      input_columns: res.columns.filter((c) => c.startsWith("u")),
      output_column: "y",
    });
    ElMessage.success(`仿真数据集 ${res.dataset_name} 真实生成成功！`);
  } catch (err: any) {
    ElMessage.error(`生成失败 [${err.code || 'ERR'}]: ${err.message}`);
  } finally {
    loading.value = false;
  }
};

const handleDownloadCSV = () => {
  if (!result.value?.download_url) return;
  window.open(result.value.download_url, "_blank", "noopener");
};

const handleGoToARX = () => {
  router.push("/modeling/arx");
};
</script>

<style scoped>
.simulation-view {
  min-height: 100%;
}

.simulation-layout {
  display: flex;
  flex-direction: column;
  gap: var(--section-gap-md);
}

.simulation-view .industrial-card-title {
  font-family: var(--font-sans);
  letter-spacing: normal;
  text-transform: none;
}

.input-count-field {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 6px;
}

.input-count-help {
  color: var(--text-tertiary);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 400;
  letter-spacing: normal;
  line-height: 1.4;
}

.gt-params-box {
  margin-top: 16px;
  background: var(--surface-1);
  padding: 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
}

.gt-params-box h4 {
  font-size: 13px;
  margin-bottom: 6px;
  color: var(--text-primary);
}

.params-pre {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  margin-top: 6px;
  background: var(--surface-2);
  padding: 8px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-subtle);
}
</style>
