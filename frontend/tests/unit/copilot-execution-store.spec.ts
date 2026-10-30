import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import {
  COPILOT_ACTIVE_EXECUTION_STORAGE_KEY,
  useCopilotExecutionStore,
} from "../../src/stores/copilotExecution";

const executionId = "22222222-2222-4222-8222-222222222222";

describe("Copilot execution store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActivePinia(createPinia());
  });

  it("persists only the active execution UUID", () => {
    const store = useCopilotExecutionStore();

    store.setActiveExecutionId(executionId);

    expect(store.activeExecutionId).toBe(executionId);
    expect(window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)).toBe(executionId);
    expect(window.localStorage.length).toBe(1);
  });

  it("hydrates the UUID from localStorage and clears it explicitly", () => {
    window.localStorage.setItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY, executionId);
    setActivePinia(createPinia());
    const store = useCopilotExecutionStore();

    expect(store.activeExecutionId).toBe(executionId);
    store.clearActiveExecutionId();

    expect(store.activeExecutionId).toBeNull();
    expect(window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)).toBeNull();
  });
});