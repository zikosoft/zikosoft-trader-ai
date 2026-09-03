"""B07 — Onboarding Alpaca. Tests d'intégration contre l'app FastAPI réelle
(TestClient), PostgreSQL et Redis réels — seule la frontière HTTP avec
Alpaca (tiers externe, pas notre infra) est simulée via `respx`, voir
.env.example et le docstring de `app/alpaca_client.py`."""

from __future__ import annotations

import httpx
import pytest
import respx
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

ALPACA_ACCOUNT_URL = f"{settings.alpaca_paper_base_url}/v2/account"
ALPACA_ASSETS_URL = f"{settings.alpaca_paper_base_url}/v2/assets"


def _assets_response() -> list[dict]:
    # §B09 — réponse minimale mais représentative de `GET /v2/assets`
    # (voir `app/alpaca_client.py::AlpacaClient.get_assets`) : un actif
    # négociable, un non-négociable (`tradable=False`), pour couvrir le
    # filtre `tradable_only` de `GET /api/assets/search` en aval.
    return [
        {
            "id": "asset-aapl",
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "class": "us_equity",
            "exchange": "NASDAQ",
            "status": "active",
            "tradable": True,
            "fractionable": True,
            "shortable": True,
        },
        {
            "id": "asset-halted",
            "symbol": "HALTED",
            "name": "Halted Co.",
            "class": "us_equity",
            "exchange": "NASDAQ",
            "status": "active",
            "tradable": False,
            "fractionable": False,
            "shortable": False,
        },
    ]


def _account_response(**overrides) -> dict:
    body = {
        "id": "alpaca-account-123",
        "account_number": "PA000TEST",
        "status": "ACTIVE",
        "currency": "USD",
        "cash": "98765.43",
        "portfolio_value": "100000.00",
        "buying_power": "197530.86",
        # §B18 — présents dans une vraie réponse Alpaca ; ajoutés ici pour
        # que ce fixture reste représentatif (voir `AlpacaAccount.equity`/
        # `.last_equity`, tolérés absents ailleurs mais réellement envoyés
        # par Alpaca en pratique).
        "equity": "100000.00",
        "last_equity": "99800.00",
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _clean_onboarding_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM onboarding_steps"))
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM user_trading_accounts"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.execute(text("DELETE FROM user_sessions"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM onboarding_steps"))
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM user_trading_accounts"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.execute(text("DELETE FROM user_sessions"))
        conn.commit()
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


def test_status_requires_auth(client):
    assert client.get("/api/onboarding/status").status_code == 401


def test_status_with_no_account_yet(logged_in_client):
    response = logged_in_client.get("/api/onboarding/status")
    assert response.status_code == 200
    body = response.json()
    assert body["account"] is None
    assert body["steps"] == []


def test_connect_with_invalid_key_is_rejected_clearly(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(401, json={"message": "no"}))
        response = logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "bad", "secret_key": "bad"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["status"] == "failed"
    steps_by_code = {s["step_code"]: s for s in body["steps"]}
    assert steps_by_code["credentials_validated"]["status"] == "FAILED"
    assert "invalides" in steps_by_code["credentials_validated"]["error_details"]["message"]
    # §B07 "Empêcher l'exécution des étapes dépendantes" : rien après n'a tourné.
    for code in (
        "paper_environment_confirmed",
        "account_synchronized",
        "portfolio_loaded",
        "assets_synchronized",
    ):
        assert steps_by_code[code]["status"] == "PENDING"


def test_invalid_key_is_never_persisted(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(401, json={}))
        logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "definitely-wrong", "secret_key": "also-wrong"}
        )
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT encrypted_api_key, encrypted_secret_key FROM user_trading_accounts")
        ).one()
    assert row.encrypted_api_key is None
    assert row.encrypted_secret_key is None


def test_connect_with_valid_key_completes_real_steps_and_stubs_the_rest(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        response = logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["status"] == "connected"
    assert body["account"]["external_account_id"] == "alpaca-account-123"

    steps_by_code = {s["step_code"]: s for s in body["steps"]}
    for code in (
        "credentials_validated",
        "paper_environment_confirmed",
        "account_synchronized",
        "portfolio_loaded",
        "assets_synchronized",
    ):
        assert steps_by_code[code]["status"] == "COMPLETED"
        assert steps_by_code[code]["error_details"] is None

    for code in (
        "market_stream_established",
        "mcp_session_initialized",
        "ai_agents_ready",
    ):
        assert steps_by_code[code]["status"] == "COMPLETED"
        assert "stub" in steps_by_code[code]["error_details"]["note"]


def test_balance_reflects_real_alpaca_response_not_hardcoded(logged_in_client):
    """§B07 "solde jamais hard-codé" — on change les montants renvoyés par
    le mock et on vérifie que la réponse de l'API suit, pas une valeur figée
    quelque part dans le code."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(
            return_value=httpx.Response(
                200,
                json=_account_response(cash="4242.42", portfolio_value="13370.00", buying_power="8484.84"),
            )
        )
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        response = logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"}
        )
    balance = response.json()["account"]["balance"]
    assert balance["cash"] == 4242.42
    assert balance["portfolio_value"] == 13370.00
    assert balance["buying_power"] == 8484.84


def test_credentials_are_encrypted_at_rest(logged_in_client):
    from app.encryption import decrypt_secret

    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"}
        )
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT encrypted_api_key, encrypted_secret_key FROM user_trading_accounts")
        ).one()
    assert row.encrypted_api_key != "AKGOOD"
    assert row.encrypted_secret_key != "SKGOOD"
    assert decrypt_secret(row.encrypted_api_key) == "AKGOOD"
    assert decrypt_secret(row.encrypted_secret_key) == "SKGOOD"


def test_no_secret_ever_appears_in_api_response(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        response = logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "AKGOOD-SECRET-MARKER", "secret_key": "SKGOOD-SECRET-MARKER"}
        )
    assert "AKGOOD-SECRET-MARKER" not in response.text
    assert "SKGOOD-SECRET-MARKER" not in response.text

    status_response = logged_in_client.get("/api/onboarding/status")
    assert "AKGOOD-SECRET-MARKER" not in status_response.text
    assert "SKGOOD-SECRET-MARKER" not in status_response.text


def test_retry_only_reruns_the_failed_step(logged_in_client):
    # Premier appel : step 1 (credentials) et step 3 (account_synchronized)
    # utilisent toutes deux `get_account()` — on fait échouer le 2e appel
    # HTTP (survient pendant account_synchronized) pour simuler une panne
    # Alpaca transitoire APRÈS que les identifiants aient été validés.
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(
            side_effect=[
                httpx.Response(200, json=_account_response()),  # step 1 : OK
                httpx.Response(500, json={}),  # step 3 : panne Alpaca
            ]
        )
        first = logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"}
        )
    steps_by_code = {s["step_code"]: s for s in first.json()["steps"]}
    assert steps_by_code["credentials_validated"]["status"] == "COMPLETED"
    assert steps_by_code["paper_environment_confirmed"]["status"] == "COMPLETED"
    assert steps_by_code["account_synchronized"]["status"] == "FAILED"
    assert steps_by_code["portfolio_loaded"]["status"] == "PENDING"
    credentials_completed_at = steps_by_code["credentials_validated"]["completed_at"]

    # Retry (pas de clés à refournir) : Alpaca répond correctement cette fois.
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        second = logged_in_client.post("/api/onboarding/retry")
    steps_by_code = {s["step_code"]: s for s in second.json()["steps"]}
    assert steps_by_code["credentials_validated"]["completed_at"] == credentials_completed_at  # pas rejoué
    assert steps_by_code["account_synchronized"]["status"] == "COMPLETED"
    assert steps_by_code["portfolio_loaded"]["status"] == "COMPLETED"
    assert second.json()["account"]["status"] == "connected"


def test_restart_resets_everything_and_clears_credentials(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        logged_in_client.post("/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"})

    response = logged_in_client.post("/api/onboarding/restart")
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["status"] == "pending"
    assert all(s["status"] == "PENDING" for s in body["steps"])

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT encrypted_api_key, encrypted_secret_key FROM user_trading_accounts")
        ).one()
    assert row.encrypted_api_key is None
    assert row.encrypted_secret_key is None


def test_portfolio_snapshot_written_with_paper_execution_context(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        logged_in_client.post("/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"})

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT ps.cash, ec.kind FROM portfolio_snapshots ps "
                "JOIN execution_contexts ec ON ec.id = ps.execution_context_id"
            )
        ).one()
    assert row.kind == "PAPER"
    assert float(row.cash) == 98765.43


def test_demo_readiness_requires_authentication(client):
    assert client.get("/api/demo-readiness").status_code == 401
    assert client.post("/api/demo-readiness/paper-preflight").status_code == 401


def test_demo_readiness_honestly_reports_unconfigured_paper_account(logged_in_client):
    response = logged_in_client.get("/api/demo-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["account_configured"] is False
    assert body["account_connected"] is False
    assert body["paper_connection_status"] == "NOT_CONFIGURED"
    assert body["mcp_session_status"] == "NOT_STARTED"
    assert body["active_option_contract_count"] == 0
    assert body["ready_for_paper_demo"] is False
    assert body["non_transactional"] is True


def test_paper_preflight_only_reads_account_and_never_sends_an_order(logged_in_client):
    """Regression proof for the Settings test button: no order route exists."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        connected = logged_in_client.post(
            "/api/onboarding/connect", json={"api_key": "AK-PREFLIGHT-MARKER", "secret_key": "SK-PREFLIGHT-MARKER"}
        )
    assert connected.json()["account"]["status"] == "connected"

    with respx.mock(assert_all_called=True) as mock:
        account_route = mock.get(ALPACA_ACCOUNT_URL).mock(
            return_value=httpx.Response(200, json=_account_response())
        )
        response = logged_in_client.post("/api/demo-readiness/paper-preflight")

    assert response.status_code == 200
    body = response.json()
    assert body["paper_connection_status"] == "VERIFIED"
    assert body["paper_connection_checked_at"] is not None
    assert body["non_transactional"] is True
    assert account_route.call_count == 1
    assert account_route.calls[0].request.method == "GET"
    assert "AK-PREFLIGHT-MARKER" not in response.text
    assert "SK-PREFLIGHT-MARKER" not in response.text


def test_paper_preflight_returns_sanitized_auth_failure_without_sending_an_order(logged_in_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_response()))
        mock.get(ALPACA_ASSETS_URL).mock(return_value=httpx.Response(200, json=_assets_response()))
        logged_in_client.post("/api/onboarding/connect", json={"api_key": "AKGOOD", "secret_key": "SKGOOD"})

    with respx.mock(assert_all_called=True) as mock:
        account_route = mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(401, json={}))
        response = logged_in_client.post("/api/demo-readiness/paper-preflight")

    assert response.status_code == 200
    assert response.json()["paper_connection_status"] == "AUTH_FAILED"
    assert account_route.call_count == 1
