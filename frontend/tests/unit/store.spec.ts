import { describe, it, expect, beforeEach, vi } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useDatasetStore } from "../../src/stores/datasetStore";
import { useSystemStore } from "../../src/stores/systemStore";
import { getHealthLive, getHealthReady } from "../../src/api/health";

vi.mock("../../src/api/health", () => ({
  getHealthLive: vi.fn(),
  getHealthReady: vi.fn(),
}));

const mockedGetHealthLive = vi.mocked(getHealthLive);
const mockedGetHealthReady = vi.mocked(getHealthReady);
const live = { status: "ok" as const, service: "indusopt-backend" };
const ready = { status: "ready" as const, database: "connected" as const, queue: "connected" as const };

describe("Pinia Stores", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("should manage active dataset state", () => {
    const store = useDatasetStore();
    expect(store.activeDataset).toBeNull();

    const mockItem = {
      id: "ds_test",
      name: "Test Dataset",
      version_id: "V0_Original",
      file_size_bytes: 1000,
      row_count: 100,
      col_count: 3,
      created_at: "2026-07-28T00:00:00Z",
      time_column: "timestamp",
      input_columns: ["u1"],
      output_column: "y",
    };

    store.setActiveDataset(mockItem);
    expect(store.activeDataset?.id).toBe("ds_test");
  });

  it("starts connecting and accepts only the current readiness contract", async () => {
    const store = useSystemStore();
    expect(store.status).toBe("connecting");

    mockedGetHealthLive.mockResolvedValue(live);
    mockedGetHealthReady.mockResolvedValue(ready);
    await store.checkHealth();

    expect(store.status).toBe("ready");
  });

  it.each([
    ["database disconnected", { status: "ready", database: "disconnected", queue: "connected" }],
    ["queue disconnected", { status: "ready", database: "connected", queue: "disconnected" }],
    ["legacy healthy status", { status: "healthy", database: "connected", queue: "connected" }],
  ])("moves offline when %s", async (_label, invalidReady) => {
    const store = useSystemStore();
    mockedGetHealthLive.mockResolvedValue(live);
    mockedGetHealthReady.mockResolvedValue(invalidReady as never);

    await store.checkHealth();

    expect(store.status).toBe("offline");
  });

  it("moves offline after a failed request and recovers on a later success", async () => {
    const store = useSystemStore();
    mockedGetHealthLive.mockRejectedValueOnce(new Error("connection refused"));

    await store.checkHealth();
    expect(store.status).toBe("offline");

    mockedGetHealthLive.mockResolvedValue(live);
    mockedGetHealthReady.mockResolvedValue(ready);
    await store.checkHealth();

    expect(store.status).toBe("ready");
  });

  it("does not overlap health requests", async () => {
    const store = useSystemStore();
    let resolveLive: ((value: typeof live) => void) | undefined;
    mockedGetHealthLive.mockImplementationOnce(() => new Promise((resolve) => {
      resolveLive = resolve;
    }));

    const firstCheck = store.checkHealth();
    const overlappingCheck = store.checkHealth();
    expect(mockedGetHealthLive).toHaveBeenCalledTimes(1);

    resolveLive!(live);
    mockedGetHealthReady.mockResolvedValue(ready);
    await Promise.all([firstCheck, overlappingCheck]);
    expect(store.status).toBe("ready");
  });
});
