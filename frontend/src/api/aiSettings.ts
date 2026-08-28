

import { apiGet, apiPut } from "./client";

export type AISettings = {
  enabled: boolean;
  max_calls_per_minute: number;
  high_stakes_model: string;
  low_stakes_model: string;
};

export async function fetchAISettings(): Promise<AISettings> {
  return apiGet<AISettings>("/api/settings/ai");
}

export async function updateAISettings(enabled: boolean): Promise<AISettings> {
  return apiPut<AISettings>("/api/settings/ai", { enabled });
}
