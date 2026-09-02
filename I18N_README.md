# Internationalization (i18n)

ZikosoftTrader AI uses a frontend-first internationalization layer. English is the default locale and the current locale is persisted in both a cookie and `localStorage`, so a refresh keeps the user's choice.

## Supported languages

| Code | Language | Flag | Intl locale |
| --- | --- | --- | --- |
| `en` | English (default) | 🇺🇸 | `en-US` |
| `fr` | Français | 🇫🇷 | `fr-FR` |
| `pt` | Português | 🇵🇹 | `pt-PT` |
| `es` | Español | 🇪🇸 | `es-ES` |
| `de` | Deutsch | 🇩🇪 | `de-DE` |

## File layout

- `frontend/src/i18n/config.ts` defines the supported locale metadata, default locale, cookie name, and storage key.
- `frontend/src/i18n/locales/*.json` contains the translated message dictionaries. Keys are stable dotted identifiers; components never depend on translated text.
- `frontend/src/i18n/messages.ts` loads dictionaries and falls back to English when a newly added key is not translated yet.
- `frontend/src/i18n/I18nContext.tsx` exposes `useI18n()` and updates the document language and text direction.
- `frontend/src/i18n/formatters.ts` keeps dates, numbers, and currencies consistent with the selected locale.

The language selector is available in the signed-in user's header menu. It displays the language flag and native name.

## Adding a language

1. Add a new JSON file under `frontend/src/i18n/locales/` using the same keys as `en.json`.
2. Add the locale metadata (code, native name, flag, and Intl locale) to `SUPPORTED_LOCALES` in `frontend/src/i18n/config.ts`.
3. Import the dictionary and register it in `frontend/src/i18n/messages.ts`.
4. Add the language's display label to each dictionary (`language.<code>`), then verify that every key in `en.json` exists in the new file.
5. Run the frontend build (`npm run build`) and manually switch to the new language from the user menu.

No backend rewrite is required for UI translations. API errors continue to use stable backend error codes; `frontend/src/api/client.ts` maps those codes to localized `errors.<CODE>` messages. Backend response data remains machine-readable and is localized at the presentation boundary.

