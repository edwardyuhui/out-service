<template>
  <div class="collin-artifact" data-test="collinearity-artifact-renderer">
    <section class="collin-section">
      <div class="collin-heading">
        <h3>输入相关性</h3>
        <div class="collin-switch" aria-label="相关系数类型">
          <button type="button" :class="{ active: mode === 'pearson' }" data-test="correlation-mode-pearson" @click="mode = 'pearson'">Pearson</button>
          <button type="button" :class="{ active: mode === 'spearman' }" data-test="correlation-mode-spearman" @click="mode = 'spearman'">Spearman</button>
        </div>
      </div>
      <ChartContainer v-if="hasMatrixValues" :options="heatmapOptions" :height="`${Math.max(270, variables.length * 38 + 140)}px`" data-test="correlation-chart" />
      <p v-else class="collin-empty" data-test="correlation-empty">{{ modeLabel }}相关矩阵无可用数据。</p>
      <p class="collin-note">灰色 N/A 单元格表示本次结果未提供可计算的相关系数。</p>
      <ol v-if="variables.length" class="collin-variable-key" aria-label="输入变量全名">
        <li v-for="name in variables" :key="name" :title="name">{{ name }}</li>
      </ol>
    </section>

    <section class="collin-section">
      <h3>输入变量 VIF</h3>
      <ChartContainer v-if="hasVifValues" :options="vifOptions" :height="`${Math.max(190, variables.length * 38 + 60)}px`" data-test="vif-chart" />
      <p v-else class="collin-empty" data-test="vif-empty">VIF 无可用数据。</p>
      <div v-if="variables.length" class="collin-vif-list">
        <div v-for="name in variables" :key="name" class="collin-vif-row">
          <span :title="name">{{ name }}</span><strong>{{ formatMetric(vifScores[name]) }}</strong>
        </div>
      </div>
    </section>

    <section class="collin-section collin-condition">
      <span>条件数</span><strong data-test="collinearity-condition-number">{{ formatMetric(payload.condition_number) }}</strong>
    </section>

    <section class="collin-section" data-test="collinearity-recommendations">
      <h3>变量建议</h3>
      <p v-if="!recommendations.length" class="collin-empty">当前结果未提供变量建议。</p>
      <p v-else-if="completeRecommendations && !recommendations.some(item => item.action === 'drop')" class="collin-no-drops" data-test="collinearity-no-drops">本次未建议剔除输入变量。</p>
      <p v-else-if="!completeRecommendations" class="collin-empty">当前结果的变量建议不完整。</p>
      <div v-for="item in recommendations" :key="item.variable" class="collin-advice">
        <div class="collin-advice-heading"><strong :title="item.variable">{{ item.variable }}</strong><span :class="item.action">{{ actionLabel[item.action] }}</span></div>
        <p>{{ item.reason || '当前结果未提供详细依据。' }}</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import ChartContainer, { type ChartOption } from '../ChartContainer.vue';

const props = defineProps<{ payload: Record<string, unknown> }>();
const mode = ref<'pearson' | 'spearman'>('pearson');
const modeLabel = computed(() => mode.value === 'pearson' ? 'Pearson ' : 'Spearman ');
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const formatMetric = (value: unknown) => finite(value) ? value.toFixed(2) : 'N/A';
const variables = computed((): string[] =>
  Array.isArray(props.payload.variables) && props.payload.variables.every(value => typeof value === 'string')
    ? props.payload.variables as string[] : []
);
const vifScores = computed(() => record(props.payload.vif_scores) ? props.payload.vif_scores : {});
const hasVifValues = computed(() => variables.value.some(name => finite(vifScores.value[name])));

const matrix = computed((): unknown[][] | null => {
  const raw = mode.value === 'pearson' ? props.payload.matrix : props.payload.spearman_matrix;
  const size = variables.value.length;
  return size > 0 && Array.isArray(raw) && raw.length === size
    && raw.every(row => Array.isArray(row) && row.length === size)
    ? raw as unknown[][] : null;
});
const hasMatrixValues = computed(() => matrix.value?.some(row => row.some(finite)) ?? false);
const heatmapOptions = computed<ChartOption>(() => {
  const values: [number, number, number][] = [];
  const unavailable: [number, number][] = [];
  matrix.value?.forEach((row, y) => row.forEach((value, x) => {
    if (finite(value)) values.push([x, y, value]);
    else unavailable.push([x, y]);
  }));
  return {
    tooltip: {
      renderMode: 'richText',
      formatter: (params: any) => {
        const point = params.value as number[];
        return `${variables.value[point[1]]} × ${variables.value[point[0]]}: ${point.length === 3 ? point[2].toFixed(3) : 'N/A'}`;
      },
    },
    grid: { left: 112, right: 18, top: 18, bottom: 98 },
    xAxis: { type: 'category', data: variables.value, axisLabel: { rotate: 35, width: 100, overflow: 'truncate', fontSize: 10 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: variables.value, axisLabel: { width: 96, overflow: 'truncate', fontSize: 10 }, splitArea: { show: true } },
    visualMap: { show: false, min: -1, max: 1, inRange: { color: ['#7995A8', '#FFFFFF', '#B8746E'] } },
    series: [
      { type: 'heatmap', data: values, label: { show: variables.value.length <= 6, formatter: (params: any) => Number(params.value[2]).toFixed(2), fontSize: 10 } },
      {
        type: 'custom', data: unavailable,
        renderItem: (_params: unknown, api: { value: (index: number) => number; coord: (value: number[]) => number[]; size: (value: number[]) => number[] }) => {
          const point = api.coord([api.value(0), api.value(1)]);
          const size = api.size([1, 1]);
          return { type: 'group', children: [
            { type: 'rect', shape: { x: point[0] - size[0] * 0.46, y: point[1] - size[1] * 0.46, width: size[0] * 0.92, height: size[1] * 0.92 }, style: { fill: '#EEF1ED' } },
            { type: 'text', style: { x: point[0], y: point[1], text: 'N/A', textAlign: 'center', textVerticalAlign: 'middle', fill: '#66716A', fontSize: 10 } },
          ] };
        },
      },
    ],
  };
});

const vifOptions = computed<ChartOption>(() => ({
  tooltip: { trigger: 'axis', renderMode: 'richText', formatter: (params: any) => {
    const item = Array.isArray(params) ? params[0] : params;
    return `${item?.name ?? ''}: ${formatMetric(vifScores.value[item?.name])}`;
  } },
  grid: { left: 112, right: 28, top: 12, bottom: 30 },
  xAxis: { type: 'value', min: 0, name: 'VIF' },
  yAxis: { type: 'category', inverse: true, data: variables.value, axisLabel: { width: 96, overflow: 'truncate', fontSize: 10 } },
  series: [{ type: 'bar', data: variables.value.map(name => finite(vifScores.value[name]) ? vifScores.value[name] as number : null), barMaxWidth: 18, itemStyle: { color: '#52735A', borderRadius: [0, 4, 4, 0] } }],
}));

type Advice = { variable: string; action: 'keep' | 'drop' | 'merge' | 'review'; reason: string };
const actionLabel: Record<Advice['action'], string> = { keep: '建议保留', drop: '建议剔除', merge: '建议合并', review: '建议复核' };
const recommendations = computed((): Advice[] =>
  Array.isArray(props.payload.recommendations)
    ? props.payload.recommendations.filter((item): item is Advice =>
      record(item) && typeof item.variable === 'string' && item.variable.length > 0
      && variables.value.includes(item.variable)
      && typeof item.action === 'string' && item.action in actionLabel
      && typeof item.reason === 'string')
    : []
);
const completeRecommendations = computed(() => variables.value.length > 0
  && variables.value.every(name => recommendations.value.some(item => item.variable === name)));
</script>

<style scoped>
.collin-artifact { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.collin-section { min-width: 0; padding: 13px; border: 1px solid #e5e5e8; border-radius: 8px; background: #fff; }
.collin-section h3 { margin: 0 0 10px; font-size: 12px; font-weight: 650; color: #333; }
.collin-heading { display: flex; justify-content: space-between; gap: 8px; align-items: center; flex-wrap: wrap; }
.collin-heading h3 { margin-bottom: 0; }
.collin-switch { display: flex; padding: 2px; border-radius: 6px; background: #f5f5f7; }
.collin-switch button { border: 0; padding: 5px 9px; border-radius: 4px; background: transparent; color: #666; cursor: pointer; font-size: 11px; }
.collin-switch button.active { background: #fff; color: #426340; box-shadow: 0 1px 3px #0001; font-weight: 600; }
.collin-empty, .collin-note { margin: 9px 0 0; color: #777; font-size: 11px; line-height: 1.5; }
.collin-variable-key { display: flex; flex-wrap: wrap; gap: 5px 20px; margin: 10px 0 0; padding-left: 20px; color: #555; font-size: 11px; }
.collin-variable-key li { overflow-wrap: anywhere; }
.collin-vif-list { display: grid; gap: 4px; margin-top: 8px; }
.collin-vif-row { display: flex; justify-content: space-between; gap: 10px; padding: 5px 7px; border-radius: 4px; background: #f8f9f7; font-size: 11px; }
.collin-vif-row span { min-width: 0; overflow-wrap: anywhere; }
.collin-vif-row strong { flex: none; color: #426340; }
.collin-condition { display: flex; align-items: center; justify-content: space-between; color: #666; font-size: 12px; }
.collin-condition strong { color: #333; font-size: 16px; }
.collin-no-drops { margin: 0 0 8px; padding: 8px 10px; background: #eef5eb; border-radius: 5px; color: #426340; font-size: 11px; }
.collin-advice { padding: 9px 0; border-top: 1px solid #ececed; }
.collin-advice-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 5px; font-size: 12px; }
.collin-advice-heading strong { min-width: 0; overflow-wrap: anywhere; }
.collin-advice-heading span { padding: 2px 7px; border-radius: 4px; background: #eef5eb; color: #426340; font-size: 10px; }
.collin-advice-heading span.drop { background: #f7eeea; color: #965d51; }
.collin-advice-heading span.review, .collin-advice-heading span.merge { background: #f7f3e8; color: #846f42; }
.collin-advice p { margin: 5px 0 0; color: #666; line-height: 1.5; font-size: 11px; }
</style>
