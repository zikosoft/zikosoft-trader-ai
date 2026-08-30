"""B12 — CRUD d'instances de stratégie (`/api/strategies/instances/*`).
Contre PostgreSQL/Redis réels et l'app FastAPI réelle (TestClient), aucun
mock — utilise la vraie stratégie `moving_average_crossover` synchronisée
au démarrage par le registre B11 (voir strategy_sync.py), pas une
définition injectée artificiellement pour le test."""

from __future__ import annotations

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

VALID_PARAMS = {
    "timeframe": "1Day",
    "short_period": 10,
    "long_period": 30,
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
}


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        # §B30 — les limites actives/symboles dépendent désormais du profil
        # (`novice` par défaut, 1 active/2 symboles) ; ce module teste les
        # constantes historiques (3 actives/10 symboles), qui sont
        # désormais le palier `expert` — remis à `novice` ici pour ne
        # jamais laisser un test fuiter son `expert` vers un autre module.
        conn.execute(text("UPDATE users SET experience_profile = 'novice' WHERE email = :email"), {"email": settings.demo_user_email})
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.execute(text("UPDATE users SET experience_profile = 'novice' WHERE email = :email"), {"email": settings.demo_user_email})
        conn.commit()


def _set_demo_profile(profile: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET experience_profile = :profile WHERE email = :email"),
            {"profile": profile, "email": settings.demo_user_email},
        )


@pytest.fixture()
def client():
    with TestClient(app) as c:  # déclenche le lifespan -> sync réelle de strategies/
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
def paper_client(logged_in_client):
    response = logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    assert response.status_code == 200
    return logged_in_client


def _create(client, **overrides):
    payload = {
        "type_code": "moving_average_crossover",
        "name": "Ma stratégie MA",
        "symbols": ["AAPL"],
        "parameters": VALID_PARAMS,
    }
    payload.update(overrides)
    return client.post("/api/strategies/instances", json=payload)


class TestCreate:
    def test_requires_auth(self, client):
        response = client.post(
            "/api/strategies/instances",
            json={
                "type_code": "moving_average_crossover",
                "name": "x",
                "symbols": ["AAPL"],
                "parameters": VALID_PARAMS,
            },
        )
        assert response.status_code == 401

    def test_requires_active_context(self, logged_in_client):
        response = _create(logged_in_client)
        assert response.status_code == 400

    def test_valid_creation_succeeds_as_ready(self, paper_client):
        response = _create(paper_client)
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "READY"
        assert body["type_code"] == "moving_average_crossover"
        assert body["symbols"] == ["AAPL"]
        assert body["definition_version"] == "1.0.0"

    def test_symbols_are_normalized_uppercase_and_deduplicated(self, paper_client):
        response = _create(paper_client, symbols=["aapl", "AAPL", " msft "])
        assert response.status_code == 201
        assert response.json()["symbols"] == ["AAPL", "MSFT"]

    def test_unknown_type_code_is_404(self, paper_client):
        response = _create(paper_client, type_code="does_not_exist")
        assert response.status_code == 404

    def test_empty_symbols_rejected(self, paper_client):
        # Rejeté dès la couche Pydantic (`Field(min_length=1)` sur le
        # schéma de la requête) — 422 FastAPI standard, avant même d'
        # atteindre la validation métier de `strategy_instances.py`
        # (qui a sa propre garde redondante pour tout appelant direct
        # du service, voir test_service-level coverage ci-dessous).
        response = _create(paper_client, symbols=[])
        assert response.status_code == 422

    def test_schema_invalid_parameters_rejected(self, paper_client):
        bad_params = dict(VALID_PARAMS)
        bad_params["timeframe"] = "not-a-real-timeframe"
        response = _create(paper_client, parameters=bad_params)
        assert response.status_code == 400
        assert "errors" in response.json()["error"]["details"]

    def test_cross_field_validation_short_not_less_than_long_rejected(self, paper_client):
        bad_params = dict(VALID_PARAMS, short_period=30, long_period=30)
        response = _create(paper_client, parameters=bad_params)
        assert response.status_code == 400
        errors = response.json()["error"]["details"]["errors"]
        assert any("short_period" in e for e in errors)

    def test_saved_limit_of_five_enforced(self, paper_client):
        # §B30 — plafond fixe, indépendant du profil (voir docstring de
        # `strategy_instances.py`) : `novice` suffit ici, mais le profil
        # `expert` est forcé quand même pour ne pas dépendre du plafond de
        # symboles (2 pour `novice`) qui saturerait avant celui-ci.
        _set_demo_profile("expert")
        for i in range(5):
            response = _create(paper_client, name=f"Strat {i}", symbols=[f"SYM{i}"])
            assert response.status_code == 201, response.text
        response = _create(paper_client, name="Strat 6", symbols=["SYM6"])
        assert response.status_code == 409

    def test_cumulative_symbol_limit_of_ten_enforced(self, paper_client):
        # 2 stratégies de 5 symboles chacune = 10 (OK), une 3e avec un
        # nouveau symbole dépasse la limite cumulée. §B30 — 10 est le
        # plafond du profil `expert` (voir `profile_limits.py`), forcé ici.
        _set_demo_profile("expert")
        r1 = _create(paper_client, name="A", symbols=[f"S{i}" for i in range(5)])
        assert r1.status_code == 201
        r2 = _create(paper_client, name="B", symbols=[f"S{i}" for i in range(5, 10)])
        assert r2.status_code == 201
        r3 = _create(paper_client, name="C", symbols=["S10"])
        assert r3.status_code == 409


class TestProfileTieredLimits:
    """§B30 — preuve bout-en-bout que les trois paliers (novice/
    intermediate/expert) appliquent bien LEURS propres plafonds actifs/
    symboles, et pas seulement le plafond `expert` déjà couvert par
    `TestCreate.test_cumulative_symbol_limit_of_ten_enforced` /
    `TestCloneActivatePauseStop.test_active_limit_of_three_enforced`."""

    @pytest.mark.parametrize(
        ("profile", "max_symbols"),
        [("novice", 2), ("intermediate", 5), ("expert", 10)],
    )
    def test_symbol_limit_matches_profile(self, paper_client, profile, max_symbols):
        _set_demo_profile(profile)
        within_limit = _create(paper_client, name="Within", symbols=[f"SYM{i}" for i in range(max_symbols)])
        assert within_limit.status_code == 201, within_limit.text

        over_limit = _create(paper_client, name="Over", symbols=["EXTRA"])
        assert over_limit.status_code == 409

    @pytest.mark.parametrize(
        ("profile", "max_active"),
        [("novice", 1), ("intermediate", 2), ("expert", 3)],
    )
    def test_active_limit_matches_profile(self, paper_client, profile, max_active):
        _set_demo_profile(profile)
        for i in range(max_active):
            created = _create(paper_client, name=f"A{i}", symbols=[f"SYM{i}"]).json()
            activate = paper_client.post(f"/api/strategies/instances/{created['id']}/activate")
            assert activate.status_code == 200, activate.text

        extra = _create(paper_client, name="Extra", symbols=["EXTRASYM"]).json()
        response = paper_client.post(f"/api/strategies/instances/{extra['id']}/activate")
        assert response.status_code == 409


class TestListAndGet:
    def test_list_is_scoped_to_current_execution_context(self, paper_client):
        _create(paper_client, name="Paper strat", symbols=["AAPL"])

        replay = paper_client.post("/api/contexts/select", json={"kind": "REPLAY", "confirm": True})
        assert replay.status_code == 200
        response = paper_client.get("/api/strategies/instances")
        assert response.status_code == 200
        assert response.json() == []  # rien dans REPLAY, isolation respectée

        paper_client.post("/api/contexts/select", json={"kind": "PAPER", "confirm": True})
        response = paper_client.get("/api/strategies/instances")
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "Paper strat"

    def test_get_unknown_instance_is_404(self, paper_client):
        response = paper_client.get("/api/strategies/instances/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


class TestUpdate:
    def test_update_parameters_revalidates(self, paper_client):
        created = _create(paper_client).json()
        bad_params = dict(VALID_PARAMS, short_period=100, long_period=10)
        response = paper_client.patch(
            f"/api/strategies/instances/{created['id']}", json={"parameters": bad_params}
        )
        assert response.status_code == 400

    def test_update_name_and_symbols_succeeds(self, paper_client):
        created = _create(paper_client).json()
        response = paper_client.patch(
            f"/api/strategies/instances/{created['id']}",
            json={"name": "Renommée", "symbols": ["msft"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Renommée"
        assert body["symbols"] == ["MSFT"]

    def test_cannot_update_an_active_instance(self, paper_client):
        created = _create(paper_client).json()
        paper_client.post(f"/api/strategies/instances/{created['id']}/activate")
        response = paper_client.patch(f"/api/strategies/instances/{created['id']}", json={"name": "x"})
        assert response.status_code == 409


class TestCloneActivatePauseStop:
    def test_clone_creates_new_instance_with_new_id(self, paper_client):
        created = _create(paper_client).json()
        response = paper_client.post(f"/api/strategies/instances/{created['id']}/clone", json={})
        assert response.status_code == 201
        clone = response.json()
        assert clone["id"] != created["id"]
        assert clone["cloned_from_id"] == created["id"]
        assert clone["status"] == "READY"
        assert clone["symbols"] == created["symbols"]

    def test_activate_then_pause_then_activate_again(self, paper_client):
        created = _create(paper_client).json()
        instance_id = created["id"]

        activated = paper_client.post(f"/api/strategies/instances/{instance_id}/activate")
        assert activated.status_code == 200
        assert activated.json()["status"] == "ACTIVE"

        paused = paper_client.post(f"/api/strategies/instances/{instance_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "PAUSED"

        reactivated = paper_client.post(f"/api/strategies/instances/{instance_id}/activate")
        assert reactivated.status_code == 200
        assert reactivated.json()["status"] == "ACTIVE"

    def test_cannot_pause_a_non_active_instance(self, paper_client):
        created = _create(paper_client).json()
        response = paper_client.post(f"/api/strategies/instances/{created['id']}/pause")
        assert response.status_code == 409

    def test_active_limit_of_three_enforced(self, paper_client):
        # §B30 — 3 actives est le plafond du profil `expert`, forcé ici.
        _set_demo_profile("expert")
        ids = []
        for i in range(3):
            created = _create(paper_client, name=f"S{i}", symbols=[f"SYM{i}"]).json()
            ids.append(created["id"])
            activate = paper_client.post(f"/api/strategies/instances/{created['id']}/activate")
            assert activate.status_code == 200

        fourth = _create(paper_client, name="S4", symbols=["SYM4"]).json()
        response = paper_client.post(f"/api/strategies/instances/{fourth['id']}/activate")
        assert response.status_code == 409

    def test_stop_from_ready_succeeds(self, paper_client):
        created = _create(paper_client).json()
        response = paper_client.post(f"/api/strategies/instances/{created['id']}/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "STOPPED"


class TestServiceLevelGuards:
    """Le service `strategy_instances.py` a ses propres gardes, indépendantes
    de la couche Pydantic de la route (`Field(min_length=1)` sur `symbols`,
    voir `test_empty_symbols_rejected` ci-dessus qui ne peut jamais
    atteindre cette garde via l'API) — tout futur appelant direct du
    service (ex. un script d'admin, une future route interne) en bénéficie
    aussi. Testé ici en appelant le service directement."""

    def test_create_instance_rejects_empty_symbols_at_service_level(self, db_session):
        from app import strategy_instances as service
        from app.context import ensure_user_contexts
        from app.models import User
        from app.strategy_sync import sync_from_directory
        from sqlalchemy import select

        # Indépendant de l'ordre d'exécution des autres tests du fichier
        # (qui déclenchent la synchro via le lifespan de TestClient) — ce
        # test-ci n'utilise pas TestClient, donc s'assure lui-même que
        # `moving_average_crossover` existe en base avant de l'utiliser.
        sync_from_directory(db_session)

        user = db_session.execute(select(User)).scalars().first()
        contexts = ensure_user_contexts(db_session, user)
        db_session.commit()

        with pytest.raises(service.StrategyParametersInvalid):
            service.create_instance(
                db_session,
                user,
                contexts["PAPER"].id,
                type_code="moving_average_crossover",
                name="x",
                symbols=[],
                parameters=VALID_PARAMS,
            )


class TestDelete:
    def test_delete_inactive_instance_succeeds(self, paper_client):
        created = _create(paper_client).json()
        response = paper_client.delete(f"/api/strategies/instances/{created['id']}")
        assert response.status_code == 204
        assert paper_client.get(f"/api/strategies/instances/{created['id']}").status_code == 404

    def test_cannot_delete_an_active_instance(self, paper_client):
        created = _create(paper_client).json()
        paper_client.post(f"/api/strategies/instances/{created['id']}/activate")
        response = paper_client.delete(f"/api/strategies/instances/{created['id']}")
        assert response.status_code == 409

    def test_deleting_a_strategy_with_run_history_is_blocked_not_silently_cascaded(self, paper_client, db_session):
        """§ "jamais de suppression physique silencieuse" — une ligne
        `strategy_runs` qui référence l'instance doit bloquer la
        suppression (contrainte FK, aucun ondelete=CASCADE déclaré), pas
        disparaître avec elle."""
        from sqlalchemy import text as sa_text

        created = _create(paper_client).json()
        db_session.execute(
            sa_text(
                "INSERT INTO strategy_runs "
                "(id, strategy_id, execution_context_id, window_key, market_data_timestamp, outcome, confidence) "
                "VALUES (gen_random_uuid(), :strategy_id, :context_id, 'window-1', now(), 'HOLD', 5000)"
            ),
            {"strategy_id": created["id"], "context_id": created["execution_context_id"]},
        )
        db_session.commit()

        response = paper_client.delete(f"/api/strategies/instances/{created['id']}")
        assert response.status_code == 409
