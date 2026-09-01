// Client API pour l'authentification locale (B05).
//
// §B25 : `ApiError`/`parseOrThrow` ont déménagé vers `api/client.ts` (client
// API centralisé) — ce module se contente désormais de les consommer, comme
// tous les autres modules `api/*.ts`, plutôt que de les posséder par
// accident (c'était le premier module écrit, B05).

import { apiGet, apiPost, parseOrThrow } from "./client";

export type User = {
  id: string;
  email: string;
  display_name: string;
};

export async function fetchMe(): Promise<User | null> {
  const response = await fetch("/api/auth/me");
  if (response.status === 401) {
    return null;
  }
  const body = await parseOrThrow<{ user: User }>(response);
  return body.user;
}

export async function login(email: string, password: string): Promise<User> {
  const body = await apiPost<{ user: User }>("/api/auth/login", { email, password });
  return body.user;
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
}

export async function fetchDemoCredentials(): Promise<{ email: string; password: string } | null> {
  try {
    return await apiGet<{ email: string; password: string }>("/api/auth/demo-credentials");
  } catch {
    return null;
  }
}
