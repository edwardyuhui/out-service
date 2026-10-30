import { defineStore } from "pinia";
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { getHealthLive, getHealthReady } from "../api/health";
import type { LivenessData, ReadinessData, SystemInfoData } from "../types/api";

export type SystemStatus = "connecting" | "ready" | "offline";

const HEALTH_POLL_INTERVAL_MS = 5_000;
// Number of consecutive failed health checks before we interrupt the user
// with a toast. The status dot in AppHeader already reflects every failure
// passively; this only covers the case where polling has been silently
// broken for a while and the user hasn't noticed the dot.
const HEALTH_CHECK_FAILURE_WARNING_THRESHOLD = 3;

export const useSystemStore = defineStore("system", () => {
  const liveness = ref<LivenessData | null>(null);
  const readiness = ref<ReadinessData | null>(null);
  const systemInfo = ref<SystemInfoData | null>(null);
  const status = ref<SystemStatus>("connecting");
  const isChecking = ref(false);
  let pollingTimer: ReturnType<typeof setInterval> | null = null;
  let consecutiveHealthCheckFailures = 0;
  let hasWarnedForCurrentOutage = false;

  function isReady(live: LivenessData, ready: ReadinessData): boolean {
    return (
      live.status === "ok" &&
      ready.status === "ready" &&
      ready.database === "connected" &&
      ready.queue === "connected"
    );
  }

  async function checkHealth(): Promise<SystemStatus> {
    if (isChecking.value) {
      return status.value;
    }

    isChecking.value = true;
    try {
      const live = await getHealthLive();
      const ready = await getHealthReady();
      liveness.value = live;
      readiness.value = ready;
      status.value = isReady(live, ready) ? "ready" : "offline";
      consecutiveHealthCheckFailures = 0;
      hasWarnedForCurrentOutage = false;
    } catch {
      liveness.value = null;
      readiness.value = null;
      status.value = "offline";
      consecutiveHealthCheckFailures += 1;
      if (
        consecutiveHealthCheckFailures >= HEALTH_CHECK_FAILURE_WARNING_THRESHOLD &&
        !hasWarnedForCurrentOutage
      ) {
        hasWarnedForCurrentOutage = true;
        ElMessage.warning("与后端服务的连接持续异常，请检查网络或服务状态");
      }
    } finally {
      isChecking.value = false;
    }

    return status.value;
  }

  function startHealthPolling() {
    if (pollingTimer !== null) {
      return;
    }

    void checkHealth();
    pollingTimer = setInterval(() => {
      void checkHealth();
    }, HEALTH_POLL_INTERVAL_MS);
  }

  function stopHealthPolling() {
    if (pollingTimer !== null) {
      clearInterval(pollingTimer);
      pollingTimer = null;
    }
  }

  function setSystemInfo(info: SystemInfoData) {
    systemInfo.value = info;
  }

  return {
    liveness,
    readiness,
    systemInfo,
    status,
    isChecking,
    checkHealth,
    startHealthPolling,
    stopHealthPolling,
    setSystemInfo,
  };
});
