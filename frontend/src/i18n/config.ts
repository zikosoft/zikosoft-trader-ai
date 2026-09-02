export const DEFAULT_LOCALE = "en" as const;
export const LOCALE_COOKIE_NAME = "zikosofttrader_locale";
export const LOCALE_STORAGE_KEY = "zikosofttrader.locale";

export const SUPPORTED_LOCALES = [
  { code: "en", nativeName: "English", flag: "🇺🇸", intlLocale: "en-US" },
  { code: "fr", nativeName: "Français", flag: "🇫🇷", intlLocale: "fr-FR" },
  { code: "pt", nativeName: "Português", flag: "🇵🇹", intlLocale: "pt-PT" },
  { code: "es", nativeName: "Español", flag: "🇪🇸", intlLocale: "es-ES" },
  { code: "de", nativeName: "Deutsch", flag: "🇩🇪", intlLocale: "de-DE" },
] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number]["code"];

const ONE_YEAR_IN_SECONDS = 60 * 60 * 24 * 365;

export function isLocale(value: string | null | undefined): value is Locale {
  return SUPPORTED_LOCALES.some((locale) => locale.code === value);
}

function readLocaleCookie(): Locale | null {
  if (typeof document === "undefined") return null;

  const cookie = document.cookie
    .split(";")
    .map((entry) => entry.trim())
    .find((entry) => entry.startsWith(`${LOCALE_COOKIE_NAME}=`));
  const value = cookie?.slice(LOCALE_COOKIE_NAME.length + 1);

  return isLocale(value) ? value : null;
}

export function readStoredLocale(): Locale {
  const cookieLocale = readLocaleCookie();
  if (cookieLocale) return cookieLocale;

  try {
    const localStorageLocale = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (isLocale(localStorageLocale)) return localStorageLocale;
  } catch {
    // Local storage can be unavailable in strict privacy contexts. The app
    // still works with the English default and the preference cookie.
  }

  return DEFAULT_LOCALE;
}

export function persistLocale(locale: Locale): void {
  if (typeof document !== "undefined") {
    document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; Path=/; Max-Age=${ONE_YEAR_IN_SECONDS}; SameSite=Lax`;
  }

  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // The cookie remains the primary persistence mechanism.
  }
}

export function getLocaleMetadata(locale: Locale) {
  return SUPPORTED_LOCALES.find((candidate) => candidate.code === locale) ?? SUPPORTED_LOCALES[0];
}
