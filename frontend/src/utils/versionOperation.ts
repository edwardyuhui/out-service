import type { DatasetVersionNode } from "../types/api";

const VERSION_OPERATION_LABELS: Record<string, string> = {
  simulation_generate: "仿真原始数据",
  raw_upload: "原始上传",
  "preprocessing.clean": "清洗规整",
  "preprocessing.lag_compensation": "时滞补偿",
  "preprocessing.feature_selection": "特征优选",
};

export const versionOperationLabel = (operation: string) =>
  VERSION_OPERATION_LABELS[operation] ?? (operation || "其他处理");

export const versionDisplayName = (version: DatasetVersionNode) =>
  version.name?.trim() || versionOperationLabel(version.tool);

export const shortVersionId = (versionId: string) =>
  versionId.length <= 16 ? versionId : `${versionId.slice(0, 8)}…${versionId.slice(-4)}`;

export const formatVersionDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
};
