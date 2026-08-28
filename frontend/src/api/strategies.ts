

import { apiDelete, apiGet, apiPatch, apiPost } from "./client";

export type ParameterFieldSchema = {
  type: "string" | "integer" | "number" | "boolean";
  enum?: string[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
};

export type ParameterSchema = {
  type: "object";
  properties: Record<string, ParameterFieldSchema>;
  required?: string[];
};

export type UiFieldSchema = {
  widget: "select" | "number" | "checkbox";
  label: string;
  order: number;
};

export type UiSchema = Record<string, UiFieldSchema>;

export type StrategyDefinition = {
  id: string;
  type_code: string;
  version: string;
  name: string;
  description: string;
  parameter_schema: ParameterSchema;
  ui_schema: UiSchema;
  defaults_by_profile: Record<string, Record<string, unknown>>;
  required_market_data: Record<string, unknown>;
  required_capabilities: string[];
};

export type StrategyInstanceStatus = "DRAFT" | "READY" | "ACTIVE" | "PAUSED" | "STOPPED" | "ERROR";

export type StrategyInstance = {
  id: string;
  type_code: string;
  name: string;
  symbols: string[];
  status: StrategyInstanceStatus;
  latest_signal: string | null;
};


export type StrategyInstanceDetail = {
  id: string;
  strategy_definition_id: string;
  type_code: string;
  name: string;
  definition_version: string;
  parameters: Record<string, unknown>;
  symbols: string[];
  risk_configuration: Record<string, unknown>;
  status: StrategyInstanceStatus;
  last_evaluated_at: string | null;
  next_evaluation_at: string | null;
  latest_signal: string | null;
  cloned_from_id: string | null;
  execution_context_id: string;
  created_at: string;
  updated_at: string;
};

export type CreateStrategyInstanceRequest = {
  type_code: string;
  name: string;
  symbols: string[];
  parameters: Record<string, unknown>;
  risk_configuration?: Record<string, unknown>;
};

export async function fetchStrategyDefinitions(): Promise<StrategyDefinition[]> {
  return apiGet<StrategyDefinition[]>("/api/strategies/definitions");
}

export async function fetchStrategyInstances(): Promise<StrategyInstance[]> {
  return apiGet<StrategyInstance[]>("/api/strategies/instances");
}

export async function createStrategyInstance(
  payload: CreateStrategyInstanceRequest,
): Promise<StrategyInstanceDetail> {
  return apiPost<StrategyInstanceDetail>("/api/strategies/instances", payload);
}

export async function cloneStrategyInstance(id: string, name?: string): Promise<StrategyInstanceDetail> {
  return apiPost<StrategyInstanceDetail>(`/api/strategies/instances/${id}/clone`, { name: name ?? null });
}

export async function activateStrategyInstance(id: string): Promise<StrategyInstanceDetail> {
  return apiPost<StrategyInstanceDetail>(`/api/strategies/instances/${id}/activate`);
}

export async function pauseStrategyInstance(id: string): Promise<StrategyInstanceDetail> {
  return apiPost<StrategyInstanceDetail>(`/api/strategies/instances/${id}/pause`);
}

export async function stopStrategyInstance(id: string): Promise<StrategyInstanceDetail> {
  return apiPost<StrategyInstanceDetail>(`/api/strategies/instances/${id}/stop`);
}

export async function updateStrategyInstance(
  id: string,
  payload: Partial<Pick<CreateStrategyInstanceRequest, "name" | "symbols" | "parameters" | "risk_configuration">>,
): Promise<StrategyInstanceDetail> {
  return apiPatch<StrategyInstanceDetail>(`/api/strategies/instances/${id}`, payload);
}

export async function deleteStrategyInstance(id: string): Promise<void> {
  return apiDelete(`/api/strategies/instances/${id}`);
}
