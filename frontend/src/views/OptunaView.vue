<template>
  <div class="page-container optuna-view">
    <PageHeader
      eyebrow="CLOSED-LOOP OPTIMIZATION / OPTUNA"
      title="闭环参数自动寻优"
      description="通过滚动验证调整质量门控和 ARX / FIR 结构；可选实验模式比较全量训练与优选片段，保留验证证据和试验轨迹"
    />

    <div class="optuna-layout">
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><RefreshRight /></el-icon> 闭环寻优任务控制台
          </div>
        </div>

        <el-form :model="form" class="parameter-form-grid">
          <el-form-item label="数据版本 ID">
            <el-input v-model="form.version_id" placeholder="version_id" />
          </el-form-item>
          <el-form-item label="输入变量">
            <el-input v-model="inputColumnsText" placeholder="u1,u2" />
          </el-form-item>
          <el-form-item label="输出变量">
            <el-input v-model="form.output_column" placeholder="y" />
          </el-form-item>
          <el-form-item label="Trial 次数">
            <el-input-number v-model="form.max_trials" :min="1" :max="500" :step="5" />
          </el-form-item>
          <el-form-item label="随机种子">
            <el-input-number v-model="form.random_seed" :min="0" :max="99999" />
          </el-form-item>
          <el-form-item label="搜索方案">
            <el-select v-model="searchPolicy">
              <el-option label="现有默认方案" value="established" />
              <el-option label="实验：全量对照与时间覆盖" value="paired_coverage" />
              <el-option label="实验：ARX 历史扰动补偿" value="disturbance_aware" />
              <el-option label="实验：全折验证与质量验收" value="validation_guarded" />
            </el-select>
            <span v-if="searchPolicy !== 'established'">仍需验证泛化效果，耗时增加</span>
          </el-form-item>
          <el-form-item class="parameter-form-actions">
            <el-button
              type="primary"
              :loading="isSearching"
              icon="VideoPlay"
              @click="handleStart"
            >
              开始闭环寻优
            </el-button>
          </el-form-item>
        </el-form>

        <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
          <template #title>寻优失败：{{ errorMessage }}</template>
        </el-alert>
        <el-alert v-if="isSearching" type="info" :closable="false" show-icon class="alert-gap">
          <template #title>
            正在执行质量门控、数据策略对照、模型结构扫描和滚动自由仿真验证，请稍候
          </template>
        </el-alert>
      </div>

      <template v-if="status">
        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Trophy /></el-icon> 寻优结论
            </div>
            <el-tag v-if="status.warm_started_from" type="warning">
              已从历史相似工况热启动
            </el-tag>
            <el-tag v-else type="info">冷启动（策略记忆库中无相似工况）</el-tag>
          </div>

          <el-descriptions border :column="4" size="small">
            <el-descriptions-item label="最佳 Trial">
              #{{ status.best_trial_id ?? "—" }}
            </el-descriptions-item>
            <el-descriptions-item label="最优目标值">
              <span class="fit-val">{{ num(status.best_value) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="有效 / 剪枝 / 失败">
              {{ stat("completed_trials") }} / {{ stat("pruned_trials") }} /
              {{ stat("failed_trials") }}
            </el-descriptions-item>
            <el-descriptions-item label="单 Trial 平均耗时">
              {{ num(status.statistics.mean_trial_ms) }} ms
            </el-descriptions-item>
            <el-descriptions-item label="模型拟合次数">
              {{ stat("structure_evaluations") }}
            </el-descriptions-item>
            <el-descriptions-item label="区间优选执行次数">
              {{ stat("selection_computations") }}
            </el-descriptions-item>
            <el-descriptions-item label="昂贵环节摊薄倍数">
              <span class="fit-val">{{ num(status.statistics.evaluations_per_selection) }}×</span>
            </el-descriptions-item>
            <el-descriptions-item label="血缘缓存命中率">
              {{ pct(status.statistics.hit_rate) }}
            </el-descriptions-item>
          </el-descriptions>

          <el-alert v-if="validationQuality" :type="validationQuality === 'passed' ? 'info' : 'warning'"
            :closable="false" show-icon class="alert-gap">
            <template #title>{{ qualityMessage }}</template>
          </el-alert>
          <p v-if="status.best_params.training_policy" class="alert-gap">
            采用数据策略：{{ status.best_params.training_policy === 'full_train' ? '全量有效训练行' : '优选片段' }}（依据滚动验证选择）
          </p>

          <el-alert type="info" :closable="false" class="alert-gap">
            <template #title>
              摊薄倍数 = 模型拟合次数 / 区间优选执行次数。优选是流水线中最昂贵的环节，分级搜索让每次优选服务于整组模型结构评估。血缘缓存命中率在扁平采样下通常很低（实测约
              1.7%），真正的节省来自分级搜索本身。
            </template>
          </el-alert>
        </div>

        <div class="charts-grid">
          <div class="industrial-card">
            <div class="industrial-card-header">
              <div class="industrial-card-title">
                <el-icon><TrendCharts /></el-icon> 历史最佳目标值收敛曲线
              </div>
            </div>
            <ChartContainer :options="convergenceOptions" height="320px" />
          </div>

          <div class="industrial-card">
            <div class="industrial-card-header">
              <div class="industrial-card-title">
                <el-icon><DataBoard /></el-icon> 超参数重要性（秩相关，归一化）
              </div>
            </div>
            <ChartContainer :options="importanceOptions" height="320px" />
          </div>
        </div>

        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Setting /></el-icon> 最优参数组合
            </div>
          </div>
          <el-descriptions border :column="3" size="small">
            <el-descriptions-item
              v-for="(value, key) in status.best_params"
              :key="key"
              :label="String(key)"
            >
              <span class="code-inline">{{ formatParam(value) }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <div class="footer-actions">
            <el-button type="success" icon="Document" @click="$router.push('/deliverables')">
              生成图文报告并导出优选数据集 →
            </el-button>
          </div>
        </div>

        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><List /></el-icon> 全部试验记录（含失败与剪枝）
            </div>
          </div>
          <el-table :data="status.trials" stripe height="360" style="width: 100%">
            <el-table-column prop="trial_id" label="Trial" width="90" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="stateType(row.state)" size="small">{{ stateLabel(row.state) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="目标值" width="130">
              <template #default="{ row }">{{ num(row.value) }}</template>
            </el-table-column>
            <el-table-column label="失败原因" width="220">
              <template #default="{ row }">{{ row.error_code || "—" }}</template>
            </el-table-column>
            <el-table-column label="参数">
              <template #default="{ row }">
                <span class="code-inline params-cell">{{ compactParams(row.params) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import {
  DataBoard,
  Document,
  List,
  RefreshRight,
  Setting,
  TrendCharts,
  Trophy,
  VideoPlay,
} from "@element-plus/icons-vue";
import PageHeader from "../components/common/PageHeader.vue";
import ChartContainer from "../components/ChartContainer.vue";
import { getOptunaStatus, startOptunaStudy } from "../api/modeling";
import type { OptunaStartRequest, OptunaStatusResponse } from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage } from "element-plus";

const STATE_LABELS: Record<string, string> = {
  complete: "成功",
  pruned: "剪枝",
  failed: "失败",
  running: "运行中",
  queued: "排队",
};

const isSearching = ref(false);
const searchPolicy = ref<"established" | "paired_coverage" | "disturbance_aware" | "validation_guarded">("established");
const status = ref<OptunaStatusResponse | null>(null);
const errorMessage = ref("");
const inputColumnsText = ref("u1,u2");
const validationQuality = computed(() => status.value?.trials
  .find((trial) => trial.trial_id === status.value?.best_trial_id)
  ?.metrics?.validation_acceptance?.status as string | undefined);
const qualityMessage = computed(() => {
  if (validationQuality.value === "insufficient") {
    return "模型效果不足：存在自由仿真 FIT 非正或未优于持值预测的验证段。请补充激励或调整模型后复核。";
  }
  if (validationQuality.value === "inconclusive") return "验证对照证据不足，模型效果尚不能确认。";
  return "已通过本次滚动验证的效果检查，仍需独立测试和现场工况验证。";
});

const form = reactive<OptunaStartRequest>({
  version_id: "",
  input_columns: [],
  output_column: "y",
  max_trials: 30,
  random_seed: 42,
});

const handleStart = async () => {
  errorMessage.value = "";
  if (!form.version_id) {
    errorMessage.value = "请先填写数据版本 ID。";
    return;
  }
  form.input_columns = inputColumnsText.value
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (!form.input_columns.length) {
    errorMessage.value = "请至少指定一个输入变量。";
    return;
  }

  isSearching.value = true;
  status.value = null;
  try {
    const started = await startOptunaStudy({ ...form,
      optimization_policy: searchPolicy.value });
    // No mock convergence loop: the curve shown must come from real trials.
    status.value = await getOptunaStatus(started.study_id);
    if (status.value.best_trial_id == null || status.value.best_value == null) {
      errorMessage.value = "本次寻优未得到可用模型，请查看试验失败原因并调整数据或参数。";
      ElMessage.warning(errorMessage.value);
    } else if (validationQuality.value && validationQuality.value !== "passed") {
      ElMessage.warning(`寻优已完成，模型效果仍需复核：${num(status.value.best_value)}`);
    } else {
      ElMessage.success(`闭环寻优完成：最优目标值 ${num(status.value.best_value)}`);
    }
  } catch (err) {
    status.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    isSearching.value = false;
  }
};

const stat = (key: keyof NonNullable<OptunaStatusResponse["statistics"]>) => {
  const value = status.value?.statistics?.[key];
  return value === undefined ? "—" : value;
};

const convergenceOptions = computed(() => {
  if (!status.value) return {};
  const curve = status.value.best_curve;
  return {
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "4%", bottom: "10%", containLabel: true },
    xAxis: { type: "category", data: curve.map((_, index) => `#${index}`) },
    yAxis: { type: "value", name: "目标值", scale: true },
    series: [
      {
        name: "历史最佳目标值",
        type: "line",
        step: "end",
        color: "#6E9B69",
        showSymbol: false,
        data: curve,
      },
      {
        name: "各 Trial 目标值",
        type: "scatter",
        color: "#B8746E",
        symbolSize: 6,
        data: status.value.trials.map((trial) => trial.value),
      },
    ],
  };
});

const importanceOptions = computed(() => {
  if (!status.value) return {};
  const entries = Object.entries(status.value.param_importances).sort((a, b) => b[1] - a[1]);
  return {
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "6%", bottom: "6%", containLabel: true },
    xAxis: { type: "value", name: "相对重要性" },
    yAxis: { type: "category", data: entries.map(([name]) => name).reverse() },
    series: [
      {
        type: "bar",
        color: "#7995A8",
        data: entries.map(([, value]) => value).reverse(),
      },
    ],
  };
});

const stateLabel = (state: string) => STATE_LABELS[state] ?? state;

const stateType = (state: string) =>
  state === "complete" ? "success" : state === "failed" ? "danger" : "warning";

const formatParam = (value: unknown) =>
  typeof value === "number" ? num(value) : String(value);

const compactParams = (params: Record<string, unknown>) =>
  Object.entries(params)
    .map(([key, value]) => `${key}=${formatParam(value)}`)
    .join("  ");

const num = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(4);
};

const pct = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${(value * 100).toFixed(1)}%`;
</script>

<style scoped>
.optuna-view {
  min-height: 100%;
}

.optuna-layout {
  display: flex;
  flex-direction: column;
  gap: var(--section-gap-md);
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 20px;
}

.fit-val {
  font-weight: 600;
  color: var(--color-primary);
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.alert-gap {
  margin-top: 12px;
}

.footer-actions {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.params-cell {
  font-size: 12px;
  word-break: break-all;
}
</style>
