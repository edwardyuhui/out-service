import { defineStore } from "pinia";
import { ref } from "vue";

export const COPILOT_ACTIVE_EXECUTION_STORAGE_KEY = "indusopt.copilot.activeExecutionId";

const readStoredExecutionId = (): string | null => {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)?.trim();
  return value || null;
};

export const useCopilotExecutionStore = defineStore("copilotExecution", () => {
  const activeExecutionId = ref<string | null>(readStoredExecutionId());

  function setActiveExecutionId(executionId: string) {
    const value = executionId.trim();
    activeExecutionId.value = value || null;
    if (typeof window === "undefined") return;
    if (value) {
      window.localStorage.setItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY, value);
    } else {
      window.localStorage.removeItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY);
    }
  }

  function clearActiveExecutionId() {
    activeExecutionId.value = null;
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY);
    }
  }

  return { activeExecutionId, setActiveExecutionId, clearActiveExecutionId };
});