"""B11 — pont entre le registre de stratégies en mémoire
(`shared.strategy_registry`, chargé depuis le dossier `strategies/`) et sa
persistance DB (`backend.app.models.strategies.StrategyDefinition`, table
`strategy_definitions` — schéma déjà posé en B03).

Règle volontaire : **jamais de suppression physique** d'une ligne
`strategy_definitions`. Des instances utilisateur (`Strategy`, table
`strategies`, B12) y pointent par clé étrangère — supprimer la ligne
casserait ces instances existantes (et l'historique `strategy_runs`, B13).
Un module retiré du dossier `strategies/` (ou qui échoue désormais sa
validation) est seulement désactivé (`is_active=False`), jamais supprimé —
une stratégie utilisateur déjà créée à partir de lui doit rester
consultable/arrêtable même si son module d'origine a disparu."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.strategy_registry import RegistryLoadResult, load_definitions_from_directory

from .models import StrategyDefinition as StrategyDefinitionRow

logger = logging.getLogger("strategy_sync")

# backend/app/strategy_sync.py -> backend/app -> backend -> racine du monorepo
DEFAULT_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "strategies"


@dataclass
class SyncSummary:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _manifest_for(definition) -> dict:
    return {
        "name": definition.name,
        "description": definition.description,
        "required_capabilities": list(definition.required_capabilities),
    }


def sync_strategy_definitions(db: Session, load_result: RegistryLoadResult) -> SyncSummary:
    summary = SyncSummary(failures=[f.module_name for f in load_result.failures])
    loaded_type_codes = {d.type_code for d in load_result.definitions}

    existing_rows = {row.type_code: row for row in db.execute(select(StrategyDefinitionRow)).scalars().all()}

    for definition in load_result.definitions:
        manifest = _manifest_for(definition)
        row = existing_rows.get(definition.type_code)

        if row is None:
            row = StrategyDefinitionRow(
                type_code=definition.type_code,
                version=definition.version,
                manifest=manifest,
                parameter_schema=definition.parameter_schema,
                ui_schema=definition.ui_schema,
                defaults_by_profile=definition.defaults_by_profile,
                required_market_data=definition.required_market_data,
                is_active=True,
            )
            db.add(row)
            summary.created.append(definition.type_code)
            continue

        changed = (
            row.version != definition.version
            or row.manifest != manifest
            or row.parameter_schema != definition.parameter_schema
            or row.ui_schema != definition.ui_schema
            or row.defaults_by_profile != definition.defaults_by_profile
            or row.required_market_data != definition.required_market_data
            or not row.is_active
        )
        if changed:
            row.version = definition.version
            row.manifest = manifest
            row.parameter_schema = definition.parameter_schema
            row.ui_schema = definition.ui_schema
            row.defaults_by_profile = definition.defaults_by_profile
            row.required_market_data = definition.required_market_data
            row.is_active = True
            summary.updated.append(definition.type_code)
        else:
            summary.unchanged.append(definition.type_code)

    for type_code, row in existing_rows.items():
        if type_code not in loaded_type_codes and row.is_active:
            row.is_active = False
            summary.deactivated.append(type_code)

    db.commit()

    logger.info(
        "synchronisation du registre de stratégies : %d créée(s), %d mise(s) à jour, "
        "%d désactivée(s), %d inchangée(s), %d échec(s) isolé(s)",
        len(summary.created),
        len(summary.updated),
        len(summary.deactivated),
        len(summary.unchanged),
        len(summary.failures),
    )
    return summary


def sync_from_directory(db: Session, directory: Path = DEFAULT_STRATEGIES_DIR) -> SyncSummary:
    load_result = load_definitions_from_directory(directory)
    return sync_strategy_definitions(db, load_result)
