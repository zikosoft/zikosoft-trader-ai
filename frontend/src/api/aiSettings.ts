// Client API pour l'interrupteur IA global (§B10 "Interrupteur IA dédié
// dans Settings", D026 — `backend/app/routers/ai_settings.py`). Le contrat
// backend existait depuis B10 sans écran dédié ; cette carte Settings est
// l'écran qui manquait (trouvé lors de l'audit B10 du 28/08 — voir
// AVANCEMENT.md).

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
