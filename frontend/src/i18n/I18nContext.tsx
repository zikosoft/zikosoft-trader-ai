import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getLocaleMetadata, persistLocale, readStoredLocale, type Locale } from "./config";
import { translate, type Translate, type TranslationParams } from "./messages";

type I18nContextValue = {
  locale: Locale;
  intlLocale: string;
  setLocale: (locale: Locale) => void;
  t: Translate;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  const setLocale = useCallback((nextLocale: Locale) => {
    persistLocale(nextLocale);
    setLocaleState(nextLocale);
  }, []);

  useEffect(() => {
    const metadata = getLocaleMetadata(locale);
    document.documentElement.lang = locale;
    document.documentElement.dir = "ltr";
    document.documentElement.dataset.locale = locale;
    document.title = "ZikosoftTrader AI";
    // Keep the browser's formatting conventions aligned with the selected UI
    // language. `metadata` is intentionally read here so a locale config
    // change remains a single-source update.
    document.documentElement.dataset.intlLocale = metadata.intlLocale;
  }, [locale]);

  const t = useCallback(
    (key: string, params?: TranslationParams) => translate(locale, key, params),
    [locale],
  );

  const value = useMemo<I18nContextValue>(
    () => ({ locale, intlLocale: getLocaleMetadata(locale).intlLocale, setLocale, t }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used inside I18nProvider");
  }
  return context;
}
