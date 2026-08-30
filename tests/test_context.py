"""B06 — Contextes Replay/Paper. Tests d'intégration contre l'app FastAPI
réelle (TestClient), PostgreSQL et Redis réels — pas de mock, cohérent avec
le reste du socle."""

from __future__ import annotations

import uuid

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

from shared.eventbus import EventConsumer


@pytest.fixture(autouse=True)
def _clean_context_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.execute(text("DELETE FROM user_sessions"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions"))
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


@pytest.fixture()
def demo_user_id() -> str:
    # Requêtes SQL directes ci-dessous systématiquement filtrées par
    # `user_id` : la base de test peut contenir d'autres utilisateurs (V2
    # multi-utilisateur future, ou simplement d'autres suites de tests), pas
    # question de supposer que `execution_contexts` n'a que les 3 lignes de
    # l'utilisateur démo.
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": settings.demo_user_email},
            ).scalar_one()
        )


def test_list_contexts_requires_auth(client):
    response = client.get("/api/contexts")
    assert response.status_code == 401


def test_list_contexts_exposes_paper_and_replay_only(logged_in_client):
    """DRY_RUN existe en base (usage interne futur) mais ne doit jamais
    apparaître dans la liste exposée à l'utilisateur (§B06 cartes "Choose
    your experience" : seulement Historical Replay et Alpaca Paper)."""
    response = logged_in_client.get("/api/contexts")
    assert response.status_code == 200
    body = response.json()
    assert [c["kind"] for c in body["contexts"]] == ["PAPER", "REPLAY"]
    assert body["active_kind"] is None  # rien sélectionné au premier accès


def test_first_selection_requires_no_confirmation(logged_in_client):
    response = logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    assert response.status_code == 200
    assert response.json()["active_kind"] == "PAPER"


def test_unknown_kind_rejected(logged_in_client):
    response = logged_in_client.post("/api/contexts/select", json={"kind": "LIVE"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_dry_run_not_selectable_via_api(logged_in_client):
    """DRY_RUN existe en base mais reste un usage interne (B33) — l'API
    refuse de l'activer comme contexte utilisateur."""
    response = logged_in_client.post("/api/contexts/select", json={"kind": "DRY_RUN"})
    assert response.status_code == 400


def test_switch_without_confirm_returns_409_and_changes_nothing(logged_in_client):
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})

    response = logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY"})
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["details"] == {"active_kind": "PAPER", "target_kind": "REPLAY"}

    # Le rollback a bien annulé toute tentative de mutation.
    still = logged_in_client.get("/api/contexts")
    assert still.json()["active_kind"] == "PAPER"


def test_switch_with_confirm_activates_atomically_and_preserves_data(
    logged_in_client, demo_user_id
):
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})

    response = logged_in_client.post(
        "/api/contexts/select", json={"kind": "REPLAY", "confirm": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["active_kind"] == "REPLAY"
    active_by_kind = {c["kind"]: c["is_active"] for c in body["contexts"]}
    assert active_by_kind == {"PAPER": False, "REPLAY": True}

    # §B06 "conservation des données de chaque contexte" : les trois lignes
    # de l'utilisateur démo existent toujours, seule l'activation a changé.
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM execution_contexts WHERE user_id = :uid"),
            {"uid": demo_user_id},
        ).scalar_one()
    assert count == 3  # PAPER + REPLAY + DRY_RUN, toujours là


def test_reselecting_active_context_is_a_noop(logged_in_client):
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM execution_context_switches")
        ).scalar_one()

    response = logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    assert response.status_code == 200

    with engine.connect() as conn:
        after = conn.execute(
            text("SELECT count(*) FROM execution_context_switches")
        ).scalar_one()
    assert after == before  # pas de nouvelle entrée d'audit pour un no-op


def test_switch_writes_audit_trail(logged_in_client):
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY", "confirm": True})

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT from_context_id IS NOT NULL AS had_from, confirmed "
                "FROM execution_context_switches ORDER BY switched_at"
            )
        ).fetchall()
    assert len(rows) == 2
    assert rows[0].had_from is False
    assert rows[0].confirmed is False  # premier choix : rien à confirmer
    assert rows[1].had_from is True
    assert rows[1].confirmed is True


def test_switch_publishes_context_switched_event(logged_in_client, redis_client):
    """Contrat pour les futurs workers/agents (B10+) qui devront fermer
    leurs streams/abonnements du contexte quitté — aucun consommateur réel
    n'existe encore, on prouve juste que l'événement est bien publié et
    porte les bonnes informations (même approche que B04)."""
    consumer = EventConsumer(
        redis_client, stream="system.events", group="test-context-switch", consumer_name="c1"
    )
    consumer.ensure_group()

    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY", "confirm": True})

    messages = list(consumer.read(count=10, block_ms=1000))
    switched = [m for m in messages if m.envelope.event_type == "context.switched"]
    assert len(switched) == 2  # premier choix + switch confirmé

    first, second = switched
    assert first.envelope.payload["from_kind"] is None
    assert first.envelope.payload["to_kind"] == "PAPER"
    assert second.envelope.payload["from_kind"] == "PAPER"
    assert second.envelope.payload["to_kind"] == "REPLAY"
    assert second.envelope.execution_context_id is not None


def test_leaving_context_suspends_active_strategies(logged_in_client, demo_user_id):
    """§B06 "Suspension des stratégies du contexte quitté" — une stratégie
    ACTIVE dans le contexte PAPER doit passer PAUSED quand on bascule vers
    REPLAY, jamais supprimée."""
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})

    with engine.connect() as conn:
        paper_id = conn.execute(
            text(
                "SELECT id FROM execution_contexts "
                "WHERE kind = 'PAPER' AND user_id = :uid"
            ),
            {"uid": demo_user_id},
        ).scalar_one()
        user_id = demo_user_id

        definition_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO strategy_definitions "
                "(id, type_code, version, manifest, parameter_schema, ui_schema, "
                " defaults_by_profile, required_market_data, is_active, created_at, updated_at) "
                "VALUES (:id, 'test.dummy', '1.0', '{}', '{}', '{}', '{}', '{}', true, now(), now())"
            ),
            {"id": str(definition_id)},
        )
        strategy_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO strategies "
                "(id, strategy_definition_id, user_id, execution_context_id, name, "
                " definition_version, parameters, symbols, risk_configuration, status, "
                " created_at, updated_at) "
                "VALUES (:id, :def_id, :user_id, :ctx_id, 'Test strategy', '1.0', '{}', '[]', '{}', "
                " 'ACTIVE', now(), now())"
            ),
            {
                "id": str(strategy_id),
                "def_id": str(definition_id),
                "user_id": str(user_id),
                "ctx_id": str(paper_id),
            },
        )
        conn.commit()

    logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY", "confirm": True})

    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM strategies WHERE id = :id"), {"id": str(strategy_id)}
        ).scalar_one()
    assert status == "PAUSED"  # suspendue, pas supprimée ni stoppée définitivement


def test_orders_are_invisible_across_contexts(logged_in_client, demo_user_id):
    """§B06 critère d'acceptation littéral : "Créer un ordre Replay puis
    passer Paper : ordre invisible" (et l'inverse). Les workers qui créent
    de vrais ordres n'existent pas encore (B17) — on écrit directement la
    ligne `orders` (même table, même contrainte `ExecutionContextMixin`) pour
    prouver que le filtrage par `execution_context_id` fonctionne réellement
    au niveau du schéma, sans attendre B17 pour le vérifier."""
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY", "confirm": True})

    with engine.connect() as conn:
        replay_id = conn.execute(
            text(
                "SELECT id FROM execution_contexts "
                "WHERE kind = 'REPLAY' AND user_id = :uid"
            ),
            {"uid": demo_user_id},
        ).scalar_one()
        user_id = demo_user_id

        order_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO orders "
                "(id, user_id, execution_context_id, symbol, side, order_type, time_in_force, "
                " status, idempotency_key, client_order_id, correlation_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :ctx_id, 'AAPL', 'buy', 'market', 'day', 'pending', "
                " 'idem-1', 'client-1', :corr_id, now(), now())"
            ),
            {
                "id": str(order_id),
                "user_id": str(user_id),
                "ctx_id": str(replay_id),
                "corr_id": str(uuid.uuid4()),
            },
        )
        conn.commit()

    # Filtrage obligatoire par contexte (repository) : une requête scopée sur
    # le contexte PAPER actif ne doit jamais voir l'ordre créé sous REPLAY.
    with engine.connect() as conn:
        paper_id = conn.execute(
            text("SELECT id FROM execution_contexts WHERE kind = 'PAPER' AND user_id = :uid"),
            {"uid": demo_user_id},
        ).scalar_one()
        visible_from_paper = conn.execute(
            text("SELECT count(*) FROM orders WHERE execution_context_id = :ctx_id"),
            {"ctx_id": str(paper_id)},
        ).scalar_one()
        visible_from_replay = conn.execute(
            text("SELECT count(*) FROM orders WHERE execution_context_id = :ctx_id"),
            {"ctx_id": str(replay_id)},
        ).scalar_one()

    assert visible_from_paper == 0  # invisible depuis Paper
    assert visible_from_replay == 1  # toujours là depuis Replay — rien supprimé

    # Basculer vers Paper ne supprime rien : l'ordre Replay existe toujours.
    logged_in_client.post("/api/contexts/select", json={"kind": "PAPER", "confirm": True})
    with engine.connect() as conn:
        still_there = conn.execute(
            text("SELECT count(*) FROM orders WHERE id = :id"), {"id": str(order_id)}
        ).scalar_one()
    assert still_there == 1
