"""B11 — synchronisation DB du registre de stratégies
(`backend.app.strategy_sync`) et route de lecture (`GET /api/strategies/definitions`).
Contre PostgreSQL/Redis réels, aucun mock — la seule chose "fausse" ici est
le contenu des `StrategyDefinition` utilisées pour piloter la synchronisation
(pour ne pas dépendre du contenu réel de `strategies/`, qui évoluera)."""

from __future__ import annotations

import pytest
from app.config import settings
from app.main import app
from app.models import StrategyDefinition as StrategyDefinitionRow
from app.strategy_sync import sync_strategy_definitions
from fastapi.testclient import TestClient

from shared.strategy_registry import RegistryLoadResult, StrategyDefinition

PARAMETER_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}}


def _definition(**overrides) -> StrategyDefinition:
    kwargs = {
        "type_code": "test_sync_strategy",
        "version": "1.0.0",
        "name": "Test Sync Strategy",
        "description": "Stratégie de test pour la synchronisation B11.",
        "parameter_schema": PARAMETER_SCHEMA,
    }
    kwargs.update(overrides)
    return StrategyDefinition(**kwargs)


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    db_session.execute(
        StrategyDefinitionRow.__table__.delete().where(
            StrategyDefinitionRow.type_code.in_(["test_sync_strategy", "test_sync_strategy_2"])
        )
    )
    db_session.commit()


class TestSyncStrategyDefinitions:
    def test_creates_new_definition(self, db_session):
        summary = sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        assert summary.created == ["test_sync_strategy"]

        row = (
            db_session.query(StrategyDefinitionRow)
            .filter_by(type_code="test_sync_strategy")
            .one()
        )
        assert row.version == "1.0.0"
        assert row.is_active is True
        assert row.manifest["name"] == "Test Sync Strategy"

    def test_resyncing_identical_definition_is_a_noop(self, db_session):
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        summary = sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        assert summary.created == []
        assert summary.updated == []
        assert summary.unchanged == ["test_sync_strategy"]

    def test_version_bump_updates_the_row(self, db_session):
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        summary = sync_strategy_definitions(
            db_session, RegistryLoadResult(definitions=[_definition(version="1.1.0")])
        )
        assert summary.updated == ["test_sync_strategy"]
        row = (
            db_session.query(StrategyDefinitionRow)
            .filter_by(type_code="test_sync_strategy")
            .one()
        )
        assert row.version == "1.1.0"

    def test_definition_missing_from_a_later_scan_is_deactivated_not_deleted(self, db_session):
        """§ "jamais de suppression physique" — une stratégie retirée du
        dossier `strategies/` (ou dont le module échoue désormais) doit
        rester en base (désactivée), jamais disparaître : de futures
        instances utilisateur (B12) y pointent par clé étrangère."""
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        summary = sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[]))
        assert summary.deactivated == ["test_sync_strategy"]

        row = (
            db_session.query(StrategyDefinitionRow)
            .filter_by(type_code="test_sync_strategy")
            .one()
        )
        assert row.is_active is False  # toujours présente, juste désactivée

    def test_isolated_load_failures_are_reported_without_touching_the_db(self, db_session):
        from shared.strategy_registry import StrategyLoadFailure

        summary = sync_strategy_definitions(
            db_session,
            RegistryLoadResult(
                definitions=[_definition()],
                failures=[StrategyLoadFailure(module_name="broken_module", error="boom")],
            ),
        )
        assert summary.created == ["test_sync_strategy"]
        assert summary.failures == ["broken_module"]

    def test_reactivating_a_previously_deactivated_definition(self, db_session):
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[]))  # désactivée

        summary = sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        assert summary.updated == ["test_sync_strategy"]  # is_active False -> True compte comme un changement
        row = (
            db_session.query(StrategyDefinitionRow)
            .filter_by(type_code="test_sync_strategy")
            .one()
        )
        assert row.is_active is True


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


class TestStrategyDefinitionsEndpoint:
    def test_requires_auth(self, client):
        assert client.get("/api/strategies/definitions").status_code == 401

    def test_lists_the_real_moving_average_crossover_strategy(self, logged_in_client):
        """Preuve de bout en bout (B11 + B12) : le vrai dossier `strategies/`
        du dépôt applicatif, synchronisé au démarrage du process FastAPI de
        test, est bien servi par l'API — pas une donnée injectée pour le
        test."""
        response = logged_in_client.get("/api/strategies/definitions")
        assert response.status_code == 200
        body = response.json()
        by_code = {item["type_code"]: item for item in body}
        assert "moving_average_crossover" in by_code

        entry = by_code["moving_average_crossover"]
        assert entry["name"] == "Moving Average Crossover"
        assert entry["required_capabilities"] == []
        assert "short_period" in entry["parameter_schema"]["properties"]
        assert "short_period" in entry["ui_schema"]

    def test_inactive_definitions_are_not_listed(self, logged_in_client, db_session):
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[_definition()]))
        sync_strategy_definitions(db_session, RegistryLoadResult(definitions=[]))  # désactivée

        response = logged_in_client.get("/api/strategies/definitions")
        assert response.status_code == 200
        codes = {item["type_code"] for item in response.json()}
        assert "test_sync_strategy" not in codes
