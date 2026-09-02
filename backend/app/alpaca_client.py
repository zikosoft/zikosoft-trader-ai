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
class AlpacaOptionContract:
    """Contract catalogue returned by ``/v2/options/contracts``.

    The fields mirror Alpaca's documented option-contract response while
    keeping the model deliberately small.  Option symbols are stored as the
    canonical/OCC symbol so the later Order Worker can submit the same value
    without another translation step.
    """

    id: str
    symbol: str
    name: str
    status: str
    tradable: bool
    expiration_date: str
    root_symbol: str
    underlying_symbol: str
    option_type: str
    strike_price: str
    size: int
    open_interest: int | None = None
    close_price: str | None = None


@dataclass(frozen=True)
class AlpacaOptionSnapshot:
    """Latest quote/trade snapshot for one option contract.

    Alpaca's market-data API uses camelCase keys (``latestQuote`` and
    ``latestTrade``); the client normalizes them here so all downstream code
    can use stable snake_case names.
    """

    symbol: str
    bid_price: float | None
    ask_price: float | None
    last_trade_price: float | None
    bid_size: int | None = None
    ask_size: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


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
        data_base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = (base_url or settings.alpaca_paper_base_url).rstrip("/")
        self._data_base_url = (data_base_url or settings.alpaca_data_base_url).rstrip("/")
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

    def get_option_contracts(
        self,
        *,
        underlying_symbol: str,
        status: str = "active",
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        option_type: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        limit: int = 100,
    ) -> list[AlpacaOptionContract]:
        """Fetch option contracts from Alpaca's Trading API catalogue.

        This is a read-only discovery call.  It intentionally uses the Paper
        Trading host (the same authenticated host as ``get_assets``), while
        quote snapshots use ``get_option_chain`` on Alpaca's market-data host.
        Pagination is followed up to the requested limit so callers receive a
        deterministic bounded result rather than an arbitrary first page.
        """
        if not underlying_symbol.strip():
            raise ValueError("underlying_symbol must not be empty")
        bounded_limit = max(1, min(int(limit), 1000))
        params: dict[str, str | int | float] = {
            "underlying_symbols": underlying_symbol.strip().upper(),
            "status": status,
            "limit": min(bounded_limit, 100),
        }
        optional = {
            "expiration_date_gte": expiration_date_gte,
            "expiration_date_lte": expiration_date_lte,
            "type": option_type,
            "strike_price_gte": strike_price_gte,
            "strike_price_lte": strike_price_lte,
        }
        params.update({key: value for key, value in optional.items() if value is not None})

        contracts: list[AlpacaOptionContract] = []
        page_token: str | None = None
        while len(contracts) < bounded_limit:
            if page_token:
                params["page_token"] = page_token
            response = self._request_json("GET", "/v2/options/contracts", params=params)
            body = response
            if not isinstance(body, dict) or not isinstance(body.get("option_contracts"), list):
                raise AlpacaUpstreamError("réponse Alpaca illisible (option_contracts manquant)")
            try:
                for item in body["option_contracts"]:
                    contracts.append(
                        AlpacaOptionContract(
                            id=str(item["id"]),
                            symbol=str(item["symbol"]),
                            name=str(item.get("name") or item["symbol"]),
                            status=str(item["status"]),
                            tradable=bool(item["tradable"]),
                            expiration_date=str(item["expiration_date"]),
                            root_symbol=str(item.get("root_symbol") or item.get("underlying_symbol") or underlying_symbol.upper()),
                            underlying_symbol=str(item.get("underlying_symbol") or underlying_symbol.upper()),
                            option_type=str(item["type"]).lower(),
                            strike_price=str(item["strike_price"]),
                            size=int(item.get("size", 100)),
                            open_interest=int(item["open_interest"]) if item.get("open_interest") is not None else None,
                            close_price=str(item["close_price"]) if item.get("close_price") is not None else None,
                        )
                    )
            except (TypeError, ValueError, KeyError) as exc:
                raise AlpacaUpstreamError("réponse Alpaca illisible (contrat option incomplet)") from exc
            contracts = contracts[:bounded_limit]
            page_token = body.get("page_token")
            if not page_token or not body["option_contracts"]:
                break
        return contracts

    def get_option_chain(
        self,
        *,
        underlying_symbol: str,
        option_type: str | None = None,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        feed: str | None = None,
        limit: int = 100,
    ) -> list[AlpacaOptionSnapshot]:
        """Fetch the latest option-chain snapshots from Alpaca market data."""
        if not underlying_symbol.strip():
            raise ValueError("underlying_symbol must not be empty")
        params: dict[str, str | int | float] = {"limit": max(1, min(int(limit), 1000))}
        optional = {
            "type": option_type,
            "expiration_date_gte": expiration_date_gte,
            "expiration_date_lte": expiration_date_lte,
            "strike_price_gte": strike_price_gte,
            "strike_price_lte": strike_price_lte,
            "feed": feed,
        }
        params.update({key: value for key, value in optional.items() if value is not None})
        body = self._request_json(
            "GET",
            f"/v1beta1/options/snapshots/{underlying_symbol.strip().upper()}",
            params=params,
            data_api=True,
        )
        if not isinstance(body, dict):
            raise AlpacaUpstreamError("réponse Alpaca illisible (chaîne options inattendue)")
        # The documented endpoint currently returns a symbol-keyed object;
        # tolerate a future/enveloped ``{"snapshots": {...}}`` response as
        # well so the read-only boundary remains forward compatible.
        if isinstance(body.get("snapshots"), dict):
            body = body["snapshots"]

        snapshots: list[AlpacaOptionSnapshot] = []
        try:
            for symbol, raw in body.items():
                if not isinstance(raw, dict):
                    continue
                quote = raw.get("latestQuote") or raw.get("latest_quote") or {}
                trade = raw.get("latestTrade") or raw.get("latest_trade") or {}
                greeks = raw.get("greeks") or {}

                def _float(source: dict, *keys: str) -> float | None:
                    for key in keys:
                        value = source.get(key)
                        if value is not None:
                            try:
                                return float(value)
                            except (TypeError, ValueError):
                                return None
                    return None

                def _int(source: dict, *keys: str) -> int | None:
                    for key in keys:
                        value = source.get(key)
                        if value is not None:
                            try:
                                return int(value)
                            except (TypeError, ValueError):
                                return None
                    return None

                snapshots.append(
                    AlpacaOptionSnapshot(
                        symbol=str(symbol),
                        bid_price=_float(quote, "bp", "bid_price", "bidPrice"),
                        ask_price=_float(quote, "ap", "ask_price", "askPrice"),
                        last_trade_price=_float(trade, "p", "price"),
                        bid_size=_int(quote, "bs", "bid_size", "bidSize"),
                        ask_size=_int(quote, "as", "ask_size", "askSize"),
                        implied_volatility=_float(greeks, "impliedVolatility", "implied_volatility"),
                        delta=_float(greeks, "delta"),
                        gamma=_float(greeks, "gamma"),
                        theta=_float(greeks, "theta"),
                        vega=_float(greeks, "vega"),
                    )
                )
        except (TypeError, ValueError) as exc:
            raise AlpacaUpstreamError("réponse Alpaca illisible (snapshot option incomplet)") from exc
        return snapshots

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int | float] | None = None,
        data_api: bool = False,
    ) -> object:
        """Authenticated JSON request shared by the read-only option calls."""
        base_url = self._data_base_url if data_api else self._base_url
        try:
            response = httpx.request(
                method,
                f"{base_url}{path}",
                headers={
                    "APCA-API-KEY-ID": self._api_key,
                    "APCA-API-SECRET-KEY": self._secret_key,
                },
                params=params,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AlpacaUpstreamError("délai dépassé en contactant Alpaca") from exc
        except httpx.HTTPError as exc:
            raise AlpacaUpstreamError(f"erreur réseau en contactant Alpaca : {exc}") from exc

        if response.status_code in (401, 403):
            raise AlpacaAuthError("identifiants Alpaca refusés")
        if response.status_code != 200:
            raise AlpacaUpstreamError(f"Alpaca a répondu {response.status_code} de façon inattendue")
        try:
            return response.json()
        except ValueError as exc:
            raise AlpacaUpstreamError("réponse Alpaca illisible (JSON attendu)") from exc

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
