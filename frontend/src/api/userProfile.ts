// Client API pour le profil d'expérience utilisateur (§B30
// "novice/intermediate/expert" — `backend/app/routers/user_profile.py`).
// Indépendant du pipeline d'onboarding (voir docstring backend) : lu/écrit
// depuis Settings ET depuis l'écran d'onboarding via CE client, jamais via
// une étape `_STUBBED_STEPS`.

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

// §"Avertissement si le niveau d'autonomie augmente" — comparaison
// client-side sur `PROFILE_ORDER` (même principe que
// `profile_limits.is_increase()` côté backend, jamais appelé depuis le
// frontend : la confirmation vit entièrement côté UI, le backend accepte
// le changement une fois confirmé, voir `user_profile.py`).
export function isProfileIncrease(from: ExperienceProfile, to: ExperienceProfile): boolean {
  return PROFILE_ORDER.indexOf(to) > PROFILE_ORDER.indexOf(from);
}
