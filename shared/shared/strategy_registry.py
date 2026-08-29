"""B11 — Strategy Registry : découverte, validation et chargement des
modules de stratégie développeur, rangés dans le dossier `strategies/` à la
racine du monorepo (voir la structure cible définie en B01).

Interdictions du brief B11 respectées :
- pas d'éditeur Python utilisateur : ce module importe uniquement des
  fichiers `.py` déjà commit dans le dépôt applicatif ;
- pas de JSON interne éditable en V1 : `parameter_schema`/`ui_schema` sont
  définis dans le code du module, jamais dans une table éditable par un
  utilisateur ;
- pas d'exécution arbitraire : `load_definitions_from_directory()` ne prend
  jamais un chemin fourni par une requête API — uniquement le dossier
  `strategies/` fixé au démarrage du service (voir `backend/app/main.py`).

Attention à ne pas confondre deux classes homonymes volontairement, comme
le nom `StrategyDefinition` est celui du brief B11 :
- `shared.strategy_registry.StrategyDefinition` (ce module) : le contrat EN
  MÉMOIRE que chaque module `strategies/<type_code>/` doit exposer ;
- `backend.app.models.strategies.StrategyDefinition` : la ligne DB qui
  PERSISTE une définition une fois chargée et validée ici (voir
  `backend/app/strategy_sync.py`, qui fait le pont entre les deux).
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

logger = logging.getLogger("strategy_registry")

# Chaque module de stratégie (fichier `strategies/<type_code>.py` ou
# package `strategies/<type_code>/__init__.py`) doit exposer une instance
# de `StrategyDefinition` sous cet attribut de module.
STRATEGY_MODULE_ATTR = "DEFINITION"


class StrategyLoadError(Exception):
    """Erreur de chargement/validation d'UN module de stratégie — jamais
    fatale pour le registre entier (§B11 "erreur isolée si un plugin est
    invalide"), voir `load_definitions_from_directory`."""


class StrategyDefinition(BaseModel):
    """Interface `StrategyDefinition` du brief B11 — immuable une fois
    construite (`frozen=True`) : un module ne doit jamais muter sa propre
    définition après le chargement."""

    model_config = ConfigDict(frozen=True)

    type_code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    # §B11 "Validation JSON Schema" — voir _parameter_schema_must_be_a_valid_json_schema.
    parameter_schema: dict[str, Any]
    # §B11 "Validation UI Schema" — convention maison documentée dans
    # _ui_schema_keys_must_match_parameter_schema (aucun standard externe
    # imposé par le projet, MUI n'arrive qu'en B25).
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    # §B11 "Defaults par profil" — ex. {"beginner": {...}, "advanced": {...}}.
    defaults_by_profile: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # §B11 "Déclaration des données requises" — ex.
    # {"bars": {"timeframes": ["5Min"], "lookback": 60}}.
    required_market_data: dict[str, Any] = Field(default_factory=dict)
    # §B11 "Déclaration des capacités requises" — ex. ["ai"] pour une
    # stratégie qui consomme AIProvider (voir B12 "AI Market Agent Strategy").
    required_capabilities: list[str] = Field(default_factory=list)

    @field_validator("parameter_schema")
    @classmethod
    def _parameter_schema_must_be_a_valid_json_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator.check_schema(value)
        except Exception as exc:  # noqa: BLE001 — normalisé en erreur de validation Pydantic
            raise ValueError(f"parameter_schema n'est pas un JSON Schema valide : {exc}") from exc
        return value

    @field_validator("ui_schema")
    @classmethod
    def _ui_schema_keys_must_match_parameter_schema(
        cls, value: dict[str, Any], info: ValidationInfo
    ) -> dict[str, Any]:
        """Convention maison (aucun standard UI Schema externe imposé) :
        chaque clé de `ui_schema` doit correspondre à une propriété déclarée
        dans `parameter_schema.properties` — évite qu'un formulaire dynamique
        (B12) référence un champ qui n'existe pas côté validation."""
        parameter_schema = info.data.get("parameter_schema")
        if not isinstance(parameter_schema, dict):
            # parameter_schema a déjà échoué sa propre validation — l'erreur
            # correspondante est déjà remontée séparément par Pydantic,
            # inutile de la dupliquer ici.
            return value
        known_properties = set(parameter_schema.get("properties", {}).keys())
        unknown = set(value.keys()) - known_properties
        if unknown:
            raise ValueError(
                f"ui_schema référence des champs absents de parameter_schema.properties : {sorted(unknown)}"
            )
        return value


@dataclass(frozen=True)
class StrategyLoadFailure:
    module_name: str
    error: str


@dataclass
class RegistryLoadResult:
    definitions: list[StrategyDefinition] = field(default_factory=list)
    failures: list[StrategyLoadFailure] = field(default_factory=list)


def load_definitions_from_directory(directory: Path) -> RegistryLoadResult:
    """Scanne `directory` (typiquement `strategies/` à la racine du
    monorepo) : un module Python par stratégie (fichier `<type_code>.py` ou
    package `<type_code>/__init__.py`), chacun doit exposer un attribut de
    module `DEFINITION` (une instance de `StrategyDefinition`).

    §B11 "Erreur isolée si un plugin est invalide" : un module cassé (import
    qui échoue, attribut manquant, validation Pydantic qui échoue, type_code
    en doublon) est consigné dans `failures` et ignoré — ne bloque jamais le
    chargement des autres modules valides."""
    definitions: list[StrategyDefinition] = []
    failures: list[StrategyLoadFailure] = []
    seen_type_codes: dict[str, str] = {}

    if not directory.is_dir():
        logger.info("dossier de stratégies introuvable (%s) — registre vide", directory)
        return RegistryLoadResult()

    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue  # __pycache__, .gitkeep, etc.

        if entry.is_file():
            if entry.suffix != ".py":
                continue
            module_name = entry.stem
            module_path = entry
        elif entry.is_dir():
            module_name = entry.name
            module_path = entry / "__init__.py"
            if not module_path.exists():
                continue  # dossier sans __init__.py — pas un module de stratégie
        else:
            continue

        try:
            definition = _load_single_module(module_name, module_path)
            if definition.type_code in seen_type_codes:
                raise StrategyLoadError(
                    f"type_code {definition.type_code!r} en doublon avec le module "
                    f"{seen_type_codes[definition.type_code]!r}"
                )
            seen_type_codes[definition.type_code] = module_name
            definitions.append(definition)
        except Exception as exc:  # noqa: BLE001 — isolation volontaire, voir docstring
            logger.warning("échec de chargement du module de stratégie %r : %s", module_name, exc)
            failures.append(StrategyLoadFailure(module_name=module_name, error=str(exc)))

    return RegistryLoadResult(definitions=definitions, failures=failures)


def _load_single_module(module_name: str, module_path: Path):
    # Un module de stratégie peut être un simple fichier `<type_code>.py`
    # OU un package `<type_code>/__init__.py` (utile dès que le calcul mérite
    # d'être scindé en plusieurs fichiers, ex. `definition.py`/`engine.py`,
    # voir strategies/moving_average_crossover/ en B12). Les deux formes
    # sont supportées par le même loader.
    is_package = module_path.name == "__init__.py"
    synthetic_name = f"_strategy_plugin_{module_name}"
    spec = importlib.util.spec_from_file_location(
        synthetic_name,
        module_path,
        submodule_search_locations=[str(module_path.parent)] if is_package else None,
    )
    if spec is None or spec.loader is None:
        raise StrategyLoadError("impossible de créer le spec d'import pour ce module")
    module = importlib.util.module_from_spec(spec)
    if is_package:
        # Un package chargé dynamiquement doit être enregistré dans
        # `sys.modules` AVANT `exec_module()` pour que ses imports relatifs
        # internes (ex. `from .engine import evaluate` dans son
        # `__init__.py`) puissent résoudre leur propre package parent —
        # sinon Python lève "attempted relative import with no known
        # parent package".
        sys.modules[synthetic_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if is_package:
            # Nettoyage : ne laisse rien traîner dans sys.modules entre deux
            # appels à reload() (les sous-modules importés pendant
            # exec_module, ex. `synthetic_name.engine`, s'y enregistrent
            # aussi automatiquement).
            for key in [k for k in sys.modules if k == synthetic_name or k.startswith(synthetic_name + ".")]:
                del sys.modules[key]

    definition = getattr(module, STRATEGY_MODULE_ATTR, None)
    if definition is None:
        raise StrategyLoadError(f"attribut de module `{STRATEGY_MODULE_ATTR}` manquant")
    if not isinstance(definition, StrategyDefinition):
        raise StrategyLoadError(
            f"`{STRATEGY_MODULE_ATTR}` doit être une instance de StrategyDefinition, "
            f"reçu {type(definition).__name__}"
        )
    return definition


class StrategyRegistry:
    """§B11 "Cache sûr des définitions" : le scan du dossier et l'import des
    modules Python ne se refont pas à chaque appel — chargés une fois (au
    premier `get()`, ou explicitement via `reload()`), protégés par un
    verrou pour un accès concurrent sûr (plusieurs requêtes HTTP
    simultanées ne doivent jamais déclencher plusieurs scans en parallèle).

    §B11 "Message indiquant que de nouveaux modules développeur peuvent
    être ajoutés" : loggé à chaque `reload()`, voir ci-dessous — de
    nouveaux fichiers dans `strategies/` sont pris en compte au prochain
    `reload()`, sans redéploiement du code du registre lui-même."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._result: RegistryLoadResult | None = None

    def reload(self) -> RegistryLoadResult:
        result = load_definitions_from_directory(self._directory)
        with self._lock:
            self._result = result
        total = len(result.definitions) + len(result.failures)
        logger.info(
            "registre de stratégies rechargé : %d définition(s) valide(s) sur %d module(s) "
            "découvert(s) dans %s — de nouveaux modules développeur peuvent y être ajoutés "
            "sans redéploiement du registre, ils seront pris en compte au prochain reload()",
            len(result.definitions),
            total,
            self._directory,
        )
        for failure in result.failures:
            logger.warning("module de stratégie ignoré (%s) : %s", failure.module_name, failure.error)
        return result

    def get(self) -> RegistryLoadResult:
        with self._lock:
            if self._result is not None:
                return self._result
        return self.reload()
