import apiClient from "./client";
import type {
  DatasetItem,
  DatasetListResponse,
  DatasetUploadResponse,
  DatasetProfile,
  DatasetVersionPreviewParams,
  DatasetVersionPreviewResponse,
  DatasetVersionsResponse,
  DelaySourceVersionsResponse,
  CollinearitySourceVersionsData,
  DatasetDeleteResponse,
  DatasetConfigRequest,
  CleaningVersionCompareChannelsData,
  CleaningVersionCompareData,
} from "../types/api";

export const uploadDataset = (file: File, name?: string): Promise<DatasetUploadResponse> => {
  const formData = new FormData();
  formData.append("file", file);
  if (name) formData.append("name", name);
  return apiClient.post("/datasets/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const getDatasets = (page = 1, pageSize = 20): Promise<DatasetListResponse> =>
  apiClient.get(`/datasets?page=${page}&page_size=${pageSize}`);

/** Alias with object params — used by AgentComposer */
export const listDatasets = (params: { page?: number; page_size?: number } = {}): Promise<DatasetListResponse> =>
  apiClient.get(`/datasets?page=${params.page ?? 1}&page_size=${params.page_size ?? 50}`);

export const getDatasetDetail = (datasetId: string): Promise<DatasetItem> =>
  apiClient.get(`/datasets/${datasetId}`);

export const getDatasetVersionPreview = (
  datasetId: string,
  versionId: string,
  params: DatasetVersionPreviewParams
): Promise<DatasetVersionPreviewResponse> =>
  apiClient.get(`/datasets/${datasetId}/versions/${versionId}/preview`, { params });

export const configureDataset = (
  datasetId: string,
  payload: DatasetConfigRequest
): Promise<{ dataset: DatasetItem; profile: DatasetProfile }> =>
  apiClient.post(`/datasets/${datasetId}/config`, payload);

export const getDatasetProfile = (datasetId: string): Promise<DatasetProfile> =>
  apiClient.get(`/datasets/${datasetId}/profile`);

export const getDatasetVersions = (datasetId: string): Promise<DatasetVersionsResponse> =>
  apiClient.get(`/datasets/${datasetId}/versions`);

export const getCleaningVersionCompareChannels = (
  datasetId: string,
  params: {
    baseline_version_id: string;
    compare_version_id: string;
  }
): Promise<CleaningVersionCompareChannelsData> =>
  apiClient.get(`/datasets/${datasetId}/cleaning-version-compare/channels`, { params });

export const getCleaningVersionCompare = (
  datasetId: string,
  params: {
    baseline_version_id: string;
    compare_version_id: string;
    channel: string;
    max_points?: number;
  }
): Promise<CleaningVersionCompareData> =>
  apiClient.get(`/datasets/${datasetId}/cleaning-version-compare`, {
    params: { ...params, max_points: params.max_points ?? 10_000 },
  });

export const getDelaySourceVersions = (datasetId: string): Promise<DelaySourceVersionsResponse> =>
  apiClient.get(`/datasets/${datasetId}/delay-sources`);

export const getCollinearitySourceVersions = (
  datasetId: string
): Promise<CollinearitySourceVersionsData> =>
  apiClient.get(`/datasets/${datasetId}/collinearity-sources`);

export const deleteDataset = (datasetId: string): Promise<DatasetDeleteResponse> =>
  apiClient.delete(`/datasets/${datasetId}`);
