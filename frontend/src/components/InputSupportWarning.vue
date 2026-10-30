<template>
  <el-alert v-if="message" :title="message" type="warning" :closable="false" show-icon
    data-test="input-support-warning" />
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ support?: unknown }>();
const message = computed(() => {
  const support = props.support;
  if (!support || typeof support !== "object" || Array.isArray(support)) return "";
  const record = support as Record<string, unknown>;
  const channels = Array.isArray(record.unsupported_constant_inputs)
    ? record.unsupported_constant_inputs.filter((name): name is string => typeof name === "string").join("、")
    : "";
  if (record.status === "unsupported") {
    return `控制量${channels ? ` ${channels} ` : ""}在训练期间没有变化，却在评价期间发生变化。请补充这些控制量变化的真实运行数据，再重新训练和验证。`;
  }
  if (record.status === "extrapolation") return "评价输入超出实际训练行的取值范围，预测包含外推。请补充相应工况数据并验证跨工况效果。";
  if (record.status === "unavailable") return "缺少完整训练输入范围证据，当前无法确认工况覆盖。";
  return "";
});
</script>
