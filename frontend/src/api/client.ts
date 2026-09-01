// Client API centralisé (§B25 "Client API centralisé"). Avant B25, chaque
// module `api/*.ts` dupliquait son propre `fetch("/api/...")` et un même
// `ApiError`/`parseOrThrow` vivait accidentellement dans `auth.ts` (premier
// module écrit, B05) puis était réimporté par les autres — fonctionnel,
// mais la dépendance implicite "tout le monde importe de auth.ts" n'avait
// aucun sens architectural. Ce module devient l'UNIQUE point d'entrée HTTP :
// tous les modules `api/*.ts` importent `ApiError`/`parseOrThrow`/`apiGet`/
// `apiPost` d'ici, plus jamais de `auth.ts`.
//
// Les appels restent relatifs (`/api/...`, same-origin via le proxy Vite,
// voir vite.config.ts) — le cookie de session posé par le backend (B05)
// continue de voyager automatiquement, aucune manipulation manuelle requise.

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    request_id: string;
    occurred_at: string;
    details?: Record<string, unknown> | null;
  };
};

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown> | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.code = body.error.code;
    this.status = status;
    this.details = body.error.details ?? null;
  }
}

export async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json()) as ApiErrorBody;
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

// §"Impossible de contacter le serveur" — message affiché partout dans le
// frontend (LoginForm, ContextChooser, Onboarding, ContextSwitcher…) quand
// une erreur n'est PAS une `ApiError` (le backend a répondu avec un format
// d'erreur reconnu) mais un échec réseau brut (backend injoignable, DNS,
// CORS…). Centralisé ici pour que tout appelant produise le même message
// sans le retaper.
export const NETWORK_ERROR_MESSAGE = "Impossible de contacter le serveur.";

export function describeError(err: unknown): string {
  return err instanceof ApiError ? err.message : NETWORK_ERROR_MESSAGE;
}

// GET simple — la majorité des lectures de l'app.
export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  return parseOrThrow<T>(response);
}

// POST JSON — la majorité des écritures de l'app. `body` omis = POST sans
// corps (ex. logout, retry) plutôt que d'envoyer `"null"` ou `"{}"` à tort.
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return parseOrThrow<T>(response);
}

// PUT JSON — mise à jour d'une ressource existante en un appel (ex.
// `PUT /api/settings/ai`, B10/D026) plutôt qu'un POST sémantiquement
// incorrect pour une écriture idempotente sur une ressource déjà nommée.
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseOrThrow<T>(response);
}

// PATCH JSON — mise à jour partielle (ex. `PATCH /api/strategies/instances/{id}`,
// B12/écran dédié du 28/08) : premier appelant PATCH du frontend, même
// convention que `apiPut`/`apiPost` ci-dessus.
export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseOrThrow<T>(response);
}

// DELETE — sans corps de requête ni de réponse (§`DELETE /api/strategies/instances/{id}`
// répond `204 No Content`, B12) : `parseOrThrow` appelle inconditionnellement
// `response.json()` sur un succès, ce qui lèverait sur un corps vide — cette
// fonction gère donc le succès elle-même plutôt que de réutiliser `parseOrThrow`.
export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(path, { method: "DELETE" });
  if (!response.ok) {
    const body = (await response.json()) as ApiErrorBody;
    throw new ApiError(response.status, body);
  }
}
