// Safe Paper demo preflight. The endpoint accepts no credentials and its only
// broker request is GET /v2/account; it cannot create, modify or cancel an
// order.

import { apiGet, apiPost } from "./client";

export type PaperConnectionStatus = "NOT_CONFIGURED" | "NOT_RUN" | "VERIFIED" | "AUTH_FAILED" | "UNREACHABLE";
export type McpSessionStatus = "NOT_STARTED" | "STARTING" | "HEALTHY" | "RECONNECTING" | "STOPPED" | "UNKNOWN";
export type KillSwitchReadinessStatus = "DISENGAGED" | "ENGAGED" | "UNKNOWN";

export type PaperDemoReadiness = {
  account_configured: boolean;
  account_connected: boolean;
  paper_url_locked: boolean;
  paper_connection_status: PaperConnectionStatus;
  paper_connection_checked_at: string | null;
  mcp_session_status: McpSessionStatus;
  active_option_contract_count: number;
  options_last_synced_at: string | null;
  trading_kill_switch_status: KillSwitchReadinessStatus;
  ready_for_paper_demo: boolean;
  non_transactional: true;
};

export async function fetchPaperDemoReadiness(): Promise<PaperDemoReadiness> {
  return apiGet<PaperDemoReadiness>("/api/demo-readiness");
}

export async function runPaperPreflight(): Promise<PaperDemoReadiness> {
  return apiPost<PaperDemoReadiness>("/api/demo-readiness/paper-preflight");
}
