"""Package de la stratégie Moving Average Crossover — première stratégie
prédéfinie livrée pour le registre B11 (§B12 "première stratégie" du
chemin critique, voir AVANCEMENT.md §36).

Import relatif volontaire (`from .definition import DEFINITION`) : prouve
que le loader dynamique de `shared.strategy_registry` supporte les modules
de stratégie multi-fichiers, pas seulement les fichiers `.py` isolés — voir
`tests/test_strategy_registry.py::test_package_style_module_supports_relative_imports_between_its_own_files`."""

from __future__ import annotations

from .definition import DEFINITION
from .engine import evaluate, validate_parameters

__all__ = ["DEFINITION", "evaluate", "validate_parameters"]
