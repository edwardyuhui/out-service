import apiClient from "./client";
import type {
  CleanRequest,
  CleanResponse,
  SegmentRequest,
  SegmentResponse,
  DelayRequest,
  DelayResponse,
  LatestDelayRequest,
  CollinearityRequest,
  CollinearityResponse,
  LatestCollinearityRequest,
  FeatureSelectionApplyRequest,
  LagCompensationRequest,
  VersionApplyResponse,
} from "../types/api";

export const cleanDataset = (req: CleanRequest): Promise<CleanResponse> =>
  apiClient.post("/preprocessing/clean", req);

export const segmentDataset = (req: SegmentRequest): Promise<SegmentResponse> =>
  apiClient.post("/preprocessing/segment", req);

export const calculateDelay = (req: DelayRequest): Promise<DelayResponse> =>
  apiClient.post("/preprocessing/delay", req);

export const getLatestDelay = (req: LatestDelayRequest): Promise<DelayResponse> =>
  apiClient.get("/preprocessing/delay/latest", { params: req });

export const applyLagCompensation = (req: LagCompensationRequest): Promise<VersionApplyResponse> =>
  apiClient.post("/preprocessing/delay/apply", req);

export const calculateCollinearity = (req: CollinearityRequest): Promise<CollinearityResponse> =>
  apiClient.post("/preprocessing/collinearity", req);

export const getLatestCollinearity = (
  req: LatestCollinearityRequest
): Promise<CollinearityResponse> =>
  apiClient.get("/preprocessing/collinearity/latest", { params: req });

export const applyFeatureSelection = (req: FeatureSelectionApplyRequest): Promise<VersionApplyResponse> =>
  apiClient.post("/preprocessing/features/apply", req);
