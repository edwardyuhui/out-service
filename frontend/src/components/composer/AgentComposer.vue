<template>
  <div ref="agentComposerRef" class="agent-composer" :class="{ 'is-focused': isFocused, 'has-content': message.trim().length > 0, 'is-submitting': isSubmitting }">
    <div class="composer-body">
      <!-- Attached Dataset Pill (if any) -->
      <div v-if="attachedDataset" class="composer-attachments">
        <div class="attachment-chip">
          <svg class="attachment-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
          </svg>
          <span class="attachment-name">{{ attachedDataset.name }}</span>
          <span class="attachment-version" v-if="selectedVersion" :title="selectedVersion.id">
            {{ versionDisplayName(selectedVersion) }} ({{ shortIdentifier(selectedVersion.id) }})
          </span>
          <button
            type="button"
            class="attachment-remove"
            title="移除附件"
            aria-label="移除数据附件"
            :disabled="isSubmitting"
            @click="detachDataset"
          >
            ✕
          </button>
        </div>
      </div>

      <div v-if="attachedDataset" class="composer-version-selector">
        <VersionLineagePicker
          :key="attachedDataset.id"
          :dataset-name="attachedDataset.name"
          :versions="versions"
          :selected-version-id="selectedVersionId"
          :loading="versionsLoading"
          context-label="选择本次 Agent 任务的起始版本"
          eligible-label="可选为任务起点"
          selected-badge-label="本次任务起点"
          :is-eligible="isVersionSelectable"
          :disabled-reason="versionDisabledReason"
          empty-state-text="暂无可选择的版本"
          placeholder="请选择任务起始版本"
          @select="selectVersion"
        />
        <div v-if="versionsError" class="composer-version-error" role="alert">
          {{ versionsError }}
          <button type="button" :disabled="isSubmitting || versionsLoading" @click="loadVersions()">重新加载</button>
        </div>
      </div>

      <!-- Main Input Textarea -->
      <textarea
        ref="textareaRef"
        v-model="message"
        class="composer-textarea"
        :placeholder="placeholder"
        :rows="rows"
        :disabled="isSubmitting"
        @focus="isFocused = true"
        @blur="isFocused = false"
        @keydown.enter.exact.prevent="handleSubmit"
        @input="autoResize"
      />

      <!-- Action Footer -->
      <div class="composer-footer">
        <div class="composer-footer__left">
          <!-- Dataset Attachment Button -->
          <button
            type="button"
            class="composer-btn composer-btn--dataset"
            :class="{ 'is-active': showDatasetPicker }"
            title="选择要分析的数据集"
            aria-label="挂载数据集"
            :disabled="isSubmitting"
            @click="showDatasetPicker = !showDatasetPicker"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
            <span>{{ attachedDataset ? '更换数据' : '挂载数据' }}</span>
          </button>
        </div>

        <div class="composer-footer__right">
          <span class="composer-hint">
            <span>↵</span> 发送 · <span>{{ isMac ? '⇧↵' : 'Shift+↵' }}</span> 换行
          </span>

          <!-- Send / Stop Button -->
          <button
            type="button"
            class="composer-submit"
            :class="{ 'is-ready': canSubmit, 'is-submitting': isSubmitting }"
            :disabled="!canSubmit"
            :title="canSubmit ? '提交任务' : '请输入分析目标'"
            aria-label="提交任务"
            @click="handleSubmit"
          >
            <!-- Spinner when submitting -->
            <svg v-if="isSubmitting" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/>
              <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
            </svg>
            <!-- Up arrow / send icon -->
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="m5 12 7-7 7 7"/>
              <path d="M12 19V5"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Dataset Picker Dropdown -->
    <div
      v-if="showDatasetPicker"
      v-click-outside="() => (showDatasetPicker = false)"
      class="dataset-picker"
      :class="{ 'is-positioned': pickerPositioned }"
      :style="pickerStyle"
    >
      <div class="dataset-picker__header">
        <span class="label">选择挂载数据集</span>
        <input
          ref="pickerInputRef"
          v-model="datasetSearch"
          type="text"
          class="dataset-picker__search"
          placeholder="搜索数据集名称…"
        />
      </div>
      <div class="dataset-picker__list">
        <button
          v-for="ds in filteredDatasets"
          :key="ds.id"
          type="button"
          class="dataset-picker__item"
          :disabled="isSubmitting"
          @click="attachDataset(ds)"
        >
          <span class="dataset-picker__name">{{ ds.name }}</span>
          <span v-if="ds.row_count" class="dataset-picker__meta">
            <span>{{ ds.row_count.toLocaleString() }}</span> 行
          </span>
        </button>
        <div v-if="filteredDatasets.length === 0" class="dataset-picker__empty">
          暂无可用数据集
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onBeforeUnmount, watch, type CSSProperties } from 'vue';
import { ElMessage } from 'element-plus';
import { useDatasetStore } from '../../stores/datasetStore';
import { getDatasetVersions, listDatasets } from '../../api/datasets';
import type { DatasetItem, DatasetVersionNode } from '../../types/api';
import VersionLineagePicker from '../versioning/VersionLineagePicker.vue';
import { versionDisplayName } from '../../utils/versionOperation';

const props = withDefaults(defineProps<{
  placeholder?: string;
  rows?: number;
  initialPrompt?: string;
  submitting?: boolean;
}>(), {
  placeholder: '描述你的工业建模或参数优化目标，例如：分析 S3 时序数据并建立 ARX 动态模型…',
  rows: 3,
  initialPrompt: '',
  submitting: false,
});

const emit = defineEmits<{
  submit: [payload: { message: string; datasetId?: string | null; versionId?: string | null }];
}>();

const datasetStore = useDatasetStore();
const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

const message = ref(props.initialPrompt ?? '');
const isFocused = ref(false);
const localSubmitting = ref(false);
const showDatasetPicker = ref(false);
const datasetSearch = ref('');
const agentComposerRef = ref<HTMLElement | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const pickerInputRef = ref<HTMLInputElement | null>(null);
const pickerPositioned = ref(false);
const pickerStyle = ref<CSSProperties>({});
const datasets = ref<DatasetItem[]>([]);
const attachedDataset = ref<DatasetItem | null>(datasetStore.activeDataset ?? null);
const versions = ref<DatasetVersionNode[]>([]);
const selectedVersionId = ref<string | null>(null);
const versionsLoading = ref(false);
const versionsError = ref('');
let versionsRequest = 0;
const selectedVersion = computed(() =>
  versions.value.find(version => version.id === selectedVersionId.value) ?? null
);

const PICKER_VIEWPORT_MARGIN = 12;
const PICKER_GAP = 8;
const PICKER_MAX_HEIGHT = 288;
let observedVisualViewport: VisualViewport | null = null;
let pickerPositionListenersActive = false;

const isSubmitting = computed(() => props.submitting || localSubmitting.value);
const canSubmit = computed(() =>
  message.value.trim().length > 0 && !isSubmitting.value && !versionsLoading.value
  && (!attachedDataset.value || !!selectedVersion.value)
);

function isVersionSelectable(version: DatasetVersionNode) {
  return !isSubmitting.value && !!version.artifact_path;
}

function versionDisabledReason(version: DatasetVersionNode) {
  return !version.artifact_path ? '该版本缺少数据文件记录' : '正在提交任务';
}

function selectVersion(versionId: string) {
  const version = versions.value.find(item => item.id === versionId);
  if (version && isVersionSelectable(version)) selectedVersionId.value = versionId;
}

async function loadVersions() {
  const request = ++versionsRequest;
  const datasetId = attachedDataset.value?.id;
  versions.value = [];
  selectedVersionId.value = null;
  versionsError.value = '';
  versionsLoading.value = !!datasetId;
  if (!datasetId) return;
  try {
    const response = await getDatasetVersions(datasetId);
    if (request !== versionsRequest) return;
    if (response.dataset_id !== datasetId) throw new Error('Dataset version scope mismatch');
    versions.value = response.nodes;
    const active = response.nodes.find(version => version.id === response.active_version_id);
    if (active?.artifact_path) selectedVersionId.value = active.id;
  } catch {
    if (request !== versionsRequest) return;
    versionsError.value = '版本血缘加载失败，请重新加载后选择。';
  } finally {
    if (request === versionsRequest) versionsLoading.value = false;
  }
}

watch(attachedDataset, () => { void loadVersions(); }, { immediate: true, flush: 'sync' });

const filteredDatasets = computed(() => {
  const q = datasetSearch.value.toLowerCase();
  return datasets.value.filter(ds => ds.name.toLowerCase().includes(q));
});

function shortIdentifier(id?: string) {
  if (!id) return '';
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function autoResize() {
  const ta = textareaRef.value;
  if (!ta) return;
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 240) + 'px';
}

async function handleSubmit() {
  if (!canSubmit.value) return;
  if (!attachedDataset.value) {
    ElMessage.warning('请先点击输入框左下角「📎 挂载数据」选择数据集，Agent 将基于该数据集执行全流程建模任务。');
    return;
  }
  localSubmitting.value = true;
  try {
    emit('submit', {
      message: message.value.trim(),
      datasetId: attachedDataset.value?.id ?? null,
      versionId: selectedVersion.value!.id,
    });
    message.value = '';
    await nextTick();
    autoResize();
  } finally {
    localSubmitting.value = false;
  }
}

function attachDataset(ds: DatasetItem) {
  if (isSubmitting.value) return;
  attachedDataset.value = { ...ds };
  datasetStore.setActiveDataset(ds);
  showDatasetPicker.value = false;
  datasetSearch.value = '';
}

function detachDataset() {
  if (isSubmitting.value) return;
  attachedDataset.value = null;
}

function updateDatasetPickerPosition() {
  if (!showDatasetPicker.value || !agentComposerRef.value) return;

  const anchor = agentComposerRef.value.getBoundingClientRect();
  const visualViewport = window.visualViewport;
  const viewportTop = visualViewport?.offsetTop ?? 0;
  const viewportLeft = visualViewport?.offsetLeft ?? 0;
  const viewportHeight = visualViewport?.height ?? window.innerHeight;
  const viewportWidth = visualViewport?.width ?? window.innerWidth;
  const viewportBottom = viewportTop + viewportHeight;
  const viewportRight = viewportLeft + viewportWidth;
  const availableAbove = Math.max(
    0,
    anchor.top - viewportTop - PICKER_GAP - PICKER_VIEWPORT_MARGIN
  );
  const availableBelow = Math.max(
    0,
    viewportBottom - anchor.bottom - PICKER_GAP - PICKER_VIEWPORT_MARGIN
  );
  const placeAbove =
    availableAbove >= Math.min(PICKER_MAX_HEIGHT, availableBelow) ||
    availableAbove > availableBelow;
  const availableHeight = placeAbove ? availableAbove : availableBelow;
  const maxHeight = Math.min(PICKER_MAX_HEIGHT, availableHeight);
  const width = Math.min(
    anchor.width,
    Math.max(0, viewportWidth - PICKER_VIEWPORT_MARGIN * 2)
  );
  const left = Math.min(
    Math.max(anchor.left, viewportLeft + PICKER_VIEWPORT_MARGIN),
    viewportRight - PICKER_VIEWPORT_MARGIN - width
  );

  pickerStyle.value = {
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.floor(maxHeight)}px`,
    top: placeAbove ? 'auto' : `${Math.round(anchor.bottom + PICKER_GAP)}px`,
    bottom: placeAbove ? `${Math.round(window.innerHeight - anchor.top + PICKER_GAP)}px` : 'auto',
  };
  pickerPositioned.value = true;
}

function bindDatasetPickerPositionListeners() {
  if (pickerPositionListenersActive) return;
  pickerPositionListenersActive = true;
  window.addEventListener('resize', updateDatasetPickerPosition);
  window.addEventListener('scroll', updateDatasetPickerPosition, true);
  observedVisualViewport = window.visualViewport;
  observedVisualViewport?.addEventListener('resize', updateDatasetPickerPosition);
  observedVisualViewport?.addEventListener('scroll', updateDatasetPickerPosition);
}

function unbindDatasetPickerPositionListeners() {
  if (!pickerPositionListenersActive) return;
  pickerPositionListenersActive = false;
  window.removeEventListener('resize', updateDatasetPickerPosition);
  window.removeEventListener('scroll', updateDatasetPickerPosition, true);
  observedVisualViewport?.removeEventListener('resize', updateDatasetPickerPosition);
  observedVisualViewport?.removeEventListener('scroll', updateDatasetPickerPosition);
  observedVisualViewport = null;
}

watch(showDatasetPicker, async (v) => {
  if (v) {
    pickerPositioned.value = false;
    await nextTick();
    updateDatasetPickerPosition();
    bindDatasetPickerPositionListeners();
    pickerInputRef.value?.focus();
    if (datasets.value.length === 0) {
      try {
        const res = await listDatasets({ page: 1, page_size: 50 });
        datasets.value = res.items;
      } catch {
        ElMessage.error('数据集列表加载失败');
      }
    }
  } else {
    pickerPositioned.value = false;
    unbindDatasetPickerPositionListeners();
  }
});

onBeforeUnmount(() => {
  ++versionsRequest;
  unbindDatasetPickerPositionListeners();
});

// v-click-outside directive shim
const vClickOutside = {
  mounted(el: HTMLElement, binding: any) {
    (el as any)._clickOutsideHandler = (e: Event) => {
      if (!el.contains(e.target as Node)) binding.value(e);
    };
    document.addEventListener('mousedown', (el as any)._clickOutsideHandler);
  },
  unmounted(el: HTMLElement) {
    document.removeEventListener('mousedown', (el as any)._clickOutsideHandler);
  },
};
</script>

<style scoped>
.composer-version-selector {
  margin: 0 0 10px;
}

.composer-version-error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.composer-version-error button {
  margin-left: 8px;
  cursor: pointer;
}

.agent-composer {
  position: relative;
  width: 100%;
}

.composer-body {
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 12px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  overflow: hidden;
}

.agent-composer.is-focused .composer-body {
  border-color: #5E8358;
  box-shadow: 0 0 0 3px rgba(66, 99, 64, 0.08), 0 2px 10px rgba(0, 0, 0, 0.03);
}

/* Attachments */
.composer-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px 0;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: #F0F4EE;
  border: 1px solid #DFE6DC;
  border-radius: 6px;
  font-size: 12px;
  color: #426340;
}

.attachment-icon {
  width: 13px;
  height: 13px;
  color: #5E8358;
}

.attachment-name {
  font-weight: 500;
  color: #2C332B;
}

.attachment-version {
  color: #747A72;
  font-size: 11px;
}

.attachment-remove {
  background: none;
  border: none;
  color: #858B82;
  cursor: pointer;
  font-size: 11px;
  padding: 0 2px;
  line-height: 1;
  transition: color 0.15s ease;
}

.attachment-remove:hover {
  color: #B34E48;
}

/* Textarea */
.composer-textarea {
  width: 100%;
  padding: 16px 18px 12px;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  color: #171717;
  font-size: 14px;
  line-height: 1.6;
  min-height: 84px;
  max-height: 240px;
  font-family: inherit;
  box-sizing: border-box;
}

.composer-textarea::placeholder {
  color: #A1A1A6;
}

/* Footer */
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 14px;
  background: #FAFAFA;
  border-top: 1px solid #ECECED;
  box-sizing: border-box;
}

.composer-footer__left,
.composer-footer__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.composer-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  height: 30px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  color: #666666;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.composer-btn:hover {
  background: #F5F5F7;
  border-color: #D1D1D6;
  color: #171717;
}

.composer-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.composer-btn svg {
  width: 13px;
  height: 13px;
}

.composer-hint {
  font-size: 11px;
  color: #A1A1A6;
}

/* Send Button */
.composer-submit {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #EBEBED;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  color: #8E8E93;
  cursor: not-allowed;
  transition: all 0.15s ease;
}

.composer-submit:hover:not(.is-ready) {
  background: #E5E5E8;
}

.composer-submit.is-ready {
  background: #426340;
  border-color: #426340;
  color: #FFFFFF;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(66, 99, 64, 0.18);
}

.composer-submit.is-ready:hover {
  background: #345032;
  border-color: #345032;
}

.composer-submit svg {
  width: 14px;
  height: 14px;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Dataset Picker */
.dataset-picker {
  position: fixed;
  display: flex;
  flex-direction: column;
  background: #FFFFFF;
  font-family: var(--font-sans);
  border: 1px solid #D1D1D6;
  border-radius: 10px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  z-index: 100;
  overflow: hidden;
  visibility: hidden;
}

.dataset-picker.is-positioned {
  visibility: visible;
}

.dataset-picker__header {
  padding: 12px 14px;
  border-bottom: 1px solid #ECECED;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: none;
}

.dataset-picker__header .label {
  font-family: var(--font-sans);
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.dataset-picker__search {
  width: 100%;
  background: #F5F5F7;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  padding: 6px 10px;
  font-family: var(--font-sans);
  font-size: 13px;
  color: #171717;
  outline: none;
}

.dataset-picker__search:focus {
  border-color: #5E8358;
}

.dataset-picker__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px;
}

.dataset-picker__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 12px;
  background: none;
  border: none;
  border-radius: 6px;
  color: #171717;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s ease;
}

.dataset-picker__item:hover {
  background: #F0F2ED;
}

.dataset-picker__name {
  font-size: 13px;
  font-weight: 500;
}

.dataset-picker__meta {
  font-size: 11px;
  color: #8E8E93;
}

.dataset-picker__empty {
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: #8E8E93;
}
</style>
