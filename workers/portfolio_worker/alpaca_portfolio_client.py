"""AlpacaPortfolioClient — B18, frontière REST dédiée à la LECTURE du
compte/positions Alpaca (`GET /v2/account`, `GET /v2/positions`). Distincte
de `backend/app/alpaca_client.py` (B07, même API mais depuis l'image
backend-api — les workers n'ont pas accès à `backend`, voir docstring de
`agents/market_agent/main.py`) et d'`AlpacaTradingClient` (B17, écriture sur
les ordres, `workers/order_worker/alpaca_trading_client.py`).

**Pourquoi un client REST dédié plutôt que la session MCP du Market Agent :**
le Market Agent (B10) possède LA session MCP par compte pour les données de
MARCHÉ (`get_clock`, `get_stock_snapshot`, `get_stock_bars`, `get_news`) —
un seul point de déchiffrement/rate-limit pour cette préoccupation précise
(voir docstring de `market_agent/main.py`). Le compte/les positions sont une
préoccupation DIFFÉRENTE (état du portefeuille, pas données de marché), avec
son propre rythme de rafraîchissement (voir `PORTFOLIO_SNAPSHOT_INTERVAL_SECONDS`
dans `main.py`) — même principe de séparation par préoccupation que D037
(B17, ordres vs marché). Un client REST direct, périodique et sans état,
correspond mieux à ce besoin qu'une session WebSocket/MCP persistante.

**Paper uniquement** (même verrouillage que B07/B17) — pas d'option pour
cibler l'API live.

**Honnêteté sur la couverture de test** : comme `alpaca_client.py`/
`alpaca_trading_client.py`, ce module ne peut pas être exercé contre le
vrai endpoint Alpaca depuis cette sandbox. Testé exclusivement via `respx`
contre les formes de requête/réponse documentées officiellement (voir
https://docs.alpaca.markets/us/reference/getaccount-1.md et
.../getallopenpositions.md, et AVANCEMENT.md journal B18)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class AlpacaPortfolioError(Exception):
    """Base commune — permet un `except AlpacaPortfolioError` générique."""


class AlpacaPortfolioAuthError(AlpacaPortfolioError):
    """Identifiants Alpaca refusés (401/403)."""


class AlpacaPortfolioUpstreamError(AlpacaPortfolioError):
    """Timeout, 5xx, ou réponse illisible."""


@dataclass(frozen=True)
class AlpacaAccountSnapshot:
    """Sous-ensemble des champs de `GET /v2/account` consommés par ce
    worker (mêmes noms que `backend.app.alpaca_client.AlpacaAccount` par
    cohérence, mais classe distincte — pas d'import cross-image, voir
    docstring du module)."""

    cash: str
    buying_power: str
    portfolio_value: str
    equity: str | None
    last_equity: str | None


@dataclass(frozen=True)
class AlpacaPositionSnapshot:
    symbol: str
    qty: str
    avg_entry_price: str
    market_value: str
    unrealized_pl: str


def _default_base_url() -> str:
    return os.environ.get("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")


class AlpacaPortfolioClient:
    def __init__(self, api_key: str, secret_key: str, *, base_url: str | None = None, timeout: float = 10.0) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self._api_key, "APCA-API-SECRET-KEY": self._secret_key}

    def _get(self, path: str) -> httpx.Response:
        try:
            return httpx.get(f"{self._base_url}{path}", headers=self._headers(), timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise AlpacaPortfolioUpstreamError("délai dépassé en contactant Alpaca") from exc
        except httpx.HTTPError as exc:
            raise AlpacaPortfolioUpstreamError(f"erreur réseau en contactant Alpaca : {exc}") from exc

    def _check_status(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise AlpacaPortfolioAuthError("identifiants Alpaca refusés")
        if response.status_code != 200:
            raise AlpacaPortfolioUpstreamError(f"Alpaca a répondu {response.status_code} de façon inattendue")

    def get_account(self) -> AlpacaAccountSnapshot:
        response = self._get("/v2/account")
        self._check_status(response)
        try:
            body = response.json()
            return AlpacaAccountSnapshot(
                cash=body["cash"],
                buying_power=body["buying_power"],
                portfolio_value=body["portfolio_value"],
                equity=body.get("equity"),
                last_equity=body.get("last_equity"),
            )
        except (ValueError, KeyError) as exc:
            raise AlpacaPortfolioUpstreamError("réponse Alpaca illisible (champ manquant)") from exc

    def get_positions(self) -> list[AlpacaPositionSnapshot]:
        """`GET /v2/positions` — Alpaca renvoie `[]` (200), jamais une
        erreur, quand aucune position n'est ouverte."""
        response = self._get("/v2/positions")
        self._check_status(response)
        try:
            body = response.json()
            if not isinstance(body, list):
                raise ValueError("réponse /v2/positions inattendue (pas une liste)")
            return [
                AlpacaPositionSnapshot(
                    symbol=item["symbol"],
                    qty=item["qty"],
                    avg_entry_price=item["avg_entry_price"],
                    market_value=item["market_value"],
                    unrealized_pl=item["unrealized_pl"],
                )
                for item in body
            ]
        except (ValueError, KeyError) as exc:
            raise AlpacaPortfolioUpstreamError("réponse Alpaca illisible (champ manquant)") from exc
