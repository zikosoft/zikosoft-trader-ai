import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { I18nProvider } from "./i18n/I18nContext";
import { ThemeModeProvider } from "./ThemeModeContext";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("#root introuvable dans index.html");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <I18nProvider>
        <ThemeModeProvider>
          <App />
        </ThemeModeProvider>
      </I18nProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
