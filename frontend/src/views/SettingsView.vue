<template>
  <div class="page-container settings-view">
    <PageHeader
      eyebrow="ENVIRONMENT / SETTINGS"
      title="系统设置"
      description="检查服务连接状态，管理 Agent 规划模型及本地/远程执行环境配置"
    />

    <div class="settings-layout">
      <!-- Theme Selection Card -->
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Sunny /></el-icon> 界面主题
          </div>
          <el-tag type="success" effect="plain">默认：Warm Light</el-tag>
        </div>
        <div class="theme-switch-row">
          <div class="theme-option" :class="{ 'is-selected': currentTheme === 'light' }" @click="setTheme('light')">
            <div class="theme-preview theme-preview--light">
              <span class="tp-sidebar"></span>
              <span class="tp-main"></span>
            </div>
            <div class="theme-info">
              <div class="theme-name">Warm Light（推荐）</div>
              <div class="theme-desc">柔暖明亮米白，现代 Agent 工作台</div>
            </div>
          </div>
          <div class="theme-option" :class="{ 'is-selected': currentTheme === 'dark' }" @click="setTheme('dark')">
            <div class="theme-preview theme-preview--dark">
              <span class="tp-sidebar"></span>
              <span class="tp-main"></span>
            </div>
            <div class="theme-info">
              <div class="theme-name">Warm Graphite</div>
              <div class="theme-desc">柔暖石墨暗色，弱光环境适用</div>
            </div>
          </div>
        </div>
      </div>

      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Connection /></el-icon> 服务连接状态
          </div>
          <el-button type="primary" size="small" icon="Refresh" :loading="systemStore.isChecking" @click="checkHealth">
            重新检测
          </el-button>
        </div>

        <el-descriptions border :column="2">
          <el-descriptions-item label="PostgreSQL 数据库">
            <el-tag :type="databaseTagType">{{ databaseStatus }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Redis 任务队列">
            <el-tag :type="queueTagType">{{ queueStatus }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="系统状态">
            <el-tag :type="systemTagType">{{ systemStatus }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="后端版本">{{ backendVersion }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Key /></el-icon> Agent 规划方式
          </div>
          <el-tag :type="agentConfigTagType" effect="plain">
            {{ agentConfigTag }}
          </el-tag>
        </div>

        <el-alert
          type="warning"
          title="运行时配置仅保存在当前后端进程"
          description="API Key 仅在点击保存时发送给后端，不写入浏览器存储，也不会被接口回显。服务重启后自动恢复部署环境变量。"
          :closable="false"
          show-icon
        />

        <dl class="config-list">
          <div>
            <dt>当前规划方式</dt>
            <dd>{{ planningMode }}</dd>
          </div>
          <div>
            <dt>配置来源</dt>
            <dd>{{ configSource }}</dd>
          </div>
          <div>
            <dt>API Key 状态</dt>
            <dd>{{ apiKeyStatus }}</dd>
          </div>
        </dl>

        <el-alert
          v-if="configLoadError"
          class="config-error"
          type="error"
          title="无法读取 Agent 配置"
          :description="configLoadError"
          :closable="false"
          show-icon
        />

        <el-form class="agent-config-form" label-position="top" @submit.prevent>
          <el-form-item label="模型服务类型">
            <el-select v-model="form.provider" @change="handleProviderChange">
              <el-option label="不使用大模型（确定性规则）" value="none" />
              <el-option label="OpenAI" value="openai" />
              <el-option label="DeepSeek" value="deepseek" />
              <el-option label="通义千问 / Qwen" value="qwen" />
              <el-option label="Ollama 本地模型" value="ollama" />
              <el-option label="其他 OpenAI 兼容服务" value="custom" />
            </el-select>
          </el-form-item>

          <el-form-item label="模型名称">
            <el-input
              v-model="form.model"
              :disabled="modelDisabled"
              placeholder="请填写当前账户或部署可用的模型名称"
            />
          </el-form-item>

          <el-form-item class="form-field-wide" label="OpenAI 兼容接口地址">
            <el-input
              v-model="form.baseUrl"
              :disabled="modelDisabled"
              placeholder="https://example.com/v1"
            />
          </el-form-item>

          <el-form-item class="form-field-wide" label="API Key">
            <el-input
              v-model="apiKey"
              type="password"
              show-password
              autocomplete="new-password"
              :disabled="modelDisabled || clearApiKey"
              :placeholder="apiKeyPlaceholder"
            />
            <div class="field-help">
              空白表示保留后端已有密钥；本地无鉴权服务可不填。
            </div>
          </el-form-item>

          <el-form-item label="请求超时">
            <div class="number-with-unit">
              <el-input-number
                v-model="form.timeoutSeconds"
                :disabled="modelDisabled"
                :min="1"
                :max="600"
                :step="5"
                controls-position="right"
              />
              <span class="input-unit">秒</span>
            </div>
          </el-form-item>

          <el-form-item v-if="agentConfig?.has_api_key" label="密钥处理">
            <el-checkbox v-model="clearApiKey" :disabled="modelDisabled">
              保存时清除后端当前密钥
            </el-checkbox>
          </el-form-item>
        </el-form>

        <div class="config-actions">
          <el-button
            type="primary"
            :loading="savingConfig"
            :disabled="loadingConfig"
            @click="saveAgentConfig"
          >
            保存并立即生效
          </el-button>
          <el-button
            :loading="testingConnection"
            :disabled="!agentConfig?.enabled || savingConfig"
            @click="testConnection"
          >
            测试当前连接
          </el-button>
          <el-button :disabled="agentConfig?.source !== 'runtime'" @click="restoreEnvironment">
            恢复部署配置
          </el-button>
        </div>

        <el-collapse class="config-help">
          <el-collapse-item title="配置生效范围" name="llm-runtime-scope">
            <p>
              保存后，Agent 计划与报告结论会共用该模型服务。大模型只能提出计划，
              仍需通过工具白名单、依赖关系与人工确认校验；连接失败时自动回退到确定性规则。
              当前项目尚无管理员登录与权限系统，请只在受信任的本地或内网环境中开放本页。
            </p>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Connection, Refresh, Key, Sunny } from "@element-plus/icons-vue";
import PageHeader from "../components/common/PageHeader.vue";
import { useSystemStore } from "../stores/systemStore";
import { getSystemInfo } from "../api/health";
import {
  getAgentLlmConfig,
  resetAgentLlmConfig,
  testAgentLlmConnection,
  updateAgentLlmConfig,
} from "../api/agentSettings";
import type { AgentLlmConfigData } from "../types/api";
import { ElMessage, ElMessageBox } from "element-plus";

const currentTheme = ref<'light' | 'dark'>('light');

function initTheme() {
  const saved = localStorage.getItem('indusopt_theme');
  if (saved === 'dark') {
    currentTheme.value = 'dark';
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    currentTheme.value = 'light';
    document.documentElement.removeAttribute('data-theme');
  }
}

function setTheme(theme: 'light' | 'dark') {
  currentTheme.value = theme;
  localStorage.setItem('indusopt_theme', theme);
  if (theme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
    ElMessage.success('已切换至 Warm Graphite 深色模式');
  } else {
    document.documentElement.removeAttribute('data-theme');
    ElMessage.success('已切换至 Warm Light 浅色模式');
  }
}

const systemStore = useSystemStore();
const agentConfig = ref<AgentLlmConfigData | null>(null);
const loadingConfig = ref(false);
const savingConfig = ref(false);
const testingConnection = ref(false);
const configLoadError = ref("");
const apiKey = ref("");
const clearApiKey = ref(false);
const form = reactive({
  provider: "none",
  baseUrl: "",
  model: "",
  timeoutSeconds: 60,
});

const systemStatus = computed(() => ({
  connecting: "正在检测",
  ready: "系统就绪",
  offline: "服务离线",
}[systemStore.status]));
const databaseStatus = computed(() => systemStore.readiness?.database === "connected" ? "已连接" : systemStore.status === "connecting" ? "等待检测" : "未连接");
const queueStatus = computed(() => systemStore.readiness?.queue === "connected" ? "已连接" : systemStore.status === "connecting" ? "等待检测" : "未连接");
const databaseTagType = computed(() => systemStore.status === "ready" ? "success" : "danger");
const queueTagType = computed(() => systemStore.status === "ready" ? "success" : "danger");
const systemTagType = computed(() => systemStore.status === "ready" ? "success" : systemStore.status === "offline" ? "danger" : "warning");
const backendVersion = computed(() => systemStore.systemInfo?.version ? `v${systemStore.systemInfo.version}` : "等待读取");
const modelDisabled = computed(() => form.provider === "none");
const agentConfigTag = computed(() => {
  if (loadingConfig.value) return "正在读取";
  if (!agentConfig.value?.enabled) return "确定性规则";
  return agentConfig.value.source === "runtime" ? "运行时配置已生效" : "部署配置已生效";
});
const agentConfigTagType = computed(() => agentConfig.value?.enabled ? "success" : "info");
const planningMode = computed(() => agentConfig.value?.enabled
  ? "大模型提案 + 确定性规则回退"
  : "确定性规则编排");
const configSource = computed(() => agentConfig.value?.source === "runtime"
  ? "本页运行时配置"
  : "后端部署环境变量");
const apiKeyStatus = computed(() => agentConfig.value?.has_api_key
  ? "已配置（不回显）"
  : "未配置");
const apiKeyPlaceholder = computed(() => agentConfig.value?.has_api_key
  ? "已配置；留空则保留原密钥"
  : "输入 API Key；本地无鉴权服务可留空");

const providerDefaults: Record<string, { baseUrl: string; model: string }> = {
  deepseek: {
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-flash",
  },
};

const checkHealth = async () => {
  const status = await systemStore.checkHealth();
  if (status === "ready") {
    ElMessage.success("系统健康检查通过：PostgreSQL 与 Redis 均就绪");
  } else {
    ElMessage.error("服务离线：无法连接后端，或数据库、任务队列尚未就绪");
  }
};

const applyConfig = (config: AgentLlmConfigData) => {
  agentConfig.value = config;
  configLoadError.value = "";
  form.provider = config.enabled ? config.provider : "none";
  form.baseUrl = config.base_url;
  form.model = config.model;
  form.timeoutSeconds = config.timeout_seconds;
  apiKey.value = "";
  clearApiKey.value = false;
};

const loadAgentConfig = async () => {
  loadingConfig.value = true;
  configLoadError.value = "";
  try {
    applyConfig(await getAgentLlmConfig());
  } catch (error) {
    configLoadError.value = error instanceof Error ? error.message : "请检查后端服务。";
  } finally {
    loadingConfig.value = false;
  }
};

const handleProviderChange = () => {
  if (form.provider === "none") {
    form.baseUrl = "";
    form.model = "";
    apiKey.value = "";
    clearApiKey.value = false;
    return;
  }

  const defaults = providerDefaults[form.provider];
  if (defaults) {
    form.baseUrl = defaults.baseUrl;
    form.model = defaults.model;
  }
};

const saveAgentConfig = async () => {
  if (!modelDisabled.value && (!form.baseUrl.trim() || !form.model.trim())) {
    ElMessage.error("启用大模型时必须填写接口地址和模型名称");
    return;
  }

  savingConfig.value = true;
  try {
    const config = await updateAgentLlmConfig({
      provider: form.provider,
      base_url: form.baseUrl.trim(),
      model: form.model.trim(),
      api_key: apiKey.value.trim() || null,
      clear_api_key: clearApiKey.value,
      timeout_seconds: form.timeoutSeconds,
    });
    applyConfig(config);
    ElMessage.success(config.enabled
      ? "Agent 模型配置已生效"
      : "已切换为确定性规则编排");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Agent 配置保存失败");
  } finally {
    savingConfig.value = false;
  }
};

const testConnection = async () => {
  testingConnection.value = true;
  try {
    const result = await testAgentLlmConnection();
    ElMessage.success(`${result.message}耗时 ${Math.round(result.latency_ms)} ms`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "模型服务连接失败");
  } finally {
    testingConnection.value = false;
  }
};

const restoreEnvironment = async () => {
  try {
    await ElMessageBox.confirm(
      "当前运行时配置和内存中的 API Key 将被清除，并恢复后端部署配置。",
      "恢复部署配置",
      { type: "warning", confirmButtonText: "确认恢复", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }

  try {
    applyConfig(await resetAgentLlmConfig());
    ElMessage.success("已恢复后端部署配置");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "恢复部署配置失败");
  }
};

onMounted(async () => {
  initTheme();
  await Promise.all([
    getSystemInfo()
      .then((info) => systemStore.setSystemInfo(info))
      .catch(() => {
        ElMessage.error("获取系统信息失败");
        return undefined;
      }),
    loadAgentConfig(),
  ]);
});
</script>

<style scoped>
.theme-switch-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 12px;
}

.theme-option {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.theme-option:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
}

.theme-option.is-selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.theme-preview {
  width: 44px;
  height: 32px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-default);
  display: flex;
  overflow: hidden;
  flex-shrink: 0;
}

.theme-preview--light .tp-sidebar {
  width: 14px;
  background: #F8F9F6;
  border-right: 1px solid #ECEEE9;
}

.theme-preview--light .tp-main {
  flex: 1;
  background: #FFFFFF;
}

.theme-preview--dark .tp-sidebar {
  width: 14px;
  background: #0E0F0D;
  border-right: 1px solid rgba(242,240,232,0.06);
}

.theme-preview--dark .tp-main {
  flex: 1;
  background: #171815;
}

.theme-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-name {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.theme-desc {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}
.settings-view {
  min-height: 100%;
}

.settings-layout {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.config-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.config-list > div {
  padding: 14px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}

.config-list dt {
  margin-bottom: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.config-list dd {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.6;
}

.config-error {
  margin-top: 16px;
}

.agent-config-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
  row-gap: 2px;
  margin-top: 20px;
}

.agent-config-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.agent-config-form :deep(.el-select),
.agent-config-form :deep(.el-input),
.agent-config-form :deep(.el-input-number) {
  width: 100%;
}

.form-field-wide {
  grid-column: 1 / -1;
}

.field-help {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.input-unit {
  color: var(--text-secondary);
  font-size: 13px;
}

.number-with-unit {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.number-with-unit :deep(.el-input-number) {
  flex: 1;
  width: auto;
}

.config-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding-top: 2px;
}

.config-help {
  margin-top: 16px;
}

.config-help p,
.config-help ul {
  color: var(--text-secondary);
  font-size: 13px;
}

.config-help ul {
  margin: 10px 0 0 20px;
}

.config-help li + li {
  margin-top: 6px;
}

.config-help code {
  font-family: var(--font-mono);
  color: var(--color-primary);
}

@media (max-width: 900px) {
  .config-list,
  .agent-config-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .form-field-wide {
    grid-column: auto;
  }
}
</style>
