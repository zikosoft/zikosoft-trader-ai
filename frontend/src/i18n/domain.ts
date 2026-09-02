import type { Translate } from "./messages";

/** Resolve a known domain value through a stable UI key, keeping the API's
 * original value as a safe fallback for future backend additions. */
export function localizeValue(t: Translate, key: string, fallback: string): string {
  const translated = t(key);
  return translated === key ? fallback : translated;
}

export function contextLabel(t: Translate, kind: string): string {
  return localizeValue(t, `context.${kind}`, kind);
}

export function profileLabel(t: Translate, profile: string): string {
  return localizeValue(t, `profile.${profile}`, profile);
}

export function serviceLabel(t: Translate, service: string, fallback?: string): string {
  return localizeValue(t, `service.${service}`, fallback ?? service);
}

export function strategyLabel(t: Translate, typeCode: string, fallback: string): string {
  return localizeValue(t, `strategy.${typeCode}.name`, fallback);
}

export function strategyDescription(t: Translate, typeCode: string, fallback: string): string {
  return localizeValue(t, `strategy.${typeCode}.description`, fallback);
}

export function strategyParameterLabel(t: Translate, parameter: string, fallback: string): string {
  return localizeValue(t, `strategy.parameter.${parameter}`, fallback);
}

export function strategyEnumLabel(t: Translate, value: string): string {
  return localizeValue(t, `strategy.value.${value}`, value);
}
