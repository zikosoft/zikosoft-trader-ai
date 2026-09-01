// Client API pour le kill switch trading (§B31 — `backend/app/routers/kill_switch.py`).

import { apiGet, apiPost } from "./client";

export type KillSwitchEvent = {
  action: "KILL_SWITCH_ENGAGED" | "KILL_SWITCH_DISENGAGED";
  actor_user_id: string | null;
  reason: string | null;
  occurred_at: string;
  detail: Record<string, unknown>;
};

export type KillSwitchStatus = {
  engaged: boolean;
  last_event: KillSwitchEvent | null;
};

export type KillSwitchActionResult = {
  engaged: boolean;
  already_engaged: boolean;
  already_disengaged: boolean;
  event: KillSwitchEvent | null;
  suspended_strategy_ids: string[];
};

export async function fetchKillSwitchStatus(): Promise<KillSwitchStatus> {
  return apiGet<KillSwitchStatus>("/api/system/kill-switch/status");
}

export async function fetchKillSwitchHistory(limit = 20): Promise<KillSwitchEvent[]> {
  const result = await apiGet<{ events: KillSwitchEvent[] }>(`/api/system/kill-switch/history?limit=${limit}`);
  return result.events;
}

export async function engageKillSwitch(reason: string): Promise<KillSwitchActionResult> {
  return apiPost<KillSwitchActionResult>("/api/system/kill-switch/engage", { reason });
}

export async function disengageKillSwitch(reason: string): Promise<KillSwitchActionResult> {
  return apiPost<KillSwitchActionResult>("/api/system/kill-switch/disengage", { reason });
}
