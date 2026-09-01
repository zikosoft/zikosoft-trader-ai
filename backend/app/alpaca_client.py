"""Client Alpaca minimal (B07) — seul `GET /v2/account` est nécessaire pour
l'onboarding (vérifier les identifiants, récupérer le vrai solde). Pas de
SDK tiers : Alpaca expose une API REST simple, un client `httpx` direct
évite une dépendance de plus pour un seul endpoint.

Portée volontairement étroite : ce module est la SEULE frontière du code
avec Alpaca. Tout le reste (onboarding.py, routers/onboarding.py) parle à
`AlpacaClient`, jamais directement à `httpx`/Alpaca — ce qui permet de
tester le reste pour de vrai (Postgres/Redis réels) tout en substituant
uniquement cette frontière dans les tests automatisés (voir
tests/test_onboarding.py et le commentaire dans .env.example : Alpaca est un
tiers externe, pas notre infra, donc hors de la règle "pas de mock" qui
s'applique à PostgreSQL/Redis/notre propre API — cette même règle nous
empêche d'ailleurs de tester le VRAI aller-retour réseau ici sans de vraies
clés Alpaca, que nous n'avons pas en environnement de développement).

V1 : Paper uniquement (§B07 "Mode Paper verrouillé", D0xx à venir) — le
client ne prend même pas d'option pour cibler l'API live."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import settings


class AlpacaError(Exception):
    """Base commune — permet un `except AlpacaError` générique côté appelant."""


class AlpacaAuthError(AlpacaError):
    """Identifiants Alpaca rejetés (401/403) — §B07 "clé invalide rejetée
    clairement". Ne contient jamais la clé elle-même dans son message."""


class AlpacaUpstreamError(AlpacaError):
    """Alpaca a répondu autre chose qu'un succès ou un rejet d'identifiants
    (5xx, timeout, réponse illisible) — distingué de `AlpacaAuthError` pour
    que l'UI puisse afficher un message différent ("réessayer plus tard" vs
    "vérifiez votre clé")."""


@dataclass(frozen=True)
class AlpacaAccount:
    """Sous-ensemble des champs de `GET /v2/account` réellement utilisés par
    l'onboarding (§B07 "Affichage du véritable solde retourné" — jamais
    hard-codé) et, depuis B18, par le worker de portefeuille. Alpaca renvoie
    plus de champs ; on ne modélise que ceux consommés pour ne pas prétendre
    couvrir un contrat qu'on ne teste pas.

    §B18 ajoute `equity`/`last_equity` (vus via
    https://docs.alpaca.markets/us/reference/getaccount-1.md) : `equity` =
    cash + long_market_value + short_market_value (valeur totale du compte à
    l'instant présent) ; `last_equity` = `equity` telle qu'elle était à la
    clôture du jour de bourse précédent (16h ET). C'est la seule paire de
    champs qu'Alpaca expose pour calculer un P&L quotidien réel — voir
    `workers/portfolio_worker/main.py::_compute_daily_pl`. Optionnels (pas
    `str | None` mais absents du dataclass si Alpaca ne les renvoie pas dans
    un contexte de test qui ne les simule pas) pour ne pas casser
    `AlpacaAccount(...)` positionnel existant ailleurs — traités comme
    `None` par le worker si absents plutôt que de fabriquer un P&L."""

    id: str
    account_number: str
    status: str
    currency: str
    cash: str
    portfolio_value: str
    buying_power: str
    equity: str | None = None
    last_equity: str | None = None


@dataclass(frozen=True)
class AlpacaAsset:
    """Sous-ensemble des champs de `GET /v2/assets` réellement utilisés
    (§B09 — catalogue des actifs) — vus via
    https://docs.alpaca.markets/us/reference/get-v2-assets-1.md. Comme
    `AlpacaAccount`/`AlpacaPosition`, seuls les champs consommés sont
    modélisés (mêmes conventions : `tradable`/`fractionable`/`shortable`
    RÉELLEMENT utilisés par le catalogue, `id`/`symbol`/`name`/`class`/
    `exchange`/`status` pour le mapping canonique <-> provider)."""

    id: str
    symbol: str
    name: str
    asset_class: str
    exchange: str
    status: str
    tradable: bool
    fractionable: bool
    shortable: bool


@dataclass(frozen=True)
class AlpacaPosition:
    """Sous-ensemble des champs de `GET /v2/positions` réellement utilisés
    (§B18) — vus via https://docs.alpaca.markets/us/reference/getallopenpositions.md.
    Alpaca renvoie davantage de champs (asset_class, exchange, cost_basis,
    lastday_price, change_today, ...) ; comme `AlpacaAccount`, on ne modélise
    que ceux consommés pour ne pas prétendre couvrir un contrat qu'on ne
    teste pas."""

    symbol: str
    qty: str
    avg_entry_price: str
    market_value: str
    unrealized_pl: str
    current_price: str
    side: str


class AlpacaClient:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = (base_url or settings.alpaca_paper_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.alpaca_request_timeout_seconds

    def get_account(self) -> AlpacaAccount:
        """`GET /v2/account` — utilisé à la fois pour valider les
        identifiants (§B07 étape "credentials_validated") et pour lire le
        vrai solde (étapes suivantes). Clés envoyées en en-têtes HTTP,
        jamais en query string (§B07 "aucun secret dans URL")."""
        try:
            response = httpx.get(
                f"{self._base_url}/v2/account",
                headers={
                    "APCA-API-KEY-ID": self._api_key,
                    "APCA-API-SECRET-KEY": self._secret_key,
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AlpacaUpstreamError("délai dépassé en contactant Alpaca") from exc
        except httpx.HTTPError as exc:
            raise AlpacaUpstreamError(f"erreur réseau en contactant Alpaca : {exc}") from exc

        if response.status_code in (401, 403):
            raise AlpacaAuthError("identifiants Alpaca refusés")
        if response.status_code != 200:
            raise AlpacaUpstreamError(
                f"Alpaca a répondu {response.status_code} de façon inattendue"
            )

        try:
            body = response.json()
            return AlpacaAccount(
                id=body["id"],
                account_number=body["account_number"],
                status=body["status"],
                currency=body["currency"],
                cash=body["cash"],
                portfolio_value=body["portfolio_value"],
                buying_power=body["buying_power"],
                # §B18 — `.get()`, jamais `[...]` : contrairement aux champs
                # ci-dessus (déjà exigés par B07 depuis le premier jour),
                # l'absence d'`equity`/`last_equity` ne doit pas faire
                # échouer `get_account()` pour les appelants qui n'en ont
                # pas besoin (onboarding.py) ni casser une réponse simulée
                # plus ancienne dans les tests existants.
                equity=body.get("equity"),
                last_equity=body.get("last_equity"),
            )
        except (ValueError, KeyError) as exc:
            raise AlpacaUpstreamError("réponse Alpaca illisible (champ manquant)") from exc

    def get_assets(self, *, status: str = "active", asset_class: str = "us_equity") -> list[AlpacaAsset]:
        """`GET /v2/assets` (§B09) — catalogue des actifs négociables chez
        Alpaca. Contrairement à `get_account()`/`get_positions()`, cette
        route accepte des paramètres de requête (`status`/`asset_class`,
        jamais de secret — §B07 "aucun secret dans URL", toujours respecté
        ici, seules les clés d'auth restent en en-tête). Alpaca ne pagine
        pas cet endpoint (retourne la liste complète en un seul appel,
        potentiellement plusieurs milliers d'actifs pour `us_equity`) —
        même limite honnête que `get_account()`/`get_positions()` : jamais
        validé contre le vrai endpoint Alpaca depuis cette sandbox (aucune
        clé réelle, aucun accès réseau sortant), voir R21/R23."""
        try:
            response = httpx.get(
                f"{self._base_url}/v2/assets",
                headers={
                    "APCA-API-KEY-ID": self._api_key,
                    "APCA-API-SECRET-KEY": self._secret_key,
                },
                params={"status": status, "asset_class": asset_class},
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AlpacaUpstreamError("délai dépassé en contactant Alpaca") from exc
        except httpx.HTTPError as exc:
            raise AlpacaUpstreamError(f"erreur réseau en contactant Alpaca : {exc}") from exc

        if response.status_code in (401, 403):
            raise AlpacaAuthError("identifiants Alpaca refusés")
        if response.status_code != 200:
            raise AlpacaUpstreamError(
                f"Alpaca a répondu {response.status_code} de façon inattendue"
            )

        try:
            body = response.json()
            if not isinstance(body, list):
                raise ValueError("réponse /v2/assets inattendue (pas une liste)")
            return [
                AlpacaAsset(
                    id=item["id"],
                    symbol=item["symbol"],
                    name=item.get("name") or item["symbol"],
                    asset_class=item["class"],
                    exchange=item["exchange"],
                    status=item["status"],
                    tradable=bool(item["tradable"]),
                    fractionable=bool(item.get("fractionable", False)),
                    shortable=bool(item.get("shortable", False)),
                )
                for item in body
            ]
        except (ValueError, KeyError) as exc:
            raise AlpacaUpstreamError("réponse Alpaca illisible (champ manquant)") from exc

    def get_positions(self) -> list[AlpacaPosition]:
        """`GET /v2/positions` (§B18) — liste des positions ouvertes du
        compte Paper. Alpaca renvoie `[]` (200) quand aucune position n'est
        ouverte, jamais une erreur — voir
        https://docs.alpaca.markets/us/reference/getallopenpositions.md."""
        try:
            response = httpx.get(
                f"{self._base_url}/v2/positions",
                headers={
                    "APCA-API-KEY-ID": self._api_key,
                    "APCA-API-SECRET-KEY": self._secret_key,
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AlpacaUpstreamError("délai dépassé en contactant Alpaca") from exc
        except httpx.HTTPError as exc:
            raise AlpacaUpstreamError(f"erreur réseau en contactant Alpaca : {exc}") from exc

        if response.status_code in (401, 403):
            raise AlpacaAuthError("identifiants Alpaca refusés")
        if response.status_code != 200:
            raise AlpacaUpstreamError(
                f"Alpaca a répondu {response.status_code} de façon inattendue"
            )

        try:
            body = response.json()
            if not isinstance(body, list):
                raise ValueError("réponse /v2/positions inattendue (pas une liste)")
            return [
                AlpacaPosition(
                    symbol=item["symbol"],
                    qty=item["qty"],
                    avg_entry_price=item["avg_entry_price"],
                    market_value=item["market_value"],
                    unrealized_pl=item["unrealized_pl"],
                    current_price=item["current_price"],
                    side=item["side"],
                )
                for item in body
            ]
        except (ValueError, KeyError) as exc:
            raise AlpacaUpstreamError("réponse Alpaca illisible (champ manquant)") from exc
