"""B09 — Catalogue des actifs Alpaca. Deux niveaux de couverture, même
discipline que le reste du projet (PostgreSQL/Redis réels, seule la
frontière Alpaca est simulée) :

- `TestSyncAssetsUnit` : `app/assets.py::sync_assets`/`last_sync_status`
  appelés directement contre une vraie session PostgreSQL, avec un
  `client_factory` factice (pas de `respx` ici — la frontière HTTP est déjà
  couverte par `test_alpaca_client.py::TestGetAssets`, inutile de la
  redupliquer) — se concentre sur la logique d'upsert/désactivation.
- `TestAssetsRouter` : `POST/GET /api/assets/*` via `TestClient`, en
  s'appuyant sur `POST /api/onboarding/connect` (respx-mocké, même
  convention que `test_onboarding.py`) pour obtenir un compte connecté
  plutôt que de fabriquer un `UserTradingAccount` à la main."""

from __future__ import annotations

import httpx
import pytest
import respx
from app.alpaca_client import AlpacaAsset
from app.assets import AssetSyncError, last_sync_status, sync_assets
from app.config import settings
from app.db import engine
from app.main import app
from app.models import UserTradingAccount
from app.seed import seed_demo_user, seed_trading_provider
from fastapi.testclient import TestClient
from sqlalchemy import text

ALPACA_ACCOUNT_URL = f"{settings.alpaca_paper_base_url}/v2/account"
ALPACA_ASSETS_URL = f"{settings.alpaca_paper_base_url}/v2/assets"

_AAPL = AlpacaAsset(
    id="asset-aapl",
    symbol="AAPL",
    name="Apple Inc.",
    asset_class="us_equity",
    exchange="NASDAQ",
    status="active",
    tradable=True,
    fractionable=True,
    shortable=True,
)
_HALTED = AlpacaAsset(
    id="asset-halted",
    symbol="HALTED",
    name="Halted Co.",
    asset_class="us_equity",
    exchange="NASDAQ",
    status="active",
    tradable=False,
    fractionable=False,
    shortable=False,
)


def _account_response(**overrides) -> dict:
    body = {
        "id": "alpaca-account-123",
        "account_number": "PA000TEST",
        "status": "ACTIVE",
        "currency": "USD",
        "cash": "98765.43",
        "portfolio_value": "100000.00",
        "buying_power": "197530.86",
    }
    body.update(overrides)
    return body


def _assets_json(*assets: AlpacaAsset) -> list[dict]:
    return [
        {
            "id": a.id,
            "symbol": a.symbol,
            "name": a.name,
            "class": a.asset_class,
            "exchange": a.exchange,
            "status": a.status,
            "tradable": a.tradable,
            "fractionable": a.fractionable,
            "shortable": a.shortable,
        }
        for a in assets
    ]


class _FakeAlpacaClient:
    """Injecté via `client_factory` — évite de dupliquer la couverture
    HTTP de `test_alpaca_client.py` pour tester uniquement la logique
    d'upsert de `sync_assets`."""

    _NEXT_RESULT: list[AlpacaAsset] = []
    _NEXT_ERROR: Exception | None = None

    def __init__(self, api_key: str, secret_key: str) -> None:
        self.api_key = api_key
        self.secret_key = secret_key

    def get_assets(self, *, status: str, asset_class: str) -> list[AlpacaAsset]:
        if _FakeAlpacaClient._NEXT_ERROR is not None:
            raise _FakeAlpacaClient._NEXT_ERROR
        return _FakeAlpacaClient._NEXT_RESULT


def _wipe():
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM provider_assets"))
        conn.execute(text("DELETE FROM assets"))
        conn.execute(text("DELETE FROM onboarding_steps"))
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM user_trading_accounts"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.execute(text("DELETE FROM user_sessions"))
        conn.commit()


@pytest.fixture(autouse=True)
def _clean_assets_state(redis_client):
    # `redis_client.flushdb()` est indispensable ici (pas seulement le
    # ménage Postgres) : le rate-limiter de `/api/auth/login` (§B05) est
    # backé par Redis et partagé par tout le process pytest — sans ce
    # flush, les nombreux `logged_in_client` de ce module fini(ssen)t par
    # se heurter à un 429 hérité d'un test précédent (même principe déjà
    # appliqué par `test_onboarding.py::_clean_onboarding_state`).
    _wipe()
    redis_client.flushdb()
    yield
    _wipe()
    redis_client.flushdb()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def logged_in_client(client):
    response = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": settings.demo_user_password},
    )
    assert response.status_code == 200
    return client


class TestSyncAssetsUnit:
    def _account(self, db_session) -> UserTradingAccount:
        from app.encryption import encrypt_secret

        user = seed_demo_user(db_session)
        provider = seed_trading_provider(db_session)
        account = UserTradingAccount(
            user_id=user.id,
            trading_provider_id=provider.id,
            # `sync_assets` déchiffre réellement ces valeurs (même client
            # `_FakeAlpacaClient` ensuite injecté via `client_factory` —
            # seule la frontière HTTP Alpaca est simulée, pas le
            # chiffrement) — il faut donc de vrais secrets chiffrés, pas
            # une chaîne arbitraire.
            encrypted_api_key=encrypt_secret("fake-api-key"),
            encrypted_secret_key=encrypt_secret("fake-secret-key"),
            status="connected",
        )
        db_session.add(account)
        db_session.flush()
        return account

    def test_first_sync_creates_assets_and_provider_assets(self, db_session):
        account = self._account(db_session)
        _FakeAlpacaClient._NEXT_RESULT = [_AAPL, _HALTED]
        _FakeAlpacaClient._NEXT_ERROR = None

        result = sync_assets(db_session, account, client_factory=_FakeAlpacaClient)
        db_session.commit()

        assert result.synced_count == 2
        assert result.created_count == 2
        assert result.updated_count == 0
        assert result.deactivated_count == 0

        synced_at, total = last_sync_status(db_session, account)
        assert synced_at is not None
        assert total == 2

    def test_resync_updates_existing_and_deactivates_missing_without_deleting(self, db_session):
        account = self._account(db_session)
        _FakeAlpacaClient._NEXT_RESULT = [_AAPL, _HALTED]
        _FakeAlpacaClient._NEXT_ERROR = None
        sync_assets(db_session, account, client_factory=_FakeAlpacaClient)
        db_session.commit()

        # Deuxième sync : HALTED n'est plus renvoyé par Alpaca (retiré du
        # catalogue) ; AAPL revient avec un nom mis à jour.
        renamed_aapl = AlpacaAsset(
            id=_AAPL.id,
            symbol="AAPL",
            name="Apple Inc. (renamed)",
            asset_class="us_equity",
            exchange="NASDAQ",
            status="active",
            tradable=True,
            fractionable=True,
            shortable=True,
        )
        _FakeAlpacaClient._NEXT_RESULT = [renamed_aapl]

        result = sync_assets(db_session, account, client_factory=_FakeAlpacaClient)
        db_session.commit()

        assert result.synced_count == 1
        assert result.created_count == 0
        assert result.updated_count == 1
        assert result.deactivated_count == 1

        rows = db_session.execute(text("SELECT canonical_symbol, label FROM assets ORDER BY canonical_symbol")).all()
        assert [r.canonical_symbol for r in rows] == ["AAPL", "HALTED"]  # §jamais supprimé
        assert dict(rows)["AAPL"] == "Apple Inc. (renamed)"

        statuses = dict(
            db_session.execute(text("SELECT provider_symbol, status FROM provider_assets")).all()
        )
        assert statuses["AAPL"] == "active"
        assert statuses["HALTED"] == "inactive"  # §désactivé, pas supprimé

    def test_alpaca_error_is_wrapped_in_asset_sync_error(self, db_session):
        from app.alpaca_client import AlpacaUpstreamError

        account = self._account(db_session)
        _FakeAlpacaClient._NEXT_ERROR = AlpacaUpstreamError("panne simulée")
        with pytest.raises(AssetSyncError):
            sync_assets(db_session, account, client_factory=_FakeAlpacaClient)

    def test_last_sync_status_with_no_account_reports_none(self, db_session):
        synced_at, total = last_sync_status(db_session, None)
        assert synced_at is None
        assert total == 0


class TestAssetsRouter:
    def _connect(self, logged_in_client, assets: list[AlpacaAsset]) -> None:
        with respx.mock(assert_all_called=False) as mock:
            mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
            mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_json(*assets)))
            response = logged_in_client.post(
                "/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"}
            )
        assert response.status_code == 200

    def test_search_requires_auth(self, client):
        assert client.get("/api/assets/search").status_code == 401

    def test_search_default_filters_out_non_tradable(self, logged_in_client):
        self._connect(logged_in_client, [_AAPL, _HALTED])
        response = logged_in_client.get("/api/assets/search")
        assert response.status_code == 200
        symbols = [item["canonical_symbol"] for item in response.json()["items"]]
        assert symbols == ["AAPL"]

    def test_search_with_tradable_only_false_includes_everything(self, logged_in_client):
        self._connect(logged_in_client, [_AAPL, _HALTED])
        response = logged_in_client.get("/api/assets/search", params={"tradable_only": "false"})
        symbols = sorted(item["canonical_symbol"] for item in response.json()["items"])
        assert symbols == ["AAPL", "HALTED"]

    def test_search_filters_by_query_substring(self, logged_in_client):
        self._connect(logged_in_client, [_AAPL, _HALTED])
        response = logged_in_client.get("/api/assets/search", params={"q": "aap", "tradable_only": "false"})
        symbols = [item["canonical_symbol"] for item in response.json()["items"]]
        assert symbols == ["AAPL"]

    def test_status_reflects_last_sync(self, logged_in_client):
        self._connect(logged_in_client, [_AAPL, _HALTED])
        response = logged_in_client.get("/api/assets/status")
        assert response.status_code == 200
        body = response.json()
        assert body["last_synced_at"] is not None
        assert body["active_asset_count"] == 2

    def test_manual_sync_without_connected_account_is_a_clear_validation_error(self, logged_in_client):
        response = logged_in_client.post("/api/assets/sync")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_manual_sync_deactivates_symbol_removed_from_alpaca(self, logged_in_client):
        self._connect(logged_in_client, [_AAPL, _HALTED])
        with respx.mock(assert_all_called=False) as mock:
            mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_json(_AAPL)))
            response = logged_in_client.post("/api/assets/sync")
        assert response.status_code == 200
        body = response.json()
        assert body["deactivated_count"] == 1

        # §"actualiser sans supprimer l'historique" : la ligne existe
        # toujours, simplement inactive — jamais retournée par /search
        # même avec tradable_only=false.
        search = logged_in_client.get("/api/assets/search", params={"tradable_only": "false"})
        symbols = [item["canonical_symbol"] for item in search.json()["items"]]
        assert "HALTED" not in symbols
