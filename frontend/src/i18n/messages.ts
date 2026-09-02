import de from "./locales/de.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import pt from "./locales/pt.json";
import { DEFAULT_LOCALE, readStoredLocale, type Locale } from "./config";

export type TranslationParams = Record<string, string | number | boolean | null | undefined>;
export type Translate = (key: string, params?: TranslationParams) => string;

type MessageDictionary = Record<string, string>;

const dictionaries: Record<Locale, MessageDictionary> = { en, fr, pt, es, de };

function interpolate(message: string, params?: TranslationParams): string {
  if (!params) return message;

  return message.replace(/{{\s*([\w.]+)\s*}}/g, (_match, name: string) => {
    const value = params[name];
    return value === undefined || value === null ? "" : String(value);
  });
}

/**
 * Translates a stable dotted key. A missing non-English value falls back to
 * English, while an unknown key is returned unchanged so gaps are obvious in
 * development instead of silently rendering an empty label.
 */
export function translate(locale: Locale, key: string, params?: TranslationParams): string {
  const message = dictionaries[locale][key] ?? dictionaries[DEFAULT_LOCALE][key];
  return message ? interpolate(message, params) : key;
}

export function hasTranslation(locale: Locale, key: string): boolean {
  return Boolean(dictionaries[locale][key] ?? dictionaries[DEFAULT_LOCALE][key]);
}

export function translateCurrentLocale(key: string, params?: TranslationParams): string {
  return translate(readStoredLocale(), key, params);
}

export function translateEnum(t: Translate, namespace: string, value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  const key = `${namespace}.${value}`;
  const translated = t(key);
  return translated === key ? value : translated;
}
