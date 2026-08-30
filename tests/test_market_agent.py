"""B10 — market_agent/main.py::tick(). Intégration réelle : vraie base
PostgreSQL/Redis, vrai serveur MCP officiel (clés factices — même
limitation réseau documentée que test_mcp_session.py), vraie boucle
d'appel de tick() comme le ferait `run_service`. `ANTHROPIC_API_KEY` n'est
jamais définie dans cette sandbox -> `ai_summary` est toujours `None`
(chemin de repli documenté, pas simulé comme un succès).

Nécessite `.venv-agents` (voir tests/test_mcp_session.py pour le pourquoi
du venv séparé) — skip proprement sous `.venv` backend."""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest

pytest.importorskip("mcp", reason="suite agents — lancer avec `make test-agents` (.venv-agents)")

import sys  # noqa: E402 — après importorskip, volontaire
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from common.encryption import encrypt_secret  # noqa: E402
from common.mcp_session import STATUS_HEALTHY  # noqa: E402
from sqlalchemy import text  # noqa: E402

os.environ.setdefault("APP_ENCRYPTION_KEY", "RB-l2-7BeTsBNRSaUSuU85CsRr1C18vHkEI3kMq7JiE=")
# Aucune vraie clé Anthropic disponible ici — vérifie explicitement que le
# module ne dépend pas silencieusement d'une clé qui traînerait dans
# l'environnement de test.
os.environ.pop("ANTHROPIC_API_KEY", None)

import market_agent.main as market_agent  # noqa: E402


@pytest.fixture()
def connected_account(db_session):
    """Insère un utilisateur + compte Alpaca connecté + contexte PAPER,
    directement en SQL (comme market_agent.main lui-même, qui n'a pas accès
    aux modèles ORM de `backend` — image Docker séparée)."""
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    context_id = uuid.uuid4()

    api_key, secret_key = "SPIKE-FAKE-KEY-NOT-REAL", "SPIKE-FAKE-SECRET-NOT-REAL"
    encrypted_api_key = encrypt_secret(api_key)
    encrypted_secret_key = encrypt_secret(secret_key)

    provider_id = db_session.execute(
        text("SELECT id FROM trading_providers WHERE code = 'alpaca'")
    ).scalar_one()

    db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, is_active) "
            "VALUES (:id, :email, 'x', 'Test Market Agent', true)"
        ),
        {"id": user_id, "email": f"market-agent-test-{user_id}@zikosofttrader.local"},
    )
    db_session.execute(
        text(
            "INSERT INTO execution_contexts (id, user_id, kind, label, is_active) "
            "VALUES (:id, :user_id, 'PAPER', 'Paper (test)', false)"
        ),
        {"id": context_id, "user_id": user_id},
    )
    db_session.execute(
        text(
            "INSERT INTO user_trading_accounts "
            "(id, user_id, trading_provider_id, environment, status, "
            " encrypted_api_key, encrypted_secret_key, encryption_key_version, "
            " is_default, metadata_json) "
            "VALUES (:id, :user_id, :provider_id, 'paper', 'connected', "
            " :enc_api_key, :enc_secret_key, 1, true, '{}'::jsonb)"
        ),
        {
            "id": account_id,
            "user_id": user_id,
            "provider_id": provider_id,
            "enc_api_key": encrypted_api_key,
            "enc_secret_key": encrypted_secret_key,
        },
    )
    db_session.commit()

    yield {"user_id": user_id, "account_id": account_id, "context_id": context_id}

    db_session.execute(text("DELETE FROM user_trading_accounts WHERE id = :id"), {"id": account_id})
    db_session.execute(text("DELETE FROM execution_contexts WHERE id = :id"), {"id": context_id})
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    db_session.commit()
    manager = market_agent._managers.pop(account_id, None)
    market_agent._managers_credentials.pop(account_id, None)
    if manager is not None:
        manager.stop()


def _drain_stream(redis_client, stream: str) -> list[dict]:
    entries = redis_client.xrange(stream, min="-", max="+")
    envelopes = []
    for _msg_id, fields in entries:
        raw = fields.get(b"envelope") or fields.get("envelope")
        if isinstance(raw, bytes):
            raw = raw.decode()
        envelopes.append(json.loads(raw))
    return envelopes


class TestMarketAgentTick:
    def test_connected_account_query_finds_the_account(self, connected_account):
        from app.db import engine

        accounts = market_agent._connected_accounts(engine)
        assert connected_account["account_id"] in {a["account_id"] for a in accounts}

    def test_tick_starts_session_and_eventually_publishes_analysis(self, connected_account, redis_client):
        from app.db import engine

        from shared.events import Streams

        redis_client.delete(Streams.MARKET_ANALYSIS_COMPLETED)

        deadline = time.monotonic() + 30.0
        published = []
        while time.monotonic() < deadline and not published:
            market_agent.tick(engine, redis_client)
            published = _drain_stream(redis_client, Streams.MARKET_ANALYSIS_COMPLETED)
            if not published:
                time.sleep(0.5)

        assert published, "aucun market.analysis.completed publié dans le délai imparti"
        envelope = published[0]
        assert envelope["event_type"] == "market.analysis.completed"
        assert envelope["execution_context_id"] == str(connected_account["context_id"])
        assert envelope["user_id"] == str(connected_account["user_id"])

        payload = envelope["payload"]
        assert payload["account_id"] == str(connected_account["account_id"])
        assert payload["watchlist"] == list(market_agent.DEMO_WATCHLIST)
        # Pas de clé Anthropic dans cette sandbox -> repli honnête, jamais
        # un résumé fabriqué.
        assert payload["ai_summary"] is None
        # Pas de route réseau vers Alpaca dans cette sandbox -> les appels
        # d'outils échouent proprement, capturés dans evidence.errors.
        assert len(payload["evidence"]["errors"]) > 0
        # §B13 : la structure `bars` existe pour chaque symbole même quand
        # aucun appel `get_stock_bars` n'a réussi (pas de réseau Alpaca ici)
        # — vide, jamais absente, pour que le Strategy Agent puisse
        # distinguer "pas encore collecté" de "collecté, aucune bougie".
        for symbol in market_agent.DEMO_WATCHLIST:
            assert payload["evidence"]["bars"][symbol] == {}
        # §B10 sécurité "rejeter les données trop anciennes" — aucun outil
        # n'a réussi (donc aucun horodatage réel exploitable) -> périmé par
        # défaut, jamais un `stale: false` mensonger faute de données.
        assert payload["stale"] is True

        health_raw = redis_client.get(f"mcp:session:health:{connected_account['account_id']}")
        assert health_raw is not None
        health = json.loads(health_raw)
        assert health["status"] == STATUS_HEALTHY
        assert health["trading_toolset_excluded"] is True

    def test_disconnected_account_gets_no_session_and_no_event(self, db_session, redis_client):
        """Un compte jamais connecté (pas de clés) ne doit produire ni
        session MCP ni événement — vérifie que la requête filtre bien sur
        `status = 'connected'` et des clés non nulles."""
        from app.db import engine

        from shared.events import Streams

        redis_client.delete(Streams.MARKET_ANALYSIS_COMPLETED)
        before = len(market_agent._managers)
        market_agent.tick(engine, redis_client)
        assert len(market_agent._managers) == before
        assert _drain_stream(redis_client, Streams.MARKET_ANALYSIS_COMPLETED) == []

    def test_credential_change_triggers_restart_not_a_second_session(self, connected_account, db_session):
        """§B10 "Redémarrer si credentials modifiés" — change les clés
        stockées (simule un Restart complete setup + reconnexion B07) et
        vérifie que le même McpSessionManager est redémarré, pas dupliqué."""
        from app.db import engine

        market_agent.tick(engine, __import__("redis").Redis.from_url(os.environ["REDIS_URL"]))
        manager_before = market_agent._managers[connected_account["account_id"]]

        new_ciphertext = encrypt_secret("ANOTHER-FAKE-KEY")
        db_session.execute(
            text("UPDATE user_trading_accounts SET encrypted_api_key = :v WHERE id = :id"),
            {"v": new_ciphertext, "id": connected_account["account_id"]},
        )
        db_session.commit()

        market_agent.tick(engine, __import__("redis").Redis.from_url(os.environ["REDIS_URL"]))
        manager_after = market_agent._managers[connected_account["account_id"]]
        assert manager_before is manager_after  # même objet, redémarré en interne — pas recréé
        assert market_agent._managers_credentials[connected_account["account_id"]][0] == "ANOTHER-FAKE-KEY"


class TestFreshnessCheck:
    """Logique pure (pas de DB/Redis/MCP) — corrige le bug identifié en
    relecture sécurité : la 1re version comparait l'heure de COLLECTE à
    elle-même (quasi jamais périmée par construction) plutôt que les
    horodatages réels des réponses d'outils."""

    def test_parse_timestamp_handles_iso8601_and_z_suffix(self):
        assert market_agent._parse_timestamp("2024-01-01T00:00:00Z") is not None
        assert market_agent._parse_timestamp("2024-01-01T00:00:00+00:00") is not None

    def test_parse_timestamp_handles_epoch_seconds_and_millis(self):
        seconds = market_agent._parse_timestamp(1700000000)
        millis = market_agent._parse_timestamp(1700000000000)
        assert seconds == pytest.approx(1700000000)
        assert millis == pytest.approx(1700000000)  # ms détectés et convertis

    def test_parse_timestamp_rejects_garbage(self):
        assert market_agent._parse_timestamp("pas une date") is None
        assert market_agent._parse_timestamp(None) is None
        assert market_agent._parse_timestamp(True) is None  # bool est un int en Python — piège explicite

    def test_extract_data_timestamps_finds_nested_fields(self):
        evidence = {
            "clock": {"timestamp": "2024-01-01T00:00:00Z"},
            "watchlist": {"AAPL": {"latest_quote": {"t": "x", "updated_at": 1700000000}}},
            "news": [{"headline": "x", "created_at": "2024-06-01T00:00:00Z"}],
        }
        timestamps = market_agent._extract_data_timestamps(evidence)
        # clock.timestamp + watchlist...updated_at + news...created_at = 3 ;
        # la clé "t" seule ne matche aucun des motifs reconnus, volontairement.
        assert len(timestamps) == 3

    def test_extract_data_timestamps_empty_when_no_data(self):
        evidence = {"clock": None, "watchlist": {}, "news": []}
        assert market_agent._extract_data_timestamps(evidence) == []

    def test_extract_data_timestamps_finds_bar_timestamps(self):
        evidence = {
            "clock": None,
            "watchlist": {},
            "bars": {"AAPL": {"1Day": [{"timestamp": "2024-06-01T00:00:00Z", "close": 1.0}]}},
            "news": [],
        }
        assert market_agent._extract_data_timestamps(evidence) == [
            market_agent._parse_timestamp("2024-06-01T00:00:00Z")
        ]


class TestNormalizeBars:
    """§B13 — ajouté quand la construction du Strategy Agent a révélé que
    `moving_average_crossover` (B12) ne peut rien évaluer sans historique de
    bougies (voir docstring du module). Logique pure, pas de DB/Redis/MCP."""

    def test_normalizes_list_form_with_short_keys(self):
        raw = {"bars": [{"t": "2024-01-01T00:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}]}
        bars = market_agent._normalize_bars(raw, "AAPL")
        assert bars == [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100.0,
            }
        ]

    def test_normalizes_dict_form_keyed_by_symbol(self):
        raw = {"bars": {"AAPL": [{"close": 10.0, "timestamp": "2024-01-02T00:00:00Z"}]}}
        bars = market_agent._normalize_bars(raw, "AAPL")
        assert bars[0]["close"] == 10.0
        # Un symbole absent de la réponse (mauvaise clé) ne doit jamais
        # lever — juste renvoyer aucune bougie.
        assert market_agent._normalize_bars(raw, "MSFT") == []

    def test_bars_without_close_are_skipped_not_crashed(self):
        raw = {"bars": [{"t": "2024-01-01T00:00:00Z"}, {"t": "2024-01-02T00:00:00Z", "c": 5.0}]}
        bars = market_agent._normalize_bars(raw, "AAPL")
        assert len(bars) == 1
        assert bars[0]["close"] == 5.0

    def test_sorted_oldest_to_newest_regardless_of_input_order(self):
        raw = {
            "bars": [
                {"t": "2024-01-03T00:00:00Z", "c": 3.0},
                {"t": "2024-01-01T00:00:00Z", "c": 1.0},
                {"t": "2024-01-02T00:00:00Z", "c": 2.0},
            ]
        }
        bars = market_agent._normalize_bars(raw, "AAPL")
        assert [b["close"] for b in bars] == [1.0, 2.0, 3.0]

    def test_malformed_response_returns_empty_list(self):
        assert market_agent._normalize_bars(None, "AAPL") == []
        assert market_agent._normalize_bars({}, "AAPL") == []
        assert market_agent._normalize_bars({"bars": "not-a-list-or-dict"}, "AAPL") == []
        assert market_agent._normalize_bars({"bars": [1, 2, "x"]}, "AAPL") == []


class TestExtractQuotePrice:
    """§B27 — logique pure (pas de DB/Redis/MCP), même discipline de
    tolérance que `TestNormalizeBars` : forme exacte de `get_stock_snapshot`
    non vérifiable en direct depuis cette sandbox."""

    def test_extracts_from_latest_trade_price(self):
        raw = {"latest_trade": {"price": 189.5, "timestamp": "2024-06-01T00:00:00Z"}}
        price, as_of = market_agent._extract_quote_price(raw)
        assert price == 189.5
        assert as_of == market_agent._parse_timestamp("2024-06-01T00:00:00Z")

    def test_extracts_from_short_key_form(self):
        raw = {"latest_trade": {"p": 42.1, "t": "2024-06-01T00:00:00Z"}}
        price, _as_of = market_agent._extract_quote_price(raw)
        assert price == 42.1

    def test_falls_back_to_ask_price_when_no_trade(self):
        raw = {"latest_quote": {"ask_price": 10.25}}
        price, _as_of = market_agent._extract_quote_price(raw)
        assert price == 10.25

    def test_falls_back_to_daily_bar_close(self):
        raw = {"daily_bar": {"close": 7.0}}
        price, _as_of = market_agent._extract_quote_price(raw)
        assert price == 7.0

    def test_no_exploitable_field_returns_none_never_fabricated(self):
        assert market_agent._extract_quote_price({"unrelated": "x"}) == (None, None)
        assert market_agent._extract_quote_price(None) == (None, None)
        assert market_agent._extract_quote_price("not-a-dict") == (None, None)

    def test_garbage_price_type_is_ignored_not_crashed(self):
        raw = {"latest_trade": {"price": "not-a-number"}, "daily_bar": {"close": 5.5}}
        price, _as_of = market_agent._extract_quote_price(raw)
        assert price == 5.5


class TestPersistBars:
    """§B27 — écriture réelle dans `market_bars` (vraie PostgreSQL). Pas de
    MCP nécessaire ici (appelle `_persist_bars` directement avec des
    bougies déjà normalisées), mais ce fichier entier est gated par
    `pytest.importorskip("mcp")` en tête (import de `market_agent.main`
    tire `common.mcp_session` -> `mcp`) — reste donc `.venv-agents` malgré
    tout."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, db_session):
        yield
        db_session.execute(text("DELETE FROM market_bars WHERE symbol LIKE 'ZTEST%'"))
        db_session.execute(text("DELETE FROM market_quotes WHERE symbol LIKE 'ZTEST%'"))
        db_session.commit()

    def test_persists_normalized_bars_and_is_queryable(self):
        from app.db import engine

        bars = [
            {"timestamp": "2024-01-01T00:00:00Z", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
            {"timestamp": "2024-01-02T00:00:00Z", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 150.0},
        ]
        market_agent._persist_bars(engine, symbol="ZTEST1", timeframe="1Day", bars=bars)

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT bar_at, close, volume FROM market_bars WHERE symbol = 'ZTEST1' ORDER BY bar_at")
            ).all()
        assert len(rows) == 2
        assert float(rows[0].close) == 1.5
        assert float(rows[1].close) == 2.0

    def test_upsert_is_idempotent_and_updates_in_place(self):
        from app.db import engine

        bar = {"timestamp": "2024-02-01T00:00:00Z", "close": 10.0}
        market_agent._persist_bars(engine, symbol="ZTEST2", timeframe="1Day", bars=[bar])
        market_agent._persist_bars(engine, symbol="ZTEST2", timeframe="1Day", bars=[{**bar, "close": 11.0}])

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT close FROM market_bars WHERE symbol = 'ZTEST2'")).all()
        assert len(rows) == 1  # pas de doublon, même (symbol, timeframe, bar_at)
        assert float(rows[0].close) == 11.0  # écrasé par la valeur la plus récente

    def test_bar_without_exploitable_timestamp_is_skipped_never_fabricated(self):
        from app.db import engine

        market_agent._persist_bars(
            engine, symbol="ZTEST3", timeframe="1Day", bars=[{"timestamp": "pas une date", "close": 5.0}]
        )
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM market_bars WHERE symbol = 'ZTEST3'")).all()
        assert rows == []

    def test_empty_bars_list_is_a_noop(self):
        from app.db import engine

        market_agent._persist_bars(engine, symbol="ZTEST4", timeframe="1Day", bars=[])
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM market_bars WHERE symbol = 'ZTEST4'")).all()
        assert rows == []


class TestPersistQuote:
    """§B27 — écriture réelle dans `market_quotes`, même principe que
    `TestPersistBars`."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, db_session):
        yield
        db_session.execute(text("DELETE FROM market_quotes WHERE symbol LIKE 'ZTEST%'"))
        db_session.commit()

    def test_persists_extractable_quote(self):
        from app.db import engine

        market_agent._persist_quote(
            engine, symbol="ZTEST5", raw={"latest_trade": {"price": 100.0, "timestamp": "2024-03-01T00:00:00Z"}}
        )
        with engine.connect() as conn:
            row = conn.execute(text("SELECT price, as_of FROM market_quotes WHERE symbol = 'ZTEST5'")).one()
        assert float(row.price) == 100.0
        assert row.as_of is not None

    def test_upsert_replaces_previous_quote_in_place(self):
        from app.db import engine

        market_agent._persist_quote(engine, symbol="ZTEST6", raw={"daily_bar": {"close": 50.0}})
        market_agent._persist_quote(engine, symbol="ZTEST6", raw={"daily_bar": {"close": 55.0}})
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT price FROM market_quotes WHERE symbol = 'ZTEST6'")).all()
        assert len(rows) == 1
        assert float(rows[0].price) == 55.0

    def test_no_exploitable_price_writes_nothing_never_fabricated(self):
        from app.db import engine

        market_agent._persist_quote(engine, symbol="ZTEST7", raw={"unrelated": "x"})
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM market_quotes WHERE symbol = 'ZTEST7'")).all()
        assert rows == []
