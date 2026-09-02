import type { Locale } from "./config";
import { getLocaleMetadata } from "./config";

export function formatCurrency(locale: Locale, value: number, currency = "USD"): string {
  return new Intl.NumberFormat(getLocaleMetadata(locale).intlLocale, { style: "currency", currency }).format(value);
}

export function formatNumber(
  locale: Locale,
  value: number,
  options: Intl.NumberFormatOptions = {},
): string {
  return new Intl.NumberFormat(getLocaleMetadata(locale).intlLocale, options).format(value);
}

export function formatDateTime(
  locale: Locale,
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "medium" },
): string {
  return new Intl.DateTimeFormat(getLocaleMetadata(locale).intlLocale, options).format(new Date(value));
}

export function formatDate(
  locale: Locale,
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium" },
): string {
  return new Intl.DateTimeFormat(getLocaleMetadata(locale).intlLocale, options).format(new Date(value));
}
