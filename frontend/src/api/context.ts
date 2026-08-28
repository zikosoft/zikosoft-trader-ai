

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
