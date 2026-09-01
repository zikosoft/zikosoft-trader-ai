// Client API pour les contextes Replay/Paper (B06).

import { apiGet, ApiError } from "./client";

export type ContextKind = "PAPER" | "REPLAY";

export type ExecutionContext = {
  id: string;
  kind: ContextKind;
  label: string;
  is_active: boolean;
};

export type ContextListResponse = {
  contexts: ExecutionContext[];
  active_kind: ContextKind | null;
};

export async function fetchContexts(): Promise<ContextListResponse> {
  return apiGet<ContextListResponse>("/api/contexts");
}

// Renvoie soit la nouvelle liste (succès), soit `{ confirmationRequired }`
// si le backend renvoie 409 CONFLICT (changement de contexte sans
// confirmation, §B06) — l'appelant décide alors d'afficher une confirmation
// puis de rejouer l'appel avec `confirm: true`, plutôt que de traiter ça
// comme une erreur générique. Ce cas de figure (un 409 métier attendu, pas
// une erreur) est la raison pour laquelle cette fonction n'utilise pas
// simplement `apiPost` — elle a besoin d'inspecter le statut avant de
// décider s'il s'agit d'une erreur ou d'un résultat normal.
export async function selectContext(
  kind: ContextKind,
  confirm = false,
): Promise<ContextListResponse | { confirmationRequired: true; activeKind: ContextKind }> {
  const response = await fetch("/api/contexts/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, confirm }),
  });
  if (response.status === 409) {
    const body = await response.json();
    return { confirmationRequired: true, activeKind: body.error.details.active_kind };
  }
  if (!response.ok) {
    const body = await response.json();
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as ContextListResponse;
}
