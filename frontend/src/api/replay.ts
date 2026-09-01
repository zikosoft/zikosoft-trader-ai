// Client API pour le Replay Engine (§B19 Étape A — `backend/app/routers/replay.py`).
// Premier consommateur frontend de ces routes : jusqu'ici `ReplayPage` était
// un `PlaceholderPage` ("UI à venir"). Reste volontairement aligné Étape A
// (pas de vitesses x1/x2/x5/x10, pas de lecture automatique — voir la
// docstring du router backend) : avance manuelle bougie-par-bougie
// uniquement, par instruction explicite de Zac ("minimum de travail").

import { apiGet, apiPost } from "./client";

export type ReplayDataset = {
  dataset_id: string;
  trading_day: string;
  timezone: string;
  symbols: string[];
  total_bars: number;
  checksum: string;
};

export type ReplayBar = {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type ReplaySession = {
  dataset_id: string;
  trading_day: string;
  symbols: string[];
  total_bars: number;
  current_index: number;
  current_timestamp: string | null;
  current_bars: Record<string, ReplayBar>;
  is_finished: boolean;
};

export async function fetchReplayDataset(): Promise<ReplayDataset> {
  return apiGet<ReplayDataset>("/api/replay/dataset");
}

export async function fetchReplaySession(): Promise<ReplaySession> {
  return apiGet<ReplaySession>("/api/replay/session");
}

export async function resetReplaySession(): Promise<ReplaySession> {
  return apiPost<ReplaySession>("/api/replay/session/reset");
}

export async function advanceReplaySession(): Promise<ReplaySession> {
  return apiPost<ReplaySession>("/api/replay/session/advance");
}
