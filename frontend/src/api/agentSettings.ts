import apiClient from "./client";
import type {
  AgentLlmConfigData,
  AgentLlmConfigUpdate,
  AgentLlmConnectionData,
} from "../types/api";

export const getAgentLlmConfig = (): Promise<AgentLlmConfigData> =>
  apiClient.get("/system/agent-config");

export const updateAgentLlmConfig = (
  payload: AgentLlmConfigUpdate,
): Promise<AgentLlmConfigData> => apiClient.put("/system/agent-config", payload);

export const resetAgentLlmConfig = (): Promise<AgentLlmConfigData> =>
  apiClient.delete("/system/agent-config");

export const testAgentLlmConnection = (): Promise<AgentLlmConnectionData> =>
  apiClient.post("/system/agent-config/test");
