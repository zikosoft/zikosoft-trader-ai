// Client API pour l'interrupteur IA global (§B10 "Interrupteur IA dédié
// dans Settings", D026 — `backend/app/routers/ai_settings.py`). Le contrat
// backend existait depuis B10 sans écran dédié ; cette carte Settings est
// l'écran qui manquait (trouvé lors de l'audit B10 du 28/08 — voir
// AVANCEMENT.md).

import { apiGet, apiPut } from "./client";

export type AISettings = {
  enabled: boolean;
  max_calls_per_minute: number;
  max_calls_per_day: number;
  high_stakes_model: string;
  low_stakes_model: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  daily_budget_usd: number;
  daily_budget_hard_cap_usd: number;
  daily_budget_reserved_usd: number;
  daily_budget_remaining_usd: number;
  daily_calls_reserved: number;
  daily_budget_reset_at: string;
  api_key_configured: boolean;
};

export type AISettingsUpdate = Partial<
  Omit<
    AISettings,
    | "api_key_configured"
    | "daily_budget_hard_cap_usd"
    | "daily_budget_reserved_usd"
    | "daily_budget_remaining_usd"
    | "daily_calls_reserved"
    | "daily_budget_reset_at"
  >
> & { api_key?: string };

export async function fetchAISettings(): Promise<AISettings> {
  return apiGet<AISettings>("/api/settings/ai");
}

export async function updateAISettings(update: boolean | AISettingsUpdate): Promise<AISettings> {
  return apiPut<AISettings>("/api/settings/ai", typeof update === "boolean" ? { enabled: update } : update);
}
