<template>
  <aside class="difference-detail-card" data-test="difference-detail-card" aria-live="polite">
    <header class="difference-detail-card__header">
      <div>
        <span class="difference-detail-card__eyebrow">DIFFERENCE DETAIL</span>
        <h4>{{ typeLabel }}</h4>
      </div>
      <button
        type="button"
        class="difference-detail-card__close"
        data-test="difference-detail-close"
        aria-label="关闭差异详情"
        @click="emit('close')"
      >×</button>
    </header>

    <dl class="difference-detail-card__fields">
      <div><dt>时间</dt><dd>{{ formatTimestamp(difference.timestamp) }}</dd></div>
      <template v-if="difference.difference_kind === 'VALUE_CHANGED'">
        <div><dt>Baseline</dt><dd data-test="difference-baseline-value">{{ formatValue(difference.baseline_value) }}</dd></div>
        <div><dt>Compare</dt><dd data-test="difference-compare-value">{{ formatValue(difference.compare_value) }}</dd></div>
        <div><dt>Absolute delta</dt><dd data-test="difference-absolute-delta">{{ formatDelta(difference.absolute_delta) }}</dd></div>
      </template>
      <template v-else-if="difference.difference_kind === 'POINT_ADDED'">
        <div><dt>Baseline</dt><dd data-test="difference-baseline-value">不存在</dd></div>
        <div><dt>Compare</dt><dd data-test="difference-compare-value">{{ formatValue(difference.compare_value) }}</dd></div>
      </template>
      <template v-else-if="difference.difference_kind === 'POINT_REMOVED'">
        <div><dt>Baseline</dt><dd data-test="difference-baseline-value">{{ formatValue(difference.baseline_value) }}</dd></div>
        <div><dt>Compare</dt><dd data-test="difference-compare-value">不存在</dd></div>
      </template>
    </dl>

    <div
      v-if="difference.difference_kind === 'AMBIGUOUS_ALIGNMENT'"
      class="difference-detail-card__occurrences"
      data-test="difference-occurrences"
    >
      <OccurrenceList label="Baseline" :occurrences="difference.baseline_occurrences" />
      <OccurrenceList label="Compare" :occurrences="difference.compare_occurrences" />
      <p>该时间戳存在多个记录，系统未推测 occurrence 配对。</p>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, type PropType } from "vue";
import type { VersionComparePoint, VersionDifferencePoint } from "../../types/api";

const props = defineProps<{
  difference: VersionDifferencePoint;
}>();

const emit = defineEmits<{
  close: [];
}>();

const TYPE_LABELS: Record<VersionDifferencePoint["difference_kind"], string> = {
  VALUE_CHANGED: "值变化",
  POINT_ADDED: "新增点",
  POINT_REMOVED: "移除点",
  AMBIGUOUS_ALIGNMENT: "对齐歧义",
};

const typeLabel = computed(() => TYPE_LABELS[props.difference.difference_kind]);

const formatTimestamp = (timestamp: string) => {
  const match = timestamp.replace("T", " ").match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? timestamp.replace("T", " ");
};

const formatValue = (value: number | null) => {
  if (value === null || !Number.isFinite(value)) return "缺失";
  const magnitude = Math.abs(value);
  if (magnitude > 0 && magnitude < 0.0001) return value.toExponential(4).replace(/\.0+(?=e)/, "");
  return value.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 4 });
};

const formatDelta = (value: number | null) => value === null ? "未提供" : formatValue(value);

const OccurrenceList = defineComponent({
  name: "OccurrenceList",
  props: {
    label: { type: String, required: true },
    occurrences: {
      type: Array as PropType<VersionComparePoint[]>,
      required: true,
    },
  },
  setup(occurrenceProps) {
    return () => h("section", { class: "occurrence-list" }, [
      h("strong", `${occurrenceProps.label} occurrences (${occurrenceProps.occurrences.length})`),
      occurrenceProps.occurrences.length
        ? h("ul", occurrenceProps.occurrences.map((occurrence) => h("li", { key: occurrence.occurrence_index }, [
          h("span", `#${occurrence.occurrence_index}`),
          h("code", formatValue(occurrence.value)),
        ])))
        : h("small", "无记录"),
    ]);
  },
});
</script>

<style scoped>
.difference-detail-card {
  width: min(292px, calc(100vw - 64px));
  box-sizing: border-box;
  padding: 14px 15px;
  border: 1px solid #cbd5cc;
  border-radius: 8px;
  background: rgba(250, 250, 247, 0.97);
  box-shadow: 0 8px 22px rgba(49, 65, 54, 0.13);
  color: var(--text-primary);
  backdrop-filter: blur(3px);
}

.difference-detail-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.difference-detail-card__eyebrow {
  display: block;
  margin-bottom: 2px;
  font-family: var(--font-sans);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: normal;
  color: #65796b;
}

.difference-detail-card h4 {
  margin: 0;
  font-size: 14px;
}

.difference-detail-card__close {
  display: grid;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: #748178;
  font: 18px/1 var(--font-sans);
  cursor: pointer;
  place-items: center;
}

.difference-detail-card__close:hover,
.difference-detail-card__close:focus-visible {
  border-color: #c7d0c8;
  background: #eef2ed;
  color: #40564a;
  outline: none;
}

.difference-detail-card__fields {
  display: grid;
  gap: 8px;
  margin: 13px 0 0;
}

.difference-detail-card__fields > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 8px;
  align-items: baseline;
}

.difference-detail-card dt {
  font-size: 10px;
  color: var(--text-muted);
}

.difference-detail-card dd {
  overflow-wrap: anywhere;
  margin: 0;
  font-family: var(--font-sans);
  font-size: 11px;
  color: #34443a;
}

.difference-detail-card__occurrences {
  display: grid;
  gap: 10px;
  max-height: 230px;
  margin-top: 13px;
  padding-right: 4px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.occurrence-list strong {
  font-size: 10px;
  color: var(--text-muted);
}

.occurrence-list ul {
  display: grid;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.occurrence-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 6px;
  background: #f0f3ef;
  font-size: 10px;
}

.occurrence-list code {
  color: #34443a;
}

.occurrence-list small,
.difference-detail-card__occurrences p {
  font-size: 10px;
  color: var(--text-muted);
}

.difference-detail-card__occurrences p {
  margin: 0;
  padding-top: 9px;
  border-top: 1px solid #dce3dc;
  line-height: 1.5;
}
</style>
