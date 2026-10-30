<template>
  <div class="feature-artifact" data-test="feature-selection-artifact-renderer">
    <template v-if="kept !== null && dropped !== null">
      <div class="feature-counts" data-test="feature-selection-counts">
        <div><span>保留</span><strong>{{ kept.length }}</strong></div>
        <div><span>剔除</span><strong>{{ dropped.length }}</strong></div>
      </div>
      <div v-if="kept.length + dropped.length > 0" class="feature-balance" role="img" :aria-label="`保留 ${kept.length} 个输入，剔除 ${dropped.length} 个输入`">
        <span class="feature-balance-kept" :style="{ width: `${kept.length / (kept.length + dropped.length) * 100}%` }" />
        <span class="feature-balance-dropped" :style="{ width: `${dropped.length / (kept.length + dropped.length) * 100}%` }" />
      </div>
      <section class="feature-section" data-test="feature-selection-kept">
        <h3>保留输入</h3>
        <div class="feature-list"><span v-for="name in kept" :key="name" class="feature-tag kept" :title="name">{{ name }}</span></div>
        <p v-if="!kept.length" class="feature-empty">未记录保留的输入变量。</p>
      </section>
      <section class="feature-section" data-test="feature-selection-dropped">
        <h3>剔除输入</h3>
        <div class="feature-list"><span v-for="name in dropped" :key="name" class="feature-tag dropped" :title="name">{{ name }}</span></div>
        <p v-if="!dropped.length" class="feature-empty">本次没有剔除输入变量。</p>
      </section>
    </template>
    <p v-else class="feature-empty" data-test="feature-selection-empty">该历史步骤未保存完整的变量决策，暂无可展示的保留或剔除数量。</p>

    <section class="feature-section" data-test="feature-selection-version-status">
      <h3>数据版本</h3>
      <p v-if="noChange" class="feature-status unchanged">数据未变 · 未生成新版本</p>
      <p v-else-if="hasNewVersion" class="feature-status changed">数据已变 · 已生成新版本</p>
      <p v-else class="feature-status unknown">版本变更状态未记录。</p>
      <div v-if="sourceVersion" class="feature-version"><span>来源版本</span><span :title="sourceVersion">{{ shortVersion(sourceVersion) }}</span></div>
      <div v-if="resultVersion" class="feature-version"><span>结果版本</span><span :title="resultVersion">{{ shortVersion(resultVersion) }}</span></div>
    </section>
    <p v-if="reason" class="feature-reason" data-test="feature-selection-reason">{{ reason }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  payload: Record<string, unknown>;
  sourceVersionId?: string | null;
  resultVersionId?: string | null;
}>();

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const summary = computed(() => record(props.payload.summary) ? props.payload.summary : {});
const columnList = (value: unknown): string[] | null =>
  Array.isArray(value) && value.every(item => typeof item === 'string') ? value : null;
const kept = computed(() => columnList(summary.value.kept_input_columns));
const dropped = computed(() => columnList(summary.value.dropped_columns));
const sourceVersion = computed(() => props.sourceVersionId || (typeof props.payload.source_version_id === 'string' ? props.payload.source_version_id : null));
const resultVersion = computed(() => props.resultVersionId || (typeof props.payload.result_version_id === 'string' ? props.payload.result_version_id : null));
const noChange = computed(() => props.payload.data_changed === false && !resultVersion.value);
const hasNewVersion = computed(() => !!resultVersion.value && !!dropped.value?.length);
const reason = computed(() => typeof summary.value.reason === 'string' ? summary.value.reason.trim() : '');
const shortVersion = (value: string) => value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
</script>

<style scoped>
.feature-artifact { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.feature-counts { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; overflow: hidden; border: 1px solid #e5e5e8; border-radius: 8px; background: #e5e5e8; }
.feature-counts > div { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 13px 15px; background: #f8f9f7; color: #666; font-size: 12px; }
.feature-counts strong { color: #426340; font-size: 22px; }
.feature-counts > div:last-child strong { color: #965d51; }
.feature-balance { display: flex; height: 10px; overflow: hidden; border-radius: 999px; background: #ececed; }
.feature-balance-kept { background: #6e9b69; }
.feature-balance-dropped { background: #b8746e; }
.feature-section { padding: 12px; border: 1px solid #e5e5e8; border-radius: 8px; background: #fff; }
.feature-section h3 { margin: 0 0 9px; color: #666; font-size: 11px; font-weight: 600; }
.feature-list { display: flex; flex-wrap: wrap; gap: 6px; }
.feature-tag { max-width: 100%; padding: 5px 9px; border-radius: 5px; font-size: 12px; overflow-wrap: anywhere; }
.feature-tag.kept { background: #eef5eb; color: #426340; }
.feature-tag.dropped { background: #f7eeea; color: #965d51; }
.feature-empty { margin: 0; padding: 10px 12px; border-radius: 6px; background: #f8f9f7; color: #777; font-size: 11px; line-height: 1.5; }
.feature-status { margin: 0 0 9px; padding: 8px 10px; border-radius: 5px; font-size: 12px; }
.feature-status.unchanged { background: #eef5eb; color: #426340; }
.feature-status.changed { background: #f7eeea; color: #965d51; }
.feature-status.unknown { background: #f8f9f7; color: #777; }
.feature-version { display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; border-top: 1px solid #ececed; color: #666; font-size: 11px; }
.feature-version span:last-child { color: #333; }
.feature-reason { margin: 0; padding: 10px 12px; border-left: 3px solid #6e9b69; background: #f8f9f7; color: #555; font-size: 11px; line-height: 1.6; }
</style>
