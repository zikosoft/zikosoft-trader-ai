

import { apiGet, apiPut } from "./client";

export type ExperienceProfile = "novice" | "intermediate" | "expert";

export const PROFILE_ORDER: ExperienceProfile[] = ["novice", "intermediate", "expert"];

export const PROFILE_LABELS: Record<ExperienceProfile, string> = {
  novice: "Novice",
  intermediate: "Intermédiaire",
  expert: "Expert",
};

export type ProfileLimits = {
  max_active_strategies: number;
  max_symbols: number;
  order_risk_pct: number;
  daily_loss_pct: number;
  approval_mode: string;
};

export type UserProfile = {
  profile: ExperienceProfile;
  limits: ProfileLimits;
};

export async function fetchUserProfile(): Promise<UserProfile> {
  return apiGet<UserProfile>("/api/settings/profile");
}

export async function updateUserProfile(profile: ExperienceProfile): Promise<UserProfile> {
  return apiPut<UserProfile>("/api/settings/profile", { profile });
}



export function isProfileIncrease(from: ExperienceProfile, to: ExperienceProfile): boolean {
  return PROFILE_ORDER.indexOf(to) > PROFILE_ORDER.indexOf(from);
}
