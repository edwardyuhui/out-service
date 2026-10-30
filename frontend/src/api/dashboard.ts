import apiClient from "./client";
import type { DashboardLeaderboardResponse } from "../types/api";

export const getDashboardLeaderboard = (): Promise<DashboardLeaderboardResponse> =>
  apiClient.get("/dashboard/leaderboard");
