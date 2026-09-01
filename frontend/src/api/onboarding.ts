// Client API pour l'onboarding Alpaca (B07).

import { apiGet, apiPost } from "./client";

export type StepCode =
  | "credentials_validated"
  | "paper_environment_confirmed"
  | "account_synchronized"
  | "portfolio_loaded"
  | "assets_synchronized"
  | "market_stream_established"
  | "mcp_session_initialized"
  | "ai_agents_ready";

export type StepStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export type OnboardingStep = {
  step_code: StepCode;
  status: StepStatus;
  started_at: string | null;
  completed_at: string | null;
  error_details: { message?: string; note?: string; retriable?: boolean } | null;
};

export type Balance = {
  cash: number;
  buying_power: number;
  portfolio_value: number;
  snapshot_at: string;
};

export type OnboardingAccount = {
  id: string;
  environment: string;
  status: "pending" | "connected" | "failed";
  external_account_id: string | null;
  last_synced_at: string | null;
  balance: Balance | null;
};

export type OnboardingStatus = {
  account: OnboardingAccount | null;
  steps: OnboardingStep[];
};

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  return apiGet<OnboardingStatus>("/api/onboarding/status");
}

export async function connectAlpaca(apiKey: string, secretKey: string): Promise<OnboardingStatus> {
  return apiPost<OnboardingStatus>("/api/onboarding/connect", { api_key: apiKey, secret_key: secretKey });
}

export async function retryOnboardingStep(): Promise<OnboardingStatus> {
  return apiPost<OnboardingStatus>("/api/onboarding/retry");
}

export async function restartOnboarding(): Promise<OnboardingStatus> {
  return apiPost<OnboardingStatus>("/api/onboarding/restart");
}
