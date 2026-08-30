"""B11 — Strategy Registry (`shared.strategy_registry`). Logique pure (pas
de DB/Redis) — écrit de vrais modules `.py` sur disque via `tmp_path` et les
charge pour de vrai (pas de simulation d'import), pour prouver que le scan
de dossier / l'isolation d'erreur fonctionnent contre de vrais fichiers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.strategy_registry import (
    StrategyDefinition,
    StrategyRegistry,
    load_definitions_from_directory,
)

VALID_PARAMETER_SCHEMA = {
    "type": "object",
    "properties": {
        "short_period": {"type": "integer", "minimum": 1},
        "long_period": {"type": "integer", "minimum": 1},
    },
    "required": ["short_period", "long_period"],
}


def _valid_definition(**overrides) -> StrategyDefinition:
    kwargs = {
        "type_code": "demo_strategy",
        "version": "1.0.0",
        "name": "Demo Strategy",
        "description": "Une stratégie de démonstration pour les tests.",
        "parameter_schema": VALID_PARAMETER_SCHEMA,
        "ui_schema": {"short_period": {"widget": "number"}},
    }
    kwargs.update(overrides)
    return StrategyDefinition(**kwargs)


class TestStrategyDefinitionValidation:
    def test_valid_definition_constructs(self):
        definition = _valid_definition()
        assert definition.type_code == "demo_strategy"

    def test_frozen_instance_cannot_be_mutated(self):
        definition = _valid_definition()
        with pytest.raises(ValidationError):
            definition.version = "2.0.0"

    def test_invalid_json_schema_rejected(self):
        with pytest.raises(ValidationError, match="JSON Schema"):
            _valid_definition(parameter_schema={"type": "not-a-real-type"})

    def test_ui_schema_referencing_unknown_field_rejected(self):
        with pytest.raises(ValidationError, match="ui_schema"):
            _valid_definition(ui_schema={"nonexistent_field": {"widget": "text"}})

    def test_type_code_must_be_snake_case(self):
        with pytest.raises(ValidationError):
            _valid_definition(type_code="Not-Valid! Code")


class TestLoadDefinitionsFromDirectory:
    def test_missing_directory_returns_empty_result_not_an_error(self, tmp_path):
        result = load_definitions_from_directory(tmp_path / "does-not-exist")
        assert result.definitions == []
        assert result.failures == []

    def test_loads_valid_module(self, tmp_path):
        (tmp_path / "demo_strategy.py").write_text(
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='demo_strategy', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        result = load_definitions_from_directory(tmp_path)
        assert len(result.definitions) == 1
        assert result.definitions[0].type_code == "demo_strategy"
        assert result.failures == []

    def test_loads_package_style_module(self, tmp_path):
        """§B11 module = fichier `.py` OU package avec `__init__.py`
        (utilisé par la vraie stratégie livrée en B12, moving_average_crossover/)."""
        pkg = tmp_path / "demo_strategy"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='demo_strategy', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        result = load_definitions_from_directory(tmp_path)
        assert len(result.definitions) == 1
        assert result.failures == []

    def test_package_style_module_supports_relative_imports_between_its_own_files(self, tmp_path):
        """Un package de stratégie multi-fichiers (definition.py + engine.py
        + __init__.py qui fait `from .definition import DEFINITION`) doit
        se charger sans "attempted relative import with no known parent
        package" — c'est exactement la structure de la vraie stratégie
        moving_average_crossover livrée en B12."""
        pkg = tmp_path / "demo_package_strategy"
        pkg.mkdir()
        (pkg / "definition.py").write_text(
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='demo_package_strategy', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        (pkg / "engine.py").write_text("def compute():\n    return 42\n")
        (pkg / "__init__.py").write_text(
            "from .definition import DEFINITION\n"
            "from .engine import compute\n"
            "__all__ = ['DEFINITION', 'compute']\n"
        )
        result = load_definitions_from_directory(tmp_path)
        assert len(result.failures) == 0, result.failures
        assert len(result.definitions) == 1
        assert result.definitions[0].type_code == "demo_package_strategy"

    def test_isolated_failure_does_not_block_valid_modules(self, tmp_path):
        """§B11 "erreur isolée si un plugin est invalide" — un module cassé
        (import qui échoue) ne doit jamais empêcher le chargement d'un autre
        module valide à côté."""
        (tmp_path / "broken.py").write_text("raise RuntimeError('boom, module cassé')\n")
        (tmp_path / "demo_strategy.py").write_text(
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='demo_strategy', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        result = load_definitions_from_directory(tmp_path)
        assert len(result.definitions) == 1
        assert result.definitions[0].type_code == "demo_strategy"
        assert len(result.failures) == 1
        assert result.failures[0].module_name == "broken"
        assert "boom" in result.failures[0].error

    def test_missing_definition_attribute_is_isolated_failure(self, tmp_path):
        (tmp_path / "no_definition.py").write_text("X = 1\n")
        result = load_definitions_from_directory(tmp_path)
        assert result.definitions == []
        assert len(result.failures) == 1
        assert "manquant" in result.failures[0].error

    def test_wrong_type_for_definition_attribute_is_isolated_failure(self, tmp_path):
        (tmp_path / "wrong_type.py").write_text("DEFINITION = {'not': 'a StrategyDefinition'}\n")
        result = load_definitions_from_directory(tmp_path)
        assert result.definitions == []
        assert len(result.failures) == 1

    def test_duplicate_type_code_across_modules_is_isolated_failure(self, tmp_path):
        module_source = (
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='same_code', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        (tmp_path / "a_module.py").write_text(module_source)
        (tmp_path / "b_module.py").write_text(module_source)
        result = load_definitions_from_directory(tmp_path)
        # Ordre alphabétique garanti par `sorted(directory.iterdir())` dans
        # l'implémentation -> a_module chargé en premier, b_module en échec.
        assert len(result.definitions) == 1
        assert result.definitions[0].type_code == "same_code"
        assert len(result.failures) == 1
        assert result.failures[0].module_name == "b_module"
        assert "doublon" in result.failures[0].error

    def test_underscore_and_dot_prefixed_entries_are_skipped(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "_helpers.py").write_text("raise RuntimeError('ne devrait jamais être importé')\n")
        (tmp_path / ".gitkeep").write_text("")
        result = load_definitions_from_directory(tmp_path)
        assert result.definitions == []
        assert result.failures == []

    def test_non_python_files_are_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("# pas un module\n")
        result = load_definitions_from_directory(tmp_path)
        assert result.definitions == []
        assert result.failures == []


class TestStrategyRegistryCache:
    def test_get_only_scans_once_across_calls(self, tmp_path, monkeypatch):
        (tmp_path / "demo_strategy.py").write_text(
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='demo_strategy', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        registry = StrategyRegistry(tmp_path)

        call_count = {"n": 0}
        import shared.strategy_registry as strategy_registry_module

        real_loader = strategy_registry_module.load_definitions_from_directory

        def _counting_loader(directory):
            call_count["n"] += 1
            return real_loader(directory)

        monkeypatch.setattr(strategy_registry_module, "load_definitions_from_directory", _counting_loader)

        first = registry.get()
        second = registry.get()
        assert first is second
        assert call_count["n"] == 1  # §B11 "cache sûr" — pas de rescan au 2e get()

    def test_reload_forces_a_rescan_and_picks_up_new_modules(self, tmp_path):
        registry = StrategyRegistry(tmp_path)
        assert registry.get().definitions == []

        (tmp_path / "demo_strategy.py").write_text(
            "from shared.strategy_registry import StrategyDefinition\n"
            "DEFINITION = StrategyDefinition(\n"
            "    type_code='demo_strategy', version='1.0.0', name='Demo',\n"
            "    parameter_schema={'type': 'object', 'properties': {}},\n"
            ")\n"
        )
        # §B11 "de nouveaux modules développeur peuvent être ajoutés" — pris
        # en compte au prochain reload(), sans redémarrage du process.
        result = registry.reload()
        assert len(result.definitions) == 1
        assert registry.get() is result
