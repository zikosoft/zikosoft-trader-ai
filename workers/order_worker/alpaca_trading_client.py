"""AlpacaTradingClient — B17, frontière REST dédiée aux opérations
d'ÉCRITURE sur les ordres (passer/annuler/remplacer/lire). Distincte de
`backend/app/alpaca_client.py` (B07, lecture seule — `GET /v2/account`
uniquement) et de la session MCP du Market Agent (B10, toolset
volontairement `trading`-exclu, voir `agents/common/mcp_session.py`).

**Pourquoi un client dédié plutôt que le toolset MCP `trading` (D0xx,
AVANCEMENT.md §37) :** D006 ("Order Worker seul autorisé à exécuter")
est appliqué en confinant TOUT accès en écriture à Alpaca à cette classe,
utilisée par ce seul worker — le toolset MCP `trading` n'est activé nulle
part dans ce dépôt, ce qui rend la contrainte vérifiable par simple lecture
du code plutôt que dépendante d'une configuration.

**Paper uniquement** (même verrouillage que B07) — pas d'option pour
cibler l'API live.

**Honnêteté sur la couverture de test** : comme `alpaca_client.py` (B07),
ce module ne peut pas être exercé contre le vrai endpoint Alpaca depuis
cette sandbox (aucune clé réelle, aucun accès réseau sortant vers Alpaca).
Testé exclusivement via `respx` contre les formes de requête/réponse
documentées officiellement (voir AVANCEMENT.md, journal B17)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class AlpacaTradingError(Exception):
    """Base commune — permet un `except AlpacaTradingError` générique."""


class AlpacaTradingAuthError(AlpacaTradingError):
    """Identifiants rejetés (401/403 sans corps métier reconnu)."""


class AlpacaOrderRejected(AlpacaTradingError):
    """Alpaca a explicitement refusé l'ordre (422, ou 403 avec un message
    métier — fonds insuffisants, marché fermé, symbole invalide, ...).
    Distingué d'une erreur d'authentification ou réseau : c'est un résultat
    métier attendu, pas une panne."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class AlpacaTradingUpstreamError(AlpacaTradingError):
    """Timeout, 5xx, ou réponse illisible — distingué d'un rejet métier
    pour que l'appelant puisse décider différemment (retry raisonnable vs
    rejet définitif)."""


@dataclass(frozen=True)
class AlpacaOrder:
    """Sous-ensemble des champs de l'objet ordre Alpaca réellement
    consommés (même discipline que `AlpacaAccount`, B07 : ne pas prétendre
    couvrir un contrat non testé)."""

    id: str
    client_order_id: str
    status: str
    symbol: str
    side: str
    submitted_at: str | None
    request_id: str | None
    raw: dict[str, Any]


def _default_base_url() -> str:
    return os.environ.get("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")


class AlpacaTradingClient:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self._api_key, "APCA-API-SECRET-KEY": self._secret_key}

    # ------------------------------------------------------------------
    # Passage d'ordre — inclut le support "bracket" (take_profit/stop_loss
    # en jambes attachées, §checklist B17 "Gérer bracket order"). Voir
    # `workers/order_worker/main.py::_build_bracket_legs` pour le calcul
    # des prix à partir de `stop_loss_pct`/`take_profit_pct`/
    # `reference_price` — cette classe ne fait AUCUN calcul de prix,
    # uniquement du transport HTTP.
    # ------------------------------------------------------------------
    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        client_order_id: str,
        order_type: str = "market",
        time_in_force: str = "day",
        qty: float | None = None,
        notional: float | None = None,
        limit_price: float | None = None,
        order_class: str | None = None,
        take_profit: dict[str, str] | None = None,
        stop_loss: dict[str, str] | None = None,
    ) -> AlpacaOrder:
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
        }
        if qty is not None:
            body["qty"] = str(qty)
        if notional is not None:
            body["notional"] = str(notional)
        if limit_price is not None:
            body["limit_price"] = f"{limit_price:.2f}"
        if order_class is not None:
            body["order_class"] = order_class
        if take_profit is not None:
            body["take_profit"] = take_profit
        if stop_loss is not None:
            body["stop_loss"] = stop_loss

        response = self._request("POST", "/v2/orders", json=body)
        return self._parse_order(response)

    def cancel_order(self, provider_order_id: str) -> None:
        """`DELETE /v2/orders/{id}` — succès attendu : 204 (aucun corps)."""
        response = self._request("DELETE", f"/v2/orders/{provider_order_id}")
        if response.status_code not in (200, 204):
            self._raise_for_error(response)

    def replace_order(self, provider_order_id: str, **fields: Any) -> AlpacaOrder:
        """`PATCH /v2/orders/{id}` — `fields` transmis tels quels (ex.
        `qty`, `limit_price`, `time_in_force`, `client_order_id`) : ce
        module ne connaît pas par avance quels champs un futur appelant
        voudra remplacer, contrairement à `place_order` dont la forme est
        entièrement connue."""
        body = {k: (str(v) if v is not None else v) for k, v in fields.items()}
        response = self._request("PATCH", f"/v2/orders/{provider_order_id}", json=body)
        return self._parse_order(response)

    def get_order(self, provider_order_id: str) -> AlpacaOrder:
        """`GET /v2/orders/{id}` — utilisé par la réconciliation REST après
        reconnexion WebSocket (voir `trade_updates_listener.py`)."""
        response = self._request("GET", f"/v2/orders/{provider_order_id}")
        return self._parse_order(response)

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, *, json: dict | None = None) -> httpx.Response:
        try:
            return httpx.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AlpacaTradingUpstreamError("délai dépassé en contactant Alpaca") from exc
        except httpx.HTTPError as exc:
            raise AlpacaTradingUpstreamError(f"erreur réseau en contactant Alpaca : {exc}") from exc

    def _raise_for_error(self, response: httpx.Response) -> None:
        if response.status_code in (401,):
            raise AlpacaTradingAuthError("identifiants Alpaca refusés")
        message = None
        code = None
        try:
            body = response.json()
            if isinstance(body, dict):
                message = body.get("message")
                code = body.get("code")
        except ValueError:
            pass
        if response.status_code in (403, 422, 409):
            # §"fonds insuffisants"/"doublon reçu deux fois" (P0) : Alpaca
            # distingue un rejet métier (403/422, corps `{"code","message"}`
            # documenté) d'un refus d'authentification pur — traité comme un
            # résultat métier, pas une panne (voir `AlpacaOrderRejected`).
            raise AlpacaOrderRejected(message or f"Alpaca a rejeté la requête ({response.status_code})", code=code)
        raise AlpacaTradingUpstreamError(f"Alpaca a répondu {response.status_code} de façon inattendue : {message}")

    def _parse_order(self, response: httpx.Response) -> AlpacaOrder:
        if response.status_code not in (200, 201):
            self._raise_for_error(response)
        try:
            body = response.json()
            return AlpacaOrder(
                id=body["id"],
                client_order_id=body["client_order_id"],
                status=body["status"],
                symbol=body["symbol"],
                side=body["side"],
                submitted_at=body.get("submitted_at"),
                request_id=response.headers.get("x-request-id"),
                raw=body,
            )
        except (ValueError, KeyError) as exc:
            raise AlpacaTradingUpstreamError("réponse Alpaca illisible (champ manquant)") from exc
